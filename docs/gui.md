# GUI — Visual Style & Layout

Source: `docs/App asthetics guide.docx` + `docs/Layout example.png` (owner,
2026-09-30). **This file is canonical for style and layout** and supersedes any
earlier layout description (D-024, D-025). Workflow detail per tab:
[workflow/01-setup-tabs.md](workflow/01-setup-tabs.md); charts and metrics:
[workflow/02-results.md](workflow/02-results.md).

## Visual style

### Color
- **Greyscale** for everything structural: page and panel backgrounds, buttons,
  tabs, inputs, borders, chart axes/gridlines/legends, and all non-facility map
  data (basemap, property boundary, angle/length labels, site marker).
- **Color only for real data and the facility overlay:** chart traces (colors
  from the column registry, `core/timeseries/columns.py`) and the facility
  block on the map (blue in bounds, red when outside the boundary).
- No accent color on buttons, sliders, toggles or selected tabs — Streamlit's
  `primaryColor` is set to a dark grey.

### Text
- One sans-serif family everywhere, as Arial-like as available:
  `Arial, "Helvetica Neue", Helvetica, "Liberation Sans", sans-serif`.
  Charts and map labels use the same stack.
- Readable but compact. **Body/default: 12 pt (16 px), normal or light weight.**
  **Headers: at most 14 pt (≈18.7 px), bold.** No larger titles — the page
  title is 14 pt too. Chart titles/axis labels ≤ 12 pt; tick labels may be smaller.

### Corners
- **Square (90°) corners everywhere** — panels, buttons, inputs, tabs, tooltips,
  chart backgrounds, map container. No rounded corners (`theme.baseRadius = "none"`
  plus CSS for anything the theme misses).

### Other
- Dense engineering-tool feel: thin 1 px grey borders around panels, minimal
  padding, no decorative icons or emoji in labels.
- Every number carries units; sliders show value + units.
- `st.set_page_config(layout="wide")`.

## Layout — one workspace page

The whole workflow happens on **one page** (D-025). Only the Start screen
(open / new project) is separate.

```
┌ Location │ Property │ Data center │ Utility │ Modules │ Control ┐ ┌────────────┐
│                                             │   │                          │
│  INPUTS for the selected tab                │   │           MAP            │
│  (scrolls inside the panel if long)         │   │  (always visible,        │
│                                             │   │   top-right)             │
└─────────────────────────────────────────────┘   └──────────────────────────┘
──────────────────────────────────────────────────────────────────────────────── (line)
 Solar PV │ Ice storage │ … (module output)
┌─────────────────────────────────────────────────────────────────────────────┐
│ Module plot (1 panel, or 2      │ Ambient          [Temperatures][Sun]      │
│ panels on rows 1 and 2)         ├───────────────────────────────────────────┤
│                                 │ Power            [Thermal][Electrical]    │
├─────────────────────────────────┼───────────────────────────────────────────┤
│ Module text (table)             │ Operation [Utility cost][Energy price]    │
│                                 │           [Demand charge][Control state]  │
│                                 │                  [range slider]           │
└─────────────────────────────────────────────────────────────────────────────┘
   OUTPUT METRICS (tiles, full width, under all the plots)
```

- **Two layers, each two equal columns** (D-032):
  - **Input layer:** tabbed inputs panel (left) | map (right).
  - A full-width **grey line** marks the break.
  - **Output layer**, starting below the map (D-055): the **module output**
    selector (left, the same segmented control as the Modules tab), then
    **one figure** holding the module output (left: plot + text table) and
    the **three stacked results rows** (right), all on one time axis
    (D-029). The **output metrics** (text) sit under all the plots, full
    width.
- **Top row is the same height on both sides** (inputs panel ≈ map height,
  `MAP_HEIGHT_PX` = 700 px, raised 25 % from 560 for more input room, owner,
  D-060); the inputs panel scrolls internally.
- **Clear of the header:** the page content starts below Streamlit's top bar
  (navigation) with at least three text-lines (≥ 48 px) of extra space, so the
  tabs are never covered (`PAGE_TOP_PADDING` in `app/components/style.py`).
- **The map is the central element:** it stays in place for every tab and
  reflects the current inputs (location, boundary, facility block).
- **Tabs** along the top of the inputs panel, in workflow order:
  1. **Location** — address lookup / lat-lon.
  2. **Property** — draw and review the property boundary.
  3. **Data center** — type (select / create), IT load, area breakdown,
     facility placement.
  4. **Utility** — time-of-use tariff: rate categories and the painted
     month × hour schedule; weekend pricing (D-043).
  5. **Modules** — co-located systems (placeholder until the first module
     exists: "Co-located modules — coming soon").
  6. **Control** — the state machine: state diagram (click a state) and the
     selected state's IFs / THENs below it ([control.md](control.md), D-053).
     The map is display only on this tab.
  The user can move between tabs freely; nothing is lost.
- **Results fill in live** (D-025): once a location and a data center exist,
  weather is fetched (cached) and the model re-runs on every input change.
  Before that, the figure shows a short grey placeholder ("Set a location
  and a data center to see results"); the metrics appear with the results.
- **Project bar** (one row above the input layer, D-040, D-069): project name ·
  autosave status ("Autosaved 09:53:12", in the viewer's time zone) · **Save
  version** (popover: version name + Save — a named copy autosave never
  touches) · **Versions** (popover: saved versions and the latest automatic
  snapshots, each with Restore; the current state is snapshotted first) ·
  **Link** (popover: this project's URL, `…/workspace?project=<id>`) ·
  **Download** (project JSON to your computer). Code:
  `app/components/project_bar.py`.
- **Sidebar:** collapsed by default; only the read-only "Model assumptions"
  expander.

## Map
- **Outline:** 1 px black line around the map on every tab (including the
  footprint editor), drawn over the tiles (`MAP_OUTLINE` in
  `app/components/style.py`).
- **Basemap:** Esri World Gray Canvas (greyscale, no API key; CartoDB now needs
  one). Native max zoom 16, upscaled to 20.
- **The active tab sets the map's tools (D-027).** Only the tools for the
  current step exist on the map; everything else is locked:

  | Tab | Pan / zoom | Tools on the map | Everything else |
  |---|---|---|---|
  | **Location** | ✅ free (drag, scroll, +/−) | none — frame the site | boundary + block shown, not editable |
  | **Property** | ❌ locked to the saved view | **polygon tool only, armed by default** | block shown, not editable |
  | **Data center** | ❌ locked to the saved view | **facility block only**: drag to move, edge handles to resize (area fixed), knob to rotate | boundary shown, not editable |
  | **Utility** | ❌ locked to the saved view | none (display; click an object to select it) | all shown, not editable |
  | **Modules** | ❌ locked to the saved view | **polygon tool for the selected module's area**, armed while that module has no area (needs a property boundary) | boundary, block and other areas shown, not editable |

- **Saved view:** the view framed on the Location tab — its exact center and
  zoom (plus bounds) — is stored on the site, and every other tab (including the
  footprint editor) reopens at that same center and zoom, so the site looks the
  same size on every tab (D-031). The whole property must be visible on the
  Location tab. Locked means
  Leaflet dragging, scroll/double-click/box/touch/keyboard zoom and the +/−
  control are all off.
- **Boundary drawing:** Leaflet.Draw polygon via `streamlit-folium`; straight
  segments only. Labels: interior angle (°) at each vertex, side length (ft) at
  each midpoint; boundary area in acres and sqft in the Property tab (D-020).
  Boundary and labels in greys.
- **Module map categories (D-041)** — every module is one of:
  - **Scaled in map** (Solar PV): area drawn with the polygon tool; once drawn,
    selecting the module shows a **handle at every corner** — drag one to
    reshape; on release the new outline snaps by the same rules as a new
    drawing (inside the boundary, outside every block and other areas). The
    area grows/shrinks freely (not area-locked).
  - **Scaled in inputs** (Ice storage, Power generation, Hot water storage,
    Brine separation): a **block** like the data center —
    area set by the module's inputs, appears automatically beside the data
    center when enabled; drag to move, edge handles reshape with the area
    held, ◆ knob rotates; width/length/rotation inputs + "Place beside data
    center" + "Align to property edge" in its panel.
  - **"Snap edges to N/S/E/W"** (scaled-in-map modules, Modules tab): every
    *free* edge — not lying along the property line, a block or another area
    (both ends and midpoint within 0.5 m) — turns to the nearest of N, S, E,
    W, NE, NW, SE, SW about its midpoint; corners are rebuilt where the edge
    lines meet, then the area snaps to the free land as usual (D-042).
  - A block (data center or module) placed over a drawn area **cuts that area
    back** automatically (permanently — moving the block away doesn't regrow
    it). A block overlapping **another block** or leaving the boundary turns
    **red** (live while dragging, and on every tab) with a warning — never
    blocked.
- **Object labels (D-042):** every object on the map — Property, Data center,
  each module area/block — has a text label at its **upper-left corner** in the
  same colour as its outline (red when flagged), **10 px**, on every tab and in
  the map editor.
- **Click to select (D-042):** clicking an object on the map opens its place in
  the inputs panel — the data center block → Data center tab; a module area or
  block → Modules tab with that module selected.
- **Small blocks:** when a block is under 36 px on screen its edge handles are
  hidden, so grabbing it always moves it (the ◆ knob stays). The edited object
  is drawn in its own map pane above the others so they can't catch its clicks.
- **Module areas (D-036):** modules that occupy land (Solar PV now) are drawn
  on the Modules tab with the same straight-line polygon tool. The drawing may
  cross the property line or overlap the block / other areas; on closing it is
  **snapped** to the free land (clipped to the boundary, minus the data center
  block and other modules' areas), possibly into several pieces or with holes.
  Areas are shown on every tab (and in the footprint editor) in the module's
  color; later edits that create overlaps produce warnings, not changes.
- **Facility block editor (built, D-030):** on the Data center tab, once a block
  exists, a small custom Streamlit component (`app/components/footprint_editor/`:
  Leaflet 1.9.4 vendored + plain JS, no build step) replaces the folium map, with
  the same tiles, locked view and grey boundary:
  - drag the **body** → move;
  - drag an **edge handle** (square, one per side) → that side changes, the
    other adjusts so the **area stays fixed**, opposite side stays put; limited
    to the 1:10 aspect range;
  - drag the **◆ knob** above the block → rotate freely; **Shift snaps to 15°**;
  - while dragging: live "W × L ft · θ°" readout and **red fill** as soon as any
    part leaves the boundary (checked in the browser, incl. concave parcels);
  - on release the footprint goes to Python, which re-validates it
    (`edited_footprint`: sized area enforced, width clamped, rotation
    normalized) and re-checks the boundary; inputs and results then update.
  The tab's Width / Length / Rotation inputs stay as precise entry, synced both
  ways, plus "Center in boundary" and "Align to property edge" (rotate to the
  nearest boundary side). Blue fill in bounds, red outside — warning only.
- Browser geometry (`frontend/geometry.js`) mirrors `core/geometry/footprint.py`
  using WGS84 local radii; a Node-run test keeps them within 1 cm.
- Geometry math in a local metric frame (azimuthal equidistant, D-018).
- Code: `app/components/map_view.py`, `app/components/footprint_editor/`.

## Charts
- Plotly, one builder per chart in `app/components/plots.py`, traces taken from
  the column registry by `plot_group` — no hard-coded trace lists.
- **One figure, three stacked rows** (top → bottom), each showing one view
  picked with **buttons at its top right** (Plotly `updatemenus`, switched in
  the browser, D-060): **Ambient** — Temperatures (TDB/TWB/TDP lines) or Sun
  (GHI); **Power** — Thermal (stacked area) or Electrical (stacked area +
  black net-grid line); **Operation** — Utility cost (running totals as
  lines — D-043, D-044), Energy price, Demand charge or Control state (hourly
  steps). The figure keeps a fixed right margin for the widest legend, so
  switching a view never resizes it. Content:
  [workflow/02-results.md](workflow/02-results.md). Builder:
  `build_results_figure` in `app/components/plots.py`.
- **Aligned time axis (essential):** the rows share one x-axis, so zoom,
  pan and hover move them all together; a range slider under the bottom
  row selects the window. Unified hover shows every trace at that hour
  (D-029). The module output plot is in the **same figure** on its own
  x-axis with `matches: "x"`, so zooming, panning or the range slider on any
  plot moves all of them (D-055). (Two separate `st.plotly_chart`s can't be
  linked: Streamlit doesn't pass zoom events back.)
- **Zoom and views persist across every change (owner, D-060).** The figure
  is drawn by a keyed v2 component (`app/components/results_chart.py`) that
  stays mounted and updates the chart in place (`Plotly.react`); the browser
  remembers the zoom and each row's view (sessionStorage) and re-applies them
  on every redraw. `st.plotly_chart` couldn't: its element identity includes
  the figure, so each model run mounted a new chart. plotly.js is the copy
  bundled with plotly.py, served from `static/` (`server.enableStaticServing`).
- Each row has its own title (top left). The rows' legends are a
  column **to the right** of each row, top-aligned, listed top-down like
  the stack (D-056): a row legend of up to six entries is wider than the
  subplot, and Plotly only wraps legends at the full plot width, so it ran
  over the titles. Module panels (≤ 2 entries) put the legend in the same row
  as the title (the title is the legend's own title).
- **Module output:** two quantities with different units go in **two stacked
  panels**, not on two y-axes (D-055): each keeps its own grid and scale, and
  the panels line up with the main rows 1 and 2.
- **Units:** kW columns are plotted in MW (kW_th → MW_th); axis titles say so.
- **Colors:** first four slots of the dataviz reference palette
  (`#2a78d6` blue, `#eb6834` orange, `#1baf7a` aqua, `#eda100` yellow), fixed
  per column in the registry, validated for colorblind separation; net grid
  line black. Two slots are low-contrast on white, so every chart keeps a legend.
- Styling: white background, grey axes/gridlines, Arial-like font at 12 pt,
  square legend/tooltip boxes, no chart-level color other than data traces.
- 8760 points × traces is fine; switch to `scattergl` if performance lags.

## Output metrics
- Compact grey-bordered tiles under the inputs panel (left column); each value
  with units. The left column below the inputs is the home for future outputs. List: [workflow/02-results.md](workflow/02-results.md#output-metrics).

## Tariff painter (Utility tab, D-043)
- Custom component (`app/components/tariff_editor/`, plain JS): rate rows
  (swatch · name · $/kWh · $/kW · ×), "+ Add rate", and the 12 × 24 month ×
  hour table. Click a swatch (outlined when active) to pick the brush; click
  or drag over cells, or click a month/hour heading, to paint. Each action is
  one event; Python applies it and re-renders.
- Swatch colours: viridis, dark purple (cheapest) → bright yellow (dearest)
  by energy × 100 + demand. Swatches sit half a swatch width (17 px) in from
  the left so the selection outline is never clipped.
- "Weekend energy prices" radio below: Follow schedule / Off peak.

## Forms
- DC type form: `st.form`, so sliders don't trigger a rerun per move.
- No name field — the type name is generated from its inputs (D-023). Validate
  (supply < return) with inline messages. Saving a design identical to a saved
  one shows "the saved version will be used" and selects it.
- Inputs ≠ assumptions: everyday inputs live in the tabs; engineering
  assumptions stay in the sidebar expander (read-only for now).

## Implementation notes
- Theme in `.streamlit/config.toml` does most of it: `base = "light"`,
  greyscale `primaryColor`, `baseRadius = "none"`, `font` = the sans-serif
  stack, `baseFontSize = 16` (px = 12 pt), `baseFontWeight = 400`,
  `headingFontSizes` capped at `"18.67px"` (14 pt), `headingFontWeights = 700`.
  Anything the theme can't reach (panel borders, tab styling, Leaflet/Plotly
  corners) goes in one injected style block in `app/components/style.py`.
- Style constants (greys, font stack, sizes) live in `app/components/style.py`
  — UI constants, not engineering defaults.

## Future
Export (CSV of the DataFrame, PNG of charts, PDF report); multi-facility sites;
scenario compare; optional dark theme (must keep the greyscale rule).
