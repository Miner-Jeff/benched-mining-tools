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
import shutil

from .. import core
from .. import common


class BenchedOpenPit(QgsProcessingAlgorithm):
    INPUT_DEM = "INPUT_DEM"
    PIT_OUTLINE = "PIT_OUTLINE"
    TARGET_CRS = "TARGET_CRS"
    BENCH_HEIGHT = "BENCH_HEIGHT"
    BENCH_WIDTH = "BENCH_WIDTH"
    WALL_ANGLE = "WALL_ANGLE"
    MAX_IRA = "MAX_IRA"
    RIM_ELEVATION = "RIM_ELEVATION"
    FLOOR_ELEVATION = "FLOOR_ELEVATION"
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
            self.PIT_OUTLINE, "Pit outline polygon (at the rim elevation)",
            types=[QgsProcessing.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterEnum(
            self.TARGET_CRS, "UTM zone to use only if neither layer is already UTM",
            options=common.CANADIAN_UTM_ZONES, defaultValue=common.DEFAULT_ZONE_INDEX))
        self.addParameter(QgsProcessingParameterNumber(
            self.BENCH_HEIGHT, "Bench height (m)",
            QgsProcessingParameterNumber.Double, 30.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BENCH_WIDTH, "Bench width (m)",
            QgsProcessingParameterNumber.Double, 8.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.WALL_ANGLE, "Wall angle between benches (degrees from horizontal)",
            QgsProcessingParameterNumber.Double, 50.0, minValue=1.0, maxValue=89.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_IRA, "Maximum allowed inter-ramp angle (degrees) - optional; the log warns if the "
            "design exceeds it", QgsProcessingParameterNumber.Double, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.RIM_ELEVATION, "Pit rim elevation (m) - elevation of the outline",
            QgsProcessingParameterNumber.Double, 250.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.FLOOR_ELEVATION, "Pit floor elevation (m)",
            QgsProcessingParameterNumber.Double, 140.0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.GENERATE_CONTOURS, "Generate contour lines inside the pit", True))
        self.addParameter(QgsProcessingParameterNumber(
            self.CONTOUR_INTERVAL, "Contour interval (m)",
            QgsProcessingParameterNumber.Double, 10.0, minValue=0.1))
        common.add_road_parameters(self, 1, 0.84, 1.5)
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
        source = self.parameterAsSource(parameters, self.PIT_OUTLINE, context)
        if dem_layer is None or source is None:
            raise QgsProcessingException("Input DEM or pit outline could not be loaded.")
        target_crs = common.zone_crs(self.parameterAsEnum(parameters, self.TARGET_CRS, context))
        bench_h = self.parameterAsDouble(parameters, self.BENCH_HEIGHT, context)
        bench_w = self.parameterAsDouble(parameters, self.BENCH_WIDTH, context)
        angle = self.parameterAsDouble(parameters, self.WALL_ANGLE, context)
        rim = self.parameterAsDouble(parameters, self.RIM_ELEVATION, context)
        floor = self.parameterAsDouble(parameters, self.FLOOR_ELEVATION, context)
        want_contours = self.parameterAsBool(parameters, self.GENERATE_CONTOURS, context)
        interval = self.parameterAsDouble(parameters, self.CONTOUR_INTERVAL, context)
        out_dem = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        out_cont = self.parameterAsOutputLayer(parameters, self.OUTPUT_CONTOURS, context)
        out_bench = self.parameterAsOutputLayer(parameters, self.OUTPUT_BENCHES, context)
        out_rlines = self.parameterAsOutputLayer(parameters, self.OUTPUT_ROAD_LINES, context)
        out_rpolys = self.parameterAsOutputLayer(parameters, self.OUTPUT_ROAD_POLYS, context)

        if rim <= floor:
            raise QgsProcessingException(
                "Pit rim elevation (%.1f) must be above the pit floor elevation (%.1f)." % (rim, floor))

        feedback.pushInfo("=" * 60)
        feedback.pushInfo("BENCHED OPEN PIT - Benched Mining Tools v%s" % core.VERSION)
        feedback.pushInfo("=" * 60)
        feedback.pushInfo("Bench %.1f m high x %.1f m wide, wall angle %.1f deg, rim %.1f m, floor %.1f m" % (
            bench_h, bench_w, angle, rim, floor))

        working_crs = common.resolve_working_crs(
            dem_layer.crs(), source.sourceCrs(), target_crs, feedback.pushInfo)
        feedback.pushInfo("NOTICE: planning aid only, not engineered mine design. Provided without warranty "
                          "(GPL-2.0-or-later); use at your own risk. Have a qualified engineer review all results.")
        feedback.setProgress(2)
        wkts = common.footprint_wkts(source, working_crs, context, feedback)
        if feedback.isCanceled():
            feedback.pushInfo("Cancelled by user.")
            return {}
        feedback.pushInfo("Pit outline polygons used: %d" % len(wkts))
        if len(wkts) > 1:
            feedback.pushWarning(
                "More than one polygon is being processed; they are treated as ONE combined pit. "
                "Tick 'Selected features only' to use just the polygon(s) you selected.")

        roads = common.read_road_parameters(self, parameters, context, feedback, working_crs)
        if feedback.isCanceled():
            feedback.pushInfo("Cancelled by user.")
            return {}

        dem_path, tmp_dem = common.dem_file_path(dem_layer, context)
        try:
            run = core.run_pit(
                dem_path, working_crs.toWkt(), wkts, rim, floor, bench_h, bench_w, angle,
                out_dem or None, out_cont if (want_contours and out_cont) else None, interval,
                roads=roads, out_benches=out_bench or None, out_road_lines=out_rlines or None,
                out_road_polys=out_rpolys or None, max_ira=common.optional_number(parameters, self.MAX_IRA),
                log=feedback.pushInfo, progress=feedback.setProgress,
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
        return "benched_open_pit"

    def displayName(self):
        return "Generate Benched Open Pit (v%s)" % core.VERSION

    def group(self):
        return "Mining"

    def groupId(self):
        return "mining"

    def createInstance(self):
        return BenchedOpenPit()

    def shortHelpString(self):
        return (
            "<p><b>Use at your own risk.</b> Planning aid only, not engineered mine design; provided without warranty. A qualified engineer must review all results.</p>"
            "<h3>What this does</h3>"
            "<p>Cuts a <b>benched open pit</b> into your DEM. Your polygon is the pit <b>rim</b> "
            "(top edge). From the rim the pit steps <b>down and inward</b>: a wall at the wall "
            "angle, then a flat bench, then the next wall, until the floor elevation.</p>"
            "<h3>Steps</h3>"
            "<ol><li>Load your DEM and your pit outline polygon.</li>"
            "<li>If the layer has several polygons, select the one you want and tick "
            "<i>Selected features only</i>.</li>"
            "<li>Enter the design numbers below and press Run.</li>"
            "<li>Read the cut volume in the Log tab.</li></ol>"
            "<h3>The inputs</h3><ul>"
            "<li><b>Input DEM</b> - existing terrain, elevations in metres.</li>"
            "<li><b>Pit outline polygon</b> - the pit rim.</li>"
            "<li><b>UTM zone</b> - only used if neither layer is already UTM (UTM is needed for "
            "correct distances in metres). Ignored otherwise.</li>"
            "<li><b>Bench height</b> - vertical distance between benches (30 m).</li>"
            "<li><b>Bench width</b> - flat width of each bench (8 m; 0 = none).</li>"
            "<li><b>Wall angle</b> - steepness of each wall face between benches, from "
            "horizontal (50 deg). The overall slope is flatter because of the benches.</li>"
            "<li><b>Rim elevation</b> - elevation of your outline; must be above the floor.</li>"
            "<li><b>Floor elevation</b> - bottom of the pit; the floor is flat.</li>"
            "<li><b>Contours</b> - optional lines inside the pit with an ELEVATION attribute.</li>"
            "</ul>"
            "<h3>Haul road (optional)</h3><ul>"
            "<li>Add a <b>haul road centreline</b> layer (a line you draw, starting at the rim and drawn down into the pit) to design a ramp "
            "following the Deswik open pit design guidelines.</li>"
            "<li><b>Gradient</b> (8% typical, 10% ceiling) and <b>truck width</b> (sets the road width) are the key "
            "inputs. Windrow, V-ditch, crossfall, curve widening and cut/fill slopes are under Advanced Parameters.</li>"
            "<li>Or tick <b>Generate a SPIRAL haul road automatically</b> (no line needed) and the tool routes the ramp around the wall. Optional outputs: bench crest/toe lines, road centreline/edge lines and road polygons.</li>"
            "<li>The road shows in the DEM <b>and the contours</b>. The log reports length, widths, cut/fill volume and "
            "warnings (gradient, tight curves, road too short).</li></ul>"
            "<h3>Good to know</h3><ul>"
            "<li>Ground is only ever lowered. If the rim is above the terrain, cutting starts "
            "where the design surface drops below the ground.</li>"
            "<li>Output is 1 m cells in UTM. Layers already in UTM are not reprojected.</li>"
            "<li>Full instructions: USER_GUIDE.md in the plugin folder.</li></ul>"
            "<p>Version " + core.VERSION + "</p>"
        )
