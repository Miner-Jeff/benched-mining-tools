import sys, os, time, math
import os as _o; sys.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "benched_mining_tools"))
import numpy as np
from osgeo import gdal, ogr, osr
import core
HERE = os.path.dirname(os.path.abspath(__file__))
fails = []
def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond: fails.append(label)
def line(pts):
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in pts: g.AddPoint_2D(*map(float, (x, y)))
    return g.ExportToWkt()

# ---------- performance: user-sized grid, steep terrain, 2 km ramp --------------
rows, cols = 4841, 2628
gt = (559158.0, 1.0, 0, 5149902.0, 0, -1.0)
yy, xx = np.mgrid[0:rows, 0:cols]
ground = (230 + 0.02 * xx + 40 * np.exp(-(((xx - 1300) / 500.0) ** 2 + ((yy - 2400) / 700.0) ** 2))).astype(np.float32)
# pit-like bowl: 120 m deep, walls ~50 deg inside radius 300 m
d = np.hypot(xx - 1300, yy - 2400)
ground = np.where(d < 300, np.maximum(ground - 120 + (300 - d) * -0 , ground - 120) , ground).astype(np.float32)
ground = np.minimum(ground, np.where(d < 300, 140 + np.maximum(d - 120, 0) * 1.19, 1e9)).astype(np.float32)
# spiral-ish ramp: arc around the pit wall, ~2.2 km
th = np.linspace(0, 1.6 * math.pi, 400)
rr = np.linspace(310, 200, th.size)
pts = [(559158 + 1300 + r * math.cos(t), 5149902 - 2400 + r * math.sin(t)) for r, t in zip(rr, th)]
t0 = time.time(); logs = []
out, changed, st = core.apply_roads(ground.copy(), gt, [line(pts)], truck_width=6.5, grade_pct=8.0,
                                    direction="down", end_elev=140.0, log=logs.append)
dt = time.time() - t0
print("  road samples %d, time %.1f s; %s" % (st["road_samples"], dt, [l for l in logs if "Road 1" in l][0]))
check("2 km ramp on a 12.7M-cell grid completes in < 90 s (%.1f s)" % dt, dt < 90)
check("ramp modifies a bounded corridor, not the whole grid (%d cells)" % st["road_cells"], 0 < st["road_cells"] < 0.2 * rows * cols)

# ---------- end-to-end: pit + road, and pile + road, through the real runs ---------
srs = osr.SpatialReference(); srs.ImportFromEPSG(32617); proj = srs.ExportToWkt()
n, cell, x0, y0 = 60, 10.0, 560000.0, 5146600.0
xs = np.arange(n) * cell
dem = (200 + 0.1 * np.tile(xs, (n, 1))).astype(np.float32)
dem_path = os.path.join(HERE, "dem_r.tif")
ds = gdal.GetDriverByName("GTiff").Create(dem_path, n, n, 1, gdal.GDT_Float32)
ds.SetGeoTransform((x0, cell, 0, y0, 0, -cell)); ds.SetProjection(proj)
ds.GetRasterBand(1).SetNoDataValue(-9999); ds.GetRasterBand(1).WriteArray(dem); ds = None
cx, cy = 560300.0, 5146300.0
pt = ogr.Geometry(ogr.wkbPoint); pt.AddPoint_2D(cx, cy)
poly = pt.Buffer(120, 64); wkt = poly.ExportToWkt()
# road starts OUTSIDE the outline (west) and runs east into the pit
road = [(cx - 260, cy), (cx - 100, cy + 10), (cx + 40, cy + 30)]
roads = {"line_wkts": [line(road)],
         "options": dict(truck_width=6.5, traffic="two_way", grade_pct=8.0, direction="down",
                         crossfall_pct=2.0, ditch=True, ditch_depth=0.3, windrow_h=1.5,
                         cut_ratio=0.84, fill_ratio=1.5, curve_radius=75.0, curve_easing_pct=2.5,
                         min_radius=30.0, smooth_m=0.0, start_elev=None, end_elev=None, width_override=None)}
def read(p):
    d = gdal.Open(p); a = d.GetRasterBand(1).ReadAsArray(); d = None; return a
def lines_outside(path, geom, dist):
    c = ogr.Open(path); lyr = c.GetLayer(0); buf = geom.Buffer(dist)
    bad = sum(1 for f in lyr if not buf.Contains(f.GetGeometryRef())); n_ = lyr.GetFeatureCount(); c = None
    return bad, n_

logs = []
base = core.run_pit(dem_path, proj, [wkt], 250.0, 140.0, 30.0, 8.0, 50.0, os.path.join(HERE, "pit_a.tif"),
                    os.path.join(HERE, "pit_a.gpkg"), 10.0)
res = core.run_pit(dem_path, proj, [wkt], 250.0, 140.0, 30.0, 8.0, 50.0, os.path.join(HERE, "pit_b.tif"),
                   os.path.join(HERE, "pit_b.gpkg"), 10.0, roads=roads, log=logs.append)
bad_a, n_a = lines_outside(os.path.join(HERE, "pit_a.gpkg"), poly, 3.0)
bad_b, n_b = lines_outside(os.path.join(HERE, "pit_b.gpkg"), poly, 3.0)
check("pit without road: all contours inside footprint (%d outside)" % bad_a, bad_a == 0)
check("pit with road: contours also follow the road outside the footprint (%d lines outside)" % bad_b, bad_b > 0)
check("pit with road reports road volumes", "road_cut" in res and res["road_cut"] > 0)
a_ = read(os.path.join(HERE, "pit_a.tif")); b_ = read(os.path.join(HERE, "pit_b.tif"))
import tempfile
orig, _g, _p = core.prepare_dem(dem_path, tempfile.mkdtemp(), proj)
check("pit road adds NO fill (windrow aside): output never above original DEM (max excess %.3f m)" % np.nanmax(b_ - orig), np.nanmax(b_ - orig) <= 1.5 + 0.01)  # only the windrow may stand proud
check("pit road log states no-fill", any("no fill" in l for l in logs))
check("road changes the DEM", np.nanmax(np.abs(a_ - b_)) > 1.0)
check("pit road default end level = floor 140 (log)", any("140.0 m" in l for l in logs))
check("pit road logs gradient/width info", any("Running width" in l or "running width" in l for l in logs))

logs = []
roads_up = {"line_wkts": [line(list(reversed(road)))], "options": dict(roads["options"], direction="up", cut_ratio=1.5)}
res_p = core.run_pile(dem_path, proj, [wkt], 205.0, 10.0, 0.0, 3.0, 1.0, None, os.path.join(HERE, "pile_b.tif"),
                      os.path.join(HERE, "pile_b.gpkg"), 5.0, roads=roads_up, log=logs.append)
check("pile with ascending road runs and reports road volumes", res_p.get("road_samples", 0) > 100)
check("pile road default end level = dump crest (log mentions crest)", any("crest elevation" in l for l in logs) and any("Road 1" in l for l in logs))
bad_p, n_p = lines_outside(os.path.join(HERE, "pile_b.gpkg"), poly, 3.0)
check("pile contours include the road outside the footprint (%d outside of %d)" % (bad_p, n_p), bad_p > 0)

print("\\nFAILED: %s" % fails if fails else "\\nALL INTEGRATION TESTS PASSED")
sys.exit(1 if fails else 0)
