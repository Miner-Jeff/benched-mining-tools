import sys, os, math
import os as _o; sys.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "benched_mining_tools"))
import numpy as np
from osgeo import ogr
import core, validate
fails = []
def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond: fails.append(label)
def W(logs, key): return [l for l in logs if key in l]

# --- outline checks
bow = "POLYGON((0 0, 100 100, 100 0, 0 100, 0 0))"
lg = []; validate.check_outline([bow], lg.append)
check("bow-tie outline flagged invalid", len(W(lg, "not a valid shape")) == 1)
sq = lambda x: "POLYGON((%d 0,%d 0,%d 100,%d 100,%d 0))" % (x, x + 100, x + 100, x, x)
lg = []; validate.check_outline([sq(0), sq(50)], lg.append)
check("overlapping outlines flagged (5000 m2)", any("overlap by 5000" in l for l in lg))
lg = []; validate.check_outline(["POLYGON((0 0,10 0,10 10,0 10,0 0))"], lg.append)
check("tiny outline flagged", len(W(lg, "only")) == 1)

# --- design checks on a synthetic pit
n = 400; cell = 1.0
yy, xx = np.mgrid[0:n, 0:n]
d0 = np.hypot(xx - 200, yy - 200)
mask = d0 < 190
dist = core.inward_distance(mask)
dem = np.full((n, n), 250.0, np.float32)
def design(**kw):
    a = dict(bench_h=30.0, bench_w=8.0, wall=50.0, rim=250.0, floor=100.0, contour=None, max_ira=None)
    a.update(kw)
    surf = core.pit_surface(dist, a["rim"], a["bench_h"], a["bench_w"], a["wall"], a["floor"])
    lg = []
    validate.check_design("pit", a["bench_h"], a["bench_w"], a["wall"], a["rim"], a["floor"], mask, dist, surf, dem, cell,
                          a["contour"], a["max_ira"], lg.append)
    return lg
lg = design()
check("IRA reported ~ 42.1 deg", any("inter-ramp angle 42." in l for l in lg))
check("no spurious warnings for a sound pit", not W(lg, "WARNING"))
check("max IRA exceeded warns", len(W(design(max_ira=35.0), "exceeds the allowed maximum")) == 1)
check("face angle 85 deg advisory", len(W(design(wall=85.0), "usual range")) == 1)
check("contour interval not a multiple warns", len(W(design(contour=7.0), "contour interval")) == 1)
check("contour interval 10 ok", not W(design(contour=10.0), "contour interval"))
check("thin last bench warns", len(W(design(floor=127.0), "last bench is only")) == 1)
check("pit too small for the depth warns", len(W(design(floor=-300.0), "never reaches")) == 1)
check("rim below ground-level -> no-excavation warns", len(W(design(rim=200.0, floor=100.0, ), "needs no excavation")) == 0)  # ground 250 above rim: all cut
dem2 = dem.copy(); dem2[:] = 150.0
surf = core.pit_surface(dist, 250.0, 30.0, 8.0, 50.0, 100.0); lg = []
validate.check_design("pit", 30.0, 8.0, 50.0, 250.0, 100.0, mask, dist, surf, dem2, cell, None, None, lg.append)
check("ground below design warns about no excavation", len(W(lg, "needs no excavation")) == 1)

# --- road checks
def geom(x, y, z, hw=11.0):
    s = np.concatenate([[0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    tx = np.gradient(x); ty = np.gradient(y); m = np.hypot(tx, ty); tx /= m; ty /= m
    return dict(x=x, y=y, z=z, hw=np.full(x.size, hw), s=s, g=np.zeros(x.size), curve=np.zeros(x.size, bool),
                side=np.ones(x.size), tx=tx, ty=ty, xf=0.02)
gt = (0.0, 1.0, 0, float(n), 0, -1.0)
final = np.full((n, n), 150.0, np.float32)
x = np.linspace(100, 300, 201); y = np.full(201, 200.0); z = np.linspace(150, 150, 201)
dm = np.full((n, n), 150.0, np.float32)
lg = []; validate.check_roads("pit", [geom(x, y, z)], final, dm, mask, gt, 150.0, 60.0, cell, lg.append)
check("straight, open road: no warnings", not W(lg, "WARNING"))
# tight U-turn: radius 5 m with 11 m half width -> edges cross
t = np.linspace(0, math.pi, 38)
ux = 200 + 12 * np.cos(t); uy = 200 + 12 * np.sin(t)
lg = []; validate.check_roads("pit", [geom(ux, uy, np.full(38, 150.0), hw=15.0)], final, dm, mask, gt, None, 0, cell, lg.append)
check("U-turn (R 12 m) tighter than half the 30 m width: edge self-intersection flagged", len(W(lg, "crosses itself")) == 1)
# connection: road starts 5 m above ground
lg = []; validate.check_roads("pit", [geom(x, y, z + 5)], final, dm, mask, gt, None, 0, cell, lg.append)
check("road starting 5 m above ground flagged", len(W(lg, "does not connect")) == 1)
# ends outside the footprint
x2 = np.linspace(100, 395, 296); lg = []
validate.check_roads("pit", [geom(x2, np.full(296, 200.0), np.full(296, 150.0))], final, dm, mask, gt, None, 0, cell, lg.append)
check("road ending outside footprint flagged", len(W(lg, "ends outside")) == 1)
# sight distance: a 6 m high wall across a bend
fin = final.copy(); fin[:, 250:253] = 160.0
lg = []; validate.check_roads("pit", [geom(x, y, z)], fin, dm, mask, gt, 150.0, 40.0, cell, lg.append)
check("wall across the road blocks sight -> flagged", len(W(lg, "sight distance")) == 1)
lg = []; validate.check_roads("pit", [geom(x, y, z)], fin, dm, mask, gt, 150.0, 0, cell, lg.append)
check("stopping distance 0 skips the sight check", not W(lg, "sight distance"))
# overlap: two parallel roads 10 m apart with 11 m half width
lg = []; validate.check_roads("pit", [geom(x, y, z), geom(x, y + 10, z)], final, dm, mask, gt, 150.0, 0, cell, lg.append)
check("overlapping roads flagged", len(W(lg, "overlap")) == 1)
lg = []; validate.check_roads("pit", [geom(x, y, z), geom(x, y + 40, z)], final, dm, mask, gt, 150.0, 0, cell, lg.append)
check("well separated roads: no overlap", not W(lg, "overlap"))
print("\nALL VALIDATION TESTS PASSED" if not fails else "\nFAILED: %s" % fails)
sys.exit(1 if fails else 0)
