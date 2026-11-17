import sys, os, math
import os as _o; sys.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "benched_mining_tools"))
import numpy as np
from osgeo import gdal, ogr, osr
import core

HERE = os.path.dirname(os.path.abspath(__file__))
srs = osr.SpatialReference(); srs.ImportFromEPSG(32617)
proj = srs.ExportToWkt()

# synthetic 4326-free DEM already in UTM: 400x400 m, 10 m cells, ramp 200..240 m west->east
x0, y0, cell, n = 560000.0, 5146400.0, 10.0, 40
xs = np.arange(n) * cell
dem = (200 + 0.1 * np.tile(xs, (n, 1))).astype(np.float32)
dem_path = os.path.join(HERE, "dem.tif")
ds = gdal.GetDriverByName("GTiff").Create(dem_path, n, n, 1, gdal.GDT_Float32)
ds.SetGeoTransform((x0, cell, 0, y0, 0, -cell)); ds.SetProjection(proj)
ds.GetRasterBand(1).SetNoDataValue(-9999); ds.GetRasterBand(1).WriteArray(dem); ds = None

cx, cy, r = 560200.0, 5146200.0, 120.0
pt = ogr.Geometry(ogr.wkbPoint); pt.AddPoint_2D(cx, cy)
poly = pt.Buffer(r, 64); wkt = poly.ExportToWkt()

def read(path):
    ds = gdal.Open(path); a = ds.GetRasterBand(1).ReadAsArray(); ds = None
    return a

def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond: check.failed = True
check.failed = False

logs = []
# ---------- pile ----------
out = os.path.join(HERE, "pile.tif"); cont = os.path.join(HERE, "pile_cont.gpkg")
res = core.run_pile(dem_path, proj, [wkt], 205.0, 10.0, 0.0, 3.0, 1.0, None, out, cont, 5.0, log=logs.append)
a = gdal.Open(out); arr = a.GetRasterBand(1).ReadAsArray(); gt = a.GetGeoTransform()
check("pile output grid is 1 m (%.1f)" % gt[1], abs(gt[1] - 1.0) < 1e-9)
d = gdal.Open(dem_path)
# compare against original DEM resampled at same grid
orig, gt2, _ = core.prepare_dem(dem_path, HERE, proj)
mask = core.rasterize_footprint([wkt], orig.shape, gt2, proj)
outside = ~mask
check("pile leaves terrain outside footprint untouched", np.allclose(arr[outside], orig[outside], equal_nan=True))
diff = arr - orig
check("pile never cuts ground (min diff %.3f)" % np.nanmin(diff), np.nanmin(diff) >= -1e-4)
inside = arr[mask]
crest = inside.max()
expect = 205 + r / 3.0
check("crest %.1f ~ expected %.1f" % (crest, expect), abs(crest - expect) < 1.5)
check("fill volume positive (%.0f m3)" % res["fill_volume"], res["fill_volume"] > 1e5)
# monotonic rise toward the centre along the east-west centre line, above ground
row = int(round((y0 - cy) / 1.0)); 
line = arr[row, int(round(cx - x0 - r)) + 20 : int(round(cx - x0))]
check("pile rises toward centre along west half", np.all(np.diff(line) >= -1e-3))
c = ogr.Open(cont); lyr = c.GetLayer(0)
n_feat = lyr.GetFeatureCount()
vals = sorted({round(f.GetField("ELEVATION"), 3) for f in lyr})
check("contours exist (%d lines)" % n_feat, n_feat > 0)
check("contour elevations are multiples of 5: %s..%s" % (vals[0], vals[-1]), all(abs(v / 5 - round(v / 5)) < 1e-6 for v in vals))
inside_buf = poly.Buffer(3.0)
bad = sum(1 for f in lyr if not inside_buf.Contains(f.GetGeometryRef()))
check("all contour lines lie inside footprint (%d outside)" % bad, bad == 0)
c = None

# ---------- pile, auto base, bench width 8 ----------
out2 = os.path.join(HERE, "pile2.tif")
res = core.run_pile(dem_path, proj, [wkt], None, 10.0, 8.0, 3.0, 1.0, 230.0, out2, None, 5.0, log=logs.append)
arr2 = read(out2)
check("top limit caps added material at 230 (ground may exceed it)", np.all(arr2[mask] <= np.maximum(orig[mask], 230.0) + 1e-3))
check("top limit actually bites (max %.2f vs uncapped %.2f)" % (np.nanmax(arr2[mask]), np.nanmax(arr[mask])), np.nanmax(arr2[mask]) < np.nanmax(arr[mask]))

# ---------- pit ----------
out3 = os.path.join(HERE, "pit.tif"); cont3 = os.path.join(HERE, "pit_cont.gpkg")
res = core.run_pit(dem_path, proj, [wkt], 250.0, 140.0, 30.0, 8.0, 50.0, out3, cont3, 10.0, log=logs.append)
arr3 = read(out3)
d3 = arr3 - orig
check("pit never raises ground (max diff %.3f)" % np.nanmax(d3), np.nanmax(d3) <= 1e-4)
check("pit untouched outside footprint", np.allclose(arr3[outside], orig[outside], equal_nan=True))
check("pit floor respected (min %.2f >= 140)" % np.nanmin(arr3[mask]), np.nanmin(arr3[mask]) >= 140 - 1e-3)
check("pit cut volume positive (%.0f m3)" % res["cut_volume"], res["cut_volume"] > 1e5)
# wall steepness: on first wall of a cycle, gradient ~ tan(50)
dist = core.inward_distance(mask)
surf = core.pit_surface(dist, 250.0, 30.0, 8.0, 50.0, 140.0)
cyc = 30 / math.tan(math.radians(50)) + 8
s0 = surf[mask & (dist > 1) & (dist < 20)]
grad = (s0.max() - s0.min()) / (dist[mask & (dist > 1) & (dist < 20)].max() - dist[mask & (dist > 1) & (dist < 20)].min())
check("wall gradient %.2f ~ tan(50)=%.2f" % (grad, math.tan(math.radians(50))), abs(grad - math.tan(math.radians(50))) < 0.1)
# bench is flat
bench = surf[mask & (dist > 26.5) & (dist < 32.5)]
check("bench is flat (range %.3f)" % (bench.max() - bench.min()), bench.max() - bench.min() < 1e-3)
c = ogr.Open(cont3); n_feat = c.GetLayer(0).GetFeatureCount(); c = None
check("pit contours exist (%d)" % n_feat, n_feat > 0)

# ---------- edge cases ----------
try:
    far = ogr.Geometry(ogr.wkbPoint); far.AddPoint_2D(cx + 5000, cy); 
    core.run_pit(dem_path, proj, [far.Buffer(50).ExportToWkt()], 250, 140, 30, 8, 50, os.path.join(HERE, "x.tif"))
    check("non-overlapping outline raises", False)
except RuntimeError as e:
    check("non-overlapping outline raises a clear error", "does not overlap" in str(e))
try:
    core.run_pile(dem_path, proj, [wkt], 205, 10, 0, 3, 1, None, os.path.join(HERE, "x.tif"), is_canceled=lambda: True)
    check("cancel stops the run", False)
except core.Cancelled:
    check("cancel stops the run", True)

print("\n".join("  log: " + l for l in logs[:14]))
sys.exit(1 if check.failed else 0)
