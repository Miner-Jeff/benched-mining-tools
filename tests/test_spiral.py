import sys, os, math, json
import os as _o; sys.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "benched_mining_tools"))
import numpy as np
from osgeo import gdal, ogr, osr
import core
HERE = os.path.dirname(os.path.abspath(__file__))
fails = []
def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond: fails.append(label)
srs = osr.SpatialReference(); srs.ImportFromEPSG(32617); proj = srs.ExportToWkt()
n, cell, x0, y0 = 1000, 1.0, 560000.0, 5147000.0
xx = np.tile(np.arange(n) * cell, (n, 1)); yy = np.tile((np.arange(n) * cell)[:, None], (1, n))
dem = (250 - 0.03 * (xx - 500) + 0.02 * (yy - 500)).astype(np.float32)
dem_path = os.path.join(HERE, "dem_spiral.tif")
ds = gdal.GetDriverByName("GTiff").Create(dem_path, n, n, 1, gdal.GDT_Float32)
ds.SetGeoTransform((x0, cell, 0, y0, 0, -cell)); ds.SetProjection(proj)
ds.GetRasterBand(1).SetNoDataValue(-9999); ds.GetRasterBand(1).WriteArray(dem); ds = None
cx, cy = x0 + 500, y0 - 500
pt = ogr.Geometry(ogr.wkbPoint); pt.AddPoint_2D(cx, cy)
poly = pt.Buffer(210, 96); wkt = poly.ExportToWkt()
opts = dict(truck_width=6.5, traffic="two_way", grade_pct=8.0, direction="down", crossfall_pct=2.0,
            ditch=True, ditch_depth=0.3, windrow_h=1.5, cut_ratio=0.84, fill_ratio=1.5,
            curve_radius=75.0, curve_easing_pct=2.5, min_radius=30.0, smooth_m=0.0,
            start_elev=None, end_elev=None, width_override=None, landing_m=15.0)
def read(p):
    d = gdal.Open(p); a = d.GetRasterBand(1).ReadAsArray(); d = None; return a
logs = []
paths = {k: os.path.join(HERE, "sp_%s.gpkg" % k) for k in ("ben", "rl", "rp", "ct")}
t = __import__("time").time()
res = core.run_pit(dem_path, proj, [wkt], 250.0, 100.0, 30.0, 8.0, 50.0, os.path.join(HERE, "sp.tif"),
                   paths["ct"], 10.0, roads={"line_wkts": [], "options": opts, "auto": {"ccw": True, "start_wkts": []}},
                   out_benches=paths["ben"], out_road_lines=paths["rl"], out_road_polys=paths["rp"], log=logs.append)
print("  time %.1f s" % (__import__("time").time() - t))
for l in logs:
    if any(k in l for k in ("Spiral", "WARNING", "Road 1", "Roads", "Bench", "Road drawing", "Total pit", "no fill")): print("   ", l)
check("spiral built", any("Spiral road:" in l for l in logs))
check("no spiral/overlap/room WARNING", not any(("WARNING" in l and ("spiral" in l.lower() or "turns" in l or "ran out" in l)) for l in logs))
out = read(os.path.join(HERE, "sp.tif")); orig = np.where(True, dem, 0)
check("DEM never above original (windrow aside)", np.nanmax(out - orig) <= 1.51)
dsl, dsp, dsb, dsc = [ogr.Open(paths[k]) for k in ("rl","rp","ben","ct")]
rl, rp, bl = dsl.GetLayer(0), dsp.GetLayer(0), dsb.GetLayer(0)
types = {}
for f in rl: types[f.GetField("TYPE")] = types.get(f.GetField("TYPE"), 0) + 1
print("   line types", types, "polys", rp.GetFeatureCount(), "bench lines", bl.GetFeatureCount())
check("road lines have centre + both edges", set(types) == {"CENTRE", "EDGE_L", "EDGE_R"} and len(set(types.values())) == 1)
check("road polygons written", rp.GetFeatureCount() == types["CENTRE"])
kinds = {}
for f in bl: kinds[f.GetField("TYPE")] = kinds.get(f.GetField("TYPE"), 0) + 1
check("bench crest and toe lines written", kinds.get("CREST", 0) > 0 and kinds.get("TOE", 0) > 0)
# road max grade check from segments
gmax = max(f.GetField("GRADE_PCT") for f in rl); check("segment gradients <= 8.05%% (max %.2f)" % gmax, gmax <= 8.05)
zs = sorted(f.GetField("ELEV_START") for f in rl if f.GetField("TYPE") == "CENTRE")
check("road reaches the pit floor (min elev %.1f)" % zs[0], zs[0] <= 101.0)
# dump geometry for plotting
def lines(layer, **filt):
    out = []
    layer.ResetReading()
    for f in layer:
        if all(f.GetField(k) == v for k, v in filt.items()):
            out.append({"p": [list(p[:2]) for p in f.GetGeometryRef().GetPoints()], "t": f.GetField("TYPE") if layer.GetLayerDefn().GetFieldIndex("TYPE") >= 0 else ""})
    return out
polys = []
rp.ResetReading()
for f in rp:
    polys.append([list(p[:2]) for p in f.GetGeometryRef().GetGeometryRef(0).GetPoints()])
ct = []
c = dsc.GetLayer(0)
for f in c: ct.append([list(p[:2]) for p in f.GetGeometryRef().GetPoints()])
json.dump({"bench": lines(bl), "polys": polys, "road": [x for x in lines(rl) if x["t"] == "CENTRE"], "ct": ct}, open(os.path.join(HERE, "sp.json"), "w"))
print("PIT PART DONE")

# ---------------- waste rock pile spiral ----------------
logs = []
poly = pt.Buffer(260, 96); wktp = poly.ExportToWkt()
popts = dict(opts); popts["direction"] = "up"; popts["cut_ratio"] = 1.5
pp = {k: os.path.join(HERE, "sq_%s.gpkg" % k) for k in ("ben", "rl", "rp", "ct")}
res = core.run_pile(dem_path, proj, [wktp], None, 30.0, 8.0, 3.0, 1.0, 290.0, os.path.join(HERE, "sq.tif"), pp["ct"], 10.0,
                    roads={"line_wkts": [], "options": popts, "auto": {"ccw": False, "start_wkts": []}},
                    out_benches=pp["ben"], out_road_lines=pp["rl"], out_road_polys=pp["rp"], log=logs.append)
for l in logs:
    if any(k in l for k in ("Spiral", "WARNING", "Road 1", "Roads", "Bench", "Road drawing", "crest")): print("   ", l)
check("pile spiral built, clockwise", any("Spiral road:" in l and "clockwise" in l and "counter" not in l for l in logs))
check("pile road vectors + bench lines written", res["written"].get("road_polys", 0) > 0 and res["written"].get("benches", 0) > 0)
dsl = ogr.Open(pp["rl"]); l_ = dsl.GetLayer(0)
zs = [f.GetField("ELEV_END") for f in l_ if f.GetField("TYPE") == "CENTRE"]
print("   pile road top %.1f m" % max(zs))
check("pile road ascends to the crest", max(zs) > 280.0)
out_ = read(os.path.join(HERE, "sq.tif")); check("pile road raised the DEM above ground somewhere", np.nanmax(out_ - dem) > 30)
print("\nPILE: ALL PASSED" if not fails else "\nFAILED: %s" % fails)
sys.exit(1 if fails else 0)
