# Decision Log

Append-only. One entry per decision; supersede rather than edit.

Template:
```
## D-NNN — <title>  (YYYY-MM-DD)
Status: proposed | accepted | superseded by D-MMM
Context: why this came up
Decision: what we chose
Consequences: what it affects / docs updated
```

---

## D-001 — Markdown docs are the canonical spec  (2026-09-29)
Status: accepted
Context: Original scope lived in `Project Scope Musings/Datacenter system, Step 1.docx`.
Decision: Converted into `CLAUDE.md` + `docs/`. Docs are now the source of truth.
Consequences: Spec changes are made in the docs, not the .docx.

## D-002 — Streamlit UI / pure-Python core split  (2026-09-29)
Status: proposed
Context: Needs to scale to many co-located subsystems and be testable.
Decision: `app/` (Streamlit only) + `core/` (pure, typed) + `services/` (I/O);
hourly model as a registered subsystem pipeline over one DataFrame.
Consequences: See architecture.md.

## D-003 — Free-cooling threshold based on supply temperature  (2026-09-29)
Status: accepted
Context: .docx compared ambient to return temp, with contradictory wording.
Decision: Free cooling when `t_amb + t_approach < t_supply` (no temperature
cross). Mechanical cutoff ≈ 30 °C with defaults. Mechanical COP cold side
provisionally `t_supply − t_pinch` (confirm: open-questions.md #1).
Consequences: models/datacenter-hourly.md, assumptions.md, overview.md, testing.md updated.
The .docx will be corrected by the project owner.

## D-004 — Carnot fraction = 40 %  (2026-09-29)
Status: accepted
Decision: `carnot_fraction = 0.40` in `core/config/defaults.py`.

## D-005 — Site Optimization layout: map left, charts right  (2026-09-29)
Status: accepted

## D-006 — GitHub + Streamlit Community Cloud  (2026-09-29)
Status: accepted
Decision: Repo `github.com/goldfarbmuren/Data_Center_System`, branch `main`.
Target Streamlit Community Cloud; secrets via Streamlit secrets; root
`requirements.txt` kept for deployment.

## D-007 — COP cold side = supply − pinch  (2026-09-29)
Status: accepted (resolves D-003 provisional)
Decision: `T_cold = t_supply − t_pinch` — the coldest possible combination.
Supply = cold water to IT, return = warm water back.

## D-008 — Condenser approach on Carnot hot side  (2026-09-29)
Status: accepted
Decision: `T_hot = t_amb + t_cond_approach`; 10 °C dry, 5 °C evaporative, in defaults.py.

## D-009 — Binary free/mechanical split per hour  (2026-09-29)
Status: accepted — keep simple for Step 1.

## D-010 — Persistence: autosave local JSON + download + open  (2026-09-29)
Status: accepted
Decision: Whole project autosaves to local JSON on every config change;
download button exports it; start screen offers open-file or new setup.
Single user for now; multi-user/hosted storage deferred.

## D-011 — Boundary and footprint rules  (2026-09-29)
Status: accepted
Decision: One contiguous boundary polygon. White space ratio min 10 %.
Footprint outside the boundary = warning only, with red fill during drag. Areas stay in sqft.

## D-012 — Weather & time  (2026-09-29)
Status: accepted
Decision: Local standard time, no DST. NSRDB only for now; alternate sources
(EPW upload, PVGIS) noted in roadmap.md.

## D-013 — Hourly model implementation choices  (2026-09-29)
Status: accepted
Decision: Hourly frame index is naive local standard time on reference year
2025 (non-leap), so every TMY maps onto the same index. IT profile is tiled by
hour-of-day. Heat offtake enters via a `NoHeatOfftake` (zero) subsystem that
future co-located systems replace; net grid load is a `GridBalance` subsystem
that sums all stacked electrical columns in the registry.

## D-014 — Weather columns kept  (2026-09-30)
Status: accepted
Context: nsrdb-weather.md asked to decide once whether to keep extra NSRDB fields.
Decision: The hourly frame gets only `tdb_c`, `twb_c`, `tdp_c`, `rh_pct`,
`ghi_w_m2`; other fields are dropped. The raw CSV stays in the disk cache, so a
future subsystem can register and parse more (e.g. wind, DNI) without a re-download.

## D-015 — NSRDB dataset: GOES TMY v4, pinned to tmy-2024  (2026-09-30)
Status: accepted
Context: PSM3 TMY is deprecated. `names=tmy` means "latest", which would silently
change results for saved projects (weather is re-fetched on load, not stored).
Decision: GOES TMY v4 endpoint, `names=tmy-2024`, request `utc=false` (local
standard time), map the `:30` stamp to the hour-beginning slot. Bump the pin
deliberately in `NsrdbSettings` (it's part of the cache key).
Consequences: Americas only; other regions give `WeatherNotAvailableError`.

## D-016 — Wet bulb derived with vectorized ASHRAE psychrometrics  (2026-09-30)
Status: accepted
Context: NSRDB returns no wet bulb. Options: Stull approximation (±1 °C, ignores
pressure), `psychrolib` (exact but scalar — a Python loop over 8760 rows), or
the same ASHRAE equations vectorized.
Decision: Vectorized ASHRAE Fundamentals ch. 1 equations (Hyland–Wexler
saturation, eqs. 33/35 wet-bulb humidity ratio) solved by bisection, using NSRDB
pressure. `psychrolib` is kept as the test reference. Published correlation
coefficients live in `core/weather/psychrometrics.py` beside the correlation;
tunable solver settings live in `defaults.py`.
Consequences: Matches psychrolib within 0.01 °C except within ~0.5 °C of
twb = 0 °C, where the ice/liquid equations jump and either root is valid —
irrelevant to the ~30 °C free-cooling threshold.

## D-017 — Weather cache location  (2026-09-30)
Status: accepted
Decision: `data/cache/nsrdb/` (gitignored) by default; `DCS_CACHE_DIR` env var
overrides it, e.g. to keep downloads out of OneDrive sync.

## D-018 — Local metric frame: azimuthal equidistant, not UTM  (2026-09-30)
Status: accepted
Context: gui.md asked for a projected metric CRS (local UTM) for map geometry.
Decision: Use an azimuthal equidistant projection centred on the site
(`core/geometry/local_frame.py`). Metres, +y = true north (UTM grid north can be
a few degrees off, which would skew "rotation 0 = orthogonal to screen"), and
no zone edges. Distortion is negligible over a site.

## D-019 — Interim facility placement; Esri greyscale basemap  (2026-09-30)
Status: accepted (interim)
Context: The drag/resize/rotate block needs a custom Streamlit component.
Decision: Ship Site Setup first with a width input (length follows, area held),
a rotation slider, click-to-move and "Center in boundary"; the block turns red
when outside. The custom component is the next step and will write the same
`Footprint`. Basemap switched to Esri World Gray Canvas because CartoDB tiles
now require an API key.

## D-020 — Display units on the site map  (2026-09-30)
Status: accepted
Decision: Geometry is computed in metres; the UI shows side lengths and block
dimensions in ft, and areas in sqft (plus acres for the parcel), matching the
sqft sizing units (D-011).

## D-021 — Default IT load input  (2026-09-30)
Status: accepted
Decision: IT load input range 0.1–2000 MW, default 10 MW (the sizing worked
example). In `DataCenterInputs` in defaults.py.

## D-022 — Geocoding: US Census first, Nominatim fallback; certifi CA bundle  (2026-09-30)
Status: accepted
Context: Every lookup failed with GeocoderUnavailable. Cause: geopy used
Python's default SSL context, and python.org/uv builds on macOS ship without
system CA certificates (CERTIFICATE_VERIFY_FAILED). Once fixed, Nominatim still
had no match for a rural US street address: OSM has the
road but no house numbers, which is common in rural areas.
Decision: Pass `certifi`'s CA bundle to Nominatim (`certifi` now a declared
dependency). Try the free, keyless US Census geocoder first (exact US street
addresses from TIGER address ranges), then Nominatim (towns, places, non-US).
A provider that errors is skipped; the user sees an error only if all fail.

## D-023 — Data center type names are generated, not entered  (2026-09-30)
Status: accepted
Context: Owner: the name should not be an input; it should be a concise,
informative concatenation of the inputs. Saving an existing design should tell
the user the saved version will be used; otherwise save under the new name.
Decision: `DataCenterType.name` is a computed field:
`Dry · 40→50 °C · 50 kW/rack · 65% WS · N+1 · UPS/Gen/SWG 1/1.5/0.5 sqft/kW`.
Identity = parameters (floats rounded to 6 decimals). Files are named from a
parameter stem. Type schema → v2; stored names (v1 user names, v2 derived) are
ignored on load, so old files and projects still open.
Consequences: data-model.md, gui.md, 01-site-setup.md updated.

## D-024 — Visual style and layout from the aesthetics guide  (2026-09-30)
Status: accepted — supersedes D-005 and the earlier page sketches in gui.md
Context: Owner added `docs/App asthetics guide.docx` and `docs/Layout example.png`,
to override the layout in the other docs. The guide text says the map stays
"in the left of the screen" but the image puts it top-right; owner confirmed:
follow the image.
Decision: Greyscale UI with color only for data traces and the facility overlay;
one Arial-like sans-serif, 12 pt normal/light body, headers ≤ 14 pt bold;
square corners everywhere. Layout: tabbed inputs (Location · Property · Data
center · Modules) top-left, map top-right, Temperature/GHI chart + output
metrics bottom-left, thermal + electric charts bottom-right.
Consequences: gui.md rewritten; workflow docs renamed to 01-setup-tabs.md and
02-results.md; overview, architecture, data-model, testing, roadmap, CLAUDE.md updated.

## D-025 — Single workspace page; results update live  (2026-09-30)
Status: accepted — supersedes the "Save data center configuration" step and
the separate Site Optimization page
Decision (owner): Merge Site Setup and Site Optimization into one workspace
page (Start screen stays separate). Once a location and a data center exist,
fetch weather (cached) and re-run the model on every input change — no Save
button; the project still autosaves. Model runs cached on `inputs_hash`.
`Project.step` now stores the active tab.

## D-026 — Linked time window across split charts  (2026-09-30)
Status: accepted
Context: The layout splits the three charts across two columns, so Plotly's
shared x-axis (one figure) can't link them.
Decision: One time-window control (full year default) sets the x-range of all
three charts; each chart is its own figure.

## D-027 — Map tools are set by the active tab  (2026-09-30)
Status: accepted (owner)
Decision: Location tab: free pan/zoom, no tools; note "Select a location for the
project. Ensure the map shows the entire property in question." The framed view
(bounds) is saved on the site. Property tab: view locked, polygon tool is the
only tool and armed by default; note "Use the polygon tool to select the limits
of the property." Data center tab: view locked, boundary read-only, only the
facility block is interactive (click-to-move until the drag component lands; no
"Click map to move" toggle). Modules tab: locked, display only.
Interpretation: "cannot edit the map" on the Data center tab = no pan/zoom
either. Drawing a boundary now requires a location first (the old
"boundary centroid becomes the location" path is dropped).

## D-028 — Workspace implementation choices  (2026-09-30)
Status: accepted
Decision:
- Tabs: `st.tabs(key=…, on_change="rerun")`; only the open tab's content runs;
  the tab is seeded once from `Project.step` (a changing `default` would rebuild
  the widget and drop clicks).
- Map: `st.fragment`, so Location-tab panning doesn't re-send the charts. Each
  mount opens on a view frozen per map version (`state.mount_view`) so saving
  the panned view doesn't re-fit the map. Locked tabs disable Leaflet dragging,
  all zoom inputs and the +/− control. The polygon tool is armed by a small
  `L.Draw.Polygon(...).enable()` script; the Draw toolbar (polygon only) stays
  as a fallback.
- Location tab adds "Use map center as location".
- Charts: month-range time window; kW shown as MW; registry colors from the
  dataviz reference palette.
Known deviation: GHI stays on a secondary y-axis because the spec requires it
(02-results.md), although dual axes are generally discouraged; revisit if the
chart reads poorly.

## D-029 — Results as one figure of three stacked subplots, right column  (2026-09-30)
Status: accepted (owner) — supersedes D-026 and the chart placement in D-024
Context: Owner: aligned time axes that update together are essential; the split
charts with a month slider weren't good enough.
Decision: One Plotly figure under the map with three stacked subplots
(Temperature/GHI, Thermal, Electric) sharing one x-axis; zoom/pan/hover linked
natively; range slider under the bottom subplot. Left column: output metrics
under the inputs, with space kept for more outputs. The month-range time-window
control is removed. Page content also moved down ≥ 3 text lines so the tabs
clear the top navigation bar.

## D-030 — Footprint editor: custom component with drag / resize / rotate  (2026-09-30)
Status: accepted (owner) — replaces the interim click-to-move in D-019
Decision: A small custom Streamlit component (`app/components/footprint_editor/`)
on the Data center tab: vendored Leaflet 1.9.4 + plain JS, talking to Streamlit
through the component message protocol (no npm build). Body drag moves; edge
handles resize with the area locked and the opposite edge fixed (1:10 aspect
limits); a knob rotates, Shift snaps to 15°. Live readout and red/blue fill
while dragging (browser check handles concave parcels). On release Python
re-validates (`edited_footprint`) and remains the source of truth. Tab adds a
Length input and "Align to property edge"; nudge buttons not added.
Browser geometry uses WGS84 local radii so it matches the Python AEQD frame
(a spherical-Earth version was off by ~10 cm over 40 m); a Node-run test holds
agreement within 1 cm. `xyzservices` declared as a direct dependency (tile URL).

## D-031 — Locked tabs reopen at the exact Location center + zoom  (2026-09-30)
Status: accepted — refines D-027 (saved view)
Context: Owner: switching to the Data center tab zoomed out ~50 %. The locked
tabs re-fitted the saved *bounds*; Leaflet zooms in whole steps, and the
footprint editor's panel is 2 px smaller (border), so the bounds no longer fit at
the same zoom and it dropped one level (= 50 %). Property tab had the same risk.
Decision: Store the Location tab's exact center and zoom (`map_center`,
`map_zoom`) alongside the bounds and open every locked tab — folium and the
footprint editor — with `setView(center, zoom)`. Bounds are fitted only for
projects saved before this change. The editor also calls `invalidateSize()`
after its iframe is sized.
Trade-off: on a much narrower screen than the one used to frame the view, the
edges of the view are cropped rather than the map zooming out.

## D-032 — Separate input and output layers with a line  (2026-09-30)
Status: accepted (owner) — refines D-029 placement
Decision: The workspace is two stacked layers of two equal columns: input layer
(tabbed inputs | map), a full-width grey line, then the output layer (metrics |
results figure). Outputs always start below the map, never beside it.

## D-033 — Module pattern: pure physics functions + DataFrame adapter  (2026-10-01)
Status: accepted (owner)
Decision: Modules are written in two layers — pure, DataFrame-unaware physics
functions (arrays/scalars in and out) and a thin `Subsystem` adapter that reads
`requires` columns, calls them and writes `provides` columns. Stateless modules
are vectorized; stateful modules use a one-hour step function looped over numpy
arrays (never `iterrows`). Cross-module effects go through agreed interface
columns. Documented in architecture.md → Writing a module; conventions.md loop
rule updated accordingly.

## D-034 — Keep DNI, DHI and wind speed in the weather frame  (2026-10-01)
Status: accepted — revises D-014
Decision: The hourly frame also keeps `dni_w_m2`, `dhi_w_m2`, `wind_m_s` (needed
by PVWatts). NSRDB's timestamp minute (30) is kept as `WeatherMeta.data_minute`
so solar models compute sun position at the stamped time. Units checked on parse.

## D-035 — Solar PV: PVWatts V8 run locally via PySAM  (2026-10-01)
Status: accepted (owner)
Context: The PVWatts V8 web API can't use a chosen weather file — it uses its
own NSRDB PSM V3 tmy-2020 data and `file_id` only selects from that catalog —
so its hours wouldn't align with our tmy-2024 frame. Switching our weather to
tmy-2020 was rejected (deprecated dataset; API weather lacks humidity).
Decision: Run PVWatts V8 through `nrel-pysam` (NREL, BSD-3; wheels for Py3.13
macOS/Linux) on our own weather. Inputs mirror the API; output `pv_kw` is
negative and stacked below zero in the Electric subplot. Modules are included
only when enabled; `GridBalance` sums the stacked electrical columns the active
subsystems provide. Module settings stored in `Project.modules` (additive
field; older files load with PV off).
Validation: 1 MW Phoenix → 1,758,822 kWh (PySAM, tmy-2024) vs 1,764,113 kWh
(web API, tmy-2020), 0.3 % apart.

## D-036 — Module areas drawn on the map; PV sized from area  (2026-10-01)
Status: accepted (owner) — refines D-035
Decision: Modules that occupy land are placed by drawing an area on the Modules
tab with the straight-line polygon tool (map locked, tool armed for the selected
module). The drawing may cross the property line or overlap other areas; on
closing it snaps to the free land: ∩ property boundary − data center block −
other modules' areas (can split into pieces or leave holes; slivers < 1 m²
dropped). Later edits that create overlaps give warnings, not automatic changes.
Solar PV capacity = snapped area × power density (slider 5–9 W/sqft, step 0.25,
default 6.5); the kW input and on/off toggle are removed — PV is active once it
has an area. PVWatts has no land-density value to reuse (its array area is
module area); 6.5 W/sqft is the owner's default.
Scalable pattern: `SitedModuleParams` (area) in core, `ModuleSettings.sited()`
discovers them; app registry `ModuleUI` (key, label, color, panel). Project
schema → 2 with a v1→v2 migration for the old PV fields.

## D-037 — Ice storage module and the chiller-load hand-off  (2026-10-01)
Status: accepted (owner)
Decision: The owner's one-hour ice step becomes layer 1 (`ice_step`), with
design inputs in `IceStorageParams` and per-hour inputs as arguments
(state of charge, Q_required, ambient, cleared_to_run). To let storage change
chiller power without circular dependencies, cooling electricity moved out of
`DataCenterModel` into `CoolingElectric`, which reads a new hand-off column
`cooling_chiller_kwth` (`NoCoolingStorage` = demand; `IceStorage` = demand −
ice cooling). `cooling_mech_kwth` is now the mechanical *demand* (not
plotted); the thermal stack shows chillers + ice + free cooling. Step 1
control: always cleared; Q_required = mechanical demand (state machine next).
Physics changes agreed with the owner are listed in models/ice-storage.md.
Ice storage is not sited (no area) yet.

## D-038 — PV tilt defaults to the site latitude  (2026-10-01)
Status: accepted (owner)
Decision: `SolarPVParams.tilt_deg` is optional; None means tilt = |latitude| of
the map location (`Site.lat`), capped at 90°, with 20° only as a fallback when
there is no location. A tilt typed in the Modules tab is stored and used until
"Use site latitude" resets it. (Azimuth: see D-039.)

## D-039 — PV azimuth defaults by hemisphere  (2026-10-01)
Status: accepted (owner)
Decision: `SolarPVParams.azimuth_deg` is optional; None means equator-facing —
180° (south) for site latitude ≥ 0, 0° (north) for latitude < 0 — with 180° as
the fallback without a location. Same behaviour as tilt: a typed azimuth is
kept until "Face the equator" resets it. Tilt and azimuth share one UI helper
and one model resolver (`resolve_orientation`).

## D-040 — Safe autosave, snapshots and saved versions  (2026-10-05)
Status: accepted (owner)
Context: Owner came back to a blank workspace and an overwritten autosave.
Reproduced: Streamlit drops a disconnected session after 120 s; the browser
reconnects to a new session on the workspace URL, which showed a blank project,
and the first click autosaved it over `untitled-site.json` — every new project
shared that file name.
Decision: (1) Only a session that opened/created a project autosaves; a
workspace without one reopens the most recent autosave (with a notice) or goes
to Start. (2) Each new project gets its own autosave file
`<name-slug>-<6 hex>.json`; opened autosaves keep their file. (3) Automatic
history snapshots of the autosave (≤ every 5 min, forced before a restore,
newest 50). (4) Named "Save version" copies that autosave never touches, with
restore, in a visible project bar above the workspace (sidebar now holds only
model assumptions). (5) `server.disconnectedSessionTTL` = 12 h.

## D-041 — Module map categories: scaled in map vs. scaled in inputs  (2026-10-05)
Status: accepted (owner) — refines D-036, D-037
Decision: Every module is one of two map categories (ask the owner for new
modules if unstated):
- **Scaled in map** (Solar PV; `SitedModuleParams`): drawn area; selecting it
  shows vertex handles; dragging a vertex reshapes it and the result snaps by
  the drawing rules (inside boundary, outside blocks and other areas); area is
  free to change.
- **Scaled in inputs** (Ice storage; `BlockModuleParams`): a rectangular block
  like the data center's — area from inputs (ice: tank kWh_th ÷
  `energy_density_kwh_sqft`, default 15), placed automatically beside the data
  center when enabled, drag/resize (area held)/rotate on the map and with
  inputs.
Rules (`core/site_layout.normalize_layout`, applied on every project change):
blocks — including the data center — cut back drawn areas they cover
(permanently); blocks overlapping other blocks or the boundary are red +
warning only. The map editor component gained a polygon (vertex) mode beside
its block mode; a JS separating-axis check gives live red for block overlaps
(Node-tested against shapely). Supersedes D-036's "warn when the block overlaps
a drawn area".

## D-042 — Map usability: compass snap, labels, click-select; ice defaults  (2026-10-05)
Status: accepted (owner)
Decision:
- Scaled-in-map modules get **"Snap edges to N/S/E/W"**: free edges (not along
  the boundary, a block or another area) rotate about their midpoint to the
  nearest 45° direction; corners rebuilt at the new edge-line intersections;
  then the normal snapping to free land.
- Every map object is **labelled** at its upper-left corner in its outline
  colour, 10 px. **Clicking** an object selects it (data center → Data center
  tab; module → Modules tab + that module), applied at the start of the next run.
- Ice storage defaults: size **65 TR per MW of IT load** (None = follow; log
  slider 10–200,000 TR), tank **24 h** (slider 6–72 h). Schema v3 migration.
- Fixes found with a real browser: the edited object is drawn in its own pane
  (other objects, redrawn each render, were covering it and catching the
  mouse); edge handles hidden on blocks under 36 px so they can be dragged.
  The owner's "ice reverts after a drag" could not be reproduced (drags kept
  position and inputs in Chromium); these two issues are the likely causes.

## D-043 — Utility tab: painted time-of-use tariff and monthly demand charge  (2026-10-05)
Status: accepted (owner)
Decision: New **Utility** tab between Data center and Modules. Rate categories
(name, $/kWh, $/kW; defaults Off peak 0.10/10, Shoulder 0.15/10, Peak 0.20/10;
add/edit/delete) are painted onto a 12 × 24 month × hour table (default all
off peak) with a custom component; swatch colours run viridis dark purple →
bright yellow by energy × 100 + demand. "Weekend energy prices": Follow
schedule / Off peak (= cheapest rate; weekends of reference year 2025).
Billing on **net grid load** (owner): energy cost = price × net (exports
credited at the energy price — net load, so any generating module counts);
potential demand cost = max(net, 0) × hourly demand charge; only each month's
highest potential is billed, in its hour. New columns, a fourth "Utility
cost" subplot and cost metrics. `Project.utility` is additive (no migration).

## D-044 — Utility subplot shows running totals  (2026-10-05)
Status: accepted (owner) — refines D-043
Decision: Three new columns — `cum_energy_cost_usd`, `cum_demand_cost_usd`,
`cum_utility_cost_usd` (running sums of the hourly energy cost, billed demand
charge and utility cost) — are the only traces in the Utility subplot, drawn as
lines. Hourly price and cost columns remain in the frame, unplotted.

## D-045 — Power generation module (transcritical CO2) and free-cooling hand-off  (2026-10-05)
Status: accepted (owner, 2026-10-05, incl. the three interpretations below)
Decision: New **scaled-in-inputs** module (block area = rated MWe × sqft/MWe —
category implied by the power-density input). η = %Carnot × (1 − T_cold/T_hot),
T_hot = data center hot water (`t_return_c`), T_cold = heat-rejection ambient
+ the chillers' condenser approach. The generator is rated at the max
cold-side temperature: heat input is capped at Q_design = rated / η_design,
and output at rated, so colder hours make rated power from less heat and
warmer hours make less than rated from Q_design. It takes heat only from free
cooling (never above the free-cooling cutoff). Mirroring D-037, the data
center model now provides `cooling_free_demand_kwth`. `cooling_free_kwth`
(plotted) comes from the module, or from the `NoHeatToPower` placeholder.
New traces: "Heat rejected from power generation" (thermal stack 5) and
`power_gen_kw` (negative, electrical). Both use SERIES_6 brown `#8f4a1e`, chosen
by an OKLab CVD check against the adjacent colors because the bundled
validator was unavailable. `CoolingElectric` charges fan power (`cop_free`) on
the cycle's heat rejection as well as free cooling (`fan_heat_columns`).
Interpretations confirmed by the owner: Q_design cap above the design cold
side; the cold-side slider's upper limit is the ambient cutoff value; no
hot-side pinch.

## D-046 — Hot water storage module  (2026-10-05)
Status: accepted (owner)
Decision: The owner's two tank / thermocline physics, reviewed and fixed (see
models/hot-water-storage.md). Mass is tracked; the cold tank starts full at
the supply temperature. Inputs: storage hours (4–72, default 12),
Direct/Indirect (pinch 0 / 2 K), Two tank/Thermocline (red
perfect-stratification warning), tank height (12 m).
- **Tank volume** is computed once per run in `HotWaterStorageParams.resolved`
  from IT peak kW, hours and ΔT, not fed into the hourly loop: the tank is a
  design quantity, and the map block needs it before any run.
- **Scaled in inputs:** the block comes from cylinder diameter(s) + 20 ft
  buffer, square for a thermocline and 2:1 for two tanks. New
  `BlockModuleParams.default_dims_m`. Switching the tank type resets the
  block's shape.
- **Step 1 control (owner): charge only.** Q_req = mechanical demand at the
  return temperature. The mechanical demand is now a chain: hot water storage
  → `cooling_mech_after_hws_kwth` → ice storage or `NoCoolingStorage`
  (`demand_column` field) → `cooling_chiller_kwth`.
- `ModuleContext` gains `t_supply_c` / `t_return_c`.
- New thermal trace "Hot water storage (charging)", SERIES_8 cyan `#2bb3c0`
  (OKLab CVD check against its neighbors).
- **Addendum (owner, 2026-10-05):** a new output `hws_t_sys_c` gives the
  facility-side water temperature from the storage heat exchanger: T_cold +
  pinch when charging, T_hot − pinch when discharging, T_in when no heat
  moves. Downstream processes read this one column whether the system is
  direct or indirect.
- **Addendum (owner, 2026-10-05):** the tank is sized on the full heat load,
  IT × (1 + `it_parasitic_frac`), not IT alone. The fraction comes from the
  project's assumptions through `ModuleContext.it_parasitic_frac`.

## D-047 — Floating coolant (supply) temperature  (2026-10-05)
Status: accepted (owner)
Decision: The cold supply slider on the data center type becomes two-sided:
minimum (new `t_supply_min_c`, default 5 °C) and setpoint (`t_supply_c`, 40).
New subsystem `CoolantTemperature` (weather only) provides `t_ambient_rej_c`
and `t_coolant_c`: in free cooling, clamp(ambient + approach, min, setpoint);
otherwise the setpoint. Owner confirmed it is the cold supply that floats; the
warm return (the waste-heat temperature) stays constant.
- Modules that reject into the cooling loop use `t_coolant_c`: power
  generation's cold side (was ambient + condenser approach) and the brine
  condenser.
- Chillers and the ice maker reject to the air and keep ambient (owner chose
  to keep ice on ambient).
- Type names and file stems now include the minimum; old saved types load with
  min = 5.

## D-048 — Brine separation module  (2026-10-05)
Status: accepted (owner)
Decision: The owner's single-stage evaporator step, reviewed and fixed (see
models/brine-separation.md).
- **Physics fixes (owner-approved):** cubic water-activity fit; tank sized by
  a salt balance (m_dis = W·c_high/(c_high − c_low), V = m_dis/ρ(c_low), W from
  hours of IT × 1.1 heat); stop at c_high.
- **Front of the stack:** it provides `heat_offtake_kwth`, taking the whole
  data center heat whenever the temperature stack works. The condenser uses
  the floating coolant (D-047).
- **Scaled in inputs:** a square block of the 12 m tank's diameter + 20 ft
  each side.
- New thermal band "Brine separation" (bottom, plum `#b04a8a`); condenser
  fans at `cop_free`.
- The file was renamed from `brine_separaiton.py`.

## D-049 — Ice storage: two tanks, mass-flow interface  (2026-10-06)
Status: accepted (owner)
Decision: The owner reworked `ice_step` so other modules can use ice and
produce water.
- **Two tanks** of the same size (kWh_th of ice): ice tank and water tank,
  tracked independently as `IceTankState(soc_ice, soc_water)`, passed in as
  `start` / used as `s` like the other stateful modules.
- **Inputs and outputs are mass flows** (ice requested, water offered → ice
  supplied, water accepted). Inside, flows become duties with h_f = 330 kJ/kg
  (`ICE_LATENT_HEAT_KJ_KG`) and the accounting is in kW_th; the Q terms are
  returned as an FYI.
- **No longer serves the chillers' load:** D-037's ice → `cooling_chiller_kwth`
  hand-off is removed; `NoCoolingStorage` provides it. `IceStorage` takes
  optional `ice_request_column` / `water_in_column` (None = 0).
- **Step 1:** nothing requests ice, so the ice tank fills from the water tank
  (new input `water_soc_start_frac`, default 1.0) and idles. Ice consumption
  comes next (owner).
- Fixes to the draft: Q_req = ṁ·h_f (was ÷); water balance subtracts the water
  frozen; closed-form accepted water instead of the `while` loop.

## D-050 — Ice mixer module  (2026-10-06)
Status: accepted (owner)
Decision: The owner's ice mixer step, structured as a module (see
models/ice-mixer.md).
- **No footprint:** a third map category — neither scaled in map nor in
  inputs; `IceMixerParams` is a plain model (`enabled`, `fluid`,
  `recup_eta_pct`, `mix_eta_pct`).
- **Q_request = mechanical demand** (or what hot water storage left).
- **Two passes per hour:** pass 1 (flows unknown) returns calls; pass 2 (flows
  supplied) recalculates. A solver will converge the modules; **until then the
  adapter runs pass 1 only**: ice storage reads the mixer's ice call and melt
  water; the chillers still carry the whole demand; brine calls are reported
  only (wiring them into brine separation would be a pipeline cycle).
- Ice storage's `ice_instant_kwth` / `ice_discharge_kwth` leave the thermal
  stack (they're h_f(0) duties, not the cooling the DC sees).
- Property fits moved to defaults (`ICE_PROPS`, `BrineProperties.fp_coeffs`,
  `c_coeffs`, `h_solv_coeff`); `ice_hf` → `core/domain/ice.py`; file renamed
  `ice_melter.py` → `ice_mixer.py`.
- Fixes to the draft: params / fluid enum instead of strings; Q undefined on
  pass 1; water pass 2 capped at the request; supplied flows limit
  independently (None = unknown); guard for brine too dilute to mix.
- Owner answers (2026-10-06): h = (h_f + h_solv)·recup_eta (h_solv < 0 is heat
  generated); mixing efficiency capped at 90 % (100 % is impossibly ideal);
  no recup_eta for water (made, stored, melted at 0 °C); fit mismatch is fine
  for now; recup 70 % / mix 80 % defaults confirmed.

## D-051 — Receivers report what they accepted  (2026-10-07)
Status: accepted (owner)
Decision: Ahead of the module solver, every module that receives mass reports
what it actually took for the same input: the min that limits it is applied,
the step is recalculated with the limited input, and if no min bound the
input comes back exactly as given (same math either way). Survey:
- Ice storage: ice supplied and water accepted already did; unlimited flows
  now come back exactly (no kg/s → kW → kg/s round-off).
- Ice mixer: already recalculated on pass 2; now also takes what the tanks
  accepted of its melt water / diluted brine and melts only that much ice.
- **Brine separation:** now returns `m_brine_in_kg_s` / `m_brine_out_kg_s`;
  brine out ≤ tank contents; brine in = min(offered, most that fits the tank)
  by bisection. This **replaces D-048's rule** that an overflowing step shuts
  off all brine in and out.
- Hot water storage, power generation: heat, not mass; both already report
  the heat accepted.

## D-052 — Hourly module solver  (2026-10-07)
Status: accepted (owner)
Decision: Stateful modules are stepped together hour by hour by `HourlySolver`
(docs/solver.md), so flows exchanged within an hour settle before the hour is
committed.
- Every stateful module's layer 2 is a **solver node** (brine separation,
  hot water storage, ice mixer, ice storage) plus `MechanicalDemand` (the data
  center's split, same function as `DataCenterModel`). They exchange named
  **streams**; the old year-loop adapters are gone.
- Order each hour: brine separation → mechanical demand → hot water storage →
  ice mixer → ice storage; repeat until no stream changes (1e-9 abs + rel).
- **Sticky rule (owner):** not settled after 3 iterations → each *answer*
  (supplied / accepted) sticks at its value closest to zero over those 3;
  3 more iterations; then an error. Q2 resolved: only exchanged flows stick,
  everything derived is recalculated; two-way flows stick toward zero; every
  module always enforces its own limits, so no tank over- or under-fills.
- **Refinement (found in testing):** the cap is enforced by lowering the
  *request* the answering module sees, not by clipping its output afterwards
  — clipping left the module's state computed from a flow it never passed on.
  Requests are therefore not capped; they follow the capped answers.
- The ice mixer now provides `cooling_chiller_kwth` (= request − delivered) and
  `ice_mix_q_kwth` joins the thermal stack; its flow columns are renamed
  `ice_mix_ice_kg_s` / `ice_mix_brine_kg_s` (settled use, not calls).
- Brine separation exchanges brine with the mixer (new columns
  `brine_out_kg_s`, `brine_in_kg_s`); the mixer gets the start-of-hour
  concentration, fixed within the hour.
- The ice mixer requires ice storage (and brine separation on brine).
- Measured: every hour settles in ≤ 4 iterations; sticking changes no result;
  a year runs in 0.1–0.7 s.

## D-053 — State machine control  (2026-10-07)
Status: accepted (owner) — structure; module / data center IFs and THENs pending
Decision: A user-configurable state machine on a new **Control** tab
(docs/control.md).
- **Default state** (owner): no IFs; IT load 100 %, free cooling when
  possible / mechanical when needed, every module off. Its THENs are editable
  and are the baseline other states change.
- **IFs** (AND within a state): ambient, utility (value or day / month / year
  mean / median), time (hour, month, weekend — suggested), and per-module /
  data center IFs declared in each model file (`CONTROL_SPEC`; none yet).
- **THENs**, declared by each target: data center IT load %; every module run
  on/off (provisional until the owner's write-up).
- **Choosing** (proposed, owner to confirm): the first state in priority order
  that the current state may move to and whose IFs all hold; else Default. A
  state stays only while its IFs hold; Default is always reachable both ways;
  a new state may move anywhere. Module IFs read start-of-hour values; the
  state is fixed for the hour, then the hour is solved.
- Model: the frame's IT column becomes the plan (`it_load_plan_kw`); the
  `ITLoad` solver node writes the actual `it_load_kw`. Prices move to
  `UtilityPrice` (before the solver); `UtilityCost` bills. The solver always
  runs; nodes get `then`; stateless modules read `ctl_*` columns.
- **Consequence:** with the owner's Default, an enabled module does nothing
  until a state turns it on; a "Run all modules in Default" preset restores
  the earlier always-on behaviour.
- Diagram in Plotly (no new dependency): Default centred, states on a ring,
  click to edit.


## D-054 — Routed THENs: each state a complete description  (2026-10-08)
Status: accepted (owner, `IF and THENs.docx` + answers 2026-10-08); the
physics choices marked *proposed* await the owner's confirmation.
Decision: the owner's IFs / THENs replace the provisional run on/off, and the
THENs now *route* flows between modules (docs/control.md, docs/solver.md).
- **Complete description, no background rules** (owner): a module runs only
  if a state's THEN names it; anything unlisted is off; every module has an
  explicit "… is off". Default with nothing listed = IT 100 %, all modules
  off. New states start with a copy of Default's THENs. Supersedes D-053's
  "Default THENs are the baseline other states change", D-048's "brine
  separation first in the stack", D-045's "power generation only on
  free-cooling heat" and D-046's "hot water storage charges from the
  mechanical demand": all of these are now whatever the state says.
- **Links** (owner): a connection is one THEN entered at either end; THEN
  order decides who is served first (data center heat, ice mixer cooling,
  power generation's sources); melt water and diluted brine return
  automatically; brine separation's recovered water goes to ice storage or
  the drain (the earlier open offer); the ice mixer's fluid stays a module
  input; IT load THEN is % of the *planned* load.
- **IFs added** (owner): date (MM-DD), Always (on / off), daily quartiles and
  annual statistics (monthly dropped from the list), PV output (available),
  grid draw (previous hour), planned IT load % of full load, tank levels
  (0–100 %), brine concentration.
- *Proposed* physics:
  - heat rejected into the supply coolant (power generation's cold side,
    brine separation's condenser) joins the data center's cooling: free
    cooling when possible, chillers otherwise;
  - the ice mixer serves only the data center's *mechanical* load;
  - power generation takes several sources, each at its own Carnot
    efficiency, under one run %·design heat / run %·rated power cap, with
    the first listed cold side;
  - condenser steam is a heat source at T_sat − condenser pinch;
  - hot water storage delivers at hot tank − pinch and charges before it
    discharges.
- **Thermal stack** = where the data center's heat ends up: free cooling +
  chillers + ice mixer + converted to power + hot water storage (net) = IT ×
  (1 + parasitics). Brine separation becomes a line, since it passes its heat
  on. Power generation's rejection is no longer a band of its own.
- **Solver** (D-052 revised):
  - every link is want → answer → used; senders balance on what was used, and
    wants are never cut by answers, so flows can't ratchet down;
  - a sticky cap now applies to the answer as the other modules read it,
    instead of lowering the request;
  - stick after **6** iterations (was 3), keeping the owner's "lowest of the
    last 3", max **12**, tolerance **1e-6** (was 1e-9). User-built chains run
    up to ~6 links, and the brine ↔ condenser ↔ ice loop contracts
    geometrically: sticking at 3 capped flows that were still converging and
    made them oscillate.
  - Measured: ≤ 9 iterations per hour; 12 hours stick in the hardest test
    case, with annual totals within 2e-6 of an unlimited solve; a year with
    every module takes ~2 s.
- **Data center as a node:** `DataCenterNode` replaces `ITLoad`,
  `MechanicalDemand`, `DataCenterModel`, `CoolingElectric` and the
  `NoCoolingStorage` / `NoHeatOfftake` / `NoHeatToPower` hand-offs. Power
  generation, PV (`PvOutput`) and a `GridDraw` node join the solver.
  `SolarPV` now writes `pv_available_kw`. The `ctl_*` columns are gone.

## D-055 — Module output panel; text under the plots  (2026-10-08)
- **Owner:** move all text output (the metrics) under the plots; put a
  **module output** (plot + text) left of the results figure, selected with
  the same segmented control as the Modules tab. Per-module defaults from the
  owner: ice storage, ice mixer, brine separation, PV, hot water storage
  (plot only); see [workflow/02-results.md](workflow/02-results.md).
- **Linked time axis:** the owner wanted the module plot to zoom with the
  others, but only through Plotly. Two `st.plotly_chart`s can't share zoom
  (Streamlit returns selections, not zoom), so the module panel is drawn in
  the **same figure**: its own x-axis (`xaxis2`, left domain) with
  `matches: "x"`. Zoom, pan and the range slider move every plot.
  `uirevision` + a fixed chart key keep the zoom when the figure is rebuilt.
- **Two subplots, not two y-axes** (owner asked for a recommendation):
  different units (% vs °C or wt%) each get their own panel, so each keeps its
  own grid and scale; the panels line up with the main rows 1 and 2. The text
  is a Plotly table under the module plot (rows 3–4).
- Each module declares its outputs in its UI file (`OUTPUTS`, passed to its
  `ModuleUI`), so a new module adds its panel with no edit to the figure.
- New column `brine_soc_frac` (brine volume / tank volume) for the brine SOC.
- Ice storage "ice production weighted average of ice making while on" is
  read as Σq² / Σq over the hours the ice maker runs (each hour's rate weighted
  by the ice it made), in TR. To confirm.
- Not specified by the owner, proposed: power generation (power out + heat
  in; cycle efficiency; MWh/yr and hours running) and hot water storage text
  (heat stored / delivered).

## D-056 — Modules are added to the site; legends beside the plots  (2026-10-08)
- **Owner:** the Modules tab lists only the modules on the site (none to
  start), with an **Add module** button that picks one from a dropdown; its
  tab then appears, and so does its tab in the results' module output, so
  nobody is confused about what is or isn't on the site.
- Built: Add module popover (dropdown of the modules not yet added + a
  one-line description + "Add to the site", which opens its tab); "Remove …
  from the site" at the end of each module's panel replaces the old "Include
  …" toggles. Removing keeps the module's inputs, area and block (hidden) so
  adding it back restores them. `ModuleSettings.enabled_keys()` /
  `with_enabled()` drive the Modules tab, the module output selector and the
  Control tab's components.
- Solar PV (drawn area) got an `enabled` flag like the other modules; it runs
  once added *and* drawn. Project schema v4 migrates: on where an area was
  already drawn.
- **Legends (owner: "fix the legend titles"):** the main subplots' legends ran
  over their titles. Plotly wraps a horizontal legend only at the full plot
  width, so a legend over half the figure can't wrap at its subplot; the main
  legends are now a column right of each subplot (stacks listed top-down).
  Module panels keep title + legend in one row (the title is the legend's
  title).

## D-057 — Bottom plot views, control editor fixes, peak / off-peak diagnosis  (2026-10-08)
- **Owner:** the last results subplot becomes selectable — accumulated cost,
  energy price, demand charge or state — so more outputs fit without more
  subplots. Built as `BOTTOM_VIEWS` (plot groups `utility`, `energy_price`,
  `demand_charge`, `control`); the selector sits under the figure, right half.
  Price, demand rate and state are hourly steps; the state axis is labelled
  with the state names.
- **Owner's peak / off-peak setup did nothing.** Two causes:
  1. Its tariff has 4 peak hours a day, so the daily upper quartile is the
     off-peak price: "price ≥ upper quartile" held all 8,760 h, and the
     off-peak state (ice maker cleared to run) never ran. "> / ≤ upper
     quartile" gives the intended split (1,336 h peak). Not a code bug;
     documented in control.md, and the editor now shows each state's active
     hours.
  2. With the ice maker never running, the mixer could deliver nothing: its
     melt water has to go back to the ice maker's water tank, which started
     full. More generally ice + water start at 10 % + 100 % = 110 % of one
     tank, and that sum never changes (closed loop), so the last 10 % of ice
     can never be melted. **Open — asked the owner** (default water start
     90 %? or let melt water that doesn't fit drain?).
- Ice mixer: recuperation and mixing efficiency show only on brine (owner).
- Control editor: Edit on every IF / THEN (takes it out, fills the add row,
  Add puts it back in its place); the same IF / THEN twice is refused (the
  owner's state had a duplicate link); the new state's name is typed next to
  Add state; a click on the diagram scrolls the editor into view.
- Ice storage panel: ice tank blue, water tank orange (violet vs blue were too
  close, owner).
- Module output table starts `TABLE_GAP` below row 3's top: zoomed in, the
  date ticks get a second line (the year) that ran into the table's title.

## D-058 — Ice tank starts empty  (2026-10-09)
- Resolves the open point in D-057. The loop is closed, so ice + water stays at
  its starting sum; at 10 % ice + 100 % water the last 10 % of ice could never
  melt (no room for its melt water).
- **Owner:** the ice tank starts at 0 % (`soc_start_frac` default 0.1 → 0.0);
  the water tank stays at 100 %, so the two start as one full tank.
- Projects already saved keep their own starting values; the input is still a
  slider, so the user can set it.

## D-059 — Utility IFs can compare with a rate category  (2026-10-09)
- **Owner:** the utility IFs' comparison list (quartiles, mean, median, …)
  also offers the rate categories named on the Utility tab (default Off peak,
  Shoulder, Peak), taken from the project's tariff.
- Built: `Reference.RATE` plus `Condition.category` (the category's id;
  additive, so older files load). The IF compares the hour's energy price with
  the category's `energy_usd_kwh` (the demand charge with its
  `demand_usd_kw`), via `ControlVariable.rate_field`. The controller now gets
  the tariff (`controller(settings, it_peak_kw, tariff)`).
- Compared by price, not "which category this hour is in", because the owner
  asked for it next to the statistics and it then works with every operator
  (≥ Shoulder = shoulder or peak). A deleted category: the IF never holds,
  and the editor says so.

## D-060 — Taller inputs; zoom kept across runs; three rows with view buttons  (2026-10-09)
- **Owner:** more room for the inputs: input panel and map +25 % (560 →
  700 px, `MAP_HEIGHT_PX`; the inputs panel follows it).
- **Owner:** "the plots update their zoom every time the model runs; zoom
  state must persist over any change to the model." Cause: `st.plotly_chart`
  computes its element id from the figure, so a new figure is a new element
  and the chart is remounted; `uirevision` can't help a fresh chart. Fix: a
  keyed `st.components.v2` component (identity = key) that keeps one Plotly
  chart and calls `Plotly.react`; the browser stores the zoom and the view
  picks in sessionStorage and re-applies them on every redraw (so also after
  a remount or reload). plotly.js comes from the plotly package, copied to
  `static/` (git-ignored) and served by `server.enableStaticServing`; it
  matches plotly.py and works offline. Checked in headless Chromium
  (drag-zoom, add a state → model run, reload).
- **Owner:** each plot on the right gets selection buttons: **Ambient**
  (Temperatures / Sun — GHI only for now), **Power** (Thermal / Electrical),
  **Operation** (Utility cost / Energy price / Demand charge / Control
  state — what D-057's bottom selector had; that selector is gone). Four
  subplots → three rows. Built with Plotly `updatemenus` (in-figure buttons,
  no rerun); every view has its own y-axis on its row (overlaid, own ticks).
  GHI moved to a new `sun` plot group; the unused `secondary_axis` column
  option was removed.
- The figure reserves a fixed right margin for the widest legend, so switching
  views never resizes it.

## D-061 — Greenhouse module (heating load)  (2026-10-09)
- **Owner:** a greenhouse, scaled in map like PV (the drawn area is its floor).
  Only the heating requirement, steady state (no thermal mass): a lumped
  resistance per m² of glass — outside film (wind), 4 mm glass at 0.9 W/m·K,
  inside film (2 m/s) — between the outside air and the setpoint, plus τ·GHI
  through the glass. Net heat needed is asked of the data center's coolant;
  surplus is vented. Inputs: transmissivity 90 % (80–100), wind 2 m/s (1–20,
  only where the weather has none; NSRDB wind otherwise), setpoint 20 °C
  (15–40).
- Built: films from the flat-plate forced-convection correlation (laminar /
  mixed, Incropera 7.30 / 7.38) over L = √floor area, air at 300 K; glass area
  = 1.3 × floor; each film at least 2 W/m²K (still air). The last three are
  proposals (open-questions Q2).
- Two layer-2 parts like PV: `GreenhouseLoad` (vectorized, before the solver,
  so the demand is an IF) and the `GreenhouseHeating` solver node, a heat taker
  of the data center (link THEN "Takes heat from data center", served in THEN
  order; `HEAT_TAKERS` += greenhouse). The return water must be warmer than
  the setpoint. Uncovered demand → `greenhouse_unmet_kwth`. "Run everything"
  heats the greenhouse first.
- Fixed on the way: an IF on a column whose module isn't on the site (e.g. PV
  output, greenhouse demand) stopped the model ("unsatisfiable column
  requirements"); the controller now gets only the columns the run will have,
  so such an IF never holds (as control.md says).
- Year at a Toledo, Ohio test site, 1 acre, 20 °C: 62.7 kBtu/sqft/yr. The EIA
  comparison test waits for the owner's reference value (no EIA greenhouse
  figure found).

## D-062 — Greenhouse U-value is an input  (2026-10-09)
- **Owner:** use a known U from an extension guide instead of computing it:
  a "Covering U-value" slider, 5–10 W/m²K, default 7.5, with a link right
  under it to the guide so users can look the term up. The convection films,
  glass conduction, wind speed input, plate length and still-air floor are
  gone. Cover / floor area 1.3 confirmed. (Resolves open-questions Q2.)
- Link: Texas A&M AgriLife, "Greenhouse heating requirements", Table 1
  (Btu/h·ft²·°F): single glass 1.13 (6.4 W/m²K), double glass 0.65 (3.7),
  single PE 1.15 (6.5), double PE 0.70 (4.0). Correction: D-061 quoted
  "1.2–1.4" from a search summary; the guide's single-glass value is 1.13.
- Spot check (owner): Purdue CEA's worked example (Q = U·A·ΔT, U = 0.55
  Btu/h·ft²·°F, 66.6 °F in / 30 °F out → 135,878 and 170,860 Btu/h) is
  reproduced in `test_spot_check_purdue`; its surface areas are only in a
  figure image, so the test uses the areas its results imply (a formula and
  units check). The EIA comparison test is dropped (owner).
- `wind_m_s` removed from `GreenhouseParams`: project schema v5 drops it from
  older files; the U column (`greenhouse_u_w_m2k`) is gone (it is the input).

## D-063 — Control tab layout, power generation rating in % of IT, brine supply warning  (2026-10-09)
- **Owner requests:** brine separation's water produced in **gal/yr**
  (`GAL_PER_KG_WATER` 0.264172, 1 kg ≈ 1 L); the state diagram is a **polygon**
  (Default and the states are its corners, Default at the top) so arrows
  don't run through nodes or along each other; the **state picker, new name
  and Add state sit above the diagram, pinned** at the top of the tab while
  the editor scrolls; power generation's rating is a **slider in % of the IT
  load, 0.5–150 %** (was 10 kWe–10 MWe, log), default 2 %, with the MWe in
  grey under it. Schema v6 migrates saved kWe ratings to %.
- **A test project ("nothing is happening"):** the Peak state linked ice
  storage → ice mixer → power generation (cold side) and hot water storage →
  power generation (heat), but the ice mixer runs on brine and no THEN sent it
  brine ("Brine separation: Sends brine flow to Ice mixer"). A brine mixer
  without brine stays off and publishes no temperature, so power generation
  has no cold side, asks for no heat, and hot water storage never discharges;
  brine separation then sits at its high concentration. With that one THEN
  added: 4,548 MWh/yr generated, the hot water tank and ice cycle daily. The
  editor now warns about a brine mixer that gets no brine.
- Fixed on the way: a slider format `"%g wt%"` (brine concentration) broke the
  page in the browser (sprintf needs `%%`); a test now checks every UI format.

## D-064 — Greenhouse takes heat from hot water storage  (2026-10-09)
- **Owner:** the greenhouse should be able to take heat from hot water storage
  based on the hot water / setpoint temperature difference, the cooled water
  going back to the cold tank. Owner proposed a converter in the greenhouse;
  the existing storage discharge already is that heat exchanger (it cools hot
  water against a given water temperature and mixes it into the cold tank),
  so it was generalised instead of adding mass-flow streams.
- Hot water storage "Sends hot water to" offers power generation and the
  greenhouse; receivers are served in THEN order, each cooling the hot water
  against its own temperature (power generation: supply water; greenhouse:
  setpoint + coil approach). The greenhouse "Takes heat from" offers the data
  center and hot water storage, asked in THEN order.
- **Coil approach 10 K** (owner: as the other air coils), applied to every
  greenhouse source, so the data center's return water must also be above
  setpoint + 10 K (was: above the setpoint).
- **Cold tank floats** with what comes back (owner), e.g. 32 °C from a 20 °C
  greenhouse against a 35 °C supply.
- New column `greenhouse_heat_hws_kwth`; `greenhouse_heat_kwth` is now heat
  from all sources (still the thermal-stack band, balanced by storage's net
  band when it comes from storage).

## D-065 — Greenhouse heat from a module: hatched band on top of the stack  (2026-10-09)
- **Owner:** greenhouse heat that comes from anything but the data center
  should show differently — its own trace "Greenhouse from <module>" on top of
  all the others, so the greenhouse's heat from the data center stays within
  the data center's total and the extra heat sits above it, with no negative
  heat in the plot.
- `greenhouse_heat_kwth` is again the data center's share only (stack 7);
  `greenhouse_heat_hws_kwth` ("Greenhouse from hot water storage") is a
  hatched greenhouse-green band at stack order 100 (`STACK_TOP`), drawn last.
  `ColumnSpec.hatched` marks such bands; the next "greenhouse from …" source
  gets one the same way.
- Storage's stack band is a new column `hws_stack_kwth` = charge − discharge
  to power generation (what it gives the greenhouse is the hatched band);
  `hws_net_kwth` stays the true net, no longer plotted. Below the hatched
  bands the stack still sums to the data center's heat.
- Left as is: storage discharging to **power generation** still drives its
  band below zero (that power and rejected heat are inside the stack).
- Fixed 2026-10-10 (found in a headless-browser check): the pinned picker
  didn't stick — Streamlit wraps the keyed container in a wrapper only as tall
  as the picker, and sizes the tab's content block to the panel. Sticky now
  goes on the wrapper and the content block is as tall as its content; a
  diagram click scrolls only the inputs panel (not the page, which hid the
  picker under Streamlit's top bar), so the diagram sits just below the picker.

## D-066 — State diagram clicks through its own component  (2026-10-10)
- **Owner:** sometimes a click on a state (hover label showing) gives "a tiny
  flicker but the state doesn't change", and it takes several clicks; also,
  after picking a state, a click in the first IF sometimes jumped back to
  Default.
- **Cause (confirmed for the lost clicks):** the diagram was `st.plotly_chart`
  with `on_select`. Streamlit wires Plotly's double-click and deselect events
  to "clear the selection", so a double-click (a quick second click, a
  trackpad double tap) or a click Plotly doesn't tie to a point reruns with an
  empty selection: flicker, no change. Reproduced in a headless browser on a
  standalone copy of the old diagram; single clicks always worked, which is
  why it was intermittent. Each click also needed a remount (new key) and a
  second rerun with the picker set from code after it was drawn.
- **Fix:** the diagram is drawn by a keyed v2 component (`state_diagram`, same
  plotly.js as the results figure) whose `plotly_click` sends the state id as
  a trigger value; its callback sets the picker before the page is drawn, so
  one rerun, no selection state, nothing to clear. Checked in the browser:
  single and double clicks on every node select it; the picker stays pinned;
  IF edits keep the state.
- The jump back to Default was not reproduced; it went through the same
  selection / remount / second-rerun path that is now gone. Owner to report
  if it recurs.

## D-067 — Chiller area is the lumped cooling plant  (2026-10-10)
- **Owner:** the spec's chiller area (0.4 sqft/kW IT dry, 0.2 evaporative)
  covers the chillers and their heat rejection (dry coolers / cooling towers)
  as one lumped area; the values stay, on IT load only (not IT + parasitics).
  The area breakdown row is named "Chillers" (was "Chillers / heat rejection").

## D-068 — The state being edited is kept outside the picker widget  (2026-10-12)
- **Owner:** intermittently, after Add state, opening the first IF's dropdown
  jumps back to Default (no IFs); picking the new state again works. No
  pattern yet; maybe other apps / windows.
- Not reproduced in a headless browser (Add state at every click speed,
  clicks during the model rerun, the connection dropped for up to 20 s). Ruled
  out: the project being reloaded (only open / restore / a dropped session do
  that, and a dropped session shows a "session was reset" notice); the map
  sending reruns (only on the Location tab).
- The one remaining path: the picker was a widget whose value code set (Add /
  Delete state, diagram click). If the browser misses that update, its next
  message carries the old value, Default. Now the state being edited is a
  plain session key (`w_ctl_current`), and the picker's key carries a
  generation that code bumps when it changes the selection, so the picker is
  a new widget the browser has no old value for. If the jump still happens, it
  isn't this path: note whether a "session was reset" notice appears.

## D-069 — Public database and one-link deployment  (2026-10-13)
- **Owner:** before publishing, save data center types and projects in a
  database; nothing private, all projects visible to all (to keep work
  private, fork the repo); share the app with a single link.
- **Database:** SQLAlchemy over `DATABASE_URL` (env / secrets) — hosted
  Postgres when deployed (Neon free tier recommended; any Postgres works),
  SQLite `data/dcs.sqlite` locally and in tests. Documents stay JSON text in
  three tables (`projects`, `project_snapshots`, `datacenter_types`), so the
  project schema can change without database migrations (`from_json` still
  migrates). Code: `services/store.py` (it is network I/O, so `services/`).
  Dependencies added: `sqlalchemy`, `psycopg[binary]` (Postgres driver).
- Replaces the files under `data/projects/` and `data/datacenter_types/`
  (`core/persistence/versions.py`, `type_library.py` removed). The repo's type
  files seed a database that lacks them; `python -m services.import_files`
  copies old project files in (done for the local SQLite database).
- **Session loss (D-040) changed:** the workspace URL carries the project
  (`?project=<stem>`); a dropped session reopens *that* project. The old
  fallback, "reopen the most recent autosave", would open someone else's
  project on a shared app, so it is gone; with no project in the URL it goes
  to Start. The URL is also the project's share link (project bar → Link).
- **Two sessions on one project:** last write wins, but the state being
  replaced is always snapshotted (even inside the 5 min throttle) and the
  session that replaced it gets a notice. No locking.
- Times are stored in UTC and shown in the viewer's browser time zone.
- **Deployment:** Streamlit Community Cloud from `main`; steps in
  [deployment.md](deployment.md). `static/.gitkeep` keeps the static folder
  (plotly.js is copied there at run time).

## D-070 — MIT licence  (2026-10-13)
- **Owner:** the repo will be public so anyone can fork it, including to keep
  their version private ("take it closed"). That needs a permissive licence:
  **MIT** (`LICENSE`, `pyproject.toml` `license = "MIT"`). Copyright holder:
  Rebound Technologies.
- The repo moved to `github.com/murenrb/QuTE` (owner's account
  tied to the Rebound email; D-006's old address redirects).
