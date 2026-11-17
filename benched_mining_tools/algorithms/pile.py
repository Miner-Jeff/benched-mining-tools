from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorDestination,
)
import math
import shutil

from .. import core
from .. import common

SLOPE_RATIOS = ["2:1", "2.5:1", "3:1", "3.5:1", "4:1", "4.5:1", "5:1", "5.5:1"]


class BenchedWasteRockPile(QgsProcessingAlgorithm):
    INPUT_DEM = "INPUT_DEM"
    PILE_BASE = "PILE_BASE"
    TARGET_CRS = "TARGET_CRS"
    BENCH_HEIGHT = "BENCH_HEIGHT"
    BENCH_WIDTH = "BENCH_WIDTH"
    SLOPE_RATIO = "SLOPE_RATIO"
    BASE_ELEVATION = "BASE_ELEVATION"
    TOP_ELEVATION = "TOP_ELEVATION"
    GENERATE_CONTOURS = "GENERATE_CONTOURS"
    CONTOUR_INTERVAL = "CONTOUR_INTERVAL"
    OUTPUT = "OUTPUT"
    OUTPUT_CONTOURS = "OUTPUT_CONTOURS"
    OUTPUT_BENCHES = "OUTPUT_BENCHES"
    OUTPUT_ROAD_LINES = "OUTPUT_ROAD_LINES"
    OUTPUT_ROAD_POLYS = "OUTPUT_ROAD_POLYS"

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_DEM, "Input DEM (existing terrain)"))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.PILE_BASE, "Dump footprint polygon (maximum extent at the base)",
            types=[QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterEnum(
            self.TARGET_CRS, "UTM zone to use only if neither layer is already UTM",
            options=common.CANADIAN_UTM_ZONES, defaultValue=common.DEFAULT_ZONE_INDEX))
        self.addParameter(QgsProcessingParameterNumber(
            self.BENCH_HEIGHT, "Bench height (m)",
            QgsProcessingParameterNumber.Double, 10.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BENCH_WIDTH, "Bench width (m) - 0 gives one continuous slope",
            QgsProcessingParameterNumber.Double, 0.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.SLOPE_RATIO, "Slope ratio (horizontal:vertical)",
            options=SLOPE_RATIOS, defaultValue=2))
        self.addParameter(QgsProcessingParameterNumber(
            self.BASE_ELEVATION, "Dump base elevation (m) - leave blank to use the lowest ground in the footprint",
            QgsProcessingParameterNumber.Double, 235.0, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.TOP_ELEVATION, "Maximum dump crest elevation (m) - leave blank for no limit",
            QgsProcessingParameterNumber.Double, None, optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.GENERATE_CONTOURS, "Generate contour lines inside the footprint", True))
        self.addParameter(QgsProcessingParameterNumber(
            self.CONTOUR_INTERVAL, "Contour interval (m)",
            QgsProcessingParameterNumber.Double, 5.0, minValue=0.1))
        common.add_road_parameters(self, 1, 1.5, 1.5)
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT, "Output modified DEM - OPTIONAL, leave blank to skip (the contours and ramp designs are the main outputs)",
            optional=True, createByDefault=False))
        self.addParameter(QgsProcessingParameterVectorDestination(
            self.OUTPUT_CONTOURS, "Output contours (ELEVATION attribute)",
            type=QgsProcessing.TypeVectorLine, optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterVectorDestination(
            self.OUTPUT_BENCHES, "Output bench crest and toe STRINGS at constant elevation, adjusted for the ramp (TYPE, BENCH, ELEVATION)",
            type=QgsProcessing.TypeVectorLine, optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterVectorDestination(
            self.OUTPUT_ROAD_LINES, "Output road centreline and edge lines (only when a road is designed)",
            type=QgsProcessing.TypeVectorLine, optional=True, createByDefault=True))
        self.addParameter(QgsProcessingParameterVectorDestination(
            self.OUTPUT_ROAD_POLYS, "Output road surface polygons (only when a road is designed)",
            type=QgsProcessing.TypeVectorPolygon, optional=True, createByDefault=True))

    def processAlgorithm(self, parameters, context, feedback):
        dem_layer = self.parameterAsRasterLayer(parameters, self.INPUT_DEM, context)
        source = self.parameterAsSource(parameters, self.PILE_BASE, context)
        if dem_layer is None or source is None:
            raise QgsProcessingException("Input DEM or dump footprint could not be loaded.")
        target_crs = common.zone_crs(self.parameterAsEnum(parameters, self.TARGET_CRS, context))
        bench_h = self.parameterAsDouble(parameters, self.BENCH_HEIGHT, context)
        bench_w = self.parameterAsDouble(parameters, self.BENCH_WIDTH, context)
        ratio_text = SLOPE_RATIOS[self.parameterAsEnum(parameters, self.SLOPE_RATIO, context)]
        ratio_h, ratio_v = [float(x) for x in ratio_text.split(":")]
        base = None
        if common.optional_number(parameters, self.BASE_ELEVATION) is not None:
            base = self.parameterAsDouble(parameters, self.BASE_ELEVATION, context)
        top = None
        if common.optional_number(parameters, self.TOP_ELEVATION) is not None:
            top = self.parameterAsDouble(parameters, self.TOP_ELEVATION, context)
        want_contours = self.parameterAsBool(parameters, self.GENERATE_CONTOURS, context)
        interval = self.parameterAsDouble(parameters, self.CONTOUR_INTERVAL, context)
        out_dem = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        out_cont = self.parameterAsOutputLayer(parameters, self.OUTPUT_CONTOURS, context)
        out_bench = self.parameterAsOutputLayer(parameters, self.OUTPUT_BENCHES, context)
        out_rlines = self.parameterAsOutputLayer(parameters, self.OUTPUT_ROAD_LINES, context)
        out_rpolys = self.parameterAsOutputLayer(parameters, self.OUTPUT_ROAD_POLYS, context)

        if base is not None and top is not None and top <= base:
            raise QgsProcessingException(
                "Maximum crest elevation (%.1f) must be above the base elevation (%.1f)." % (top, base))

        feedback.pushInfo("=" * 60)
        feedback.pushInfo("BENCHED WASTE ROCK PILE - Benched Mining Tools v%s" % core.VERSION)
        feedback.pushInfo("=" * 60)
        feedback.pushInfo("Slope %s (%.1f deg), bench %.1f m high x %.1f m wide" % (
            ratio_text, math.degrees(math.atan(ratio_v / ratio_h)), bench_h, bench_w))

        working_crs = common.resolve_working_crs(
            dem_layer.crs(), source.sourceCrs(), target_crs, feedback.pushInfo)
        feedback.pushInfo("NOTICE: planning aid only, not engineered mine design. Provided without warranty "
                          "(GPL-2.0-or-later); use at your own risk. Have a qualified engineer review all results.")
        feedback.setProgress(2)
        wkts = common.footprint_wkts(source, working_crs, context, feedback)
        if feedback.isCanceled():
            feedback.pushInfo("Cancelled by user.")
            return {}
        feedback.pushInfo("Footprint polygons used: %d" % len(wkts))
        if len(wkts) > 1:
            feedback.pushWarning(
                "More than one polygon is being processed; they are treated as ONE combined dump. "
                "Tick 'Selected features only' to use just the polygon(s) you selected.")

        roads = common.read_road_parameters(self, parameters, context, feedback, working_crs)
        if feedback.isCanceled():
            feedback.pushInfo("Cancelled by user.")
            return {}

        dem_path, tmp_dem = common.dem_file_path(dem_layer, context)
        try:
            run = core.run_pile(
                dem_path, working_crs.toWkt(), wkts, base, bench_h, bench_w, ratio_h, ratio_v, top,
                out_dem or None, out_cont if (want_contours and out_cont) else None, interval,
                roads=roads, out_benches=out_bench or None, out_road_lines=out_rlines or None,
                out_road_polys=out_rpolys or None, log=feedback.pushInfo, progress=feedback.setProgress,
                is_canceled=feedback.isCanceled)
        except core.Cancelled:
            feedback.pushInfo("Cancelled by user.")
            return {}
        except RuntimeError as exc:
            raise QgsProcessingException(str(exc))
        finally:
            if tmp_dem:
                shutil.rmtree(tmp_dem, ignore_errors=True)

        feedback.pushInfo("Done.")
        results = {}
        if out_dem:
            results[self.OUTPUT] = out_dem
        if want_contours and out_cont:
            results[self.OUTPUT_CONTOURS] = out_cont
        written = (run or {}).get("written", {})
        if written.get("benches") and out_bench:
            results[self.OUTPUT_BENCHES] = out_bench
        if written.get("road_lines") and out_rlines:
            results[self.OUTPUT_ROAD_LINES] = out_rlines
        if written.get("road_polys") and out_rpolys:
            results[self.OUTPUT_ROAD_POLYS] = out_rpolys
        return results

    def name(self):
        return "benched_waste_rock_pile"

    def displayName(self):
        return "Generate Benched Waste Rock Pile (v%s)" % core.VERSION

    def group(self):
        return "Mining"

    def groupId(self):
        return "mining"

    def createInstance(self):
        return BenchedWasteRockPile()

    def shortHelpString(self):
        return (
            "<p><b>Use at your own risk.</b> Planning aid only, not engineered mine design; provided without warranty. A qualified engineer must review all results.</p>"
            "<h3>What this does</h3>"
            "<p>Builds a <b>benched waste rock dump</b> on your DEM. Your polygon is the dump's "
            "<b>maximum footprint at the base</b>. The dump rises <b>inward and upward</b> from "
            "the base elevation at the slope ratio you choose, with optional flat benches.</p>"
            "<h3>Steps</h3>"
            "<ol><li>Load your DEM and your dump footprint polygon.</li>"
            "<li>If the layer has several polygons, select the one you want and tick "
            "<i>Selected features only</i>.</li>"
            "<li>Enter the design numbers below and press Run.</li>"
            "<li>Read the fill volume and crest elevation in the Log tab.</li></ol>"
            "<h3>The inputs</h3><ul>"
            "<li><b>Input DEM</b> - existing terrain, elevations in metres.</li>"
            "<li><b>Dump footprint polygon</b> - the largest extent, at the base of the dump.</li>"
            "<li><b>UTM zone</b> - only used if neither layer is already UTM. Ignored otherwise.</li>"
            "<li><b>Bench height</b> - height of each lift (10 m).</li>"
            "<li><b>Bench width</b> - flat width at each lift. 0 gives one continuous slope.</li>"
            "<li><b>Slope ratio</b> - horizontal : vertical. 3:1 is 3 m across per 1 m up "
            "(about 18.4 deg). 2:1 = 26.6, 4:1 = 14.0, 5:1 = 11.3 deg.</li>"
            "<li><b>Base elevation</b> - elevation at the footprint edge. Blank = lowest ground "
            "inside the footprint.</li>"
            "<li><b>Maximum crest elevation</b> - optional height cap; blank = no limit.</li>"
            "<li><b>Contours</b> - optional lines inside the footprint with an ELEVATION "
            "attribute.</li></ul>"
            "<h3>Haul road (optional)</h3><ul>"
            "<li>Add a <b>haul road centreline</b> layer (a line you draw, starting at the toe and drawn up onto the dump) to design a ramp "
            "following the Deswik open pit design guidelines.</li>"
            "<li><b>Gradient</b> (8% typical, 10% ceiling) and <b>truck width</b> (sets the road width) are the key "
            "inputs. Windrow, V-ditch, crossfall, curve widening and cut/fill slopes are under Advanced Parameters.</li>"
            "<li>Or tick <b>Generate a SPIRAL haul road automatically</b> (no line needed) and the tool routes the ramp around the wall. Optional outputs: bench crest/toe lines, road centreline/edge lines and road polygons.</li>"
            "<li>The road shows in the DEM <b>and the contours</b>. The log reports length, widths, cut/fill volume and "
            "warnings (gradient, tight curves, road too short).</li></ul>"
            "<h3>Good to know</h3><ul>"
            "<li>Ground is only ever raised; the dump never cuts below the terrain. Example: base "
            "235 m at 3:1 - a point 150 m inside the edge is at 285 m.</li>"
            "<li>Output is 1 m cells in UTM. Layers already in UTM are not reprojected.</li>"
            "<li>Full instructions: USER_GUIDE.md in the plugin folder.</li></ul>"
            "<p>Version " + core.VERSION + "</p>"
        )
