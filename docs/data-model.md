# Data Model

## DataCenterType (saved, reusable)

| Field | Type / UI | Range | Default | Units |
|---|---|---|---|---|
| `name` | **derived, not an input** (D-023) | — | — | — |
| `cooling_type` | radio | `dry` \| `evaporative` | `dry` | — |
| `t_supply_min_c`, `t_supply_c` | **two-sided slider** (minimum / setpoint) | 5–80 | 5 / 40 | °C |
| `t_return_c` | slider | 5–80 | 50 | °C |
| `rack_density_kw` | slider | 5–300 | 50 | kW/rack |
| `white_space_ratio` | slider | 10–100 % | 65 % | fraction (store 0–1) |
| `redundancy_x` | slider | 1–3 | 1 | — |
| `redundancy_y` | slider | 1–10 | 1 | — |
| `ups_area_sqft_per_kw` | slider | 0–4 | 1.0 | sqft/kW IT |
| `generator_area_sqft_per_kw` | slider | 0–6 | 1.5 | sqft/kW IT |
| `switchgear_area_sqft_per_kw` | slider | 0–2 | 0.5 | sqft/kW IT |

**Naming:** *supply* = the **cold** water going to the IT equipment; *return*
= the **warm** water coming back. The spec author sometimes swaps these words —
when in doubt, use the physically conservative (coldest) combination and ask.

The supply setpoint holds whenever the chillers run; with free cooling the
supply floats at ambient + approach, clamped to [min, setpoint] (D-047, column
`t_coolant_c`). The type name and file stem include the minimum, e.g.
`Dry · 5–40→50 °C · …`. Older saved types without it load with min = 5 °C.

Validation: `t_return_c > t_supply_c`, `t_supply_min_c ≤ t_supply_c`. `t_return_c` is unused in Step 1
equations but is kept for future heat-offtake calcs (warm water available for
reuse).

**Name** is generated from every input, e.g.
`Dry · 40→50 °C · 50 kW/rack · 65% WS · N+1 · UPS/Gen/SWG 1/1.5/0.5 sqft/kW`
(cooling · supply→return · rack density · white space · X·N+Y · UPS/generator/
switchgear areas). Two types with the same parameters are the same type; floats
are rounded to 6 decimals so slider noise doesn't create near-duplicates.

Stored in the database (table `datacenter_types`, one row per design, keyed
by a stem from the parameters, e.g. `dry_40-50c_50kw_ws65_1n1_1-1p5-0p5`;
[Database](#database-d-069)). The JSON files in the repo's
`data/datacenter_types/` are added to a database that lacks them when the app
starts. Saving a design that already exists uses the saved one (the user is told). Include a
`schema_version` field so old saves can be migrated (type schema v2: a stored `name`
is ignored on load and re-derived).

## DataCenter (instance on a site)

- `type`: DataCenterType (copied by value at save time, plus type name ref)
- `it_load_peak_mw`: float > 0
- `it_profile_daily_kw`: 24 hourly values; Step 1 = constant at peak
- `footprint`: `Footprint` (center_lat, center_lon, width_m, length_m, rotation_deg) or None
  until placed; area fixed by sizing. `width_m` is east–west at rotation 0; rotation is
  clockwise in [0, 180). Code: `core/domain/site.py`.
- derived: area breakdown (see models/sizing.md)

## Site

- `name`, `lat`, `lon`, optional `address`
- `boundary`: **one contiguous polygon** — open ring of (lat, lon) vertices, first vertex
  not repeated; empty until drawn
- `facilities`: list of DataCenter (list, to allow multiple / other tech later)
- `assumptions`: ModelAssumptions snapshot (see assumptions.md)
- Code: `core/domain/site.py`; the project file model is `core/persistence/project.py`.
- `weather_ref`: weather cache key, e.g. `nsrdb/33.45_-112.07_tmy-2024.csv`
- `map_center` (lat, lon) and `map_zoom`: the exact view framed on the Location
  tab; the locked tabs reopen at exactly this center and zoom (D-031).
- `map_view`: that view's bounds — (south, west, north, east) in degrees — used
  for the "boundary outside the view" check, and fitted only for older projects
  that lack center/zoom. All three are None until framed and are excluded from
  `inputs_hash` (not engineering inputs).

## Project file (persistence)

One JSON document holds everything needed to restore a session:
`schema_version`, site (location, boundary), facilities (DC type snapshot, IT
load + profile, footprint), model assumptions, and the active workspace tab
`control` (`ControlSettings`: the Default state + the user's states in priority
order, each with IFs, THENs and allowed moves; a utility IF may name a rate
category by id, D-059; additive — older files load with
only the Default state, [control.md](control.md)),
`utility` (`UtilityTariff`: rate categories, 12 × 24 schedule of category ids,
weekend pricing; additive — older files load the default tariff), `modules`
(co-located module settings — `ModuleSettings`, currently
`solar_pv: SolarPVParams` (scaled in map), `ice_storage: IceStorageParams`
(scaled in inputs: `enabled` + `footprint`, a block like the data center's,
area = tank / `energy_density_kwh_sqft`), `power_generation:
PowerGenerationParams` (scaled in inputs, area = rated MWe × sqft/MWe), `hot_water_storage:
HotWaterStorageParams` (scaled in inputs, block from the tank cylinders;
`tank_volume_m3` is derived and never saved), `ice_mixer: IceMixerParams` (no footprint: `enabled`, `fluid`,
`recup_eta_pct`, `mix_eta_pct`), `brine_separation:
BrineSeparationParams` (scaled in inputs, one 12 m tank; `brine_mass_kg` derived,
never saved); all additive, no migration; modules that occupy land derive from
`SitedModuleParams` and carry an `area`: a tuple of `AreaPolygon`
(`exterior` ring + `holes`, lat/lon), active when non-empty), and the active
workspace tab
(`step`: `location` | `property` | `data_center` | `utility` | `modules`; default `location`;
older values such as `site_setup` open on Location).
Weather and results are **not** stored — weather is re-fetched (disk cache) and
the model is re-run on load.

- **Autosave:** written on **every** config change (changed state only) to the
  project's row in the database. A new project's id (`stem`) is
  `<name-slug>-<6 hex>` (unique, so two "Untitled site" projects can't overwrite
  each other); an opened project keeps its id; renaming keeps the id. Only a
  session that opened or created a project autosaves (D-040), and a new project
  is first saved on its first change.
- **Automatic snapshots:** before an autosave overwrites changed content, the
  old content is kept as a snapshot — at most every 5 min (always before a
  restore, and always when another session saved the project in between),
  newest 50 kept (`PersistenceSettings`).
- **Saved versions:** "Save version" keeps a named copy; never overwritten or
  pruned. Restoring a version or snapshot replaces the working project (and its
  autosave), never the version.
- **Download:** project bar button exports the same JSON (portable copy);
  **Open** on Start can upload one (it becomes a new project).
- **Open:** on start, user can open any saved project or upload a file, or
  start a new setup. The workspace URL carries the id (`?project=<stem>`).

### Database (D-069)
Code: `services/store.py` (SQLAlchemy). **Public:** every project and
type is visible to, and editable by, everyone using the app; there are no
accounts (owner). Each document is stored as its JSON text, so the tables never
change when the project schema does (`from_json` migrates on load).

| Table | Columns | Holds |
|---|---|---|
| `projects` | `stem` (PK), `name`, `updated_at` (UTC), `data` | working autosave |
| `project_snapshots` | `id`, `stem`, `kind` (`history` \| `version`), `label`, `saved_at` (UTC), `data` | snapshots and saved versions |
| `datacenter_types` | `stem` (PK), `name`, `data` | type library |

- **Which database:** `DATABASE_URL` from the environment (Streamlit Cloud
  exposes root secrets this way), else `.streamlit/secrets.toml`, else a SQLite
  file `data/dcs.sqlite` (gitignored; `$DCS_DATA_DIR` moves it). Deployed: a
  hosted Postgres ([deployment.md](deployment.md)); `postgres://` URLs are
  sent to the psycopg driver. Tables are created when missing.
- **Two sessions on one project:** last write wins; the overwritten state is
  always kept as a snapshot and the session that overwrote it is told.
- **Files from before the database:** `python -m services.import_files
  [data folder]` copies `projects/` (autosaves, `history/`, `versions/`) and
  `datacenter_types/` into the database `DATABASE_URL` names; projects already
  there are skipped.
- Tests use a fresh SQLite database each (`tests/conftest.py`).
- `schema_version` **2** (2026-10-01): v1 → v2 drops Solar PV's old
  `enabled` / `system_capacity_kw` (PV became area-sized; the area starts empty).
- `schema_version` **3** (2026-10-05): v2 → v3 updates ice storage to the new
  defaults — `ice_maker_size_tr` 1,000 (old default) → None (65 TR/MW of IT
  load); `tank_charge_time_h` < 6 → 24.
- `schema_version` **4** (2026-10-08): v3 → v4 gives drawn-area modules
  (Solar PV) an `enabled` flag like the other modules (modules are added to
  the site explicitly, D-056): on where an area was already drawn.
- `schema_version` **5** (2026-10-09): v4 → v5 drops the greenhouse's
  `wind_m_s` (its first version computed U from convection; U is now the
  input `u_w_m2k`, D-062).
- `schema_version` **6** (2026-10-09): v5 → v6 replaces power generation's
  `rated_kw` (kWe, None = 2 % of IT) by `rated_pct_of_it`: a saved kWe becomes
  its % of the first facility's IT peak (clipped to 0.5–150), none = 2 %
  (D-063). `rated_kw` is now derived and not saved.
- Loading validates via pydantic and migrates older `schema_version`s
  (`MIGRATIONS` in `core/persistence/project.py`); bad files raise `ProjectFileError`.
- Results are flagged stale when `inputs_hash(project)` changes (ignores step,
  site name/address, weather_ref, map_view, map_center, map_zoom).

## Hourly DataFrame (the backbone)

- **Index**: `timestamp` (DatetimeIndex) — naive local standard time on reference
  year 2025 (non-leap), 8760 rows. First column: `it_load_plan_kw`.
- Column names: `snake_case` with a unit suffix. Units: `_c`, `_pct`, `_w_m2`,
  `_kw` (electric), `_kwth` (thermal), no suffix for dimensionless (`cop_mech`).
- Every column is registered in `core/timeseries/columns.py`.

### Step 1 columns

| Column | Unit | Source | Plot group |
|---|---|---|---|
| `timestamp` | local time | NSRDB | — |
| `it_load_plan_kw` | kW_e | planned: daily profile tiled ×365 | — |
| `it_load_kw` | kW_e | actual: planned × the state's IT load THEN (`DataCenterNode`, D-053/D-054) | electrical (stack 1) |
| `control_state` | — | state machine: 0 = Default, then priority order ([control.md](control.md)) | control (Operation row view, D-060) |
| `tdb_c` | °C | NSRDB | ambient |
| `twb_c` | °C | derived (ASHRAE psychrometrics from TDB, RH, pressure) | ambient |
| `tdp_c` | °C | NSRDB | ambient |
| `rh_pct` | % | NSRDB | — |
| `ghi_w_m2` | W/m² | NSRDB | sun (Ambient row view, D-060) |
| `dni_w_m2` | W/m² | NSRDB | — (PV input) |
| `dhi_w_m2` | W/m² | NSRDB | — (PV input) |
| `wind_m_s` | m/s | NSRDB | — (PV input) |
| `t_ambient_rej_c` | °C | `CoolantTemperature`: TDB if dry, TWB if evap | — |
| `t_coolant_c` | °C | `CoolantTemperature`: supply water — setpoint with chillers; free cooling: clamp(ambient + approach, min, setpoint) (D-047) | — |
| `cop_mech` | — | `CoolantTemperature` (weather only) | — |
| `it_parasitic_kw` | kW_e | data center node | electrical (stack 2) |
| `heat_offtake_kwth` | kW_th | data center heat used by the modules the state links (THEN order, D-054) | — |
| `brine_heat_kwth` | kW_th | brine separation boiler heat (= condenser) — [models/brine-separation.md](models/brine-separation.md) | thermal (line) |
| `brine_mass_kg`, `brine_conc_wt_pct`, `brine_water_out_kg_h` | kg, wt%, kg/h | brine separation | — |
| `brine_soc_frac` | – (brine volume / tank volume) | brine separation | module output |
| `brine_out_kg_s`, `brine_in_kg_s` | kg/s | brine separation: brine to / back from the ice mixer (D-052) | — |
| `brine_water_to_ice_kg_s` | kg/s | brine separation: recovered water taken by ice storage (D-054) | — |
| `cooling_total_kwth` | kW_th | data center heat, IT + parasitics (what the thermal stack totals) | — |
| `cooling_mech_kwth` | kW_th | data center node: heat needing mechanical cooling (its own + modules' coolant rejection), before the ice mixer | — |
| `cooling_free_kwth` | kW_th | data center node: everything free-cooled (its own + modules' coolant rejection) — D-054 | thermal (stack 4) |
| `cooling_elec_kw` | kW_e | data center node: chillers / COP + free / COP_free | electrical (stack 3) |
| `hws_net_kwth` | kW_th | hot water storage: charge − discharge — [models/hot-water-storage.md](models/hot-water-storage.md) | — |
| `hws_stack_kwth` | kW_th | hot water storage: charge − discharge to power generation (D-065) | thermal (stack 6) |
| `hws_charge_kwth`, `hws_discharge_kwth` | kW_th | hot water storage: from the data center / to power generation | — |
| `hws_soc_frac`, `hws_t_hot_c`, `hws_t_cold_c` | —, °C, °C | hot water storage | — |
| `hws_t_sys_c` | °C | hot water storage: facility water back from the HX (T_cold + pinch charging, T_hot − pinch discharging) | — |
| `cooling_chiller_kwth` | kW_th | data center node: mechanical load − the ice mixer's cooling to the data center (D-054) | thermal (stack 1) |
| `ice_instant_kwth`, `ice_discharge_kwth` | kW_th | ice storage (when enabled), FYI at h_f(0) — [models/ice-storage.md](models/ice-storage.md) | — (D-050) |
| `ice_charge_kwth`, `ice_soc_frac`, `ice_water_soc_frac` | kW_th, —, — | ice storage | — |
| `ice_supplied_kg_s`, `ice_water_in_kg_s` | kg/s | ice storage: ice handed out, water accepted (D-049) | — |
| `ice_maker_elec_kw` | kW_e | ice storage | electrical (stack 5) |
| `ice_mix_q_kwth` | kW_th | ice mixer: cooling used by its consumers — [models/ice-mixer.md](models/ice-mixer.md) | thermal (stack 2) |
| `greenhouse_loss_kwth`, `greenhouse_solar_kwth`, `greenhouse_demand_kwth`, `greenhouse_vented_kwth` | kW_th | `GreenhouseLoad` (before the solver, weather only): loss through the covering, solar gain, heating demand, surplus vented — [models/greenhouse.md](models/greenhouse.md) | — |
| `greenhouse_heat_kwth` | kW_th | greenhouse: heat from the data center's return water | thermal (stack 7) |
| `greenhouse_heat_hws_kwth` | kW_th | greenhouse: heat from hot water storage (D-064) | thermal (hatched, top of the stack, D-065) |
| `greenhouse_unmet_kwth` | kW_th | greenhouse: demand its sources didn't cover | — |
| `ice_mix_t_c` | °C | ice mixer | — |
| `ice_mix_ice_kg_s`, `ice_mix_brine_kg_s`, `ice_mix_brine_out_kg_s`, `ice_mix_water_out_kg_s` | kg/s | ice mixer: ice / brine used and what it returns (settled by the solver, D-052) | — |
| `ice_mix_brine_out_wt_pct` | wt% | ice mixer: diluted brine concentration | — |
| `power_gen_power_kwth` | kW_th | power generation: heat converted to power (= generation) — [models/power-generation.md](models/power-generation.md) | thermal (stack 5) |
| `power_gen_heat_in_kwth`, `power_gen_reject_kwth`, `power_gen_eff` | kW_th, kW_th, — | power generation (reject goes to its cold side) | — |
| `power_gen_kw` | kW_e, **negative** | power generation | electrical (stacked below zero) |
| `pv_available_kw` | kW_e | Solar PV: what the array can make (PVWatts) | — |
| `pv_kw` | kW_e, **negative** | Solar PV when the state says "Generates power" — [models/solar-pv.md](models/solar-pv.md) | electrical (stacked below zero) |
| `grid_net_kw` | kW_e | `GridBalance`: sum of the stacked electrical columns present | electrical (black line) |
| `energy_price_usd_kwh`, `demand_charge_usd_kw` | $/kWh, $/kW | `UtilityPrice` from the painted tariff — [models/utility.md](models/utility.md) | energy_price / demand_charge (Operation row views, D-060) |
| `energy_cost_usd`, `demand_cost_potential_usd`, `demand_cost_usd`, `utility_cost_usd` | $ per hour | `UtilityCost` | utility (energy + demand stacked) |

Add new rows to this table whenever a column is added.
