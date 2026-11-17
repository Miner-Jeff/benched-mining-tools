import sys, os
import os as _o; sys.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "benched_mining_tools"))
import numpy as np
from osgeo import gdal, ogr, osr
import core
HERE = os.path.dirname(os.path.abspath(__file__))

# 4326 DEM near the Norlan Rd site (-80.21, 46.475), 0.000277778 deg (~30 m) cells, ramp 200..260 m
n_x, n_y, px = 90, 120, 1/3600.0
lon0, lat0 = -80.225, 46.495
xs = np.arange(n_x)
dem = (200 + np.tile(xs, (n_y, 1)) * 0.6).astype(np.float32)
s4326 = osr.SpatialReference(); s4326.ImportFromEPSG(4326); s4326.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
p = os.path.join(HERE, "dem4326.tif")
ds = gdal.GetDriverByName("GTiff").Create(p, n_x, n_y, 1, gdal.GDT_Float32)
ds.SetGeoTransform((lon0, px, 0, lat0, 0, -px)); ds.SetProjection(s4326.ExportToWkt())
ds.GetRasterBand(1).SetNoDataValue(-32767); ds.GetRasterBand(1).WriteArray(dem); ds = None

utm = osr.SpatialReference(); utm.ImportFromEPSG(32617); utm.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
ct = osr.CoordinateTransformation(s4326, utm)
cx, cy, _ = ct.TransformPoint(-80.2125, 46.4750)
pt = ogr.Geometry(ogr.wkbPoint); pt.AddPoint_2D(cx, cy); wkt = pt.Buffer(300, 64).ExportToWkt()

out = os.path.join(HERE, "p4326.tif")
res = core.run_pile(p, utm.ExportToWkt(), [wkt], 215.0, 10.0, 0.0, 3.0, 1.0, None, out, os.path.join(HERE, "p4326.gpkg"), 5.0)
a = gdal.Open(out); gt = a.GetGeoTransform(); srs = osr.SpatialReference(wkt=a.GetProjection())
print("output EPSG:", srs.GetAuthorityCode(None), "| cell size:", gt[1], abs(gt[5]), "| size:", a.RasterXSize, "x", a.RasterYSize)
assert srs.GetAuthorityCode(None) == "32617" and abs(gt[1]-1) < 1e-9 and abs(gt[5]+1) < 1e-9
print("fill volume m3:", round(res["fill_volume"]), "| contours:", res["contours"])
assert res["fill_volume"] > 0 and res["contours"] > 0
print("4326 PATH PASS")
