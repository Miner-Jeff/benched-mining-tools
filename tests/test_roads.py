import sys, os, math
import os as _o; sys.path.insert(0, _o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "..", "benched_mining_tools"))
import numpy as np
from osgeo import gdal, ogr, osr
import core

HERE = os.path.dirname(os.path.abspath(__file__))
fails = []
def check(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond: fails.append(label)

def wkt_line(pts):
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in pts: g.AddPoint_2D(x, y)
    return g.ExportToWkt()

# ---- 1 m grid, hillside rising to the east at 20% ------------------------
N = 600
x0, y0 = 560000.0, 5146600.0
gt = (x0, 1.0, 0, y0, 0, -1.0)
col = np.arange(N)
ground = (200 + 0.2 * np.tile(col, (N, 1))).astype(np.float32)

def xy_to_rc(x, y): return int((y0 - y) // 1), int((x - x0) // 1)
def run(pts, **kw):
    logs = []
    opts = dict(truck_width=6.5, traffic="two_way", grade_pct=8.0, direction="down", windrow_h=1.5,
                cut_ratio=1.0, fill_ratio=1.5, crossfall_pct=2.0, ditch=True, ditch_depth=0.3)
    opts.update(kw)
    out, changed, st = core.apply_roads(ground.copy(), gt, [wkt_line(pts)], log=logs.append, **opts)
    return out, changed, st, logs

# ---- test 1: straight N-S road across the slope, descending 8% -----------
pts = [(560300.0, 5146550.0), (560300.0, 5146150.0)]    # heading south, 400 m
out, changed, st, logs = run(pts)
z0 = 200 + 0.2 * 300     # ground at start
rows = np.arange(int(y0 - 5146550), int(y0 - 5146150))
cz = np.array([out[r, 300] for r in rows]); s = (rows - rows[0] + 0.5)
slope = np.polyfit(s[10:-10], cz[10:-10], 1)[0]
check("centreline gradient is -8%% (got %.2f%%)" % (slope * 100), abs(slope + 0.08) < 0.002)
check("road starts at ground elevation (%.2f vs %.2f)" % (cz[1], z0), abs(cz[1] - z0) < 0.3)

mid = rows[200]                       # a row ~200 m along
zi = z0 - 0.08 * (mid - rows[0] + 0.5)
Wst = 3.5 * 6.5
band = out[mid, :]
on_road = np.abs(band - zi) <= 0.02 * Wst / 2 + 0.03
# contiguous road cells around the centre
c = 300; l = c
while on_road[l - 1]: l -= 1
r_ = c
while on_road[r_ + 1]: r_ += 1
width = r_ - l + 1
check("running width ~ %.2f m (got %d cells)" % (Wst, width), abs(width - Wst) <= 2.0)
# crossfall: ditch (uphill/east) side lower than west side edge by ~ xf*W
check("crossfall falls toward uphill ditch side (W edge %.2f > E edge %.2f)" % (band[l+1], band[r_-1]), band[l + 1] > band[r_ - 1])
check("crossfall magnitude ~2%% of width (%.3f vs %.3f)" % (band[l+1]-band[r_-1], 0.02*Wst), abs((band[l+1]-band[r_-1]) - 0.02*Wst*0.9) < 0.12)

# ditch on EAST (uphill) side: cells just east of road edge dip below the road edge
ze_in = zi - 0.02 * Wst / 2
east = band[r_ + 1:r_ + 3]
check("V-ditch dips below road edge on uphill side (min %.2f vs edge %.2f)" % (east.min(), ze_in), east.min() < ze_in - 0.12)
# windrow on WEST (downhill) side
ze_out = zi + 0.02 * Wst / 2
near_r = rows[5]
o_w, _, _, _ = run(pts)
o_n, _, _, _ = run(pts, windrow_h=0.0)
half = Wst / 2
zc_near = float(o_w[near_r, 299])                      # centreline-ish elevation
ze_out_n = zc_near + 0.02 * half                       # downhill (outer) road edge
zone_cols = [c for c in range(250, 300) if half < abs(c + 0.5 - 300) <= half + 4.5]
height = np.array([o_w[near_r, c] for c in zone_cols]) - ze_out_n
check("windrow zone is ~4.5 m wide (%d cells)" % len(zone_cols), 4 <= len(zone_cols) <= 5)
check("windrow peaks ~1.5 m above the shoulder (max %.2f)" % height.max(), 1.2 <= height.max() <= 1.51)
check("windrow is a triangle: low at both toes (%.2f, %.2f)" % (height[0], height[-1]), height[0] < 1.0 and height[-1] < 1.0 and height.min() >= -0.01)
beyond = zone_cols[0] - 1
e_b = abs(beyond + 0.5 - 300) - (half + 4.5)
check("fill batter starts at the windrow's outer toe (%.2f vs %.2f)" % (o_w[near_r, beyond], ze_out_n - e_b / 1.5),
      abs(o_w[near_r, beyond] - (ze_out_n - e_b / 1.5)) < 0.1)
check("windrow zone has no effect without a windrow (shoulder = fill slope from edge)",
      o_n[near_r, zone_cols[2]] < o_w[near_r, zone_cols[2]])
check("no windrow on the uphill (ditch) side", np.allclose((o_w - o_n)[near_r, 300 + 2:], 0, atol=1e-3))

# cut batter on uphill side: where road is deep in cut, rise per metre = 1/cut_ratio = 1.0
deep = rows[-60]
zi_d = z0 - 0.08 * (deep - rows[0] + 0.5)
b = out[deep, :]
gnd = ground[deep, :]
Wd = 3.5 * 6.5
cut_zone = np.where((b < gnd - 3) & (np.arange(N) > 300 + Wd / 2 + 1.5 + 2))[0]
seg = b[cut_zone[0]:cut_zone[0] + 6]
check("cut batter rises ~1.0 m per m (%.2f)" % np.mean(np.diff(seg)), abs(np.mean(np.diff(seg)) - 1.0) < 0.05)
check("uphill cut batter is below original ground", np.all(b[cut_zone[:20]] < gnd[cut_zone[:20]]))
# fill on downhill side near the start: road is above ground there
near = rows[5]
fb = out[near, :]; fg = ground[near, :]
west_cells = np.arange(N) < 300 - 12
check("fill batter only raises ground on downhill side", np.all(fb[west_cells] >= fg[west_cells] - 1e-3))
fill_cells = np.where(west_cells & (fb > fg + 0.2))[0]
fs = abs(np.mean(np.diff(fb[fill_cells[0] + 1:fill_cells[0] + 5])))
check("fill slope falls ~1/1.5 = 0.667 per m (%.3f)" % fs, abs(fs - 1/1.5) < 0.05)
check("ground untouched far from the road", np.array_equal(out[:, :100], ground[:, :100]))
check("changed mask covers the road", changed[mid, 300] and changed[mid, 295])
check("both cut and fill reported (%d / %d m3)" % (st["road_cut"], st["road_fill"]), st["road_cut"] > 1e4 and st["road_fill"] > 1e3)
check("log reports width", any("Running width" in l or "running width" in l for l in logs))

# ---- test 2: gradient limit warnings ------------------------------------------
_, _, _, lg = run(pts, grade_pct=12.0)
check("warns above 10%% gradient", any("WARNING: road gradient" in l for l in lg))
_, _, _, lg = run(pts, grade_pct=9.0)
check("notes 9%% as above NA typical (no warning)", any("Note: gradient" in l for l in lg) and not any("WARNING: road gradient" in l for l in lg))

# ---- test 3: clamp at end elevation + shortfall warning ----------------------
out3, _, _, lg = run(pts, end_elev=240.0)
zc = np.array([out3[r, 300] for r in rows])
check("road levels out at end elevation 240 (min %.2f)" % zc.min(), zc.min() >= 240 - 0.03)
check("log says road reaches target", any("reaches 240.0 m" in l for l in lg))
_, _, _, lg = run(pts, end_elev=150.0)
check("warns when road is too short to reach target", any("short of" in l for l in lg))

# ---- test 4: ascending ---------------------------------------------------------
out4, _, _, _ = run(pts, direction="up")
zc = np.array([out4[r, 300] for r in rows])
check("ascending road rises (%.1f -> %.1f)" % (zc[1], zc[-2]), zc[-2] > zc[1] + 20)

# ---- test 5: curves are widened and eased --------------------------------------
R = 40.0
cx, cy = 560200.0, 5146400.0
arc = [(cx + R * math.cos(t), cy + R * math.sin(t)) for t in np.linspace(math.pi, math.pi * 1.5, 40)]
line = [(cx - R, cy + 150)] + arc + [(cx + 150, cy - R)]
out5, ch5, st5, lg5 = run(line)
check("curve samples detected (%d)" % st5["curve_samples"], st5["curve_samples"] > 40)
check("log reports tightest radius ~40 m", any("tightest radius 3" in l or "tightest radius 4" in l for l in lg5))
# eased gradient on curve: effective centreline gradient there is 5.5%
logs_c = " ".join(lg5)
# sample centreline profile via densified line
x, y, s_ = core._lines_from_wkt([wkt_line(line)], 1.0, 0)[0]
rad = core._radius(x, y, s_)
cur = rad < 75
pr = np.array([out5[xy_to_rc(xx, yy)] for xx, yy in zip(x, y)])
sl = np.polyfit(s_[cur][3:-3], pr[cur][3:-3], 1)[0]
sl_straight = np.polyfit(s_[~cur][5:60], pr[~cur][5:60], 1)[0]
check("gradient eased to ~5.5%% on the curve (%.2f%%), 8%% on straight (%.2f%%)" % (-sl*100, -sl_straight*100), abs(-sl*100 - 5.5) < 0.6 and abs(-sl_straight*100 - 8.0) < 0.6)
_, _, _, lg5b = run(line, curve_easing_pct=0.0)

# ---- test 6: tight V-corner warns -----------------------------------------------
vee = [(560200.0, 5146500.0), (560200.0, 5146350.0), (560260.0, 5146350.0), (560260.0, 5146500.0)]
_, _, _, lgv = run(vee)
check("warns about radius tighter than minimum", any("tighter than" in l for l in lgv))
_, _, _, lgv2 = run(vee, smooth_m=40.0)
import re
r1 = float(re.search(r"tightest radius (\d+)", " ".join(lgv)).group(1)); r2 = float(re.search(r"tightest radius (\d+)", " ".join(lgv2)).group(1))
check("smoothing the centreline enlarges tightest radius (%d -> %d m)" % (r1, r2), r2 > r1)

# ---- test 7: one-way / fixed width ---------------------------------------------
out7, _, _, lg7 = run(pts, traffic="one_way")
mid_row = out7[mid, :]; zi7 = z0 - 0.08 * (mid - rows[0] + 0.5)
ok = np.abs(mid_row - zi7) <= 0.02 * (2.0 * 6.5) / 2 + 0.03
l7 = 300
while ok[l7 - 1]: l7 -= 1
r7 = 300
while ok[r7 + 1]: r7 += 1
check("one-way width ~ 13 m (got %d)" % (r7 - l7 + 1), abs((r7 - l7 + 1) - 13) <= 2)
out8, _, _, _ = run(pts, width_override=30.0)
m8 = out8[mid, :]; ok = np.abs(m8 - zi) <= 0.02 * 30 / 2 + 0.03
l8 = 300
while ok[l8 - 1]: l8 -= 1
r8 = 300
while ok[r8 + 1]: r8 += 1
check("width override 30 m honoured (got %d)" % (r8 - l8 + 1), abs((r8 - l8 + 1) - 30) <= 2)

# ---- test 8: no ditch / no windrow ---------------------------------------------
out9, _, _, _ = run(pts, ditch=False, windrow_h=0.0)
b9 = out9[mid, :]
o_w2, _, _, _ = run(pts, ditch=True, windrow_h=1.5)
o_nd, _, _, _ = run(pts, ditch=False, windrow_h=1.5)
dd2 = (o_w2 - o_nd)[mid, 300 + 12: 300 + 16]
check("ditch off: east side of road edge no longer dips (diff max %.2f)" % np.abs(dd2).max(), np.abs((o_w2 - o_nd)[mid, 300 + 12:300 + 14]).max() > 0.05)

# ---- test 9: off-grid start errors cleanly ------------------------------------
try:
    run([(570000.0, 5146550.0), (570000.0, 5146450.0)])
    check("road off the DEM raises", False)
except RuntimeError as e:
    check("road starting off the DEM raises a clear error", "outside the DEM" in str(e))

# ---- test 10: cancel ---------------------------------------------------------------
try:
    core.apply_roads(ground.copy(), gt, [wkt_line(pts)], truck_width=6.5, is_canceled=lambda: True)
    check("cancel stops road design", False)
except core.Cancelled:
    check("cancel stops road design", True)

print("\nFAILED: %s" % fails if fails else "\nALL ROAD TESTS PASSED")
sys.exit(1 if fails else 0)
