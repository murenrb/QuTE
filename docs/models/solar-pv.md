# Solar PV Module

Code: `core/models/solar_pv.py` (layer 1 `pvwatts_ac_kw`, layer 2 `SolarPV`).
Inputs: `SolarPVParams` (`core/domain/modules.py`), defaults in
`core/config/defaults.py` → `SolarPVInputs`. UI: Modules tab → Add module → Solar PV; it runs once added *and* an area is drawn (D-056).

## Sizing from the drawn area (D-036)
The user draws the area dedicated to solar on the map; it is snapped to the
free land (inside the property, outside the block and other areas).

```
DC capacity [kW] = snapped area [sqft] × power density [W/sqft] / 1000
```
Power density: slider 5–9 W/sqft, 0.25 steps, **default 6.5 W/sqft** of land.
PVWatts has no land-density input — its "array area" is module area from
module efficiency (standard ≈ 19 % → ≈ 17.7 W/sqft of panel); land density
also depends on row spacing (≈ 7.1 W/sqft with the default GCR 0.4). The
`gcr` input still sets PVWatts' row shading/backtracking and is independent of
the density slider. PV runs only when an area exists.

## Model
NREL **PVWatts V8**, run locally through **PySAM** (`nrel-pysam`, NREL's Python
wrapper of SAM) — the same model as the PVWatts web API, but fed with **this
project's** NSRDB weather, so every output hour lines up with the cooling and
IT rows of the hourly frame (D-035). The web API can't be pointed at our
weather file (it uses its own PSM V3 tmy-2020 data, and `file_id` only selects
from that catalog).

Weather passed per hour (all from the hourly frame, local standard time):
`dn` = `dni_w_m2`, `df` = `dhi_w_m2`, `gh` = `ghi_w_m2`, `tdry` = `tdb_c`,
`wspd` = `wind_m_s`, plus month/day/hour and **minute = 30** (NSRDB stamps
values at :30; PVWatts uses it for the sun position). Site: the NSRDB cell's
lat/lon, elevation and UTC offset (`PvSite.from_weather`).

## Inputs (PVWatts V8 names in brackets)

| Field | Default | Range | Units |
|---|---|---|---|
| `area` | none (draw on map) | snapped polygons | — |
| `power_density_w_sqft` | 6.5 | 5–9, step 0.25 | W/sqft of land |
| → system_capacity [system_capacity] | area × density | derived | kW DC |
| `array_type` [array_type] | fixed open rack (0) | 0 fixed open rack, 1 fixed roof, 2 1-axis, 3 1-axis backtracking, 4 2-axis | — |
| `module_type` [module_type] | standard (0) | 0 standard, 1 premium, 2 thin film | — |
| `tilt_deg` [tilt] | **= site latitude** (|lat| from the map; 20 only if no location) | 0–90 | ° |
| `azimuth_deg` [azimuth] | **facing the equator**: 180 (south) for lat ≥ 0, 0 (north) for lat < 0; 180 without a location | 0–359 | ° |
| `losses_pct` [losses] | 14.08 | −5–99 | % |
| `dc_ac_ratio` [dc_ac_ratio] | 1.2 | 0.5–2.0 | — |
| `gcr` [gcr] | 0.4 | 0.01–0.99 | — |
| `inv_eff_pct` [inv_eff] | 96 | 90–99.5 | % |

Defaults are the PVWatts web defaults, except tilt (site latitude, D-038) and
azimuth (equator-facing by hemisphere, D-039); size comes from the area.
`None` means "follow the site" for both; typing a value stores it, and "Use
site latitude" / "Face the equator" reset it. `resolve_orientation()` fills
them in for each run. Albedo uses the PVWatts
default (0.2); bifacial, soiling and shading are not exposed yet.

## Output column

| Column | Unit | Sign | Plot |
|---|---|---|---|
| `pv_available_kw` | kW_e | positive: what the array can make (`SolarPV`, before the solver) | — (the "PV output" IF) |
| `pv_kw` | kW_e | **negative** (generation reduces net grid load) | Electric subplot, stacked **below zero** in its own stack group |

`pv_kw` = −`pv_available_kw` in hours whose state says **"Generates power"**,
else 0 (curtailed; the `PvOutput` solver node, D-054). Every state is a
complete description, so PV generates only where a state lists it (put it in
Default; new states copy Default's THENs). `GridBalance` includes `pv_kw`
automatically when PV is enabled:
`grid_net_kw = it_load_kw + it_parasitic_kw + cooling_elec_kw + pv_kw`.
Output metric: **Annual PV generation** (MWh/yr).

## Checks / worked example
Phoenix fixture (NSRDB GOES TMY tmy-2024, cell 33.45, −112.06), defaults with
tilt fixed at 20°, 1 MW DC: **1,758,822 kWh/yr** (capacity factor 20.1 %), zero at night, AC
capped at 833 kW (= 1,000 / 1.2), peak hour 12:00 local. The PVWatts web API
for the same system gives 1,764,113 kWh on its tmy-2020 weather (0.3 % apart —
different typical years, same model). Tests: `tests/unit/test_solar_pv.py`;
live API comparison `tests/live/test_nsrdb_live.py` (within 3 %).

## Not yet modelled
Degradation, bifacial gain, soiling, shading by nearby objects,
curtailment/export limits.
