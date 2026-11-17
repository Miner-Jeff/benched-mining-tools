# Benched Mining Tools (QGIS plugin)

QGIS Processing tools that modify a DEM to show planned open pits and waste rock piles, with benches, haul roads (including an automatic spiral), contours, drawing vectors and design checks.

> **Use at your own risk.** Experimental software provided free of charge under GPL-2.0-or-later, **without any warranty**. It is a planning aid, not engineered mine design; all results must be reviewed by a qualified mining or geotechnical engineer. See `LICENSE`.

* Plugin source and full README: [`benched_mining_tools/`](benched_mining_tools/)
* User guide: [`benched_mining_tools/USER_GUIDE.md`](benched_mining_tools/USER_GUIDE.md)
* To test, have a DEM GeoTIFF for your area ready (for example a free download from [OpenTopography](https://opentopography.org)); no sample data is included.
* Install: zip the `benched_mining_tools` folder (or use a release zip) and use QGIS > Plugins > Manage and Install Plugins > Install from ZIP.
* **Bugs:** open an Issue. Reports are welcome, but **fixes and replies are not guaranteed**. See [`SUPPORT.md`](SUPPORT.md).
* Tests: `tests/run_all.sh` (needs Python with GDAL, numpy and scipy; the QGIS-facing code is only tested with stand-in objects).
