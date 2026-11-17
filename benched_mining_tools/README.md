# Benched Mining Tools (v2.8.1)

## Disclaimer - use at your own risk

This software is provided free of charge under the **GNU General Public License, version 2 or (at your option) any later version**, **WITHOUT ANY WARRANTY**, without even the implied warranty of merchantability or fitness for a particular purpose. See the `LICENSE` file.

* **You use this software entirely at your own risk and peril.** The author accepts no liability for any loss, damage, injury, cost or claim arising from its use or from decisions based on its output.
* It is a **visualization and planning aid, not an engineered mine design.** Every surface, volume, road, bench and contour it produces must be reviewed and approved by a qualified mining or geotechnical engineer before it is used for design, scheduling, permitting, costing, construction or safety decisions.
* It has **not been validated against any regulation, standard or jurisdiction.** The design rules come from public guidance (for example the Deswik open-pit design white paper) plus the author's own assumptions. The built-in validation warnings are advisory only; a clean log does not mean a design is safe or compliant.
* DEM data (for example from OpenTopography) can contain errors and has limited resolution. Results are only as good as the inputs.
* It was tested outside QGIS and is an early (experimental) release; expect bugs.

**To test:** have a DEM GeoTIFF for your area ready (for example a free download from [OpenTopography](https://opentopography.org)); no sample data is included.

QGIS Processing plugin. After installing, find the tools in
**Processing Toolbox > Benched Mining Tools > Mining**:

* **Generate Benched Open Pit** - outline = pit rim at a constant elevation; steps down and
  inward at the wall angle with benches, to the floor elevation. Only lowers ground.
* **Generate Benched Waste Rock Pile** - outline = maximum footprint; rises inward and upward
  from the base elevation at an H:V slope ratio, with benches. Only raises ground.

Both: 1 m working resolution, UTM CRS (layers already in UTM are left alone), optional
contour lines clipped to the footprint with an ELEVATION attribute, cut/fill volume in the log.
To process one polygon of a multi-polygon layer, select it and tick "Selected features only".

**Haul roads (new in 2.1.0, refined in 2.2.0):** add an optional line layer as the road centreline and set the gradient and truck width. The tool builds the ramp (width from truck width, curve widening and easing, crossfall, V-ditch, windrow, cut/fill tie-in), includes it in the contours, and warns about steep gradients, tight curves and short roads. Rules follow the Deswik white paper on open pit design.

Working cell size is the constant `CELL_SIZE` in `core.py`.

**New to the plugin? Read `USER_GUIDE.md`** - it explains the purpose of every input and walks through each tool step by step.

**Automatic spiral road and drawing layers (2.4.0):** tick the spiral option to have the tool route a ramp down the pit wall (or up the dump). Optional outputs: bench crest/toe lines, road centreline/edge lines and road polygons.

**Validation (2.5.0):** each run logs warnings for outline, slope, bench, road shape, overlap, connection and sight-distance problems. They never change the geometry.


## Bug reports and support
Bugs can be reported on the GitHub Issues page (include the plugin version, QGIS version and the full log). This is a free, volunteer project: **there is no guarantee that a report will be answered or a bug fixed**, and no timeline applies.

## License
Copyright (C) 2026 Miner-Jeff. Licensed under the GNU General Public License v2.0 or later (GPL-2.0-or-later). See `LICENSE`.

**Focus (2.6.0):** the plugin's main outputs are contours, bench crest/toe lines and ramp/road designs. Writing a modified DEM is optional and off by default, since DEM editing is expected to be done by other tools.

**Strings (2.7.0):** bench crest/toe strings are now traced at constant elevation from the finished surface, so they follow the ramp adjustments. Road ends at the lowest string need manual editing for equipment access; the log tells you where.

**Build order (2.8.0):** roads are built bottom up by default (the ramp starts at the pit floor / dump base and climbs). The log reports the road's impact on volumes and on the floor/crest area.
