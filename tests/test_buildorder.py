import sys, os, math
import os as _o; sys.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "benched_mining_tools"))
import numpy as np
from osgeo import gdal, ogr, osr
import core
HERE = _o.path.dirname(_o.path.abspath(__file__))
fails = []
def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond: fails.append(label)
srs = osr.SpatialReference(); srs.ImportFromEPSG(32617); proj = srs.ExportToWkt()
n = 800
xx = np.tile(np.arange(n) * 1.0, (n, 1)); yy = np.tile((np.arange(n) * 1.0)[:, None], (1, n))
dem = (250 - 0.03 * (xx - 400) + 0.02 * (yy - 400)).astype(np.float32)
p = os.path.join(HERE, "dem_bo.tif")
ds = gdal.GetDriverByName("GTiff").Create(p, n, n, 1, gdal.GDT_Float32)
ds.SetGeoTransform((560000.0, 1.0, 0, 5147000.0, 0, -1.0)); ds.SetProjection(proj)
ds.GetRasterBand(1).WriteArray(dem); ds = None
pt = ogr.Geometry(ogr.wkbPoint); pt.AddPoint_2D(560400.0, 5146600.0); wkt = pt.Buffer(210, 96).ExportToWkt()
opts = dict(truck_width=6.5, traffic="two_way", grade_pct=8.0, direction="up", crossfall_pct=2.0, ditch=True,
            ditch_depth=0.3, windrow_h=1.5, cut_ratio=0.84, fill_ratio=1.5, curve_radius=75.0, curve_easing_pct=2.5,
            min_radius=30.0, smooth_m=0.0, start_elev=None, end_elev=None, width_override=None, landing_m=15.0)

def run(tag, **auto):
    logs = []; rl = os.path.join(HERE, "bo_%s_rl.gpkg" % tag)
    res = core.run_pit(p, proj, [wkt], 250.0, 100.0, 30.0, 8.0, 50.0, None, None, 10.0,
                       roads={"line_wkts": [], "options": dict(opts), "auto": dict(auto, start_wkts=[])},
                       out_road_lines=rl, log=logs.append)
    ds = ogr.Open(rl); lyr = ds.GetLayer(0)
    segs = sorted([(f.GetField("SEG"), f.GetField("ELEV_START"), f.GetField("ELEV_END")) for f in lyr if f.GetField("TYPE") == "CENTRE"])
    lyr.ResetReading()
    pts = []
    for f in lyr:
        if f.GetField("TYPE") == "CENTRE":
            pts += f.GetGeometryRef().GetPoints()
    return logs, segs, np.array([q[:2] for q in pts])

def turning(pts):
    v = np.diff(pts, axis=0); a = np.arctan2(v[:, 1], v[:, 0]); d = np.diff(a); d = (d + np.pi) % (2 * np.pi) - np.pi
    return float(d.sum())          # >0 counter-clockwise

lg, segs, pts = run("up", bottom_up=True, climb_cw=True)
check("bottom-up: road starts at the pit floor (%.1f m)" % segs[0][1], abs(segs[0][1] - 100.0) < 1.0)
check("bottom-up: road climbs and ends near the rim ground (%.1f m)" % segs[-1][2], segs[-1][2] > 225.0)
check("bottom-up: climbing clockwise (turning %.0f deg)" % math.degrees(turning(pts)), turning(pts) < -math.pi)
check("road impact reported for volume and floor area", any("Road impact (pit)" in l and "pit floor area" in l for l in lg))
check("NOTE points to the lowest end (floor)", any("its lowest end" in l for l in lg))
check("build order logged", any("built from the lowest end up" in l for l in lg))
lg2, segs2, pts2 = run("ccw", bottom_up=True, climb_cw=False)
check("climb counter-clockwise option reverses the rotation", turning(pts2) > math.pi)
lg3, segs3, pts3 = run("down", bottom_up=False, climb_cw=True)
check("top-down: road starts near the rim ground (%.1f m) and ends at the floor (%.1f m)" % (segs3[0][1], segs3[-1][2]),
      segs3[0][1] > 225.0 and abs(segs3[-1][2] - 100.0) < 1.5)
check("top-down: descending traces counter-clockwise when loaded trucks climb clockwise", turning(pts3) > math.pi)
print("\nBUILD ORDER: ALL PASSED" if not fails else "\nFAILED: %s" % fails)
sys.exit(1 if fails else 0)
