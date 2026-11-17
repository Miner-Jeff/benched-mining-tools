"""Design validation checks. Everything here only WARNS (via `log`); nothing changes the geometry.

Pure numpy / GDAL so it can be tested outside QGIS.
"""
import math
import numpy as np
from osgeo import ogr

EYE_HEIGHT = 2.5          # m, truck driver's eye above the road (assumption)
OBJECT_HEIGHT = 1.0       # m, object that must be visible on the road ahead (assumption)
SIGHT_FACTOR = 2.0        # sight distance target = 2 x stopping distance (Deswik guideline)
MIN_FLOOR_AREA = 2500.0   # m2, advisory minimum working floor (assumption)
MIN_LAST_BENCH = 3.0      # m, advisory minimum height of a partial last bench (assumption)
FACE_ANGLE_RANGE = (30.0, 80.0)   # advisory band: flatter is unusual, steeper than 80 is beyond typical hard-rock faces


def _w(log, msg):
    log("WARNING: " + msg)


def check_outline(wkts, log):
    """Outline polygons: valid, closed, not tiny, not overlapping each other."""
    geoms = []
    for i, w in enumerate(wkts, 1):
        g = ogr.CreateGeometryFromWkt(w)
        if g is None or g.IsEmpty():
            continue
        geoms.append((i, g))
        if not g.IsValid():
            _w(log, "outline polygon %d is not a valid shape (a self-crossing boundary or an unclosed ring). "
                    "The fill can have gaps or flipped areas; run Vector > Geometry Tools > Check Validity "
                    "or Fix Geometries first." % i)
        if g.GetArea() < 400.0:
            _w(log, "outline polygon %d is only %.0f m2: a sliver or stray feature?" % (i, g.GetArea()))
    for a in range(len(geoms)):
        for b in range(a + 1, len(geoms)):
            ia, ga = geoms[a]; ib, gb = geoms[b]
            try:
                if ga.Intersects(gb):
                    ov = ga.Intersection(gb).GetArea()
                    if ov > 1.0:
                        _w(log, "outline polygons %d and %d overlap by %.0f m2 (they are merged into one footprint)." % (ia, ib, ov))
            except Exception:
                pass


def check_design(kind, bench_h, bench_w, wall, ref, limit, mask, dist, surf, dem, cell,
                 contour_interval=None, max_ira=None, log=print):
    """Bench geometry, angles, floor/crest size, 'negative excavation', contour snapping.

    kind 'pit': wall = face angle (deg), ref = rim, limit = floor.
    kind 'pile': wall = tan(slope) V/H, ref = base, limit = crest elevation.
    """
    tan_a = math.tan(math.radians(wall)) if kind == "pit" else wall
    face = wall if kind == "pit" else math.degrees(math.atan(tan_a))
    run = bench_h / tan_a + bench_w
    ira = math.degrees(math.atan(bench_h / run))
    log("Geometry check: face angle %.1f deg, inter-ramp angle %.1f deg (%.1f m of wall per %.0f m bench, "
        "berm %.1f m)." % (face, ira, run, bench_h, bench_w))
    if kind == "pit" and not (FACE_ANGLE_RANGE[0] <= face <= FACE_ANGLE_RANGE[1]):
        _w(log, "face angle %.0f deg is outside the usual range %.0f-%.0f deg; confirm it against your "
                "geotechnical design." % (face, FACE_ANGLE_RANGE[0], FACE_ANGLE_RANGE[1]))
    if max_ira is not None and ira > max_ira + 1e-6:
        _w(log, "inter-ramp angle %.1f deg exceeds the allowed maximum of %.1f deg. Widen the berms or lower the "
                "face angle." % (ira, max_ira))
    # overall slope between rim/base and the floor/crest, from the real distance field
    total = abs(limit - ref)
    edge = (surf <= limit + 0.01) if kind == "pit" else (surf >= limit - 0.01)
    edge &= mask
    if edge.any() and total > 0:
        dmin = float(dist[edge].min())
        if dmin > 0.5:
            osa = math.degrees(math.atan(total / dmin))
            log("Overall slope: %.1f deg (rim/base to the nearest floor/crest edge, ramp not included)." % osa)
            if osa > ira + 1.5:
                _w(log, "overall slope %.1f deg is steeper than the inter-ramp angle %.1f deg." % (osa, ira))
    # partial last bench
    full = total / bench_h
    rest = (full - math.floor(full)) * bench_h
    if rest > 1e-6 and rest < MIN_LAST_BENCH and full > 1:
        _w(log, "the last bench is only %.1f m high (total height %.1f m is not a multiple of the %.0f m bench). "
                "Adjust the %s elevation by %.1f m to get full benches." % (
                    rest, total, bench_h, "floor" if kind == "pit" else "crest", rest))
    # elevation snapping to the contour interval
    if contour_interval:
        for what, val in (("bench height", bench_h),):
            r = val / contour_interval
            if abs(r - round(r)) > 1e-6:
                _w(log, "%s %.1f m is not a multiple of the %.1f m contour interval, so bench crests and toes "
                        "fall between contour lines." % (what, val, contour_interval))
    # no-excavation / no-fill footprint area
    ok = mask & ~np.isnan(dem)
    nothing = ok & ((surf >= dem) if kind == "pit" else (surf <= dem))
    if ok.any():
        pct = 100.0 * nothing.sum() / ok.sum()
        if pct > 5.0:
            _w(log, "%.0f%% of the footprint (%.2f ha) needs no %s because the ground is already %s the design "
                    "surface there. %s" % (pct, nothing.sum() * cell ** 2 / 1e4, "excavation" if kind == "pit" else "fill",
                                          "below" if kind == "pit" else "above",
                                          "Check the rim elevation against the terrain." if kind == "pit"
                                          else "Check the base elevation against the terrain."))
    # working floor / crest area
    flat = edge
    area = float(flat.sum()) * cell ** 2
    if flat.any() and area < MIN_FLOOR_AREA:
        _w(log, "the pit floor (or dump crest) is only %.0f m2, below the %.0f m2 advisory minimum for a working "
                "area." % (area, MIN_FLOOR_AREA))
    elif not flat.any():
        _w(log, "the design never reaches the %s elevation inside the footprint (the %s is too small for the "
                "height). Lower the %s or widen the footprint." % (
                    "floor" if kind == "pit" else "crest", "pit" if kind == "pit" else "dump",
                    "floor" if kind == "pit" else "crest"))


def _simple_line(xs, ys, step=2):
    ln = ogr.Geometry(ogr.wkbLineString)
    for a, b in zip(xs[::step], ys[::step]):
        ln.AddPoint_2D(float(a), float(b))
    return ln


def _radius_min(x, y, s, win=10.0):
    try:
        from .core import _radius
    except ImportError:
        from core import _radius
    r = _radius(x, y, s)
    k = int(np.argmin(r))
    return float(r[k]), float(s[k])


def _ranges(idx, s, gap=15.0):
    out = []
    for i in idx:
        if out and s[i] - out[-1][1] <= gap:
            out[-1][1] = s[i]
        else:
            out.append([s[i], s[i]])
    return out


def check_roads(kind, geoms, final, dem, mask, gt, end_elev, stopping_m, cell, log=print):
    """Road topology, connection and sight-distance checks."""
    if not geoms:
        return
    H, Wd = final.shape

    def sample(arr, x, y):
        c = np.floor((x - gt[0]) / cell).astype(int)
        r = np.floor((gt[3] - y) / cell).astype(int)
        ok = (c >= 0) & (c < Wd) & (r >= 0) & (r < H)
        out = np.full(x.shape, np.nan)
        out[ok] = arr[r[ok], c[ok]]
        return out

    for ri, g in enumerate(geoms, 1):
        x, y, z, s, hw = g["x"], g["y"], g["z"], g["s"], g["hw"]
        tx, ty = g["tx"], g["ty"]
        # self-intersection of the centreline and of the two running-surface edges
        bad = []
        if not _simple_line(x, y).IsSimple():
            bad.append("centreline")
        if not _simple_line(x - ty * hw, y + tx * hw).IsSimple() or not _simple_line(x + ty * hw, y - tx * hw).IsSimple():
            bad.append("an edge")
        r_min, at_min = _radius_min(x, y, s)
        if r_min < float(hw.min()) and not bad:
            bad.append("the inside edge (it folds back on itself)")
        if bad:
            r, at = r_min, at_min
            _w(log, "road %d: %s crosses itself (tightest bend radius %.0f m, %.0f m from the start). Redraw the "
                    "bend wider, smooth the centreline, or reduce the road width." % (ri, " and ".join(bad), r, at))
        # connection to the surface and to the floor / crest
        g0 = sample(dem, x[:1], y[:1])[0]
        if not np.isnan(g0) and abs(z[0] - g0) > 1.0:
            _w(log, "road %d starts %.1f m %s the ground at its first point, so it does not connect to the "
                    "surface there. Move the start or change the start elevation." % (
                        ri, abs(z[0] - g0), "above" if z[0] > g0 else "below"))
        e = sample(mask.astype(float), x[-1:], y[-1:])[0]
        if not e:
            _w(log, "road %d ends outside the %s footprint, so it does not reach the %s." % (
                ri, "pit" if kind == "pit" else "dump", "pit floor" if kind == "pit" else "dump crest"))
        elif end_elev is not None and abs(z[-1] - end_elev) > 0.5:
            _w(log, "road %d ends at %.1f m, not at the %s elevation of %.1f m." % (
                ri, z[-1], "floor" if kind == "pit" else "crest", end_elev))
        # sight distance on the finished surface
        if stopping_m and stopping_m > 0 and s[-1] > 20:
            look = SIGHT_FACTOR * stopping_m
            blocked = []
            for i in range(0, x.size, 5):
                j = int(np.searchsorted(s, s[i] + look))
                if j >= x.size:
                    break
                d = math.hypot(x[j] - x[i], y[j] - y[i])
                m = max(int(d / 2.0), 3)
                t = np.linspace(0.0, 1.0, m)
                zs = sample(final, x[i] + t * (x[j] - x[i]), y[i] + t * (y[j] - y[i]))
                line = (z[i] + EYE_HEIGHT) + t * ((z[j] + OBJECT_HEIGHT) - (z[i] + EYE_HEIGHT))
                mid = slice(1, m - 1)
                if np.any(zs[mid] > line[mid] + 0.01):
                    blocked.append(i)
            if blocked:
                rng = _ranges(blocked, s)
                txt = ", ".join("%.0f-%.0f m" % (a, b) for a, b in rng[:5]) + (" ..." if len(rng) > 5 else "")
                _w(log, "road %d: sight distance is shorter than %.0f m (2 x the %.0f m stopping distance) at %d "
                        "stretch(es): %s from the start. A wall or windrow blocks the view on those bends; "
                        "widen the bend, lower the windrow or slow the road." % (ri, look, stopping_m, len(rng), txt))
    # overlaps between roads, or between turns of the same road
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        return
    pts = np.concatenate([np.column_stack([g["x"], g["y"]]) for g in geoms])
    rid = np.concatenate([np.full(g["x"].size, k) for k, g in enumerate(geoms)])
    ss = np.concatenate([g["s"] for g in geoms])
    hws = np.concatenate([g["hw"] for g in geoms])
    tree = cKDTree(pts)
    hit = set()
    for i, js in enumerate(tree.query_ball_point(pts[::4], 2.0 * hws.max())):
        i *= 4
        for j in js:
            if (rid[j] != rid[i] or abs(ss[j] - ss[i]) > 4 * hws[i] + 20) and np.hypot(*(pts[i] - pts[j])) < hws[i] + hws[j]:
                hit.add((int(rid[i]) + 1, int(ss[i] // 25)))
                break
    if hit:
        roads = sorted({h[0] for h in hit})
        _w(log, "road surfaces overlap (road %s) over about %d m in total: the running surfaces of two roads, or of "
                "two turns of one road, cover the same ground. Separate them or narrow the road." % (
                    ", ".join(map(str, roads)), len(hit) * 25))
