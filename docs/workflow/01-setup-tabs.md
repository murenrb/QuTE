# Workflow — Start Screen and Setup Tabs

Layout and style: [../gui.md](../gui.md) (canonical). Math:
[../models/sizing.md](../models/sizing.md). Results panels:
[02-results.md](02-results.md).

Everything below happens on **one workspace page**: a tabbed inputs panel
(top-left) beside the always-visible map (top-right); below a full-width line,
the output layer: the module output (left) and the three-row results figure
(right) in one figure, metrics under them (D-024, D-025, D-029, D-032, D-055). Tabs, in order: **Location · Property · Data center · Utility · Modules**. The user can switch tabs at any time without losing input.

## 0. Start screen (separate page, titled **QuTE**, D-071)
- **Open project** — pick any saved project (all projects are public, D-069;
  listed newest first as name · last saved · id), or upload a project JSON
  → restore state, open the workspace on the saved tab; results re-compute
  automatically (weather from cache or re-fetched).
- **Start new setup** → workspace, Location tab.
- From here on every config change autosaves that project in the database
  (`services/store.py`). The project bar on the workspace has **Save
  version**, **Versions** (restore), **Link** and **Download** — see
  [../data-model.md](../data-model.md#database-d-069).
- The workspace URL names the project (`/workspace?project=<id>`), so a
  reload, a shared link, or a session Streamlit dropped while the browser was
  away reopens that project — never a blank one (D-040) and never someone
  else's. Without a saved project in the URL it goes to Start.

The active tab decides which map tools exist (D-027, table in
[../gui.md](../gui.md#map)): Location = pan/zoom only; Property = polygon tool
only; Data center = facility block only; the view is locked outside Location.

## 1. Location tab
- Tab note: **"Select a location for the project. Ensure the map shows the
  entire property in question."**
- Street address **or** lat/lon. Address is geocoded: US Census geocoder first
  (exact US street addresses), then OpenStreetMap Nominatim (D-022).
- On a match the map recentres on the site; the matched address is shown.
- **Map: free pan and zoom**, no drawing or placement tools. The user frames
  the whole property; that view (map bounds) is saved as the site's map view
  and becomes the fixed view on every other tab.
- **"Use map center as location"**: pan to the site and set the location to the
  map's center (keeps the framing) — for sites without a usable address.
- Changing the location later keeps any boundary; if the boundary falls outside
  the new view, the Property tab warns and offers "Clear boundary".

## 2. Property tab
- Tab note: **"Use the polygon tool to select the limits of the property."**
- **Map locked** to the saved view (no drag or zoom). The **polygon tool is the
  only tool and is armed on entering the tab** — the user just clicks corners.
- If a boundary already exists it is shown with its labels and the tool is not
  armed; "Clear boundary and redraw" removes it and re-arms the tool.
- Needs a location first: without one, the tab says to set the location.
- **Straight segments only**; **one contiguous polygon** (no multiple parcels
  or exclusion zones yet — D-011).
- Map labels: interior angle at each vertex, side length (ft) at each midpoint.
- Tab shows boundary area (acres, sqft) and corner count.
- Self-intersecting shapes are rejected with a message and the tool re-arms.

## 3. Data center tab
### 3.1 Type
- Select a saved type, or create one via the form (fields in
  [../data-model.md](../data-model.md#datacentertype-saved-reusable)).
- No name input: the name is generated from the inputs (D-023). Saving a design
  that already exists tells the user the saved version will be used and selects
  it; otherwise it is saved under its new name.
- **Supply (cold) water** is a two-sided slider: minimum (default 5 °C) and
  setpoint (default 40 °C). The (i) note explains it: chillers hold the
  setpoint; free cooling lets the supply float down at ambient + approach, to
  no lower than the minimum (D-047).

### 3.2 IT load
- Peak IT load in **MW** for this data center (default 10 MW).
- Hourly IT profile: 24-value daily profile, constant at peak for Step 1, tiled
  over 365 days. Future versions accept a real daily (then annual) profile —
  the backend must not change when that happens.

### 3.3 Area breakdown
- Data hall, backup power, chillers, total — sqft and m². "Chillers" is the
  lumped cooling plant area: chillers and their heat rejection (dry coolers or
  cooling towers), on IT load only (owner, D-067).

### 3.4 Facility placement
- Block area = total facility area; starts as a **square** at the boundary
  centroid (or the site location if no boundary).
- On the map (footprint editor, D-030): drag the **body** to move; drag an
  **edge** handle → that side changes and the other adjusts to **keep the area
  constant**; drag the **◆ knob** to rotate freely (default orthogonal to the
  screen; hold Shift to snap to 15°). Tab note: "On the map: drag the block to
  move it · drag an edge handle to resize (area stays the same) · drag the ◆
  knob to rotate (hold Shift to snap to 15°)."
- Precise entry in the tab, synced with the map: Width (ft), Length (ft) (each
  sets the other to hold the area), Rotation slider, "Center in boundary",
  "Align to property edge".
- **Outside-boundary feedback:** the block fill turns **red** whenever any part
  is outside the property polygon, plus a text warning. Warning only — never
  blocks placement.
- **Map locked** to the saved view (no drag or zoom); the boundary is shown but
  cannot be edited. The facility block is the only interactive object.

## 4. Utility tab (D-043)
- Map locked, display only.
- Tariff painter: rate categories (defaults Off peak $0.10/kWh + $10/kW,
  Shoulder $0.15 + $10, Peak $0.20 + $10; add/rename/reprice/delete), each
  with a blue → purple → red swatch; paint them onto the month × hour table (default all
  off peak). "Weekend energy prices": Follow schedule / Off peak.
- Feeds hourly energy price, energy cost and the monthly demand charge —
  [../models/utility.md](../models/utility.md).

## 5. Modules tab
- Clicking a module's area or block on the map (any tab) opens this tab with
  that module selected; clicking the data center block opens the Data center
  tab (D-042).
- **Only the modules on the site are listed** (D-056): a selector at the top
  with one button per module added (none to start: "No modules on the site
  yet"), and an **Add module** button beside it. Add module opens a dropdown
  of the modules not on the site yet (with a one-line description); "Add to
  the site" adds it and opens its tab. Each module's panel ends with
  **"Remove … from the site"**: its inputs, area and block are kept, so adding
  it back restores them. The same list drives the results' module output
  selector and the Control tab's components.
- The **selected module sets the map tool** (D-036): map locked to the saved
  view, and the straight-line polygon tool is armed while that module has no
  area.
- Each module is **scaled in map** (drawn area, vertex-editable — PV) or
  **scaled in inputs** (block sized by its inputs — ice storage); see
  [../gui.md](../gui.md#map) (D-041).
- Drawing a module's area: it may go outside the property or over other areas;
  when closed it **snaps** to the free land — inside the property boundary,
  outside the data center block and other modules' areas. The tab then shows
  area (acres, sqft) and pieces, with "Clear area and redraw". Requires a
  property boundary. Warnings appear if later edits (moving the block,
  redrawing the boundary) create overlaps.
- Entry point for co-located systems (see [../roadmap.md](../roadmap.md)). Each
  module adds its own inputs here, its own columns to the hourly frame, and its
  own traces to the results figure; results update live.
- **Solar PV** (built): note "Use the polygon tool to draw the area dedicated
  to solar…"; once drawn: corner handles on the map, **"Snap edges to
  N/S/E/W"** and "Clear area and redraw"; **power density slider 5–9 W/sqft (0.25 steps, default 6.5)**;
  **"Cover the data center"** checkbox (default off: adds the data center
  block's roof at the same density, D-073); DC capacity = (area + roof) ×
  density (shown); array type, module type, tilt
  (defaults to the site latitude; "Use site latitude" resets a typed tilt),
  azimuth (defaults to facing the equator for the site's hemisphere; "Face the
  equator" resets a typed azimuth); Advanced: losses, DC/AC ratio, inverter efficiency, ground coverage
  ratio. PV is in the model only once an area is drawn —
  [../models/solar-pv.md](../models/solar-pv.md).
- **Ice storage** (built, **scaled in inputs**):
  **ice maker size — log-scale slider, default 65 TR per MW of IT load**
  (follows the data center until moved; "Use 65 TR per MW of IT load"
  resets), **tank size — slider 6–72 h, default 24 h**, starting ice tank and
  water tank states of charge, **energy density (kWh_th/sqft, default 15)** → footprint = tank
  kWh_th / density;
  block placement controls (width, length, rotation, "Place beside data
  center", "Align to property edge"); performance curves in an expander. Step 1 control: always cleared to make ice; nothing uses ice yet,
  so the ice tank fills from the water tank and waits (D-049) — [../models/ice-storage.md](../models/ice-storage.md).
- **Waste heat to power** (internal key `power_generation`; built, **scaled in inputs**): **rated power — slider 0.5–150 % of the IT load,
  default 2 %**, with the MWe it gives in grey right under it (D-063); **% of Carnot slider 10–50, default 30**; **max cold-side
  temperature slider 0 → free-cooling cutoff, default 10 °C**; **power
  density slider 1,000–3,000 sqft/MWe, default 2,000** → footprint; block
  placement controls — [../models/power-generation.md](../models/power-generation.md).
- **Hot water storage** (built, **scaled in inputs**): **heat storage slider 4–72 h, default 12**; **Connection
  radio Direct / Indirect**; **Tank type radio Two tank / Thermocline**
  (Thermocline shows the red perfect-stratification warning); tank height;
  volume / diameter / footprint shown; block placement controls. The default
  block is square for a thermocline and 2:1 for two tanks, with 20 ft of
  buffer — [../models/hot-water-storage.md](../models/hot-water-storage.md).
- **Brine separation** (built, **scaled in inputs**): **brine type dropdown (Potassium acetate)**;
  **concentration range two-sided slider 0–50 wt%, default 20–40**; **time to
  concentrate tank slider 6–72 h, default 24**; brine mass / tank volume /
  footprint shown; block placement controls. The default block is a square of
  the 12 m tank's diameter + 20 ft each side —
  [../models/brine-separation.md](../models/brine-separation.md).
- **Ice mixer** (built, **no footprint**):
  **Fluid radio Water / Brine**; on brine only (water melts at 0 °C, so
  neither applies; owner): **recuperation efficiency slider 50–90 %,
  default 70**; **mixing efficiency slider 50–90 %, default 80** (100 % is
  impossibly ideal). Switching to water keeps their values. Warns if
  ice storage (or, for brine, brine separation) isn't on the site. The hourly solver
  settles its ice / brine each hour; the chillers carry the rest —
  [../models/ice-mixer.md](../models/ice-mixer.md).
- **Greenhouse** (built, **scaled in map**): draw its floor with the polygon
  tool (like PV); floor and glass area shown once drawn; **glass
  transmissivity slider 80–100 %, default 90**; **temperature setpoint slider
  15–40 °C, default 20**; **covering U-value slider 5–10 W/m²K, default 7.5**,
  with a link right under it to the Texas A&M AgriLife table of typical
  U-values (and the value in Btu/h·ft²·°F). Warns if the data center's return
  water isn't warmer than the setpoint —
  [../models/greenhouse.md](../models/greenhouse.md).
- Every module is **off** until a state of the Control tab names it in a
  THEN (or the "Run everything in Default" preset does) — D-053, D-054.
- Still to come: greenhouses, wastewater, district heating, food processing.

## 5b. Control tab (D-053, D-054)
State machine: a diagram of the states (corners of a polygon, Default at the
top, arrows = allowed moves) and, below it, the selected state's
editor — name, priority, delete, "Can move to", IFs (ambient, utility, time,
the data center and each module) and THENs written as sentences (IT load %,
each module's flags, numbers and links to other modules, in order, with ↑ / ↓).
Every IF / THEN has **Edit** (takes it out and fills the add row with it;
Add puts it back in its place) and **Remove**. A new state is named in the box
next to **Add state**. Each state is a complete description. Details:
[../control.md](../control.md).

## 6. Live model run (replaces the old "Save configuration" button)
When the project has a **location** and a **data center** (type + IT load), and
again after **any** input change:
1. Autosave the project (always, on every change).
2. Get NSRDB TMY weather for the location — disk/session cache, so only a new
   location triggers a download →
   [../integrations/nsrdb-weather.md](../integrations/nsrdb-weather.md).
3. Build the hourly DataFrame and run the pipeline →
   [../models/datacenter-hourly.md](../models/datacenter-hourly.md).
4. Redraw the results figure and metrics ([02-results.md](02-results.md)).

- Model runs are cached on the project's `inputs_hash`, so reruns that don't
  change an engineering input don't recompute.
- Weather/model errors show in the results area (grey panel, error text); the
  inputs stay usable.
- Until location + data center exist, the figure and metrics show a grey placeholder.
