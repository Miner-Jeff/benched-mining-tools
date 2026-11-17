"""Smoke test: import plugin modules against stub qgis, init + run both algorithms."""
import sys, os, types
import os as _o; sys.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), ".."))
HERE = os.path.dirname(os.path.abspath(__file__))

# ---- stub qgis -------------------------------------------------------
class _Any:
    def __init__(self, *a, **k): self.a, self.k = a, k
    def __getattr__(self, n): return _Any()
    def __call__(self, *a, **k): return _Any()

def make_mod(name):
    m = types.ModuleType(name)
    def __getattr__(attr):
        if attr.startswith("__"): raise AttributeError(attr)
        cls = type(attr, (object,), {"__init__": lambda self, *a, **k: setattr(self, "_args", (a, k)), "flags": lambda self: 0, "setFlags": lambda self, f: None})
        # enum-like attributes used as class attrs
        for e in ("Double", "TypeVectorPolygon", "TypeVectorLine", "TypePoint", "NoError", "DistanceMeters", "FlagAdvanced"):
            setattr(cls, e, 1)
        setattr(m, attr, cls); return cls
    m.__getattr__ = __getattr__
    return m

qgis = make_mod("qgis"); core_m = make_mod("qgis.core"); pyqt = make_mod("qgis.PyQt"); qtgui = make_mod("qgis.PyQt.QtGui")
sys.modules.update({"qgis": qgis, "qgis.core": core_m, "qgis.PyQt": pyqt, "qgis.PyQt.QtGui": qtgui})

class FakeAlg:   # base class for the algorithms
    def __init__(self): self.params = []
    def addParameter(self, p): self.params.append(p)
core_m.QgsProcessingAlgorithm = FakeAlg
class QgsProcessingException(Exception): pass
core_m.QgsProcessingException = QgsProcessingException
class QgsProcessing: TypeVectorPolygon = 1; TypeVectorLine = 2; TypePoint = 0
core_m.QgsProcessing = QgsProcessing
class QgsUnitTypes: DistanceMeters = "m"
core_m.QgsUnitTypes = QgsUnitTypes

class FakeCRS:
    def __init__(self, auth, utm): self._a, self._u = auth, utm
    def isValid(self): return True
    def projectionAcronym(self): return "utm" if self._u else "longlat"
    def description(self): return "UTM" if self._u else "WGS 84"
    def mapUnits(self): return "m" if self._u else "deg"
    def authid(self): return self._a
    def toWkt(self):
        from osgeo import osr
        s = osr.SpatialReference(); s.ImportFromEPSG(int(self._a.split(":")[1])); return s.ExportToWkt()
    def __eq__(self, o): return self._a == o._a
    def __ne__(self, o): return not self == o
core_m.QgsCoordinateReferenceSystem = lambda s: FakeCRS(s, True)

class FakeGeom:
    def __init__(self, wkt): self.w = wkt
    def isNull(self): return False
    def isEmpty(self): return False
    def asWkt(self): return self.w
    def transform(self, x): pass
core_m.QgsGeometry = lambda g: FakeGeom(g.w)
core_m.QgsCoordinateTransform = lambda *a: None

# ---- import plugin ---------------------------------------------------
import benched_mining_tools as pkg
from benched_mining_tools import core, common
from benched_mining_tools.algorithms.pit import BenchedOpenPit
from benched_mining_tools.algorithms.pile import BenchedWasteRockPile
from benched_mining_tools.provider import BenchedMiningProvider
from benched_mining_tools.plugin import BenchedMiningPlugin
print("imports OK; classFactory ->", type(pkg.classFactory(None)).__name__)
assert common.is_utm(FakeCRS("EPSG:32617", True)) and not common.is_utm(FakeCRS("EPSG:4326", False))

from osgeo import ogr
pt = ogr.Geometry(ogr.wkbPoint); pt.AddPoint_2D(560200, 5146200)
wkt = pt.Buffer(120, 64).ExportToWkt()

class Feat:
    def geometry(self): return FakeGeom(wkt)
class Source:
    def sourceCrs(self): return FakeCRS("EPSG:32617", True)
    def getFeatures(self): return [Feat()]
class LineFeat:
    def geometry(self): return FakeGeom(ROAD_WKT)
class LineSource:
    def sourceCrs(self): return FakeCRS("EPSG:32617", True)
    def getFeatures(self): return [LineFeat()]
ROAD_WKT = None
class DemLayer:
    def crs(self): return FakeCRS("EPSG:32617", True)
    def source(self): return os.path.join(HERE, "dem.tif")
    def name(self): return "dem"
class Ctx:
    def transformContext(self): return None
class FB:
    def __init__(self): self.lines = []; self.cancel = False
    def pushInfo(self, s): self.lines.append(s)
    def pushWarning(self, s): self.lines.append("WARN " + s)
    def setProgress(self, p): pass
    def isCanceled(self): return self.cancel

def defaults(alg):
    d = {}
    for p in alg.params:
        a, k = p._args
        name = a[0]
        if type(p).__name__ == "QgsProcessingParameterNumber":
            d[name] = a[3] if len(a) > 3 else k.get("defaultValue")
        elif type(p).__name__ == "QgsProcessingParameterBoolean":
            d[name] = a[2] if len(a) > 2 else k.get("defaultValue")
        elif type(p).__name__ == "QgsProcessingParameterEnum":
            d[name] = k.get("defaultValue", 0)
    return d

def bind(alg, values):
    values = dict(defaults(alg), **values)
    alg.parameterAsRasterLayer = lambda p, n, c: DemLayer()
    alg.parameterAsSource = lambda p, n, c: (LineSource() if values.get("USE_ROAD") else None) if n == "ROAD_LINES" else (None if n == "ROAD_START_POINT" else Source())
    alg.parameterAsEnum = lambda p, n, c: values[n]
    alg.parameterAsDouble = lambda p, n, c: float(values[n])
    alg.parameterAsBool = lambda p, n, c: values[n]
    alg.parameterAsOutputLayer = lambda p, n, c: values.get(n, "")

ok = True
for cls, vals, label in [
    (BenchedOpenPit, dict(TARGET_CRS=10, BENCH_HEIGHT=30, BENCH_WIDTH=8, WALL_ANGLE=50, RIM_ELEVATION=250,
        FLOOR_ELEVATION=140, GENERATE_CONTOURS=True, CONTOUR_INTERVAL=10,
        OUTPUT=os.path.join(HERE, "s_pit.tif"), OUTPUT_CONTOURS=os.path.join(HERE, "s_pit.gpkg")), "pit"),
    (BenchedWasteRockPile, dict(TARGET_CRS=10, BENCH_HEIGHT=10, BENCH_WIDTH=0, SLOPE_RATIO=2, BASE_ELEVATION=235,
        GENERATE_CONTOURS=True, CONTOUR_INTERVAL=5,
        OUTPUT=os.path.join(HERE, "s_pile.tif"), OUTPUT_CONTOURS=os.path.join(HERE, "s_pile.gpkg")), "pile"),
]:
    a = cls(); a.initAlgorithm(); print(label, "params registered:", len(a.params), "| name:", a.name(), "|", a.displayName())
    bind(a, vals)
    for f in (vals["OUTPUT"], vals["OUTPUT_CONTOURS"]):
        if os.path.exists(f): os.remove(f)
    fb = FB()
    params = {"TOP_ELEVATION": None, "BASE_ELEVATION": vals.get("BASE_ELEVATION")}
    res = a.processAlgorithm(params, Ctx(), fb)
    good = os.path.exists(res["OUTPUT"]) and os.path.exists(res["OUTPUT_CONTOURS"])
    print(label, "results:", sorted(res), "files exist:", good)
    print("   ", fb.lines[-6:])
    ok &= good
    assert a.shortHelpString()

# auto base elevation (blank) path + cancel path
a = BenchedWasteRockPile(); a.initAlgorithm()
bind(a, dict(TARGET_CRS=10, BENCH_HEIGHT=10, BENCH_WIDTH=0, SLOPE_RATIO=2, GENERATE_CONTOURS=False, CONTOUR_INTERVAL=5,
             OUTPUT=os.path.join(HERE, "s_auto.tif"), OUTPUT_CONTOURS=""))
fb = FB(); res = a.processAlgorithm({"TOP_ELEVATION": None, "BASE_ELEVATION": None}, Ctx(), fb)
print("auto-base run:", sorted(res), [l for l in fb.lines if "Base elevation" in l])
fb = FB(); fb.cancel = True; print("cancel run returns:", a.processAlgorithm({"TOP_ELEVATION": None, "BASE_ELEVATION": None}, Ctx(), fb))
# bad inputs
a = BenchedOpenPit(); a.initAlgorithm()
bind(a, dict(TARGET_CRS=10, BENCH_HEIGHT=30, BENCH_WIDTH=8, WALL_ANGLE=50, RIM_ELEVATION=100, FLOOR_ELEVATION=140,
             GENERATE_CONTOURS=False, CONTOUR_INTERVAL=10, OUTPUT="x.tif", OUTPUT_CONTOURS=""))
try: a.processAlgorithm({}, Ctx(), FB()); ok = False
except QgsProcessingException as e: print("rim<floor rejected:", e)

# ---- road scenarios -----------------------------------------------------------
rg = ogr.Geometry(ogr.wkbLineString)
for pt_ in [(560010.0, 5146200.0), (560100.0, 5146210.0), (560190.0, 5146230.0)]: rg.AddPoint_2D(*pt_)
ROAD_WKT = rg.ExportToWkt()
for cls, vals, label, optkeys in [
    (BenchedOpenPit, dict(USE_ROAD=True, BENCH_HEIGHT=30, BENCH_WIDTH=8, WALL_ANGLE=50, RIM_ELEVATION=250, FLOOR_ELEVATION=140,
        OUTPUT=os.path.join(HERE, "r_pit.tif"), OUTPUT_CONTOURS=os.path.join(HERE, "r_pit.gpkg")), "pit+road", {}),
    (BenchedWasteRockPile, dict(USE_ROAD=True, BENCH_HEIGHT=10, BENCH_WIDTH=0, SLOPE_RATIO=2, ROAD_DIRECTION=1,
        OUTPUT=os.path.join(HERE, "r_pile.tif"), OUTPUT_CONTOURS=os.path.join(HERE, "r_pile.gpkg")), "pile+road", {"BASE_ELEVATION": 205}),
]:
    a = cls(); a.initAlgorithm()
    names = [p._args[0][0] for p in a.params]
    need = ["ROAD_LINES","ROAD_GRADE","ROAD_TRUCK_WIDTH","ROAD_TRAFFIC","ROAD_WIDTH_OVERRIDE","ROAD_DIRECTION","ROAD_START_ELEV","ROAD_END_ELEV",
            "ROAD_CROSSFALL","ROAD_DITCH","ROAD_DITCH_DEPTH","ROAD_WINDROW","ROAD_CUT_RATIO","ROAD_FILL_RATIO","ROAD_CURVE_RADIUS",
            "ROAD_CURVE_EASING","ROAD_TURN_RADIUS","ROAD_SMOOTH"]
    missing = [n for n in need if n not in names]
    print(label, "params:", len(names), "| missing road params:", missing)
    ok &= not missing
    bind(a, dict(vals, GENERATE_CONTOURS=True, CONTOUR_INTERVAL=10, TARGET_CRS=10))
    for f in (vals["OUTPUT"], vals["OUTPUT_CONTOURS"]):
        if os.path.exists(f): os.remove(f)
    fb = FB()
    params = {"TOP_ELEVATION": None, **optkeys}
    res = a.processAlgorithm(params, Ctx(), fb)
    good = os.path.exists(res["OUTPUT"]) and os.path.exists(res["OUTPUT_CONTOURS"]) and any("Road 1" in l for l in fb.lines)
    print(label, "ran:", good, "|", [l for l in fb.lines if l.startswith("Road") or "Haul" in l][:4])
    ok &= good
# no road layer -> unchanged behaviour
a = BenchedOpenPit(); a.initAlgorithm()
bind(a, dict(USE_ROAD=False, OUTPUT=os.path.join(HERE, "r_none.tif"), OUTPUT_CONTOURS="", GENERATE_CONTOURS=False))
fb = FB(); a.processAlgorithm({}, Ctx(), fb)
none_ok = not any("Road" in l for l in fb.lines); print("no road layer -> no road output:", none_ok); ok &= none_ok
# ---- automatic spiral + drawing vectors, both tools --------------------------------
for cls, extra, key, label in [
    (BenchedOpenPit, dict(BENCH_HEIGHT=30, BENCH_WIDTH=8, WALL_ANGLE=50, RIM_ELEVATION=250, FLOOR_ELEVATION=200), None, "pit"),
    (BenchedWasteRockPile, dict(BENCH_HEIGHT=10, BENCH_WIDTH=0, SLOPE_RATIO=2, ROAD_DIRECTION=1), 215, "pile"),
]:
    a = cls(); a.initAlgorithm()
    outs = {k: os.path.join(HERE, "auto_%s_%s.gpkg" % (label, k)) for k in ("c", "b", "rl", "rp")}
    for f in outs.values():
        if os.path.exists(f): os.remove(f)
    bind(a, dict(extra, ROAD_AUTO=True, ROAD_SPIRAL_DIR=1, TARGET_CRS=10, GENERATE_CONTOURS=True, CONTOUR_INTERVAL=5, OUTPUT=os.path.join(HERE, "auto_%s.tif" % label),
                 OUTPUT_CONTOURS=outs["c"], OUTPUT_BENCHES=outs["b"], OUTPUT_ROAD_LINES=outs["rl"], OUTPUT_ROAD_POLYS=outs["rp"]))
    fb = FB(); res = a.processAlgorithm({"TOP_ELEVATION": None, "BASE_ELEVATION": key}, Ctx(), fb)
    got = sorted(k for k in res if k.startswith("OUTPUT_"))
    good = {"OUTPUT_BENCHES", "OUTPUT_ROAD_LINES", "OUTPUT_ROAD_POLYS"} <= set(got) and all(os.path.exists(outs[k]) for k in ("b", "rl", "rp")) and any("Spiral road" in l for l in fb.lines)
    print(label, "auto spiral + vectors:", good, got, [l for l in fb.lines if "Spiral" in l or "WARNING" in l][:3])
    ok &= good
print("SMOKE", "PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
