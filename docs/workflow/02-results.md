# Workflow — Results (results figure + output metrics)

Live on the workspace page (layout in [../gui.md](../gui.md), D-024/D-025/D-029). They update automatically after every
input change once a location and a data center exist
([01-setup-tabs.md §6](01-setup-tabs.md#6-live-model-run-replaces-the-old-save-configuration-button)).

| Panel | Position |
|---|---|
| Module output selector | output layer, above the left half |
| Module output: plot + text table | output layer, left — same Plotly figure as the results (D-055) |
| Results figure: Ambient, Power, Operation rows, each with view buttons (D-060) | output layer, right — three stacked rows |
| Output metrics | under all the plots, full width (D-055) |

The output layer starts below the input/map layer, separated by a full-width
grey line (D-032).

The three rows share **one time axis**: zooming, panning or using the
range slider (under the bottom row) moves them all together, and hover
shows all traces at the same hour (D-029). The module output plot follows the
same axis (its own x-axis with `matches: "x"`). Traces come from the column
registry by `plot_group`, colored by the registry; everything else greyscale.

**View buttons (owner, D-060).** Each row shows one view at a time, picked
with the buttons at the row's top right. Every view is already in the figure
(its own y-axis on the row); a button only shows its traces and axis and
hides the rest of that row, in the browser, with no rerun. More outputs are
added as views instead of new rows: register the column with a new
`PlotGroup` and add a `View` to its row in `ROWS` (`app/components/plots.py`).

| Row | Views (plot_group) — the first is the default |
|---|---|
| **Ambient** | Temperatures (`ambient`) · Sun (`sun`: GHI) |
| **Power** | Thermal (`thermal`) · Electrical (`electrical`) |
| **Operation** | Utility cost (`utility`) · Energy price (`energy_price`) · Demand charge (`demand_charge`) · Control state (`control`) |

**Zoom and views persist (owner, D-060).** The figure is drawn by a keyed
Streamlit component (`app/components/results_chart.py`), not
`st.plotly_chart`, which gave the chart a new identity whenever the figure
changed and so lost the zoom on every model run. The chart stays mounted and is
updated in place; the browser remembers the zoom and each row's view for the
tab (sessionStorage) and re-applies them on every redraw, so they survive
model runs, module switches, a failed run and a page reload. Double-click
(autoscale) goes back to the full year.

## Charts

### Ambient row
- **Temperatures** (`ambient`): line traces, **no smoothing**: `tdb_c`,
  `twb_c`, `tdp_c` (°C).
- **Sun** (`sun`): `ghi_w_m2` (W/m²).

### Power row — Thermal view (plot_group = thermal)
- Time-series **stacked area** of where the data center's heat ends up
  (D-054), bottom → top: `cooling_chiller_kwth` (Chillers), `ice_mix_q_kwth`
  (Ice mixer, when on), `cooling_free_kwth` (Free cooling), `power_gen_power_kwth`
  (Converted to power, when on; the same power appears below zero on the
  electrical plot), `hws_stack_kwth` (Hot water storage, when on: charge −
  discharge to power generation, so below zero only while power generation
  runs on it), `greenhouse_heat_kwth` (Greenhouse, heat straight from the data
  center). Everything up to here adds up to the data center's heat.
  Modules' heat rejected into the supply coolant is inside free cooling /
  chillers.
- **On top, hatched** (D-065): greenhouse heat from a module rather than the
  data center — `greenhouse_heat_hws_kwth` ("Greenhouse from hot water
  storage", greenhouse green, hatched). It sits above the data center's total,
  so the extra heat the greenhouse gets from storage shows as more heat, not
  as a negative storage band.
- `brine_heat_kwth` (Brine separation, when on) is a **line**: its boiler heat
  passes on through its condenser, so it isn't a destination of its own.
- Registry-driven so future traces (heat offtake to a greenhouse, district
  heating, …) slot in when a module registers them.
- **Sanity check:** stack total = IT × (1 + parasitic frac) (= IT × 1.1).
  Enforced by a test; optionally a dashed line.

### Power row — Electrical view (plot_group = electrical)
- Stacked area, bottom → top: `it_load_kw`, `it_parasitic_kw`, `cooling_elec_kw`,
  `ice_maker_elec_kw` (when ice storage is on); `power_gen_kw` (negative, when
  power generation is on).
- **Generation below zero:** columns that are all ≤ 0 (e.g. `pv_kw`) stack
  downward from zero in their own stack group.
- **Black line (no fill):** `grid_net_kw` (loads + generation).

### Operation row (D-057, D-060)

| View | Columns (plot_group) | Drawn as |
|---|---|---|
| **Utility cost** (default, D-043) | `cum_energy_cost_usd`, `cum_demand_cost_usd` (steps once a month), `cum_utility_cost_usd` (black) — running sums through the year (D-044) (`utility`) | lines |
| **Energy price** | `energy_price_usd_kwh` (`energy_price`) | hourly steps |
| **Demand charge** | `demand_charge_usd_kw`, the hour's rate (`demand_charge`) | hourly steps |
| **Control state** | `control_state` (`control`) | hourly steps; one y tick per state, named (names over 16 characters are cut, the hover shows the whole name), Default at the bottom |

Utility details: [../models/utility.md](../models/utility.md); states:
[../control.md](../control.md).

## Module output (D-055)
Left of the results rows, in the same figure. A segmented control (the
same as the Modules tab) lists the **modules on the site** and picks one
(D-056). With none on the site the panel says "Add a module on the Modules
tab to see its output here"; a module added but not yet able to run (e.g. PV
before its area is drawn) says "… has no results yet".
Each module declares its panel in its UI file (`OUTPUTS`, a `ModuleOutputs`
in `app/components/module_outputs.py`): one plot panel spanning the first two
rows, or two stacked panels on rows 1 and 2 (two quantities with different
units get two panels rather than two y-axes, owner left it to us), and a text
table over row 3, starting a little below its top (`TABLE_GAP`) so the
two-line date ticks of a zoomed-in axis (day, then year) don't run into the
table's title. Statistics are over the year.

| Module | Plot | Text |
|---|---|---|
| Solar PV | power production (MW) | energy produced (MWh/yr) |
| Ice storage | state of charge of the ice tank (blue) and the water tank (orange) (%), one panel | median and max ice made per day (t/day; ice made = ice maker duty / 330 kJ/kg); ice making rate while on, production-weighted Σq² / Σq (TR); ice maker electricity (MWh/yr) |
| Waste heat to power | power out and heat in (MW / MW_th); cycle efficiency (%) | power generated (MWh/yr); hours running |
| Hot water storage | state of charge (%); hot and cold tank temperatures (°C) | heat stored, heat delivered (MWh_th/yr) |
| Brine separation | brine tank state of charge (`brine_soc_frac`, %); concentration (wt%) | min and max concentration (wt%); water produced (gal/yr) |
| Ice mixer | cooling delivered (MW_th); mixed temperature (°C) | median and min cooling temperature (°C), over the hours it cools |
| Greenhouse | heating demand, heat supplied and the part from hot water storage (MW_th); loss through the glass and solar gain (MW_th) | heating demand, heat from the data center, heat from hot water storage, heat not met (MWh_th/yr); peak demand (MW_th); hours heating |

Power generation and hot water storage panels weren't specified by the owner;
the ones above are proposals.

## Output metrics
Under all the plots, full width (6 tiles per row). Compact tiles/table, every value with units. Step 1 set (all derivable from
the hourly frame; see [../open-questions.md](../open-questions.md) Q1 for the
proposed additions):

| Metric | Definition | Units |
|---|---|---|
| Annual IT energy | Σ `it_load_kw` / 1000 | MWh/yr |
| Annual cooling electricity | Σ `cooling_elec_kw` / 1000 | MWh/yr |
| Annual grid energy | Σ `grid_net_kw` / 1000 | MWh/yr |
| Peak grid load | max `grid_net_kw` / 1000 | MW |
| Free-cooling hours | count(`cooling_free_kwth` > 0), and % of 8760 | h, % |
| Annual utility cost / energy cost / demand charges | Σ `utility_cost_usd`, Σ `energy_cost_usd`, Σ `demand_cost_usd` | $/yr |
| Average utility cost | Σ `utility_cost_usd` / imported MWh (net load > 0) | $/MWh |
| Annual PV generation (if PV enabled) | −Σ `pv_kw` / 1000 | MWh/yr |
| Annual cooling from ice (if ice storage on) | Σ (`ice_instant_kwth` + `ice_discharge_kwth`) / 1000 | MWh_th/yr |
| Annual ice maker electricity (if ice storage on) | Σ `ice_maker_elec_kw` / 1000 | MWh/yr |
| Heat into brine separation (if on) | Σ `brine_heat_kwth` / 1000 | MWh_th/yr |
| Water recovered from brine (if on) | Σ `brine_water_out_kg_h` × 0.264172 (`GAL_PER_KG_WATER`) | gal/yr |
| Final brine concentration (if on) | last `brine_conc_wt_pct` | wt% |
| Heat into hot water storage (if on) | Σ `hws_charge_kwth` / 1000 | MWh_th/yr |
| Annual waste heat to power (if on) | −Σ `power_gen_kw` / 1000 | MWh/yr |
| Waste heat to power hours (if on) | count(`power_gen_kw` < 0) | h |
| Weather source | NSRDB dataset + cell lat/lon + UTC offset | — |

## Future
More KPIs (PUE, WUE, heat reuse factor, CO₂, cost), module traces, parameter
sweeps and scenario comparison in this area.
