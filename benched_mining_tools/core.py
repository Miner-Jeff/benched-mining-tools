"""
Core calculations for Benched Mining Tools.

Pure GDAL / numpy - no QGIS imports - so it can be tested outside QGIS.
All work happens on ONE common grid (the DEM resampled to CELL_SIZE metres),
and the footprint is rasterized straight onto that grid with the GDAL Python
API. That avoids the grid-size mismatches and locked temp files that the
earlier step-by-step Processing scripts ran into.
"""

import math
import os
import shutil
import tempfile

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

VERSION = "2.8.1"

# Working resolution in metres. Hard coded for now; make it a parameter later.
CELL_SIZE = 1.0

# Safety limit so a huge DEM can't exhaust memory at 1 m resolution.
MAX_CELLS = 150_000_000

OUT_NODATA = -9999.0


class Cancelled(Exception):
    """Raised when the user cancels the run."""


def _noop(*_args, **_kwargs):
    pass


# --------------------------------------------------------------------------
# Grid / raster helpers
# --------------------------------------------------------------------------
def prepare_dem(src_path, work_dir, dst_srs_wkt, cell=CELL_SIZE):
    """Reproject (if needed) and resample the DEM to `cell` metres.

    Returns (array float32 with NaN for nodata, geotransform, projection_wkt).
    """
    dst_path = os.path.join(work_dir, "dem_working.tif")
    src = gdal.Open(src_path)
    if src is None:
        raise RuntimeError("GDAL could not open the DEM: %s" % src_path)
    src_nodata = src.GetRasterBand(1).GetNoDataValue()
    src = None

    opts = gdal.WarpOptions(
        format="GTiff",
        dstSRS=dst_srs_wkt,
        xRes=cell,
        yRes=cell,
        targetAlignedPixels=False,
        resampleAlg="bilinear",
        outputType=gdal.GDT_Float32,
        srcNodata=src_nodata,
        dstNodata=OUT_NODATA,
        multithread=True,
    )
    ds = gdal.Warp(dst_path, src_path, options=opts)
    if ds is None:
        raise RuntimeError("Resampling the DEM failed.")
    n_cols, n_rows = ds.RasterXSize, ds.RasterYSize
    n_cells = n_cols * n_rows
    if n_cells > MAX_CELLS:
        ds = None
        raise RuntimeError(
            "The DEM would be %d x %d cells at %.1f m (%s cells). That is too "
            "large for memory. Clip the DEM to the area around the footprint "
            "and run again." % (n_cols, n_rows, cell, format(n_cells, ","))
        )
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    arr = ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    nd = ds.GetRasterBand(1).GetNoDataValue()
    ds = None
    if nd is not None:
        arr[arr == np.float32(nd)] = np.nan
    return arr, gt, proj


def rasterize_footprint(wkt_list, shape, gt, proj_wkt):
    """Burn polygons (WKT, already in the DEM CRS) onto the DEM grid.

    Returns a boolean array, True inside any polygon.
    """
    rows, cols = shape
    srs = osr.SpatialReference()
    srs.ImportFromWkt(proj_wkt)

    vec = ogr.GetDriverByName("Memory").CreateDataSource("footprint")
    lyr = vec.CreateLayer("footprint", srs=srs, geom_type=ogr.wkbPolygon)
    for wkt in wkt_list:
        feat = ogr.Feature(lyr.GetLayerDefn())
        feat.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
        lyr.CreateFeature(feat)

    mem = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Byte)
    mem.SetGeoTransform(gt)
    mem.SetProjection(proj_wkt)
    mem.GetRasterBand(1).Fill(0)
    gdal.RasterizeLayer(mem, [1], lyr, burn_values=[1])
    mask = mem.GetRasterBand(1).ReadAsArray() > 0
    mem = None
    vec = None
    return mask


def inward_distance(mask, cell=CELL_SIZE):
    """Distance (metres) from every cell inside `mask` to the nearest cell
    outside it. Cells outside the mask get 0."""
    try:
        from scipy.ndimage import distance_transform_edt

        return distance_transform_edt(mask, sampling=cell).astype(np.float32)
    except ImportError:
        pass

    # GDAL fallback: proximity to the nearest 0-valued cell, in pixels.
    rows, cols = mask.shape
    src = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Byte)
    src.GetRasterBand(1).WriteArray(mask.astype(np.uint8))
    dst = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Float32)
    gdal.ComputeProximity(
        src.GetRasterBand(1),
        dst.GetRasterBand(1),
        ["VALUES=0", "DISTUNITS=PIXEL"],
    )
    dist = dst.GetRasterBand(1).ReadAsArray().astype(np.float32) * np.float32(cell)
    src = dst = None
    dist[~mask] = 0
    return dist


def write_raster(path, arr, gt, proj):
    out = np.where(np.isnan(arr), OUT_NODATA, arr).astype(np.float32)
    rows, cols = out.shape
    ds = gdal.GetDriverByName("GTiff").Create(
        path, cols, rows, 1, gdal.GDT_Float32,
        options=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"],
    )
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(OUT_NODATA)
    band.WriteArray(out)
    band.FlushCache()
    ds = None


def write_contours(arr, mask, gt, proj, interval, out_path, field="ELEVATION"):
    """Contour `arr` only inside `mask`; every line carries its elevation."""
    rows, cols = arr.shape
    data = np.where(mask & ~np.isnan(arr), arr, OUT_NODATA).astype(np.float32)
    mem = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Float32)
    mem.SetGeoTransform(gt)
    mem.SetProjection(proj)
    band = mem.GetRasterBand(1)
    band.SetNoDataValue(OUT_NODATA)
    band.WriteArray(data)

    ext = os.path.splitext(out_path)[1].lower()
    driver_name = {".shp": "ESRI Shapefile", ".geojson": "GeoJSON"}.get(ext, "GPKG")
    drv = ogr.GetDriverByName(driver_name)
    if os.path.exists(out_path):
        drv.DeleteDataSource(out_path)
    vec = drv.CreateDataSource(out_path)
    srs = osr.SpatialReference()
    srs.ImportFromWkt(proj)
    lyr = vec.CreateLayer("contours", srs=srs, geom_type=ogr.wkbLineString)
    lyr.CreateField(ogr.FieldDefn("ID", ogr.OFTInteger))
    lyr.CreateField(ogr.FieldDefn(field, ogr.OFTReal))
    gdal.ContourGenerate(
        band, float(interval), 0.0, [], 1, OUT_NODATA, lyr, 0, 1
    )
    n = lyr.GetFeatureCount()
    vec = None
    mem = None
    return n


# --------------------------------------------------------------------------
# Surfaces
# --------------------------------------------------------------------------
def pit_surface(dist, rim, bench_h, bench_w, wall_angle_deg, floor):
    """Benched pit surface, stepping DOWN from `rim` as distance inward grows.

    Each bench cycle is: wall (drops bench_h at the wall angle) then a flat
    bench of width bench_w.
    """
    tan_a = math.tan(math.radians(wall_angle_deg))
    wall_run = bench_h / tan_a
    cycle = wall_run + bench_w
    n = np.floor(dist / cycle)
    d_in = dist - n * cycle
    drop = n * bench_h + np.minimum(d_in * tan_a, bench_h)
    return np.maximum(rim - drop, floor).astype(np.float32)


def pile_surface(dist, base, bench_h, bench_w, ratio_h, ratio_v, top=None):
    """Benched dump surface, stepping UP from `base` as distance inward grows.

    Slope is ratio_h : ratio_v (horizontal : vertical), e.g. 3:1.
    """
    tan_a = ratio_v / ratio_h
    wall_run = bench_h / tan_a
    cycle = wall_run + bench_w
    n = np.floor(dist / cycle)
    d_in = dist - n * cycle
    rise = n * bench_h + np.minimum(d_in * tan_a, bench_h)
    elev = base + rise
    if top is not None:
        elev = np.minimum(elev, top)
    return elev.astype(np.float32)


# --------------------------------------------------------------------------
# Haul roads
#
# Design rules follow the Deswik white paper "Guidelines and considerations
# for open pit designers" (road width as multiples of truck width, gradient,
# windrow, V-ditch, crossfall, flatter curves). Site rules, legislation and
# manufacturer data take precedence over every default here.
# --------------------------------------------------------------------------
# (straight, curve) running width in truck widths
TRAFFIC_WIDTHS = {"two_way": (3.5, 4.0), "one_way": (2.0, 2.5)}
WINDROW_SIDE_SLOPE = 1.5      # H per 1 V on each side of the windrow
DITCH_INSIDE_SLOPE = 3.0      # H:V on the road side of the V-ditch
DITCH_OUTSIDE_SLOPE = 2.0     # H:V on the far side of the V-ditch
ROAD_MAX_REACH = 150.0        # furthest a cut/fill tie-in is followed (m)
GRADE_ADVISORY_PCT = 8.0      # typical North American rigid-truck gradient
GRADE_LIMIT_PCT = 10.0        # commonly cited regulatory ceiling
TURN_RADIUS_FACTOR = 1.5      # inside tyre path >= 150% of the truck's turning-circle inner clearance radius


def _smooth(a, n):
    """Moving average over n samples; end values are held fixed."""
    n = int(n)
    if n < 3 or a.size < 3:
        return a
    k = min(n // 2, a.size - 1)
    pad = np.pad(a, k, mode="reflect", reflect_type="odd")
    return np.convolve(pad, np.ones(2 * k + 1) / (2 * k + 1), mode="valid")


def _lines_from_wkt(wkts, step, smooth_m):
    """Densify centrelines to uniform `step` spacing (and optionally smooth)."""
    out = []
    for wkt in wkts:
        g = ogr.CreateGeometryFromWkt(wkt)
        g.FlattenTo2D()
        parts = ([g.GetGeometryRef(i) for i in range(g.GetGeometryCount())]
                 if g.GetGeometryType() == ogr.wkbMultiLineString else [g])
        for p in parts:
            pts = np.array([(p.GetX(i), p.GetY(i)) for i in range(p.GetPointCount())], float)
            if len(pts) < 2:
                continue
            seg = np.hypot(*np.diff(pts, axis=0).T)
            keep = np.concatenate([[True], seg > 1e-9])
            pts = pts[keep]
            if len(pts) < 2:
                continue
            chain = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
            length = chain[-1]
            if length < 3 * step:
                continue
            n = max(3, int(round(length / step)) + 1)
            s = np.linspace(0.0, length, n)
            x = np.interp(s, chain, pts[:, 0])
            y = np.interp(s, chain, pts[:, 1])
            if smooth_m and smooth_m > step:
                m = int(smooth_m / step)
                x, y = _smooth(x, m), _smooth(y, m)
            s = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
            out.append((x, y, s))
    return out


def _radius(x, y, s, half=10.0):
    """Centreline radius (m) from three points `half` metres apart."""
    n = x.size
    length = s[-1]
    if length < 2.5 * half:
        return np.full(n, np.inf)
    sm = np.clip(s - half, 0, length)
    sp = np.clip(s + half, 0, length)
    ax, ay = np.interp(sm, s, x), np.interp(sm, s, y)
    bx, by = np.interp(sp, s, x), np.interp(sp, s, y)
    ab = np.hypot(x - ax, y - ay)
    bc = np.hypot(bx - x, by - y)
    ac = np.hypot(bx - ax, by - ay)
    area2 = np.abs((x - ax) * (by - y) - (y - ay) * (bx - x))
    with np.errstate(divide="ignore", invalid="ignore"):
        r = ab * bc * ac / (2.0 * area2)
    r[area2 < 1e-9] = np.inf
    inner = np.where((s >= half) & (s <= length - half))[0]
    r[: inner[0]] = r[inner[0]]
    r[inner[-1] + 1:] = r[inner[-1]]
    return r


def _sample(grid, gt, x, y):
    """Nearest-cell lookup; NaN outside the grid."""
    c = np.floor((x - gt[0]) / gt[1]).astype(int)
    r = np.floor((y - gt[3]) / gt[5]).astype(int)
    ok = (c >= 0) & (c < grid.shape[1]) & (r >= 0) & (r < grid.shape[0])
    out = np.full(x.shape, np.nan)
    out[ok] = grid[r[ok], c[ok]]
    return out


def apply_roads(ground, gt, line_wkts, truck_width, traffic="two_way",
                width_override=None, grade_pct=8.0, curve_easing_pct=2.5,
                curve_radius=75.0, min_radius=30.0, start_elev=None,
                end_elev=None, direction="down", crossfall_pct=2.0,
                ditch=True, ditch_depth=0.3, windrow_h=1.5, cut_ratio=1.0,
                fill_ratio=1.5, smooth_m=0.0, landing_m=0.0, cap=None, log=_noop,
                is_canceled=lambda: False):
    """Design haul road(s) along centreline(s) into the surface `ground`.

    Each line is an independent road, digitized from its start. The centreline
    profile runs at `grade_pct` from the start elevation (descending or
    ascending) and levels out at `end_elev`. The cross-section is: running
    surface (crossfall toward the ditch), V-ditch on the uphill side, windrow
    on the downhill side, then cut / fill batters tying into the ground.

    Returns (new_surface, changed_mask, stats).
    """
    cell = gt[1]
    grade = grade_pct / 100.0
    ease = curve_easing_pct / 100.0
    xf = crossfall_pct / 100.0
    sign = -1.0 if direction == "down" else 1.0
    if width_override:
        w_straight = w_curve = float(width_override)
    else:
        f_s, f_c = TRAFFIC_WIDTHS[traffic]
        w_straight, w_curve = f_s * truck_width, f_c * truck_width
    ditch_w = (DITCH_INSIDE_SLOPE + DITCH_OUTSIDE_SLOPE) * ditch_depth if ditch else 0.0
    wind_w = 2.0 * WINDROW_SIDE_SLOPE * windrow_h if windrow_h > 0 else 0.0

    lines = _lines_from_wkt(line_wkts, cell, smooth_m)
    if not lines:
        raise RuntimeError("The road centreline layer has no usable lines "
                           "(each line must be longer than %.0f m)." % (3 * cell))

    log("Road running width: %.1f m straight, %.1f m on curves (truck %.1f m, %s)" % (
        w_straight, w_curve, truck_width,
        "fixed width" if width_override else traffic.replace("_", "-")))
    if grade_pct > GRADE_LIMIT_PCT:
        log("WARNING: road gradient %.1f%% is above %.0f%%, the ceiling cited in the "
            "Deswik paper (DMIRS guidance). Component life is roughly halved at 10%% versus 8%%."
            % (grade_pct, GRADE_LIMIT_PCT))
    elif grade_pct > GRADE_ADVISORY_PCT:
        log("Note: gradient %.1f%% is above the 8%% commonly used in North America "
            "(10%% is common in Australia)." % grade_pct)

    X, Y, Z, W, DS, TX, TY = [], [], [], [], [], [], []
    geoms = []
    n_curve_total = 0
    for li, (x, y, s) in enumerate(lines, 1):
        n = x.size
        rad = _radius(x, y, s)
        curve = rad < curve_radius
        n_curve_total += int(curve.sum())
        width = np.clip(_smooth(np.where(curve, w_curve, w_straight).astype(float), 31),
                        min(w_straight, w_curve), max(w_straight, w_curve))
        g = np.where(curve, max(grade - ease, 0.0), grade)
        if landing_m and landing_m > 0:
            # flat lead-in where the road joins the ground / another road
            g = np.where(s < landing_m, 0.0, g)
        ds = np.diff(s, prepend=s[0])
        z0 = start_elev
        if z0 is None:
            z0 = float(_sample(ground, gt, x[:1], y[:1])[0])
            if np.isnan(z0):
                raise RuntimeError("Road %d starts outside the DEM (or on nodata). Enter a "
                                   "road start elevation or move the first vertex onto the DEM." % li)
        z = z0 + sign * np.cumsum(g * ds)
        if end_elev is not None:
            z = np.maximum(z, end_elev) if direction == "down" else np.minimum(z, end_elev)
        reached = z[-1]

        # ditch goes on the uphill side (the side with higher ground)
        tx, ty = np.gradient(x), np.gradient(y)
        nrm = np.hypot(tx, ty)
        tx, ty = tx / nrm, ty / nrm
        off = width / 2.0 + 3.0
        zl = _sample(ground, gt, x - ty * off, y + tx * off)
        zr = _sample(ground, gt, x + ty * off, y - tx * off)
        d = np.nan_to_num(zl - zr)
        d = _smooth(d, 41)
        side = np.where(np.abs(d) < 0.05, 0.0, np.sign(d))
        side[0] = side[0] if side[0] != 0 else 1.0
        idx = np.where(side != 0, np.arange(n), 0)
        side = side[np.maximum.accumulate(idx)]

        # report
        in_dem = ~np.isnan(_sample(ground, gt, x, y))
        length = s[-1]
        eff_max = float(np.max(g))
        log("Road %d: %.0f m long, %.1f m -> %.1f m (%s), %d curve samples, tightest radius %.0f m" % (
            li, length, z0, reached, "descending" if direction == "down" else "ascending",
            int(curve.sum()), float(np.min(rad)) if np.isfinite(rad).any() else float("inf")))
        if in_dem.mean() < 0.9:
            log("WARNING: road %d: %.0f%% of the centreline is outside the DEM." % (
                li, 100 * (1 - in_dem.mean())))
        if np.isfinite(rad).any() and float(np.min(rad)) < min_radius:
            log("WARNING: road %d has a curve of radius %.0f m, tighter than your minimum of "
                "%.0f m. Redraw it with a larger radius, or use a larger 'smooth centreline' value."
                % (li, float(np.min(rad)), min_radius))
        if traffic == "two_way" and curve.any():
            # Two-way ramps are best designed to the inside (shortest) edge: on a
            # bend the inside lane is a shorter path, so it is steeper than the centreline.
            inner = rad - width / 2.0
            with np.errstate(divide="ignore", invalid="ignore"):
                steep = np.where(curve & np.isfinite(rad) & (g > 0),
                                 np.where(inner > 0.5, g * rad / inner, np.inf), 0.0)
            worst = float(steep.max())
            if worst * 100.0 > GRADE_LIMIT_PCT:
                k = int(np.argmax(steep))
                what = ("not workable (the radius is smaller than half the road width)" if not np.isfinite(worst)
                        else "about %.0f%% steep (centreline %.1f%%)" % (worst * 100.0, g[k] * 100.0))
                log("WARNING: road %d: on its tightest bend, %.0f m from the start, the inside edge of the "
                    "two-way road is %s. The paper advises designing two-way ramps to the shortest "
                    "(inside) edge. Use a larger radius or a bigger gradient reduction on curves."
                    % (li, s[k], what))
        if end_elev is not None:
            need = abs(z0 - end_elev)
            need_len = (need / grade if grade > 0 else float("inf")) + max(landing_m or 0.0, 0.0)
            if (direction == "down" and reached > end_elev + 0.05) or \
               (direction == "up" and reached < end_elev - 0.05):
                log("WARNING: road %d stops at %.1f m, still %.1f m short of %.1f m. At %.1f%% it "
                    "needs at least %.0f m of road (more if curves are eased); it is %.0f m."
                    % (li, reached, abs(reached - end_elev), end_elev, grade_pct, need_len, length))
            else:
                log("Road %d reaches %.1f m after %.0f m and then runs level." % (
                    li, end_elev, need_len))
        X.append(x); Y.append(y); Z.append(z); W.append(width)
        DS.append(side); TX.append(tx); TY.append(ty)
        geoms.append(dict(x=x, y=y, z=z, hw=width / 2.0, s=s, g=g, curve=curve,
                          side=side, tx=tx, ty=ty, xf=xf))

    X, Y, Z, W, DS, TX, TY = [np.concatenate(a) for a in (X, Y, Z, W, DS, TX, TY)]
    N = X.size
    half_all = W / 2.0

    # work only on a sub-grid around the roads
    pad = ROAD_MAX_REACH + 3 * cell
    c_lo = max(0, int(np.floor((X.min() - pad - gt[0]) / cell)))
    c_hi = min(ground.shape[1], int(np.ceil((X.max() + pad - gt[0]) / cell)) + 1)
    r_lo = max(0, int(np.floor((gt[3] - (Y.max() + pad)) / cell)))
    r_hi = min(ground.shape[0], int(np.ceil((gt[3] - (Y.min() - pad)) / cell)) + 1)
    if c_hi <= c_lo or r_hi <= r_lo:
        raise RuntimeError("The road does not overlap the DEM.")
    g0 = ground[r_lo:r_hi, c_lo:c_hi]
    rows, cols = g0.shape
    ox = gt[0] + c_lo * cell
    oy = gt[3] - r_lo * cell

    hi_env = np.full(g0.shape, np.inf, np.float32)
    lo_env = np.full(g0.shape, -np.inf, np.float32)
    dist_n = np.full(g0.shape, np.inf, np.float32)
    cross_n = np.zeros(g0.shape, np.float32)
    idx_n = np.full(g0.shape, -1, np.int32)
    capped = 0

    for k in range(N):
        if (k & 63) == 0 and is_canceled():
            raise Cancelled()
        xk, yk, zk, tx, ty, dsk = X[k], Y[k], Z[k], TX[k], TY[k], DS[k]
        half = half_all[k]
        fw_in, fw_out = half + ditch_w, half + wind_w
        fw_min = half + min(ditch_w, wind_w)
        cf = (xk - ox) / cell - 0.5
        rf = (oy - yk) / cell - 0.5
        R = max(fw_in, fw_out) + 2 * cell
        win = None
        while True:
            rc = int(np.ceil(R / cell))
            c0 = max(0, int(np.floor(cf)) - rc)
            c1 = min(cols, int(np.floor(cf)) + rc + 2)
            r0 = max(0, int(np.floor(rf)) - rc)
            r1 = min(rows, int(np.floor(rf)) + rc + 2)
            if c1 <= c0 or r1 <= r0:
                break
            win = (r0, r1, c0, c1)
            sub = g0[r0:r1, c0:c1]
            hmax = np.fmax.reduce(sub, axis=None)
            hmin = np.fmin.reduce(sub, axis=None)
            if np.isnan(hmax):
                break
            eb = max(R - fw_min, 0.0)
            hi_b = zk - xf * half + eb / cut_ratio
            lo_b = zk + xf * half - eb / fill_ratio
            if hi_b >= hmax and lo_b <= hmin:
                break
            if R >= ROAD_MAX_REACH:
                capped += 1
                break
            R = min(R * 1.6, ROAD_MAX_REACH)
        if win is None:
            continue
        r0, r1, c0, c1 = win
        dx = (ox + (np.arange(c0, c1) + 0.5) * cell - xk)[None, :]
        dy = (oy - (np.arange(r0, r1) + 0.5) * cell - yk)[:, None]
        dist = np.hypot(dx, dy)
        cross = tx * dy - ty * dx
        ud = cross * dsk
        fw = np.where(ud > 0, fw_in, fw_out)
        e = np.maximum(dist - fw, 0.0)
        ze = zk - xf * np.sign(ud) * half
        hv = hi_env[r0:r1, c0:c1]
        np.minimum(hv, ze + e / cut_ratio, out=hv)
        lv = lo_env[r0:r1, c0:c1]
        np.maximum(lv, ze - e / fill_ratio, out=lv)
        dn = dist_n[r0:r1, c0:c1]
        better = dist < dn
        dn[better] = dist[better]
        idx_n[r0:r1, c0:c1][better] = k
        cross_n[r0:r1, c0:c1][better] = cross[better]

    if capped:
        log("WARNING: the cut/fill tie-in was cut off at %.0f m from the road at %d points; "
            "very high walls beside the road may show a step where it stops." % (ROAD_MAX_REACH, capped))

    # batters: keep the ground between the fill envelope and the cut envelope
    final = np.minimum(np.maximum(g0, lo_env), hi_env)

    valid = idx_n >= 0
    i = np.where(valid, idx_n, 0)
    a = dist_n.astype(np.float64)
    hh = half_all[i]
    ud_n = cross_n * DS[i]
    zi = Z[i]
    inner = ud_n > 0
    road = valid & (a <= hh)
    final[road] = (zi - xf * np.clip(ud_n, -hh, hh))[road]
    zone = road.copy()
    if ditch_w > 0:
        dz = valid & inner & (a > hh) & (a <= hh + ditch_w)
        xd = a - hh
        ze_in = zi - xf * hh
        depth = np.where(xd <= DITCH_INSIDE_SLOPE * ditch_depth, xd / DITCH_INSIDE_SLOPE,
                         ditch_depth - (xd - DITCH_INSIDE_SLOPE * ditch_depth) / DITCH_OUTSIDE_SLOPE)
        final[dz] = (ze_in - depth)[dz]
        zone |= dz
    clipped = 0
    if cap is not None:
        capw = cap[r_lo:r_hi, c_lo:c_hi]
        with np.errstate(invalid="ignore"):
            over = zone & (final > capw + 0.05)
            clipped = int(over.sum())
            final = np.where(np.isnan(capw), final, np.minimum(final, capw))
    if wind_w > 0:
        wz = valid & ~inner & (a > hh) & (a <= hh + wind_w)
        xw = a - hh
        ze_out = zi + xf * hh
        if cap is not None:
            with np.errstate(invalid="ignore"):
                wz &= ~(ze_out > capw + 0.05)
        prof = windrow_h * (1.0 - np.abs(xw - WINDROW_SIDE_SLOPE * windrow_h)
                            / (WINDROW_SIDE_SLOPE * windrow_h))
        final[wz] = (ze_out + prof)[wz]
        zone |= wz

    with np.errstate(invalid="ignore"):
        diff = final - g0
        changed_sub = zone | (np.abs(diff) > 1e-3)
    changed_sub &= ~np.isnan(final)
    fill_vol = float(np.nansum(np.where(diff > 0, diff, 0.0))) * cell ** 2
    cut_vol = float(-np.nansum(np.where(diff < 0, diff, 0.0))) * cell ** 2

    out = ground.copy()
    out[r_lo:r_hi, c_lo:c_hi] = final
    changed = np.zeros(ground.shape, bool)
    changed[r_lo:r_hi, c_lo:c_hi] = changed_sub
    road_zone = np.zeros(ground.shape, bool)
    road_zone[r_lo:r_hi, c_lo:c_hi] = zone
    if cap is not None:
        log("Roads (no fill, pit mode): the road never rises above the original ground; inside the pit "
            "it is left as unexcavated rock. Rock left for roads/walls vs the pit surface: %s m3." %
            format(int(round(fill_vol)), ","))
        if clipped:
            log("WARNING: %d road cells would have been above the original ground (the terrain falls away beside "
                "or under the road) and were trimmed to ground, because the pit road is cut-only." % clipped)
    else:
        log("Roads: cut %s m3, fill %s m3, area touched %.2f ha" % (
            format(int(round(cut_vol)), ","), format(int(round(fill_vol)), ","),
            changed.sum() * cell ** 2 / 1e4))
    stats = {"road_cut": cut_vol, "road_fill": fill_vol, "road_cells": int(changed.sum()),
             "road_samples": int(N), "curve_samples": n_curve_total, "road_geom": geoms,
             "road_zone": road_zone}
    return out.astype(np.float32), changed, stats


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def _check(is_canceled):
    if is_canceled():
        raise Cancelled()



# --------------------------------------------------------------------------
# Automatic spiral ramp
# --------------------------------------------------------------------------
def road_widths(opts):
    """(straight, curve) running width in metres for a set of road options."""
    if opts.get("width_override"):
        w = float(opts["width_override"])
        return w, w
    f_s, f_c = TRAFFIC_WIDTHS[opts["traffic"]]
    return f_s * opts["truck_width"], f_c * opts["truck_width"]


def _profile_reach(x, y, s, z0, end_elev, sign, grade, ease, curve_radius, landing):
    """Distance along the road at which the profile reaches end_elev (None if never)."""
    rad = _radius(x, y, s)
    g = np.where(rad < curve_radius, max(grade - ease, 0.0), grade)
    if landing and landing > 0:
        g = np.where(s < landing, 0.0, g)
    ds = np.diff(s, prepend=s[0])
    z = z0 + sign * np.cumsum(g * ds)
    hit = np.where(z <= end_elev if sign < 0 else z >= end_elev)[0]
    return (float(s[hit[0]]) if hit.size else None)


def design_spiral(dist, dem, gt, kind, ref_elev, end_elev, bench_h, cycle, opts,
                  ccw=True, start_xy=None, tail=40.0, log=_noop, is_canceled=lambda: False):
    """Route a spiral haul road along the wall and return it as a WKT LineString.

    The road follows the benched wall: at every point its inward distance from
    the outline matches the average wall line at the road's elevation, so the
    ramp winds around the pit (or dump) at the design gradient. `kind` is
    'pit' (descends from the rim) or 'pile' (climbs from the base).
    """
    try:
        from scipy.ndimage import gaussian_filter, map_coordinates
        from scipy.spatial import cKDTree
    except ImportError:
        raise RuntimeError("The automatic spiral road needs scipy (included with QGIS). "
                           "Digitize a road centreline instead.")
    cell = gt[1]
    sign = -1.0 if kind == "pit" else 1.0
    grade = opts["grade_pct"] / 100.0
    ease = opts["curve_easing_pct"] / 100.0
    curve_radius = opts["curve_radius"]
    landing = max(opts.get("landing_m") or 0.0, 0.0)
    w_s, w_c = road_widths(opts)
    hw = max(w_s, w_c) / 2.0
    per_h = cycle / bench_h                      # horizontal metres of wall per metre of height

    sm = gaussian_filter(dist.astype(np.float32), 8.0 / cell)
    gr, gc = np.gradient(sm, cell)               # rows increase southward
    nx, ny = gc, -gr
    mag = np.hypot(nx, ny)
    nx = np.where(mag > 1e-6, nx / np.maximum(mag, 1e-6), 0.0).astype(np.float32)
    ny = np.where(mag > 1e-6, ny / np.maximum(mag, 1e-6), 0.0).astype(np.float32)
    d_max = float(dist.max())
    if d_max < hw + 4.0:
        raise RuntimeError("The footprint is too narrow for a road of %.0f m width." % (2 * hw))

    def at(arr, x, y):
        c = (x - gt[0]) / cell - 0.5
        r = (gt[3] - y) / cell - 0.5
        return float(map_coordinates(arr, [[r], [c]], order=1, mode="nearest")[0])

    ground_ok = ~np.isnan(dem)
    # start: lowest original ground on the entry ring
    r0 = hw + 2.0
    def ring(d):
        return (np.abs(dist - d) <= 1.0) & ground_ok
    if start_xy is not None:
        sx, sy = start_xy
        z0 = at(np.nan_to_num(dem), sx, sy)
    else:
        rr = ring(r0)
        if not rr.any():
            raise RuntimeError("No DEM data near the footprint edge to start the road from.")
        z0 = float(np.nanmin(dem[rr]))
        d_start = max(r0, abs(z0 - ref_elev) * per_h)
        rr = ring(min(d_start, d_max * 0.9))
        cand = np.where(rr)
        k = int(np.argmin(dem[cand]))
        rr_, cc_ = cand[0][k], cand[1][k]
        sx = gt[0] + (cc_ + 0.5) * cell
        sy = gt[3] - (rr_ + 0.5) * cell
        z0 = float(dem[rr_, cc_])
    drop = abs(end_elev - z0)
    if drop < 0.5:
        raise RuntimeError("The spiral road would have nowhere to go: start ground %.1f m is already "
                           "at the end elevation %.1f m." % (z0, end_elev))

    step = 2.0
    def trace(gk, length):
        x, y = sx, sy
        px, py = [x], [y]
        s = 0.0
        hx = hy = None
        while s < length:
            tx_ = at(nx, x, y); ty_ = at(ny, x, y)
            m = math.hypot(tx_, ty_)
            if m < 0.3:
                if hx is None:
                    break
                ux, uy = hx, hy
            else:
                ux, uy = tx_ / m, ty_ / m
            # tangent with the interior on the left (counter-clockwise travel)
            tx_, ty_ = (uy, -ux) if ccw else (-uy, ux)
            kk = 0.0 if s < landing else min(per_h * gk, 0.6)
            hx, hy = tx_ * math.sqrt(1 - kk * kk) + ux * kk, ty_ * math.sqrt(1 - kk * kk) + uy * kk
            x += hx * step; y += hy * step
            s += step
            c = (x - gt[0]) / cell; r = (gt[3] - y) / cell
            if not (0 <= c < dist.shape[1] and 0 <= r < dist.shape[0]) or at(dist, x, y) < 1.0:
                break
            if at(sm, x, y) > d_max * 0.97:
                break
            px.append(x); py.append(y)
            hx, hy = (hx, hy)
        return px, py

    gk = grade
    final = None
    for it in range(4):
        if is_canceled():
            raise Cancelled()
        length = (drop / gk + landing) * 1.25 + 20.0
        px, py = trace(gk, length)
        if len(px) < 5:
            raise RuntimeError("Could not route a spiral road from the chosen start point.")
        pts = ";".join("%f %f" % p for p in zip(px, py))
        ln = _lines_from_wkt(["LINESTRING(%s)" % pts.replace(";", ",")], cell, 0.0)
        if not ln:
            raise RuntimeError("Could not route a spiral road from the chosen start point.")
        x, y, s = ln[0]
        reach = _profile_reach(x, y, s, z0, end_elev, sign, grade, ease, curve_radius, landing)
        final = (x, y, s, reach)
        if reach is None:
            if s[-1] < length - 3 * step:
                break                            # ran out of room before reaching the end
            gk = gk * 0.85
            continue
        new_gk = drop / max(reach - landing, 1.0)
        if abs(new_gk - gk) / gk < 0.01:
            break
        gk = new_gk
    x, y, s, reach = final
    if reach is None:
        log("WARNING: the spiral ran out of room: the pit/dump is too small to hold a %.1f%% ramp from %.1f m "
            "down/up to %.1f m. Use a steeper gradient, a lower floor/crest, or a bigger footprint." % (
                opts["grade_pct"], z0, end_elev))
        keep = np.ones(x.size, bool)
    else:
        keep = s <= reach + tail
    x, y, s = x[keep], y[keep], s[keep]
    # lanes of successive turns must not overlap
    tree = cKDTree(np.column_stack([x, y]))
    close = 0
    for i, js in enumerate(tree.query_ball_point(np.column_stack([x, y])[::5], 2 * hw + 2.0)):
        i *= 5
        if any(abs(s[j] - s[i]) > 4 * hw + 20 for j in js):
            close += 1
    if close:
        log("WARNING: successive turns of the spiral are closer than one road width + 2 m at %d places "
            "(the wall is too steep or the gradient too flat for one ramp). Use a steeper gradient or a "
            "wider bench spacing." % close)
    turns = 0.0
    hd = np.unwrap(np.arctan2(np.gradient(y), np.gradient(x)))
    turns = abs(hd[-1] - hd[0]) / (2 * math.pi)
    log("Spiral road: start (%.0f, %.0f) at %.1f m, %.0f m long, about %.1f turns, %s." % (
        sx, sy, z0, s[-1], turns, "counter-clockwise" if ccw else "clockwise") +
        (" Descending." if sign < 0 else " Ascending."))
    return "LINESTRING(%s)" % ",".join("%f %f" % p for p in zip(x, y)), z0


# --------------------------------------------------------------------------
# Drawing vectors (bench crest / toe lines, road lines and polygons)
# --------------------------------------------------------------------------
def _vector_ds(path, layer_name, geom_type, fields, proj_wkt):
    ext = os.path.splitext(path)[1].lower()
    drv = ogr.GetDriverByName({".shp": "ESRI Shapefile", ".geojson": "GeoJSON"}.get(ext, "GPKG"))
    if os.path.exists(path):
        drv.DeleteDataSource(path)
    ds = drv.CreateDataSource(path)
    srs = osr.SpatialReference()
    srs.ImportFromWkt(proj_wkt)
    lyr = ds.CreateLayer(layer_name, srs=srs, geom_type=geom_type)
    for name, typ in fields:
        lyr.CreateField(ogr.FieldDefn(name, typ))
    return ds, lyr


def bench_levels(kind, ref, bench_h, bench_w, angle_or_slope, limit):
    """[(inward distance, elevation, 'CREST'|'TOE', bench no.)] for a pit or dump.

    pit: ref=rim, limit=floor, angle_or_slope=wall angle in degrees.
    pile: ref=base, limit=crest elevation, angle_or_slope=tan(slope) (V/H).
    """
    tan_a = math.tan(math.radians(angle_or_slope)) if kind == "pit" else angle_or_slope
    wall_run = bench_h / tan_a
    cycle = wall_run + bench_w
    out = []
    n = 0
    while n < 200:
        if kind == "pit":
            top = ref - n * bench_h
            if top <= limit + 1e-6:
                break
            bot = max(top - bench_h, limit)
            d_top = n * cycle
            d_bot = d_top + (top - bot) / tan_a
            if n == 0 or bench_w >= 0.01:
                out.append((d_top, top, "CREST", n + 1))
            out.append((d_bot, bot, "TOE", n + 1))
        else:
            bot = ref + n * bench_h
            if bot >= limit - 1e-6:
                break
            top = min(bot + bench_h, limit)
            d_bot = n * cycle
            d_top = d_bot + (top - bot) / tan_a
            if n == 0 or bench_w >= 0.01:
                out.append((d_bot, bot, "TOE", n + 1))
            out.append((d_top, top, "CREST", n + 1))
        n += 1
    return out


def write_bench_lines(dist, valid, gt, proj, levels, out_path, inside=None):
    """Crest and toe polylines: contours of the inward distance at each bench edge,
    drawn only where `valid` (the design really cuts / fills the ground)."""
    rows, cols = dist.shape
    outside = (~inside) if inside is not None else np.zeros(dist.shape, bool)
    data = np.where(valid, dist, np.where(outside, 0.0, OUT_NODATA)).astype(np.float32)
    mem = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Float32)
    mem.SetGeoTransform(gt)
    mem.SetProjection(proj)
    band = mem.GetRasterBand(1)
    band.SetNoDataValue(OUT_NODATA)
    band.WriteArray(data)
    fixed = sorted({max(round(l[0], 3), 0.5) for l in levels})
    tmp = ogr.GetDriverByName("Memory").CreateDataSource("t")
    tl = tmp.CreateLayer("t", geom_type=ogr.wkbLineString)
    tl.CreateField(ogr.FieldDefn("ID", ogr.OFTInteger))
    tl.CreateField(ogr.FieldDefn("DIST", ogr.OFTReal))
    gdal.ContourGenerate(band, 0.0, 0.0, fixed, 1, OUT_NODATA, tl, 0, 1)
    ds, lyr = _vector_ds(out_path, "bench_lines", ogr.wkbLineString,
                         [("TYPE", ogr.OFTString), ("BENCH", ogr.OFTInteger), ("ELEVATION", ogr.OFTReal)], proj)
    by_level = {}
    for d, z, kind, n in levels:
        by_level.setdefault(max(round(d, 3), 0.5), []).append((z, kind, n))
    count = 0
    for f in tl:
        lv = round(f.GetField("DIST"), 3)
        for z, kind, n in by_level.get(lv, []):
            o = ogr.Feature(lyr.GetLayerDefn())
            o.SetGeometry(f.GetGeometryRef().Clone())
            o.SetField("TYPE", kind); o.SetField("BENCH", n); o.SetField("ELEVATION", float(z))
            lyr.CreateFeature(o)
            count += 1
    ds = tmp = mem = None
    return count


def write_surface_strings(surface, valid, gt, proj, levels, out_path, eps=0.02):
    """Bench crest and toe strings at constant elevation, taken from the FINISHED surface.

    Each bench edge is traced at its elevation (just above the bench floor for a toe,
    just below the bench top for a crest), so the strings follow the projected bench
    geometry and are adjusted wherever a road cuts or fills through the wall.
    `levels` comes from bench_levels(): (distance, elevation, TYPE, bench no.).
    """
    rows, cols = surface.shape
    data = np.where(valid & ~np.isnan(surface), surface, OUT_NODATA).astype(np.float32)
    mem = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Float32)
    mem.SetGeoTransform(gt)
    mem.SetProjection(proj)
    band = mem.GetRasterBand(1)
    band.SetNoDataValue(OUT_NODATA)
    band.WriteArray(data)
    by_level = {}
    for d, z, kind, n in levels:
        lv = round(z + eps if kind == "TOE" else z - eps, 4)
        by_level.setdefault(lv, []).append((z, kind, n))
    tmp = ogr.GetDriverByName("Memory").CreateDataSource("t")
    tl = tmp.CreateLayer("t", geom_type=ogr.wkbLineString)
    tl.CreateField(ogr.FieldDefn("ID", ogr.OFTInteger))
    tl.CreateField(ogr.FieldDefn("LV", ogr.OFTReal))
    gdal.ContourGenerate(band, 0.0, 0.0, sorted(by_level), 1, OUT_NODATA, tl, 0, 1)
    ds, lyr = _vector_ds(out_path, "bench_strings", ogr.wkbLineString,
                         [("TYPE", ogr.OFTString), ("BENCH", ogr.OFTInteger), ("ELEVATION", ogr.OFTReal)], proj)
    count = 0
    for f in tl:
        for z, kind, n in by_level.get(round(f.GetField("LV"), 4), []):
            o = ogr.Feature(lyr.GetLayerDefn())
            o.SetGeometry(f.GetGeometryRef().Clone())
            o.SetField("TYPE", kind); o.SetField("BENCH", n); o.SetField("ELEVATION", float(z))
            lyr.CreateFeature(o)
            count += 1
    ds = tmp = mem = None
    return count


def write_road_vectors(geoms, proj, out_lines=None, out_polys=None, seg_m=25.0):
    """Road centreline and edge lines, and road surface polygons, cut into segments."""
    ls = lp = dl = dp = None
    fields = [("ROAD", ogr.OFTInteger), ("SEG", ogr.OFTInteger), ("ELEV_START", ogr.OFTReal),
              ("ELEV_END", ogr.OFTReal), ("GRADE_PCT", ogr.OFTReal), ("WIDTH", ogr.OFTReal),
              ("CURVE", ogr.OFTInteger)]
    if out_lines:
        dl, ls = _vector_ds(out_lines, "road_lines", ogr.wkbLineString,
                            [("TYPE", ogr.OFTString)] + fields + [("ELEVATION", ogr.OFTReal)], proj_wkt=proj)
    if out_polys:
        dp, lp = _vector_ds(out_polys, "road_polygons", ogr.wkbPolygon, fields, proj_wkt=proj)
    nl = npoly = 0
    for ri, g in enumerate(geoms, 1):
        x, y, z, hw, s = g["x"], g["y"], g["z"], g["hw"], g["s"]
        tx, ty, side, xf = g["tx"], g["ty"], g["side"], g["xf"]
        lx, ly = x - ty * hw, y + tx * hw
        rx, ry = x + ty * hw, y - tx * hw
        lz, rz = z - side * xf * hw, z + side * xf * hw
        n = x.size
        edges = [0]
        while edges[-1] < n - 1:
            nxt = int(np.searchsorted(s, s[edges[-1]] + seg_m))
            edges.append(min(max(nxt, edges[-1] + 1), n - 1))
        for si, (i0, i1) in enumerate(zip(edges[:-1], edges[1:]), 1):
            sl = slice(i0, i1 + 1)
            length = max(s[i1] - s[i0], 1e-6)
            attrs = dict(ROAD=ri, SEG=si, ELEV_START=float(z[i0]), ELEV_END=float(z[i1]),
                         GRADE_PCT=float(abs(z[i1] - z[i0]) / length * 100.0),
                         WIDTH=float(2 * hw[i0:i1 + 1].mean()), CURVE=int(g["curve"][sl].any()))

            def put(layer, geom, extra=None):
                f = ogr.Feature(layer.GetLayerDefn())
                f.SetGeometry(geom)
                for k, v in dict(attrs, **(extra or {})).items():
                    f.SetField(k, v)
                layer.CreateFeature(f)

            if ls is not None:
                for kind, xs, ys, zs in (("CENTRE", x, y, z), ("EDGE_L", lx, ly, lz), ("EDGE_R", rx, ry, rz)):
                    ln = ogr.Geometry(ogr.wkbLineString)
                    for a, b in zip(xs[sl], ys[sl]):
                        ln.AddPoint_2D(float(a), float(b))
                    put(ls, ln, {"TYPE": kind, "ELEVATION": float(zs[sl].mean())})
                    nl += 1
            if lp is not None:
                ring = ogr.Geometry(ogr.wkbLinearRing)
                for a, b in zip(lx[sl], ly[sl]):
                    ring.AddPoint_2D(float(a), float(b))
                for a, b in zip(rx[sl][::-1], ry[sl][::-1]):
                    ring.AddPoint_2D(float(a), float(b))
                ring.CloseRings()
                poly = ogr.Geometry(ogr.wkbPolygon)
                poly.AddGeometry(ring)
                put(lp, poly)
                npoly += 1
    dl = dp = None
    return nl, npoly



try:
    from . import validate
except ImportError:          # tests import this file as a plain module
    import validate


def _manual_edit_notice(geoms, kind, log):
    for i, g in enumerate(geoms, 1):
        k = int(np.argmin(g["z"])) if kind == "pit" else int(np.argmax(g["z"]))
        log("NOTE road %d: its %s end is at (%.0f, %.0f), elevation %.1f m, on the %s. Where the road meets the %s "
            "the strings are NOT adjusted for equipment access (entry, turning area, switchback): edit the "
            "strings by hand there." % (i, "lowest" if kind == "pit" else "highest", g["x"][k], g["y"][k], g["z"][k],
                                        "pit floor" if kind == "pit" else "dump crest",
                                        "lowest string" if kind == "pit" else "top string"))


def _grow(mask, cells):
    try:
        from scipy.ndimage import binary_dilation
        return binary_dilation(mask, iterations=int(cells))
    except ImportError:
        return mask


def _auto_road_lines(roads, opts, kind, dist, dem, gt, ref, target_elev, bench_h, cycle, log, is_canceled):
    """Digitized road lines if given, otherwise an automatic spiral (when requested).

    target_elev is the far end of the ramp: the pit floor, or the dump crest.
    Build order (auto["bottom_up"], default True): the road starts at its LOWEST end and
    climbs. For a pit that is the floor, ending where the ramp meets the original ground
    at the rim. False = start at the high end and descend.
    """
    wkts = list(roads.get("line_wkts") or [])
    if wkts:
        return wkts, opts
    auto = roads.get("auto")
    if not auto:
        return [], opts
    start_xy = None
    for w in auto.get("start_wkts") or []:
        g = ogr.CreateGeometryFromWkt(w)
        if g is not None and g.GetPointCount() > 0:
            start_xy = (g.GetX(0), g.GetY(0))
            break
    bottom_up = auto.get("bottom_up", True)
    if "climb_cw" in auto:
        # loaded trucks climb clockwise/counter-clockwise; the trace runs down a pit, up a dump
        ccw = auto["climb_cw"] if kind == "pit" else (not auto["climb_cw"])
    else:
        ccw = auto.get("ccw", True)
    log("Routing spiral haul road (%s) ..." % ("built from the lowest end up" if bottom_up else "built from the top down"))
    line, z0 = design_spiral(dist, dem, gt, kind, ref, target_elev, bench_h, cycle, opts, ccw=ccw,
                             start_xy=start_xy, tail=(0.0 if (kind == "pit" and bottom_up) else 40.0),
                             log=log, is_canceled=is_canceled)
    opts = dict(opts)
    # the trace runs rim -> floor (pit) or base -> crest (dump); reverse it for the other build order
    reverse = (kind == "pit" and bottom_up) or (kind == "pile" and not bottom_up)
    if reverse:
        pts = [tuple(float(v) for v in p.split()) for p in line[len("LINESTRING("):-1].split(",")]
        line = "LINESTRING(%s)" % ",".join("%f %f" % p for p in pts[::-1])
    climbs = bottom_up
    opts["direction"] = "up" if climbs else "down"
    if kind == "pit":
        low, high = target_elev, z0          # floor, ground at the rim
    else:
        low, high = z0, target_elev          # ground at the base, crest
    opts["start_elev"] = low if climbs else high
    opts["end_elev"] = high if climbs else low
    return [line], opts


def _road_impact(kind, before_vol, after_vol, area_before, area_after, changed_area, log):
    sign = "cut" if kind == "pit" else "fill"
    d = after_vol - before_vol
    log("Road impact (%s): %s volume %s -> %s m3 (%s%s m3); %s area %.2f -> %.2f ha (%+.2f ha); "
        "ground reshaped by the road works %.2f ha." % (
            "pit" if kind == "pit" else "dump", sign, format(int(round(before_vol)), ","),
            format(int(round(after_vol)), ","), "+" if d >= 0 else "-", format(int(round(abs(d))), ","),
            "pit floor" if kind == "pit" else "dump crest", area_before / 1e4, area_after / 1e4,
            (area_after - area_before) / 1e4, changed_area / 1e4))


def run_pit(dem_path, dst_srs_wkt, wkt_list, rim, floor, bench_h, bench_w,
            wall_angle, out_dem, out_contours=None, contour_interval=5.0,
            roads=None, out_benches=None, out_road_lines=None, out_road_polys=None,
            max_ira=None, log=_noop, progress=_noop, is_canceled=lambda: False):
    work = tempfile.mkdtemp(prefix="benched_mining_")
    try:
        log("Resampling DEM to %.1f m ..." % CELL_SIZE)
        progress(10)
        dem, gt, proj = prepare_dem(dem_path, work, dst_srs_wkt)
        log("Working grid: %d x %d cells" % (dem.shape[1], dem.shape[0]))
        _check(is_canceled)

        log("Rasterizing pit outline ...")
        progress(30)
        mask = rasterize_footprint(wkt_list, dem.shape, gt, proj)
        n_in = int(mask.sum())
        if n_in == 0:
            raise RuntimeError(
                "The pit outline does not overlap the DEM. Check that both "
                "cover the same area."
            )
        log("Footprint: %s cells (%.2f ha)" % (format(n_in, ","), n_in * CELL_SIZE ** 2 / 1e4))
        validate.check_outline(wkt_list, log)
        _check(is_canceled)

        log("Calculating inward distance ...")
        progress(45)
        dist = inward_distance(mask)
        _check(is_canceled)

        log("Building benched pit surface ...")
        progress(60)
        surf = pit_surface(dist, rim, bench_h, bench_w, wall_angle, floor)
        out = dem.copy()
        # Excavation only removes ground; where the design surface is above
        # the terrain (outline sits above topography) the ground is untouched.
        cut_cells = mask & ~np.isnan(dem) & (surf < dem)
        out[cut_cells] = surf[cut_cells]
        cut_vol = float(np.sum(dem[cut_cells] - surf[cut_cells])) * CELL_SIZE ** 2
        log("Excavated area: %.2f ha, cut volume: %s m3" % (
            cut_cells.sum() * CELL_SIZE ** 2 / 1e4, format(int(round(cut_vol)), ",")))
        if cut_cells.sum() == 0:
            log("WARNING: nothing was excavated. The rim elevation may be below "
                "the terrain inside the outline.")
        validate.check_design("pit", bench_h, bench_w, wall_angle, rim, floor, mask, dist, surf, dem, CELL_SIZE,
                              contour_interval if out_contours else None, max_ira, log)
        _check(is_canceled)

        road_changed, road_stats = None, {}
        if roads:
            opts = dict(roads["options"])
            if opts.get("end_elev") is None:
                opts["end_elev"] = floor if opts["direction"] == "down" else rim
            cycle = bench_h / math.tan(math.radians(wall_angle)) + bench_w
            cut_vol_before = cut_vol
            floor_before = float(np.sum(mask & (surf <= floor + 0.01))) * CELL_SIZE ** 2
            road_wkts, opts = _auto_road_lines(roads, opts, "pit", dist, dem, gt, rim, floor,
                                               bench_h, cycle, log, is_canceled)
            log("Designing haul road(s) ...")
            progress(70)
            out, road_changed, road_stats = apply_roads(
                out, gt, road_wkts, cap=dem, log=log, is_canceled=is_canceled, **opts)
            _check(is_canceled)
            both = ~np.isnan(dem) & ~np.isnan(out)
            cut_vol = float(np.sum(np.where(both & (out < dem), dem - out, 0.0))) * CELL_SIZE ** 2
            floor_after = float(np.sum(mask & ~np.isnan(out) & (out <= floor + 0.01))) * CELL_SIZE ** 2
            _road_impact("pit", cut_vol_before, cut_vol, floor_before, floor_after,
                         float(np.sum(road_changed & mask)) * CELL_SIZE ** 2, log)
        cmask = mask if road_changed is None else (mask | road_changed)
        geoms = road_stats.pop("road_geom", None)
        zone = road_stats.pop("road_zone", None)
        if zone is not None:
            zone = _grow(zone, 2)
        if geoms:
            validate.check_roads("pit", geoms, out, dem, mask, gt, opts.get("end_elev"),
                                 (roads or {}).get("stopping_m"), CELL_SIZE, log)
            _manual_edit_notice(geoms, "pit", log)

        progress(80)
        if out_dem:
            log("Writing output DEM ...")
            write_raster(out_dem, out, gt, proj)
        else:
            log("No output DEM requested; the modified surface is used only to build the contours and ramp designs.")

        n_lines = 0
        if out_contours:
            log("Generating contours every %g m ..." % contour_interval)
            progress(90)
            n_lines = write_contours(out, cmask, gt, proj, contour_interval, out_contours)
            log("Contour lines created: %d" % n_lines)
        written = {}
        if out_benches:
            lv = bench_levels("pit", rim, bench_h, bench_w, wall_angle, floor)
            written["benches"] = write_surface_strings(out, _grow(cmask, 3), gt, proj, lv, out_benches)
            log("Bench crest/toe strings created: %d (constant elevation, adjusted for the ramp)" % written["benches"])
        if geoms and (out_road_lines or out_road_polys):
            nl, npoly = write_road_vectors(geoms, proj, out_road_lines, out_road_polys)
            written["road_lines"], written["road_polys"] = (nl if out_road_lines else 0), (npoly if out_road_polys else 0)
            log("Road drawing vectors: %d line segments, %d polygons" % (nl, npoly))
        progress(100)
        return dict({"written": written, "cut_volume": cut_vol, "contours": n_lines}, **road_stats)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_pile(dem_path, dst_srs_wkt, wkt_list, base, bench_h, bench_w,
             ratio_h, ratio_v, top, out_dem, out_contours=None,
             contour_interval=5.0, roads=None, out_benches=None, out_road_lines=None,
             out_road_polys=None, log=_noop, progress=_noop,
             is_canceled=lambda: False):
    work = tempfile.mkdtemp(prefix="benched_mining_")
    try:
        log("Resampling DEM to %.1f m ..." % CELL_SIZE)
        progress(10)
        dem, gt, proj = prepare_dem(dem_path, work, dst_srs_wkt)
        log("Working grid: %d x %d cells" % (dem.shape[1], dem.shape[0]))
        _check(is_canceled)

        log("Rasterizing dump footprint ...")
        progress(30)
        mask = rasterize_footprint(wkt_list, dem.shape, gt, proj)
        n_in = int(mask.sum())
        if n_in == 0:
            raise RuntimeError(
                "The dump footprint does not overlap the DEM. Check that both "
                "cover the same area."
            )
        log("Footprint: %s cells (%.2f ha)" % (format(n_in, ","), n_in * CELL_SIZE ** 2 / 1e4))
        validate.check_outline(wkt_list, log)
        _check(is_canceled)

        if base is None:
            ground = dem[mask]
            ground = ground[~np.isnan(ground)]
            if ground.size == 0:
                raise RuntimeError("No DEM data inside the footprint to derive a base elevation.")
            base = float(ground.min())
            log("Base elevation (auto, lowest ground in footprint): %.2f m" % base)
        else:
            log("Base elevation (user): %.2f m" % base)

        log("Calculating inward distance ...")
        progress(45)
        dist = inward_distance(mask)
        _check(is_canceled)

        log("Building benched dump surface ...")
        progress(60)
        surf = pile_surface(dist, base, bench_h, bench_w, ratio_h, ratio_v, top)
        out = dem.copy()
        # A dump only adds material; it never cuts below existing ground.
        ground_ok = ~np.isnan(dem)
        fill_cells = mask & ground_ok & (surf > dem)
        no_ground = mask & ~ground_ok
        out[fill_cells] = surf[fill_cells]
        out[no_ground] = surf[no_ground]
        fill_vol = float(np.sum(surf[fill_cells] - dem[fill_cells])) * CELL_SIZE ** 2
        log("Filled area: %.2f ha, fill volume: %s m3, crest elevation: %.1f m" % (
            fill_cells.sum() * CELL_SIZE ** 2 / 1e4,
            format(int(round(fill_vol)), ","),
            float(np.nanmax(out[mask]))))
        if fill_cells.sum() == 0:
            log("WARNING: nothing was added. The base elevation may be below "
                "the terrain inside the footprint.")
        crest_chk = top if top is not None else float(np.nanmax(surf[mask]))
        validate.check_design("pile", bench_h, bench_w, ratio_v / ratio_h, base, crest_chk, mask, dist, surf, dem,
                              CELL_SIZE, contour_interval if out_contours else None, None, log)
        _check(is_canceled)

        road_changed, road_stats = None, {}
        if roads:
            opts = dict(roads["options"])
            if opts.get("end_elev") is None:
                if opts["direction"] == "up":
                    opts["end_elev"] = top if top is not None else float(np.nanmax(out[mask]))
                else:
                    opts["end_elev"] = base
            tan_s = ratio_v / ratio_h
            cycle = bench_h / tan_s + bench_w
            crest_t = top if top is not None else float(np.nanmax(out[mask]))
            crest_before = float(np.sum(mask & (out >= crest_t - 0.01))) * CELL_SIZE ** 2
            road_wkts, opts = _auto_road_lines(roads, opts, "pile", dist, dem, gt, base, crest_t,
                                               bench_h, cycle, log, is_canceled)
            log("Designing haul road(s) ...")
            progress(70)
            out, road_changed, road_stats = apply_roads(
                out, gt, road_wkts, log=log, is_canceled=is_canceled, **opts)
            _check(is_canceled)
            both = ~np.isnan(dem) & ~np.isnan(out)
            fill_vol_before = fill_vol
            fill_vol = float(np.sum(np.where(both & (out > dem), out - dem, 0.0))) * CELL_SIZE ** 2
            crest_after = float(np.sum(mask & ~np.isnan(out) & (out >= crest_t - 0.01))) * CELL_SIZE ** 2
            _road_impact("pile", fill_vol_before, fill_vol, crest_before, crest_after,
                         float(np.sum(road_changed & mask)) * CELL_SIZE ** 2, log)
        cmask = mask if road_changed is None else (mask | road_changed)
        geoms = road_stats.pop("road_geom", None)
        zone = road_stats.pop("road_zone", None)
        if zone is not None:
            zone = _grow(zone, 2)
        if geoms:
            validate.check_roads("pile", geoms, out, dem, mask, gt, opts.get("end_elev"),
                                 (roads or {}).get("stopping_m"), CELL_SIZE, log)
            _manual_edit_notice(geoms, "pile", log)

        progress(80)
        if out_dem:
            log("Writing output DEM ...")
            write_raster(out_dem, out, gt, proj)
        else:
            log("No output DEM requested; the modified surface is used only to build the contours and ramp designs.")

        n_lines = 0
        if out_contours:
            log("Generating contours every %g m ..." % contour_interval)
            progress(90)
            n_lines = write_contours(out, cmask, gt, proj, contour_interval, out_contours)
            log("Contour lines created: %d" % n_lines)
        written = {}
        if out_benches:
            crest = top if top is not None else float(np.nanmax(surf[mask]))
            lv = bench_levels("pile", base, bench_h, bench_w, ratio_v / ratio_h, crest)
            written["benches"] = write_surface_strings(out, _grow(cmask, 3), gt, proj, lv, out_benches)
            log("Bench crest/toe strings created: %d (constant elevation, adjusted for the ramp)" % written["benches"])
        if geoms and (out_road_lines or out_road_polys):
            nl, npoly = write_road_vectors(geoms, proj, out_road_lines, out_road_polys)
            written["road_lines"], written["road_polys"] = (nl if out_road_lines else 0), (npoly if out_road_polys else 0)
            log("Road drawing vectors: %d line segments, %d polygons" % (nl, npoly))
        progress(100)
        return dict({"written": written, "fill_volume": fill_vol, "contours": n_lines}, **road_stats)
    finally:
        shutil.rmtree(work, ignore_errors=True)
