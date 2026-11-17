# Benched Mining Tools – User Guide (v2.8.1)

## Important - Disclaimer - use at your own risk

This software is provided free of charge under the **GNU General Public License, version 2 or (at your option) any later version**, **WITHOUT ANY WARRANTY**, without even the implied warranty of merchantability or fitness for a particular purpose. See the `LICENSE` file.

* **You use this software entirely at your own risk and peril.** The author accepts no liability for any loss, damage, injury, cost or claim arising from its use or from decisions based on its output.
* It is a **visualization and planning aid, not an engineered mine design.** Every surface, volume, road, bench and contour it produces must be reviewed and approved by a qualified mining or geotechnical engineer before it is used for design, scheduling, permitting, costing, construction or safety decisions.
* It has **not been validated against any regulation, standard or jurisdiction.** The design rules come from public guidance (for example the Deswik open-pit design white paper) plus the author's own assumptions. The built-in validation warnings are advisory only; a clean log does not mean a design is safe or compliant.
* DEM data (for example from OpenTopography) can contain errors and has limited resolution. Results are only as good as the inputs.
* It was tested outside QGIS and is an early (experimental) release; expect bugs.

This plugin changes a terrain model (DEM) to show **planned mining**:

| Tool | What it models | Direction |
|---|---|---|
| **Generate Benched Open Pit** | A pit with benches (steps) cut into the ground | Digs **down and inward** from an outline |
| **Generate Benched Waste Rock Pile** | A waste dump built in benches | Builds **up and inward** from an outline |

You give it a DEM and one polygon. It gives you back a **new DEM** showing the pit or dump, and
optionally **contour lines** you can label and print. Your original data is never changed.
Both tools can also design a **haul road** (ramp) from a centreline you draw – see section 5.

---

## 1. What you need before you start

1. **A DEM** (terrain raster), for example one downloaded from OpenTopography. Elevations must be in
   **metres**. It can be in lat/long (EPSG:4326) or UTM – the tool handles either.
2. **A polygon layer with your outline**, drawn over your aerial imagery:
   * Open pit: the outline of the **top edge (rim)** of the pit.
   * Waste pile: the outline of the **largest footprint** of the dump, at its **base (toe)**.
3. **Elevations you want to use** (in the same elevation system as your DEM):
   * Open pit: the rim elevation and the floor (bottom) elevation.
   * Waste pile: the base elevation (and optionally a maximum crest elevation).
   * Tip: click the **Identify Features** tool on your DEM to read the ground elevation at a spot.
4. **Design numbers**: bench height, bench width, and wall angle (pit) or slope ratio (pile).

### Drawing the outline polygon
1. Layer ▸ Create Layer ▸ **New GeoPackage Layer…** – Geometry type **Polygon**, pick a CRS (UTM is best).
2. Turn on editing (pencil), **Add Polygon Feature**, click around your outline, right-click to finish, save.
3. You can keep several polygons in one layer (for example Pit A, Pit B, Dump 1). See "Several polygons" below.

---

## 2. Install the plugin
Plugins ▸ Manage and Install Plugins ▸ **Install from ZIP** ▸ choose `benched_mining_tools.zip` ▸ Install.
(If it doesn't show up: Settings tab ▸ tick **Show also experimental plugins**.)

Then open the **Processing Toolbox** (View ▸ Panels ▸ Processing Toolbox) and find
**Benched Mining Tools ▸ Mining**.

---

## 3. Open pit – step by step

1. Load your DEM and your pit outline layer. If the layer has several polygons, **select the pit** you want.
2. Double-click **Generate Benched Open Pit**.
3. Fill in the inputs (explained below), choose where to save, click **Run**.
4. When it finishes, the new DEM and contour lines are added to your project. Open the **Log** tab
   to read the **cut volume** (m³).

### Pit inputs

| Input | What it means | Typical / default |
|---|---|---|
| **Input DEM** | The existing terrain. | Your OpenTopography DEM |
| **Pit outline polygon** | The pit **rim**. Tick **Selected features only** to use just the polygon(s) you selected; leave unticked to use every polygon in the layer (they combine into one pit). | – |
| **UTM zone…** | Only used if **neither** layer is already in UTM (it's a metric system needed for correct distances). If either layer is already UTM, this is ignored. Pick the zone for your site (Kelowna = 11N; your Norlan Rd test area = 17N). | 17N |
| **Bench height (m)** | Vertical distance between benches. | 30 |
| **Bench width (m)** | Width of the flat bench at each level. Use 0 for no flat benches. | 8 |
| **Wall angle (degrees)** | Steepness of each wall face **between** benches, measured from horizontal. The **overall** pit slope is flatter because the benches interrupt it. | 50 |
| **Pit rim elevation (m)** | The elevation of your outline – the top of the pit. Must be above the floor. | 250 |
| **Pit floor elevation (m)** | The bottom of the pit. Digging stops here and the floor is flat. | 140 |
| **Generate contour lines** | Also create contour lines of the pit. | On |
| **Contour interval (m)** | Elevation spacing between contours. | 10 |
| **Output modified DEM** | OPTIONAL and off by default. The new terrain with the pit cut in, if you want it (for example to hand to other software). Leave blank to skip. The surface is still calculated internally to build the contours and ramps. | blank |
| **Output contours** | Contour lines, each with an `ELEVATION` attribute. | – |

**How the pit is built:** starting at the rim, the wall drops one bench height at the wall angle,
then a flat bench of the bench width, then the next wall, and so on inward until the floor elevation.
Example: 30 m bench, 50° wall, 8 m bench → each step covers 25.2 m + 8 m = 33.2 m horizontally,
for an overall slope of about 42°.

**Important:** the pit only ever **removes** ground. If your rim elevation is **higher than the terrain**
at the outline, the pit begins cutting only where the design surface drops below the ground.

---

## 4. Waste rock pile – step by step

1. Load your DEM and your dump footprint layer. Select the footprint polygon if there are several.
2. Double-click **Generate Benched Waste Rock Pile**.
3. Fill in the inputs, choose where to save, click **Run**.
4. Read the **fill volume** and **crest elevation** in the **Log** tab.

### Pile inputs

| Input | What it means | Typical / default |
|---|---|---|
| **Input DEM** | The existing terrain. | Your OpenTopography DEM |
| **Dump footprint polygon** | The **maximum extent at the base** of the dump. The dump rises **inward** from this line. Tick **Selected features only** to use only what you selected. | – |
| **UTM zone…** | Same as the pit: only used if neither layer is already UTM. | 17N |
| **Bench height (m)** | Vertical height of each lift. | 10 |
| **Bench width (m)** | Flat width at each lift. **0 = one continuous slope** with no flat benches. | 0 |
| **Slope ratio (H:V)** | Horizontal distance per 1 m of height. 3:1 means 3 m across for every 1 m up. | 3:1 |
| **Dump base elevation (m)** | Elevation of the dump toe at the footprint edge. **Leave blank** to use the lowest ground inside the footprint. | 235 |
| **Maximum dump crest elevation (m)** | Optional height cap. **Leave blank** for no limit. | blank |
| **Generate contour lines** | Also create contour lines of the dump. | On |
| **Contour interval (m)** | Elevation spacing between contours. | 5 |
| **Output modified DEM** | OPTIONAL and off by default. The new terrain with the dump added. Leave blank to skip. | blank |
| **Output contours** | Contour lines with an `ELEVATION` attribute. | – |

Slope ratio and angle: 2:1 = 26.6°, 2.5:1 = 21.8°, **3:1 = 18.4°**, 3.5:1 = 15.9°, 4:1 = 14.0°,
4.5:1 = 12.5°, 5:1 = 11.3°, 5.5:1 = 10.3°.

**How the dump is built:** at the footprint edge the dump is at the base elevation and climbs inward
at the slope ratio. With a bench width above 0, each lift rises one bench height, then goes flat for the
bench width, then climbs again. The dump only ever **adds** ground; it never cuts below the terrain.
Example: base 235 m, 3:1, bench width 0 → a point 150 m inside the edge is at 235 + 150/3 = 285 m.

---

## 5. Haul roads (optional – both tools)

A real pit or dump needs a way in and out. Both tools can design a **haul road** along a centreline
you draw, and put it into the new DEM **and the contours**, so the ramp shows up on your plans.

The road rules come from the Deswik white paper *"Guidelines and considerations for open pit
designers"* (road width from truck width, gradient, windrow, V-ditch, crossfall, flatter curves).
**You draw the route; the tool builds and checks the road along it.** It does not choose the route
for you. Site rules, legislation and your truck manufacturer's data always take precedence over the defaults.

### 5.1 Drawing the road centreline
1. Layer ▸ Create Layer ▸ **New GeoPackage Layer…** – Geometry type **LineString**, same CRS as your other layers.
2. Add a line along the middle of the road. **Click the first vertex where the road starts:**
   * **Pit road:** start at the **top** (the rim, on the ground) and draw **down into the pit**.
   * **Dump road:** start at the **bottom** (the toe, on the ground) and draw **up onto the dump**.
   (If you draw the other way round, change **Road direction** under Advanced Parameters.)
3. Use **gentle arcs with plenty of vertices**, not sharp corners. Trucks cannot turn on a point.
4. Each line is **its own road** with its own start elevation. Several lines = several roads.
5. A road can start **outside** the pit outline or dump footprint – it will cut or fill its way to the ground.

### 5.2 How long must the road be?
Length needed = **height to climb or drop ÷ gradient**.
Example: rim 250 m to floor 140 m is 110 m. At 8% that is 110 ÷ 0.08 = **1,375 m of road** (more if you ease
the curves). The log tells you if your line is too short, for example *"road 1 stops at 162.0 m, still 22.0 m
short of 140.0 m… needs at least 1375 m"*. A road that reaches the end elevation then **runs level**.

### 5.3 Road inputs
Always visible:

| Input | What it means | Default |
|---|---|---|
| **Haul road centreline(s)** | The line layer. Leave empty for no road. Tick **Selected features only** to use only selected lines. | empty |
| **Road gradient (%)** | Slope of the road along its length. **8%** is typical in North America, **10%** is the usual ceiling cited in the paper (component life is roughly halved at 10% compared with 8%). | 8 |
| **Overall width of your largest haul truck (m)** | Sets the road width: two-way = 3.5 x on straights, 4.0 x on curves; one-way = 2.0 x and 2.5 x. **Change this to your own truck – 6.5 m is only a placeholder.** | 6.5 |

Under **Advanced Parameters**:

| Input | What it means | Default |
|---|---|---|
| **Road traffic** | Two-way or one-way width rule (above). | Two-way |
| **Fixed road running width** | Use your own width for the whole road instead of the truck-width rule. Leave blank normally. | blank |
| **Road direction** | Whether the road goes down or up from its first vertex. | Pit: down, Dump: up |
| **Road start elevation** | Blank = the ground elevation at the first vertex. Enter a value to start at a specific level (for example the rim elevation). | blank |
| **Road end elevation** | Where the road stops climbing or dropping and runs level. Blank = **pit floor** (pit) or **dump crest** (dump). | blank |
| **Crossfall (%)** | Road surface slopes this much sideways toward the ditch, so water drains away from the drop-off edge. | 2 |
| **Cut a V-ditch** / **depth** | A drain on the **uphill** side: 3H:1V on the road side, 2H:1V on the far side. 0.3 m deep is the paper's minimum, giving a ditch about 1.5 m wide. | On, 0.3 m |
| **Windrow height (m)** | Safety berm on the **drop-off** side. The paper says at least **half the tyre height of your largest vehicle** (your risk assessment decides). 0 = none. | 1.5 |
| **Cut slope beside the road (H:V)** | Steepness of the bank cut where the road is below the ground. | Pit 0.84 (about 50 deg), Dump 1.5 |
| **Fill slope beside the road (H:V)** | Steepness of the embankment where the road is above the ground. | 1.5 |
| **Treat as a curve when radius is below (m)** | Below this radius the road is made wider and flatter (next two rows). | 75 |
| **Gradient reduction on curves (%)** | Curves are made flatter than the straight road – the paper suggests 2 to 3%. | 2.5 |
| **Truck turning-circle inner radius (m)** | Smallest INNER clearance radius of your truck's turning circle (from the spec sheet). The tool warns if a bend is tighter than 1.5 x this value plus half the road width (the paper's inside-tyre-path rule). | 10 |
| **Flat landing at the start (m)** | The paper keeps intersections flat (2 to 3% at most); the first part of each road is built level. 0 = none. | 15 |
| **Smooth the centreline over (m)** | Rounds sharp digitized corners. 0 = off. Try 30 to 50 if the log complains about tight radii. | 0 |

### 5.3a Pit roads never add fill
In the **pit** tool the road is **cut only**. It never rises above the original ground. Inside the pit the ramp is left as
**unexcavated rock** and the walls are cut back beside it, so the ramp runs on rock. The pit's cut volume in the log already
includes this. If the road's start is above the terrain it is trimmed to ground and the log warns you, so start the road at the
rim elevation. The windrow is the only thing allowed to stand above the ground. (The **pile** tool still builds the road on fill, since a dump road is built from dump material.)

### 5.7a Build order and road impact
Roads are best designed **bottom up**: the road starts at the pit floor (or dump base) and climbs, so the ramp is continuous from the working area and you can see the road's effect on the mining area and volumes. Bottom up is the default.

* **Spiral build order** (visible, next to the spiral tickbox): *Bottom up* (default) or *Top down*. For a pit, bottom up means the ramp starts at the floor and ends where it meets natural ground at the rim.
* **Digitized roads:** the default **Road direction** is now *Ascends from the first vertex*, so draw the road from the floor (or base) upward. Choose *Descends* to draw from the top.
* **Spiral direction** (Advanced) now says which way **loaded trucks climb** (clockwise by default).
* **Road impact** is written to the log after every road run: the cut volume (pit) or fill volume (dump) without and with the road and the difference, the pit floor area (or dump crest area) without and with the road, and the ground area reshaped by the road works. The totals returned and the contours include the road.

### 5.7 Automatic spiral road
Tick **Generate a SPIRAL haul road automatically** (leave the road line layer empty). The tool then routes the ramp for you.

* **Pit:** the road starts on the lowest ground at the rim and winds down the wall, following the benches around the pit at your
  gradient until it reaches the floor. **Dump:** it starts at the base and winds up to the crest.
* **Spiral direction** (Advanced): the paper notes loaded trucks usually climb clockwise, so the default is counter-clockwise going down.
* **Spiral start point** (Advanced): optional point layer; blank means the lowest ground at the footprint edge.
* If you also supply a road line, your line is used and the spiral is skipped.
* The road is placed on the average wall line at its own elevation, so it runs half in the wall and half on left-in-place rock (pit)
  or on the dump slope (dump). Check the result: sight lines, switchbacks and the final approach to the floor are yours to adjust.
* The log warns if turns are closer than one road width + 2 m (the footprint is too small or the gradient too flat for one ramp),
  if a bend is tighter than your truck allows, or if the pit or dump is too small to hold the ramp.

### 5.8 Drawing outputs (vector layers)
Each run can write these layers (leave them blank to skip):

| Layer | Contents |
|---|---|
| **Bench crest and toe strings** | The projected starter strings at constant elevation, one per bench edge (TYPE = CREST or TOE, BENCH, ELEVATION). They are traced from the finished surface, so where a ramp cuts or fills through a wall the strings are adjusted around it. |
| **Road centreline and edge lines** | 25 m segments. TYPE = CENTRE, EDGE_L or EDGE_R, with ROAD, SEG, ELEV_START, ELEV_END, GRADE_PCT, WIDTH, CURVE, ELEVATION. |
| **Road surface polygons** | The running surface in 25 m blocks with the same attributes, for outlined road drawings. |
| **Contours** | As before, now including the road. |

Style the bench lines by TYPE (for example dark blue crests, green toes), the road polygons with an outline, and the contours thin, to get a plan like a mine-design drawing.

### 5.8a Manual edits at the lowest string
The tool does not design equipment access where the road reaches the lowest string (pit floor) or the top string (dump crest): the entry, turning area and any switchback there are **adjusted by hand** in your own editing or design software. The log prints a NOTE with the end point and elevation of each road to help you find the spot.

### 5.9 Validation checks (warnings in the log)
Every run now checks the design and writes `WARNING:` lines to the log. **The checks never change the geometry**; read the log after each run.

| Check | Warns when |
|---|---|
| Outline polygons | A polygon is invalid (self-crossing, unclosed), is a sliver under 400 m2, or overlaps another polygon |
| Angles | Face angle is outside 30-80 degrees; inter-ramp angle exceeds the optional **Maximum allowed inter-ramp angle** (pit); overall slope is steeper than the inter-ramp angle. The log always prints the inter-ramp and overall angles |
| Benches | The last bench is under 3 m high; bench height is not a multiple of the contour interval |
| Surface | 5% or more of the footprint needs no excavation/fill because the ground is already past the design; the floor or crest is under 2,500 m2, or is never reached |
| Road shape | The road centreline or an edge crosses itself, or a bend is tighter than half the road width (the inside edge folds back) |
| Road connection | The road starts more than 1 m off the ground, ends outside the footprint, or ends away from the floor/crest elevation |
| Road overlap | Two roads, or two turns of one road, cover the same ground |
| Sight distance | A wall or windrow blocks the view ahead along the road. Target is 2x the **Truck stopping distance** (Advanced, default 60 m, 0 = skip); driver eye 2.5 m, object 1.0 m |

Assumptions behind the thresholds (400 m2, 2,500 m2, 3 m, 60 m stopping distance, 2.5 m eye and 1.0 m object height, 30-80 degree band) are mine, not from the paper; adjust your reading of the warnings to your site standards. The checks are advisory and do not replace a geotechnical or regulatory review.
Not checked: vertical datum and units (the DEM is assumed to be in metres), and super-elevation.

### 5.4 What the tool builds
From the **uphill** side to the **downhill** side, across the road:

**cut slope → V-ditch → running surface (falls toward the ditch) → windrow → fill slope**

* The road centreline climbs or drops at your gradient from the start elevation. Curves are **wider** and **flatter**,
  and the width changes gradually, not in a step.
* The **ditch goes on the uphill side** (the side with higher ground); the **windrow goes on the downhill side**.
* Beside the road, the DEM is cut or filled at your cut and fill slopes until it meets the existing ground.
* **Contours now cover the road too**, not just the pit or dump footprint.
* The log reports each road's length, start and end elevation, tightest radius, running widths, and the road's own **cut and fill volume**.

Example (6.5 m truck, two-way): running width 22.8 m on straights and 26 m on curves, a 4.5 m wide windrow at 1.5 m
high, a 1.5 m wide ditch.

### 5.5 What follows the Deswik paper – and what does not

| From the paper | How the tool applies it |
|---|---|
| Two-way 3.5 x truck width, 4 x on corners; one-way 2 to 2.5 x | Built in (one-way uses 2.0 x on straights and 2.5 x on corners – the paper gives only the 2 to 2.5 range) |
| Gradient 8% (North America) to 10% | Gradient input; **warns above 10%**, notes anything above 8% |
| Flatter gradient (2 to 3%) on curves | Gradient reduction on curves |
| Windrow at least half the tyre height | Windrow height input |
| V-ditch 3H:1V and 2H:1V, minimum 0.3 m deep | Built in |
| About 2% crossfall on curves/switchbacks | Crossfall input, applied along the whole road |
| Inside radius at least 150% of truck turning radius | Warning if the radius is tighter than 1.5 x your truck inner radius + half the width |
| Design two-way ramps to the shortest (inside) edge | Warns if the inside edge of a bend is steeper than 10% |
| Flat approach at intersections | Flat landing input |
| Road ends/levels at the pit bottom or dump top | Road end elevation (defaults to floor or crest) |

**Not modelled** – check these in your design: sight distance and stopping distance, passing or parking bays, direction of travel, super-elevation, switchback landings,
sumps at drain ends, ramp-to-berm flares, the minimum mining width at the pit bottom, the wider safety berm about every
6 benches, pavement thickness, and automatic route-finding for ramps (draw the centreline yourself).

Tips from the paper: ramps are usually designed to climb clockwise when loaded, and the bottom 2 to 3 benches are often one-way.

### 5.6 Things to know about roads
* **Assumptions of mine, not from the paper** – please confirm they suit your site: windrow base = 3 x its height
  (1.5H:1V sides); crossfall 2% toward the ditch; cut slope 0.84:1 in a pit and 1.5:1 in a dump; fill slope 1.5:1;
  the 75 m curve threshold; the gradient reduction applies to the centreline (the paper refers to the inside lane);
  the ditch and windrow sides are chosen from the ground.
* The ditch is only 1.5 m wide, so at 1 m cells it appears as one or two cells. The windrow (4.5 m) shows clearly.
* Very high walls beside a road: the cut slope is followed up to **150 m** from the road. Beyond that you may see a step, and the log says so.
* Overlapping or crossing roads are not blended; where two roads meet, tidy the junction yourself.
* A road runs through the pit or dump **after** it has been built, so it cuts into the walls or the dump face as it should.

---

## 6. Working with the results

* **Make permanent:** results are temporary by default. Right-click the layer ▸ Export ▸ Save As…,
  or choose a file name in the output box before running.
* **See the shape:** Raster ▸ Analysis ▸ **Hillshade** on the new DEM, then show your aerial imagery
  semi-transparent over it.
* **Label contours:** Layer Properties ▸ Labels ▸ Single Labels ▸ Value = `ELEVATION`.
* **Contours** are drawn only inside your outline, at multiples of the interval (a 5 m interval gives 205, 210, 215…).
* The output DEM is at **1 m cells**, even if your input was 30 m. This gives clean bench edges, but
  the underlying ground is still only as detailed as your original DEM.
* **Cancel** button: you can stop a run at any time without closing QGIS.

### Several polygons
* **Untick "Selected features only"** (default) → every polygon in the layer is used and they are treated as **one combined** pit or dump.
* **Select one polygon, then tick "Selected features only"** → only that polygon is used. Run again for the next one, using the previous output as the **Input DEM** to combine several pits and dumps in one terrain.

---

## 7. Troubleshooting

| Message / problem | What to do |
|---|---|
| *"…does not overlap the DEM"* | The outline and DEM cover different areas, or the outline has the wrong CRS assigned. Check both on the map. |
| *"Pit rim elevation must be above the pit floor elevation"* | Swap or correct the two elevations. |
| *"nothing was excavated"* (log warning) | Your rim elevation is below the ground inside the outline. Raise the rim elevation. |
| *"nothing was added"* (log warning) | Your dump base elevation is below the ground inside the footprint. Raise the base elevation. |
| *"…too large for memory"* | The DEM covers too big an area at 1 m. Clip it to the area around your outline (Raster ▸ Extraction ▸ Clip Raster by Extent) and rerun. |
| *"…no usable polygons"* / *"…no usable lines"* | "Selected features only" is ticked but nothing is selected. |
| *"Road 1 starts outside the DEM"* | Move the first road vertex onto the DEM, or type a **Road start elevation**. |
| *"road stops at … m, still … m short"* | The road line is too short for the gradient. Lengthen it (see 5.2), or raise the gradient. |
| *"WARNING: road gradient … above 10%"* | Lower the gradient unless your site allows it. |
| *"curve of radius … m, tighter than your minimum"* | Redraw the bend with a larger radius, or use **Smooth the centreline**. |
| Road looks like a trench or an embankment | Normal where the road gradient differs from the slope. A road cuts where the ground is higher and fills where it is lower. |
| Output looks flat or wrong height | Check the elevation inputs are in **metres** and in the same elevation system as your DEM. |
| Tool not in the toolbox | Check the plugin is ticked in Manage and Install Plugins; restart QGIS once after installing. |

---

## 8. Good to know
* Everything is calculated in **UTM metres**. If your layers are already UTM they are used as they are; no extra copies are made.
* Volumes in the log are calculated from the 1 m grid and are meant for planning-level estimates.
* This is a **surface-modelling tool for visualisation and concept planning**, not a certified design package.

## Reporting bugs
Report problems on the project's GitHub Issues page and paste the full Log text, your plugin and QGIS versions, and the inputs you used. Reports are welcome, but **there is no guarantee of a reply or a fix**, and no timeline applies.
