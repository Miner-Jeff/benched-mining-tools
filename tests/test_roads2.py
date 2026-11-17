import sys, os, math, re
import os as _o; sys.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "benched_mining_tools"))
import numpy as np
from osgeo import ogr
import core

fails = []
def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond: fails.append(label)

def wkt_line(pts):
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in pts: g.AddPoint_2D(x, y)
    return g.ExportToWkt()

N = 600; x0, y0 = 560000.0, 5146600.0
gt = (x0, 1.0, 0, y0, 0, -1.0)
ground = (200 + 0.2 * np.tile(np.arange(N), (N, 1))).astype(np.float32)
def run(pts, **kw):
    logs = []
    opts = dict(truck_width=6.5, traffic="two_way", grade_pct=8.0, direction="down", windrow_h=1.5,
                cut_ratio=1.0, fill_ratio=1.5, crossfall_pct=0.0, ditch=False, ditch_depth=0.3)
    opts.update(kw)
    out, changed, st = core.apply_roads(ground.copy(), gt, [wkt_line(pts)], log=logs.append, **opts)
    return out, changed, st, logs

# ---- landing: first 15 m flat, then 8% -------------------------------------
pts = [(560300.0, 5146550.0), (560300.0, 5146150.0)]
for landing in (0.0, 15.0, 40.0):
    out, _, _, lg = run(pts, landing_m=landing)
    rows = np.arange(int(y0 - 5146550), int(y0 - 5146150))
    cz = np.array([out[r, 300] for r in rows]); s = rows - rows[0] + 0.5
    flat = cz[s < landing - 1] if landing else np.array([cz[0]])
    check("landing %.0f m: centreline flat over the landing (range %.3f)" % (landing, np.ptp(flat)), np.ptp(flat) < 0.05)
    after = (s > landing + 10) & (s < 380)
    sl = np.polyfit(s[after], cz[after], 1)[0]
    check("landing %.0f m: 8%% descent after the landing (%.2f%%)" % (landing, -sl * 100), abs(sl + 0.08) < 0.003)
    drop = cz[2] - cz[-3]
    exp = 0.08 * (396 - landing)
    check("landing %.0f m: total drop %.1f m ~ %.1f m" % (landing, drop, exp), abs(drop - exp) < 1.0)

# ---- "needs at least" includes the landing ---------------------------------
short = [(560300.0, 5146550.0), (560300.0, 5146450.0)]
_, _, _, lg = run(short, end_elev=200 + 0.2 * 300 - 20.0, landing_m=15.0)
need = int(round(20 / 0.08 + 15))
check("too-short warning counts the landing (needs at least %d m)" % need, any(("at least %d m" % need) in l for l in lg))

# ---- inside-edge gradient on two-way bends ----------------------------------
def bend(R):
    cx, cy = 560200.0, 5146400.0
    arc = [(cx + R * math.cos(t), cy + R * math.sin(t)) for t in np.linspace(math.pi, math.pi * 1.5, 60)]
    return [(cx - R, cy + 150)] + arc + [(cx + 150, cy - R)]
_, _, _, lg = run(bend(40.0), curve_easing_pct=2.5)
check("R=40 m, 2.5%% easing: inside edge ~8%%, no warning", not any("inside edge" in l for l in lg))
_, _, _, lg = run(bend(40.0), curve_easing_pct=0.0)
w = [l for l in lg if "inside edge" in l]
check("R=40 m, no easing: inside edge >10%% warns", len(w) == 1 and "two-way" in w[0])
print("    ", w[0] if w else "")
m = re.search(r"about (\d+)% steep \(centreline ([\d.]+)%\)", w[0]) if w else None
check("warning quotes inside ~ 8 x 40/27 = 12%% (got %s)" % (m.group(1) if m else None), bool(m) and abs(int(m.group(1)) - 12) <= 1)
_, _, _, lg = run(bend(40.0), curve_easing_pct=0.0, traffic="one_way")
check("one-way road: no inside-edge warning", not any("inside edge" in l for l in lg))
_, _, _, lg = run(bend(12.0), curve_easing_pct=0.0)
check("radius below half the road width warns clearly", any("smaller than half the road width" in l for l in lg))

# ---- legacy behaviour unchanged when landing not given ----------------------
out_a, _, st_a, _ = run(pts)
out_b, _, st_b, _ = run(pts, landing_m=0.0)
check("landing default (0) leaves the design unchanged", np.array_equal(out_a, out_b))

print("\nALL NEW ROAD TESTS PASSED" if not fails else "\nFAILED: %s" % fails)
sys.exit(1 if fails else 0)
