# Project Overview

## Purpose

A Python/Streamlit tool for **systems engineering of data center installations
co-located with other technologies** — greenhouses, wastewater treatment,
district heating, food processing, etc. The data center is a large, steady heat
source; the value of the tool is quantifying how that heat (and power) can be
integrated with neighbors, hour by hour, over a typical year.

## High-level workflow

One **workspace page** (after a Start screen to open or create a project):
tabbed inputs top-left, the map top-right (always visible); below them one
figure with the selected module's output (left) and three results rows
(Ambient, Power, Operation; each with view buttons) on the right, all on a
shared time axis; output metrics under the plots.
Layout and style: [gui.md](gui.md).

1. **Location → Property → Data center → Utility → Modules tabs** — pick a location,
   draw the available land, choose or create a data center type, enter IT
   load, place and shape the facility footprint on the map, (future) add
   co-located modules. → [workflow/01-setup-tabs.md](workflow/01-setup-tabs.md)
2. **Live annual model** — as soon as a location and a data center exist, and
   after every change: fetch TMY weather (NSRDB, cached), build the 8760-hour
   DataFrame, run the models. → [models/datacenter-hourly.md](models/datacenter-hourly.md)
3. **Results** — one figure with Ambient, Power and Operation rows (view
   buttons on each) and a module output panel on a shared time axis, plus output metrics. → [workflow/02-results.md](workflow/02-results.md)
4. *(Future)* Co-located systems (Modules tab), waste-heat offtake, transient
   IT profiles, editable transfer functions. → [roadmap.md](roadmap.md)

## Core concepts

- **Data center type** — a reusable, saved template of design parameters
  (cooling type, loop temps, rack density, redundancy, area factors). It has
  no IT load and no location.
- **Data center (instance)** — a type + an IT load (MW) + a placed footprint on a site.
- **Site** — location, property boundary, placed facilities, weather, results.
- **Hourly model / DataFrame** — 8760 rows (TMY, local time, no leap day). All
  weather, loads, and system outputs are columns in this one frame.
- **Sizing vs. performance** — sizing uses *peak* IT load; performance uses the
  *hourly* IT load column.

## Glossary

| Term | Meaning |
|---|---|
| IT load | Electrical power consumed by servers (MW for input, kW in DataFrame) |
| IT parasitics | Non-IT building loads (pumps, fans, lighting); default 10 % of IT |
| White space | Floor area occupied by racks |
| White space ratio | Fraction of data hall that is white space |
| X·N+Y | Redundancy: X = multiple of N capacity, Y = extra spare units |
| TDB / TWB / TDP | Dry-bulb / wet-bulb / dew-point temperature (°C) |
| GHI | Global horizontal irradiance (W/m²) |
| TMY | Typical Meteorological Year |
| T_approach | Min. ΔT between ambient and supply water for free cooling (default 10 °C) |
| T_pinch | Evaporator pinch below supply water temp for COP calc (default 5 °C) |
| COP | Coefficient of performance (kW_th removed / kW_e consumed) |
| Free cooling | Heat rejection without compressors (only pumps/fans) |
| Waste heat offtake | Heat exported to co-located systems (0 in Step 1) |
