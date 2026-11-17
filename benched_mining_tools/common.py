"""QGIS-side helpers shared by both algorithms."""

import os
import shutil
import tempfile

from osgeo import gdal
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsRasterFileWriter,
    QgsUnitTypes,
)

from . import core

CANADIAN_UTM_ZONES = [
    "NAD83 / UTM zone 7N - EPSG:26907 (Yukon West)",
    "NAD83 / UTM zone 8N - EPSG:26908 (Yukon, BC West)",
    "NAD83 / UTM zone 9N - EPSG:26909 (BC West, Yukon)",
    "NAD83 / UTM zone 10N - EPSG:26910 (BC West Coast)",
    "NAD83 / UTM zone 11N - EPSG:26911 (BC Interior, AB)",
    "NAD83 / UTM zone 12N - EPSG:26912 (AB, SK)",
    "NAD83 / UTM zone 13N - EPSG:26913 (SK, MB)",
    "NAD83 / UTM zone 14N - EPSG:26914 (MB, ON West)",
    "NAD83 / UTM zone 15N - EPSG:26915 (ON)",
    "NAD83 / UTM zone 16N - EPSG:26916 (ON)",
    "NAD83 / UTM zone 17N - EPSG:26917 (ON, QC)",
    "NAD83 / UTM zone 18N - EPSG:26918 (QC, ON East)",
    "NAD83 / UTM zone 19N - EPSG:26919 (QC)",
    "NAD83 / UTM zone 20N - EPSG:26920 (QC, Labrador)",
    "NAD83 / UTM zone 21N - EPSG:26921 (QC East, Labrador)",
    "NAD83 / UTM zone 22N - EPSG:26922 (Newfoundland)",
]
DEFAULT_ZONE_INDEX = 10  # NAD83 / UTM 17N (last tested area)


def zone_crs(index):
    code = CANADIAN_UTM_ZONES[index].split("EPSG:")[1].split(" ")[0]
    return QgsCoordinateReferenceSystem("EPSG:" + code)


def is_utm(crs):
    """True for any UTM CRS (WGS84, NAD83, CSRS, ...) in metres."""
    if not crs.isValid():
        return False
    utm = crs.projectionAcronym().lower() == "utm" or "UTM" in crs.description().upper()
    return utm and crs.mapUnits() == QgsUnitTypes.DistanceMeters


def resolve_working_crs(dem_crs, poly_crs, target_crs, log):
    """Pick the metric CRS to work in without reprojecting more than needed."""
    if is_utm(dem_crs):
        log("DEM is already UTM (%s); working in that CRS." % dem_crs.authid())
        if is_utm(poly_crs) and poly_crs != dem_crs:
            log("Outline is UTM %s and will be reprojected to match the DEM." % poly_crs.authid())
        elif not is_utm(poly_crs):
            log("Outline CRS %s will be reprojected to match the DEM." % poly_crs.authid())
        return dem_crs
    if is_utm(poly_crs):
        log("Outline is UTM (%s); DEM (%s) will be reprojected to match." % (
            poly_crs.authid(), dem_crs.authid()))
        return poly_crs
    log("Neither layer is UTM (DEM %s, outline %s); reprojecting both to %s." % (
        dem_crs.authid(), poly_crs.authid(), target_crs.authid()))
    return target_crs


def geometry_wkts(source, working_crs, context, feedback, empty_message):
    """Geometries from a feature source, in the working CRS (as WKT).

    The source already honours the 'Selected features only' checkbox.
    """
    xform = None
    if source.sourceCrs() != working_crs:
        xform = QgsCoordinateTransform(source.sourceCrs(), working_crs, context.transformContext())
    wkts = []
    for feat in source.getFeatures():
        if feedback.isCanceled():
            break
        geom = feat.geometry()
        if geom is None or geom.isNull() or geom.isEmpty():
            continue
        geom = QgsGeometry(geom)
        if xform is not None:
            try:
                geom.transform(xform)
            except Exception as exc:  # QgsCsException
                raise QgsProcessingException("Could not reproject the layer: %s" % exc)
        wkts.append(geom.asWkt())
    if not wkts and not feedback.isCanceled():
        raise QgsProcessingException(empty_message)
    return wkts


def footprint_wkts(source, working_crs, context, feedback):
    return geometry_wkts(
        source, working_crs, context, feedback,
        "The outline layer has no usable polygons. If you ticked 'Selected "
        "features only', make sure something is selected.")


def dem_file_path(layer, context):
    """A file path GDAL can open for this raster layer.

    In-memory rasters (for example a DEM downloaded straight into the project)
    are exported to a temporary GeoTIFF first. Returns (path, temp_dir or None).
    """
    path = layer.source().split("|")[0]
    try:
        ds = gdal.Open(path)
        if ds is not None:
            ds = None
            return path, None
    except RuntimeError:
        pass

    tmp = tempfile.mkdtemp(prefix="benched_mining_dem_")
    out = os.path.join(tmp, "dem_export.tif")
    writer = QgsRasterFileWriter(out)
    err = writer.writeRaster(
        layer.pipe(), layer.width(), layer.height(), layer.extent(),
        layer.crs(), context.transformContext(),
    )
    if err != QgsRasterFileWriter.NoError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise QgsProcessingException("Could not read the DEM layer '%s'." % layer.name())
    return out, tmp


def optional_number(parameters, name):
    """Value of an optional number parameter, or None when left blank."""
    val = parameters.get(name)
    if val is None:
        return None
    if hasattr(val, "isNull") and val.isNull():
        return None
    if isinstance(val, str) and val.strip() == "":
        return None
    return val


# --------------------------------------------------------------------------
# Haul road inputs (shared by both tools)
# --------------------------------------------------------------------------
ROAD_LINES = "ROAD_LINES"
ROAD_AUTO = "ROAD_AUTO"
ROAD_SPIRAL_DIR = "ROAD_SPIRAL_DIR"
ROAD_BUILD = "ROAD_BUILD"
ROAD_START_POINT = "ROAD_START_POINT"
ROAD_GRADE = "ROAD_GRADE"
ROAD_TRUCK_WIDTH = "ROAD_TRUCK_WIDTH"
ROAD_TRAFFIC = "ROAD_TRAFFIC"
ROAD_WIDTH_OVERRIDE = "ROAD_WIDTH_OVERRIDE"
ROAD_DIRECTION = "ROAD_DIRECTION"
ROAD_START_ELEV = "ROAD_START_ELEV"
ROAD_END_ELEV = "ROAD_END_ELEV"
ROAD_CROSSFALL = "ROAD_CROSSFALL"
ROAD_DITCH = "ROAD_DITCH"
ROAD_DITCH_DEPTH = "ROAD_DITCH_DEPTH"
ROAD_WINDROW = "ROAD_WINDROW"
ROAD_CUT_RATIO = "ROAD_CUT_RATIO"
ROAD_FILL_RATIO = "ROAD_FILL_RATIO"
ROAD_CURVE_RADIUS = "ROAD_CURVE_RADIUS"
ROAD_CURVE_EASING = "ROAD_CURVE_EASING"
ROAD_TURN_RADIUS = "ROAD_TURN_RADIUS"
ROAD_LANDING = "ROAD_LANDING"
ROAD_STOPPING = "ROAD_STOPPING"
ROAD_SMOOTH = "ROAD_SMOOTH"

ROAD_TRAFFIC_CHOICES = [
    "Two-way (3.5 x truck width on straights, 4.0 x on curves)",
    "One-way (2.0 x truck width on straights, 2.5 x on curves)",
]
ROAD_TRAFFIC_KEYS = ["two_way", "one_way"]
ROAD_DIRECTION_CHOICES = [
    "Descends from the first vertex (digitize the road from the top)",
    "Ascends from the first vertex (digitize the road from the bottom)",
]
ROAD_DIRECTION_KEYS = ["down", "up"]
ROAD_SPIRAL_CHOICES = [
    "Loaded trucks climb CLOCKWISE (recommended in the design guidance)",
    "Loaded trucks climb COUNTER-CLOCKWISE",
]
ROAD_BUILD_CHOICES = [
    "Bottom up: the road starts at the pit floor / dump base and climbs (recommended)",
    "Top down: the road starts at the rim / dump crest and descends",
]


def _advanced(param):
    param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagAdvanced)
    return param


def add_road_parameters(alg, direction_index, cut_ratio, fill_ratio):
    """Optional haul road inputs. The centreline layer, gradient and truck
    width are always visible; everything else is under Advanced Parameters."""
    D = QgsProcessingParameterNumber.Double
    alg.addParameter(QgsProcessingParameterFeatureSource(
        ROAD_LINES,
        "Haul road centreline(s) - optional. Digitize each road from its start; "
        "each line is one road",
        types=[QgsProcessing.TypeVectorLine], optional=True))
    alg.addParameter(QgsProcessingParameterBoolean(
        ROAD_AUTO, "Generate a SPIRAL haul road automatically (used only when no road line is given above). "
        "Pit: winds down the wall from the rim to the floor. Dump: winds up from the base to the crest", False))
    alg.addParameter(QgsProcessingParameterEnum(
        ROAD_BUILD, "Spiral build order", options=ROAD_BUILD_CHOICES, defaultValue=0))
    alg.addParameter(_advanced(QgsProcessingParameterEnum(
        ROAD_SPIRAL_DIR, "Spiral direction", options=ROAD_SPIRAL_CHOICES, defaultValue=0)))
    alg.addParameter(_advanced(QgsProcessingParameterFeatureSource(
        ROAD_START_POINT, "Spiral entry point - optional point layer where the ramp meets natural ground at the "
        "rim / dump base; blank = the lowest ground at the footprint edge", types=[QgsProcessing.TypePoint], optional=True)))
    alg.addParameter(QgsProcessingParameterNumber(
        ROAD_GRADE, "Road gradient (%) - 8 is typical in North America, 10 is the usual ceiling",
        D, 8.0, minValue=0.5, maxValue=20.0))
    alg.addParameter(QgsProcessingParameterNumber(
        ROAD_TRUCK_WIDTH, "Overall width of your largest haul truck (m) - sets the road width",
        D, 6.5, minValue=1.0, maxValue=15.0))
    alg.addParameter(_advanced(QgsProcessingParameterEnum(
        ROAD_TRAFFIC, "Road traffic", options=ROAD_TRAFFIC_CHOICES, defaultValue=0)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_WIDTH_OVERRIDE, "Fixed road running width (m) - blank to use the truck-width rule",
        D, None, optional=True, minValue=1.0)))
    alg.addParameter(_advanced(QgsProcessingParameterEnum(
        ROAD_DIRECTION, "Road direction", options=ROAD_DIRECTION_CHOICES,
        defaultValue=direction_index)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_START_ELEV, "Road start elevation (m) - blank to start at the ground elevation of the first vertex",
        D, None, optional=True)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_END_ELEV, "Road end elevation (m) - the road then runs level. Blank = pit floor / dump crest",
        D, None, optional=True)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_CROSSFALL, "Crossfall (%) toward the ditch side", D, 2.0, minValue=0.0, maxValue=6.0)))
    alg.addParameter(_advanced(QgsProcessingParameterBoolean(
        ROAD_DITCH, "Cut a V-ditch on the uphill side", True)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_DITCH_DEPTH, "V-ditch depth (m) - 0.3 m minimum, width is 5 x depth", D, 0.3,
        minValue=0.1, maxValue=2.0)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_WINDROW, "Windrow (safety berm) height (m) - at least half the tyre height of your "
        "largest vehicle; 0 for none", D, 1.5, minValue=0.0, maxValue=4.0)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_CUT_RATIO, "Cut slope beside the road (H:V)", D, cut_ratio, minValue=0.2, maxValue=5.0)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_FILL_RATIO, "Fill slope beside the road (H:V)", D, fill_ratio, minValue=0.5, maxValue=5.0)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_CURVE_RADIUS, "Treat as a curve (wider and flatter) when the radius is below (m)",
        D, 75.0, minValue=10.0)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_CURVE_EASING, "Gradient reduction on curves (%) - the paper suggests 2 to 3",
        D, 2.5, minValue=0.0, maxValue=8.0)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_TURN_RADIUS, "Your truck's minimum turning-circle INNER clearance radius (m) - from the "
        "manufacturer; the inside tyre path must be at least 150% of it", D, 10.0,
        minValue=1.0, maxValue=60.0)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_LANDING, "Flat landing at the start of the road (m) - the paper keeps intersections "
        "flat for about one truck length; 0 = none", D, 15.0, minValue=0.0, maxValue=200.0)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_STOPPING, "Truck stopping distance (m) - sight distance is checked against 2x this; 0 = skip the check",
        QgsProcessingParameterNumber.Double, 60.0, minValue=0.0)))
    alg.addParameter(_advanced(QgsProcessingParameterNumber(
        ROAD_SMOOTH, "Smooth the centreline over (m) - rounds sharp digitized corners; 0 = off",
        D, 0.0, minValue=0.0, maxValue=200.0)))


def read_road_parameters(alg, parameters, context, feedback, working_crs):
    """Road settings for core.run_*; None when no road layer was given."""
    src = alg.parameterAsSource(parameters, ROAD_LINES, context)
    wkts = []
    if src is not None:
        try:
            wkts = geometry_wkts(
                src, working_crs, context, feedback,
                "The road centreline layer has no usable lines. If you ticked 'Selected "
                "features only', make sure something is selected.")
        except QgsProcessingException:
            if not alg.parameterAsBool(parameters, ROAD_AUTO, context):
                raise
            wkts = []
    auto = None
    if alg.parameterAsBool(parameters, ROAD_AUTO, context):
        if wkts:
            feedback.pushInfo("A road centreline layer was given, so it is used and the automatic spiral is skipped.")
        else:
            start_wkts = []
            psrc = alg.parameterAsSource(parameters, ROAD_START_POINT, context)
            if psrc is not None:
                start_wkts = geometry_wkts(psrc, working_crs, context, feedback,
                                           "The spiral start point layer has no usable points.")
            auto = {"climb_cw": alg.parameterAsEnum(parameters, ROAD_SPIRAL_DIR, context) == 0,
                    "bottom_up": alg.parameterAsEnum(parameters, ROAD_BUILD, context) == 0,
                    "start_wkts": start_wkts}
    if not wkts and auto is None:
        return None

    def opt(name):
        if optional_number(parameters, name) is None:
            return None
        return alg.parameterAsDouble(parameters, name, context)

    width = opt(ROAD_WIDTH_OVERRIDE)
    width = width if (width and width > 0) else None
    truck = alg.parameterAsDouble(parameters, ROAD_TRUCK_WIDTH, context)
    traffic = ROAD_TRAFFIC_KEYS[alg.parameterAsEnum(parameters, ROAD_TRAFFIC, context)]
    turn = alg.parameterAsDouble(parameters, ROAD_TURN_RADIUS, context)
    # Paper: inside tyre path radius >= 150% of the truck's turning-circle inner
    # clearance radius. The inside tyre path is approximated by the centreline
    # radius minus half the running width on a curve (conservative).
    w_curve = width if width else core.TRAFFIC_WIDTHS[traffic][1] * truck
    min_radius = core.TURN_RADIUS_FACTOR * turn + w_curve / 2.0
    feedback.pushInfo(
        "Minimum centreline radius = %.1f x %.1f m (truck turning circle) + half the curve width "
        "(%.1f m) = %.1f m" % (core.TURN_RADIUS_FACTOR, turn, w_curve / 2.0, min_radius))
    options = dict(
        truck_width=truck,
        traffic=traffic,
        width_override=width,
        grade_pct=alg.parameterAsDouble(parameters, ROAD_GRADE, context),
        curve_easing_pct=alg.parameterAsDouble(parameters, ROAD_CURVE_EASING, context),
        curve_radius=alg.parameterAsDouble(parameters, ROAD_CURVE_RADIUS, context),
        min_radius=min_radius,
        start_elev=opt(ROAD_START_ELEV),
        end_elev=opt(ROAD_END_ELEV),
        direction=ROAD_DIRECTION_KEYS[alg.parameterAsEnum(parameters, ROAD_DIRECTION, context)],
        crossfall_pct=alg.parameterAsDouble(parameters, ROAD_CROSSFALL, context),
        ditch=alg.parameterAsBool(parameters, ROAD_DITCH, context),
        ditch_depth=alg.parameterAsDouble(parameters, ROAD_DITCH_DEPTH, context),
        windrow_h=alg.parameterAsDouble(parameters, ROAD_WINDROW, context),
        cut_ratio=alg.parameterAsDouble(parameters, ROAD_CUT_RATIO, context),
        fill_ratio=alg.parameterAsDouble(parameters, ROAD_FILL_RATIO, context),
        smooth_m=alg.parameterAsDouble(parameters, ROAD_SMOOTH, context),
        landing_m=alg.parameterAsDouble(parameters, ROAD_LANDING, context),
    )
    if wkts:
        feedback.pushInfo("Haul road lines used: %d" % len(wkts))
    else:
        feedback.pushInfo("Automatic spiral haul road requested.")
    return {"line_wkts": wkts, "options": options, "auto": auto,
            "stopping_m": alg.parameterAsDouble(parameters, ROAD_STOPPING, context)}
