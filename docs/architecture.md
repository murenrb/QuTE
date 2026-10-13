# Architecture

Goal: add new co-located technologies, inputs, and plots **without rewriting
existing code**. Achieved by separating UI from engineering and treating the
hourly model as a pipeline of pluggable subsystems.

## Proposed layout

```
Data Center System/
├── CLAUDE.md
├── docs/                         # specs (this folder)
├── pyproject.toml                # deps (uv) + ruff/pytest/mypy config
├── uv.lock / requirements.txt    # lockfile; requirements.txt exported for Streamlit Cloud
├── streamlit_app.py              # entry point at repo root (Streamlit Cloud default)
├── .streamlit/                   # config.toml; secrets.toml (gitignored) + .example
├── app/                          # Streamlit UI ONLY
│   ├── main.py                   # page config, theme CSS, navigation (Start, Workspace)
│   ├── pages/
│   │   ├── start.py              # open project / new setup
│   │   └── workspace.py          # the single workspace: grid of panels (gui.md → Layout)
│   ├── components/               # reusable widgets
│   │   ├── style.py              # greys, font stack, sizes; injected CSS (square corners, borders)
│   │   ├── modules/              # module registry (ModuleUI) + inputs panel and outputs per module
│   │   ├── tabs/                 # one module per inputs tab
│   │   │   ├── location.py
│   │   │   ├── property.py
│   │   │   ├── data_center.py    # type, IT load, area breakdown, placement
│   │   │   ├── utility.py        # tariff painter + weekend pricing
│   │   │   └── modules.py        # co-located systems (placeholder in Step 1)
│   │   ├── map_view.py           # map per tab: folium (view, draw) or the map editor
│   │   ├── tariff_editor/        # custom component: rate swatches + month × hour painter
│   │   ├── block_controls.py     # width/length/rotation/reposition/align for any block
│   │   ├── footprint_editor/     # custom component: block mode (drag/resize/rotate) + polygon (vertex) mode
│   │   │   ├── __init__.py       # Python wrapper + re-validation of edits
│   │   │   └── frontend/         # index.html, main.js, geometry.js, vendor/leaflet
│   │   ├── weather.py            # load_weather(): st.cache_data + st.error
│   │   ├── run_model.py          # live run: weather + hourly model, cached on inputs_hash
│   │   ├── edits.py              # small shared project edits (site, footprint)
│   │   ├── metrics.py            # output metric tiles
│   │   ├── project_bar.py        # project name, autosave status, save/restore versions, download
│   │   ├── sidebar.py            # model assumptions
│   │   ├── dc_type_form.py       # DataCenterType create/select form
│   │   └── plots.py              # build_results_figure: 3 subplots, shared x (registry-driven)
│   └── state.py                  # typed wrappers around st.session_state
├── core/                         # pure Python, NO streamlit imports
│   ├── config/
│   │   └── defaults.py           # every engineering constant (see assumptions.md)
│   ├── domain/                   # dataclasses / pydantic models
│   │   ├── datacenter_type.py
│   │   ├── datacenter.py         # type + IT load + footprint
│   │   ├── site.py               # Site, Footprint
│   │   ├── modules.py            # ModuleSettings: per-module params (SolarPVParams, …)
│   │   └── utility.py            # UtilityTariff, RateCategory, WeekendPricing
│   ├── geometry/                 # local_frame (AEQD metres), boundary metrics, footprint, areas (snapping)
│   ├── site_layout.py            # layout rules: blocks, area snapping/cut-back, overlaps (pure, on Project)
│   ├── sizing/
│   │   └── datacenter_area.py
│   ├── weather/                  # provider-independent TMY cleanup + psychrometrics
│   │   ├── tmy.py                # RawTmy → 8760 frame; WeatherData/WeatherMeta
│   │   └── psychrometrics.py     # vectorized wet bulb (ASHRAE)
│   ├── timeseries/
│   │   ├── frame.py              # build 8760 index, tile daily IT profile
│   │   ├── columns.py            # column registry: name, unit, description, plot group
│   │   ├── pipeline.py           # runs registered subsystem models in order
│   │   ├── solver.py             # HourlySolver: state machine + coupled modules, hour by hour
│   │   └── streams.py            # names of the flows exchanged inside an hour
│   ├── models/                   # one module per subsystem
│   │   ├── datacenter.py         # CoolantTemperature (weather) + DataCenterNode (heat hand-out, cooling, electrical)
│   │   ├── solar_pv.py           # Solar PV: PVWatts V8 via PySAM (available) + PvOutput node
│   │   ├── ice_storage.py        # Ice storage module: one-hour step + solver node
│   │   ├── ice_mixer.py          # Ice mixer: ice into water/brine, two-pass calls (D-050)
│   │   ├── power_generation.py   # CO2 power cycle on linked heat sources / cold side (D-054)
│   │   ├── hot_water_storage.py  # Two tank / thermocline hot water storage: step + node
│   │   ├── brine_separation.py   # Single-stage evaporator brine concentrator: step + node
│   │   ├── utility.py            # UtilityCost: hourly price, energy cost, monthly demand charge
│   │   ├── grid.py               # GridBalance: net grid load from the registry; GridDraw node
│   │   └── site_model.py         # assembles subsystems, run_site_model()
│   ├── control/                  # state machine: catalog of IFs / THENs, engine → Plan (D-053, D-054)
│   └── persistence/              # project.py (JSON, migration, inputs_hash), files.py
├── services/                     # external I/O
│   ├── store.py                  # database: projects, snapshots, versions, types (D-069)
│   ├── import_files.py           # copy pre-database project / type files into it
│   ├── weather.py                # WeatherProvider interface + WeatherError types
│   ├── nsrdb.py                  # NSRDB TMY client + CSV parser + credentials
│   ├── geocode.py                # address -> lat/lon (US Census, then Nominatim)
│   └── cache.py                  # on-disk cache for API results
├── data/
│   ├── datacenter_types/         # types shipped with the repo (seed the database)
│   ├── dcs.sqlite                # local database when DATABASE_URL is unset (gitignored)
│   └── cache/                    # weather downloads (gitignored)
└── tests/
    ├── unit/  integration/  ui/  fixtures/
```

## Key patterns

### Subsystem pipeline
Each model in `core/models/` implements a common interface:

```python
class Subsystem(Protocol):
    name: str
    requires: tuple[str, ...]  # columns it reads
    provides: tuple[str, ...]  # columns it adds (registered in columns.py)

    def run(self, df: pd.DataFrame) -> pd.DataFrame: ...
```
Config (DC type, assumptions) is bound when the subsystem is constructed, so
`run` only takes the DataFrame. Implemented in `core/timeseries/pipeline.py`.

`pipeline.py` orders subsystems by their `requires`/`provides` and validates
that every required column exists. Adding a greenhouse = new module + register
it; the data center model is untouched. Heat exchange between systems (e.g.
waste-heat offtake) is expressed through shared columns.

### Column registry
`timeseries/columns.py` holds metadata for every column: name, unit, label,
`plot_group` (one view of a results row: ambient / sun / thermal / electrical
/ utility / energy_price / demand_charge / control), `stack` (bool), sign, color.
Plots are built from the registry, so a new subsystem's columns appear in the
right stacked chart automatically.

### Config & defaults
All inputs flow through typed config objects (`SiteConfig`, `ModelAssumptions`)
populated from `defaults.py`. Nothing reads a constant directly from a module
global inside a model — it's passed in. This is what makes "hard-coded now,
user-editable later" a UI-only change.

### State
Streamlit reruns the script on every interaction. Wrap `st.session_state` in
`app/state.py` with typed getters/setters; never scatter raw string keys.
Cache expensive work (`st.cache_data` for weather, model runs keyed on
`inputs_hash`). The workspace re-runs the model live after input changes (D-025),
so the cache is what keeps reruns cheap. The map is an `st.fragment`: panning on
the Location tab reruns only the map; drawing a boundary or moving the block
triggers a full rerun (D-028).

## Writing a module

A module is a co-located system (PV, ice storage, greenhouse, …) that adds
columns to the hourly frame. Every module has **two layers** — the same split
the data center model uses (`mechanical_cop()` / `data_center_hour()` vs.
`CoolantTemperature` / `DataCenterNode` in `core/models/datacenter.py`):

| Layer | Knows about the DataFrame? | Holds | Tested by |
|---|---|---|---|
| **1. Physics** — plain functions | **No.** Numbers/arrays in, numbers/arrays out | The engineering: equations, dispatch rules, losses | Hand-calculated values (one hour, one case) |
| **2. Adapter** — a `Subsystem` class | **Yes.** Reads its `requires` columns, writes its `provides` columns | Plumbing only: pull columns → call layer 1 → assign columns | Pipeline/integration tests (8760 rows, balances) |

Keep all engineering in layer 1 and keep layer 2 boring. Column names never
appear in layer 1.

### Stateless modules (no inertia) — vectorize
Output at hour *h* depends only on inputs at hour *h* (e.g. PV: GHI → power).
Write layer 1 with numpy operations so the same function works on one value or
all 8760 at once; the adapter passes whole columns, **no loop**.

```python
# core/models/solar_pv.py
def pv_power_kw(ghi_w_m2: FloatArray, area_m2: float, efficiency: float) -> FloatArray:
    """P = GHI · A · η / 1000. Works on a float or an array. (docs/models/solar-pv.md)"""
    return ghi_w_m2 * area_m2 * efficiency / 1000.0


PV_KW = register(ColumnSpec("pv_kw", "kW", "Solar PV", PlotGroup.ELECTRICAL, True, 4, color=...)).name


@dataclass(frozen=True)
class SolarPV:
    params: SolarPVParams                    # frozen dataclass; defaults in defaults.py
    name: str = "solar_pv"
    requires: tuple[str, ...] = (col.GHI_W_M2,)
    provides: tuple[str, ...] = (PV_KW,)

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        ghi = df[col.GHI_W_M2].to_numpy()
        return df.assign(**{PV_KW: -pv_power_kw(ghi, p.area_m2, p.efficiency)})
```

### Stateful modules (inertia) — step function + solver node
Output at hour *h* depends on the state after hour *h − 1* (e.g. ice storage:
state of charge). Write layer 1 as **one hour**: previous state + this hour's
inputs → new state + this hour's outputs. Layer 2 is a **solver node**
([solver.md](solver.md), D-052), not a year loop: the `HourlySolver` steps all
stateful modules together hour by hour, because they exchange flows within the
hour (ice, water, brine, the heat chain). The node pulls its columns out once
(`prepare`) and does one hour per `step`, changing nothing — the solver may
run an hour several times before it commits.

```python
# core/models/ice_storage.py
def ice_step(start: IceTankState, m_ice_requested_kg_s: float, ...) -> IceHour:
    """One hour. Returns the end state and this hour's flows."""
    s = start
    ...                                      # scalars only — hand-checkable


@dataclass(frozen=True)
class IceStorage:
    params: IceStorageParams
    name: str = "ice_storage"
    requires: tuple[str, ...] = (col.T_AMBIENT_REJ_C,)          # columns
    provides: tuple[str, ...] = (col.ICE_SOC_FRAC, ...)          # columns
    reads: tuple[str, ...] = (st.ICE_CALL_KG_S, st.MELT_WATER_KG_S)   # streams
    writes: tuple[StreamSpec, ...] = (
        StreamSpec(st.ICE_SUPPLIED_KG_S, answers=st.ICE_CALL_KG_S),  # sticky answer
        ...,
    )

    def prepare(self, df):  return df[col.T_AMBIENT_REJ_C].to_numpy(), ...
    def initial_state(self):  return initial_state(self.params)

    def step(self, data, state, h, flows) -> NodeStep:
        call = flows[st.ICE_CALL_KG_S]                 # None = nobody asked yet
        hour = ice_step(state, call or 0.0, ...)
        return NodeStep(
            hour.end,                                                 # next hour's state
            {st.ICE_SUPPLIED_KG_S: None if call is None else hour.m_ice_supplied_kg_s},
            {col.ICE_SOC_FRAC: hour.end.soc_ice, ...},                # this hour's columns
        )
```

- Use a small state class and call it `s` in the step (`IceTankState`,
  `TankState`, `BrineState`).
- A module that **receives** mass reports what it actually took: apply the
  min, recalculate with the limited input; if nothing binds, return the input
  exactly (D-051). An answer never exceeds its request.
- A year takes 0.1–0.7 s with every coupled module on. If a step gets heavy,
  decorate it with `numba.njit` (add the dependency via decisions.md).
- Decide and document the **initial state** (e.g. start full, start empty, or
  iterate the year until hour 8760 ends where hour 1 started — a "cyclic"
  year). Put it in `defaults.py`.
- Return a small frozen dataclass (`IceHour`) from the step rather than a bare
  tuple, so each output is named.

### Don'ts
- **No `df.iterrows()` / `df.apply(..., axis=1)`** — slow, and it hides what each
  step reads and writes. Pull arrays out once, then vectorize or loop.
- **No DataFrame or column names inside layer 1.**
- **No edits to another module's code** (CLAUDE.md rule 5). If a module changes
  how another subsystem behaves, see *Coupling* below.

### Checklist for a new module
1. **Spec doc** `docs/models/<module>.md`: equations, units, inputs/outputs,
   assumptions, a worked example (becomes a unit test). Check
   `docs/open-questions.md`; record answers in `docs/decisions.md`.
2. **Parameters:** a frozen dataclass of inputs with defaults in
   `core/config/defaults.py`, documented in `docs/assumptions.md`. Pass it into
   the adapter — never read module globals inside the model.
3. **Layer 1** functions in `core/models/<module>.py`, typed, docstrings with
   the equation and units.
4. **Columns:** register each output in `core/timeseries/columns.py` (or at the
   top of the module file) with units in the name and a `plot_group` if it
   should be charted. Stacked electrical columns are summed by `GridBalance`
   automatically — **generation is negative** (it reduces net grid load).
   Registration must happen at import, before the pipeline is built.
   Columns that are all ≤ 0 (generation) are drawn in their own stack group
   below zero automatically (`app/components/plots.py`).
5. **Layer 2**: a Subsystem (`name`, `requires`, `provides`, `run(df)`) if
   stateless, or a solver node (also `reads`, `writes`, `prepare`,
   `initial_state`, `step`) if stateful — see [solver.md](solver.md).
6. **Wire it in:** add it to `module_subsystems()` in `core/models/site_model.py`
   (stateful: `coupled_nodes()`, where the order is the order each hour runs),
   included only when enabled (the pipeline sorts by `requires`/`provides`, so
   Subsystem order doesn't matter). `GridBalance` is built with the stacked electrical
   columns that the active subsystems provide, so a disabled module's columns
   are simply absent. Module settings live in `Project.modules`
   (`core/domain/modules.py`). Reference implementation: Solar PV
   (`core/models/solar_pv.py`).
7. **Tests:** `tests/unit/test_<module>.py` for layer 1 (hand values; for
   stateful modules a single-step case plus an annual balance, e.g.
   ΔSOC = Σ charge − Σ discharge − losses); add the module to an integration
   test that runs the full pipeline (8760 rows, no NaN).
8. **Map category — ask the owner if not stated (D-041):** *scaled in map*
   (derive params from `SitedModuleParams`: drawn `area`, vertex-editable) or
   *scaled in inputs* (derive from `BlockModuleParams`: `enabled` + `footprint`,
   implement `block_area_m2` from the inputs). Layout rules
   (`core/site_layout.py`, applied on every project change) place/resize
   blocks, cut drawn areas back under blocks, and flag block overlaps.
   **Settings + UI:** add a field for the module to `ModuleSettings`
   (`core/domain/modules.py`). Add an inputs
   panel, its `OUTPUTS` (module output panel: one or two plot panels + text,
   [workflow/02-results.md](workflow/02-results.md)) and one `ModuleUI` entry
   (key, label, color, panel, outputs, one-line description for Add module,
   drawing note) in
   `app/components/modules/__init__.py`. The Modules tab selector, the map's
   polygon tool, snapping to free land, map colors, layout warnings and the
   results' module output selector then work with no other edits (D-036,
   D-055). A new field with defaults is additive; a
   changed field needs a `Project` schema bump + migration.
9. **Control:** declare the module's `CONTROL_SPEC` (IFs and THENs, with an
   "… is off") in its model file and add it to `TARGETS` in
   `core/control/catalog.py`; honour the hour's `Plan` in its node's `step`
   (it runs only when the plan says so) — see [control.md](control.md).
10. Update `docs/data-model.md` (columns table) and run the test gate.

### Coupling between modules
Some modules only *add* columns (PV adds generation; `GridBalance` picks it
up). Others *change what another subsystem does* — ice storage shifts when the
chillers run, which changes cooling electricity; a greenhouse taking waste heat
reduces heat rejection. Since D-054 every such exchange is a **link** the
user's states make (a link THEN), carried in the hourly solver by want →
answer → used streams ([solver.md](solver.md)): the data center node hands its
heat out in THEN order, the ice mixer serves its consumers in THEN order, and
heat a module rejects into the supply coolant joins the data center's
cooling. A new coupled module is a solver node with link THENs at both ends
(its own spec and the other module's `ends`). Sketch the streams and the
order before coding, and record them in `docs/decisions.md`.

## Tech choices (proposed — confirm in decisions.md)

| Concern | Choice |
|---|---|
| UI | Streamlit: Start page + one workspace page with tabs (gui.md) |
| Map | Leaflet via `streamlit-folium` + Leaflet.Draw for boundary; likely a **custom Streamlit component** for the draggable/resizable/rotatable footprint (see gui.md) |
| Basemap | Esri World Gray Canvas (D-019) |
| Geocoding | US Census geocoder (`requests`), fallback `geopy` Nominatim |
| Geometry | `shapely` + `pyproj` (local azimuthal-equidistant frame, D-018) |
| Plots | Plotly |
| Data | pandas |
| Schemas | pydantic v2 |
| HTTP | `requests` / `httpx` |
| Tests | pytest, Streamlit `AppTest`, ruff, mypy/pyright |
