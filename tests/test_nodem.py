import sys, os
import os as _o; sys.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "benched_mining_tools"))
import numpy as np
from osgeo import gdal, ogr, osr
import core
HERE = _o.path.dirname(_o.path.abspath(__file__))
srs = osr.SpatialReference(); srs.ImportFromEPSG(32617); proj = srs.ExportToWkt()
n = 500
ds = gdal.GetDriverByName("GTiff").Create(os.path.join(HERE, "dem_nodem.tif"), n, n, 1, gdal.GDT_Float32)
ds.SetGeoTransform((560000.0, 1.0, 0, 5147000.0, 0, -1.0)); ds.SetProjection(proj)
ds.GetRasterBand(1).WriteArray(np.full((n, n), 250.0, np.float32)); ds = None
pt = ogr.Geometry(ogr.wkbPoint); pt.AddPoint_2D(560250.0, 5146750.0)
wkt = pt.Buffer(150, 64).ExportToWkt()
cont = os.path.join(HERE, "nodem_ct.gpkg")
logs = []
opts = dict(truck_width=6.5, traffic="two_way", grade_pct=8.0, direction="down", crossfall_pct=2.0, ditch=True,
            ditch_depth=0.3, windrow_h=1.5, cut_ratio=0.84, fill_ratio=1.5, curve_radius=75.0, curve_easing_pct=2.5,
            min_radius=30.0, smooth_m=0.0, start_elev=None, end_elev=None, width_override=None, landing_m=15.0)
res = core.run_pit(os.path.join(HERE, "dem_nodem.tif"), proj, [wkt], 250.0, 160.0, 30.0, 8.0, 50.0, None, cont, 10.0,
                   roads={"line_wkts": [], "options": opts, "auto": {"ccw": True, "start_wkts": []}}, log=logs.append)
d = ogr.Open(cont); cnt = d.GetLayer(0).GetFeatureCount()
ok = cnt > 0 and res["contours"] > 0 and not os.path.exists(os.path.join(HERE, "nodem_out.tif")) and any("No output DEM requested" in l for l in logs)
print("PASS no DEM output; contours %d" % cnt if ok else "FAIL no-DEM run")
sys.exit(0 if ok else 1)
