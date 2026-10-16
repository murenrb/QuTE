# Model Assumptions & Defaults

Single source of truth for engineering constants. Code mirror:
`core/config/defaults.py`. "Editable" = planned to become a user input in the
"Model assumptions" section of the UI; until then it is fixed but still passed
through config (never inlined).

## Sizing transfer functions

| Name | Value | Units | Editable | Used in |
|---|---|---|---|---|
| `ws_density_slope` | 0.008 | (kW/sqft)/(kW/rack) | future | data hall area |
| `ws_density_intercept` | 0.1216 | kW/sqft | future | data hall area |
| `redundancy_adder_per_y` | 0.10 | fraction per Y | future | backup power area |
| `chiller_area_dry` | 0.4 | sqft/kW IT | future | chillers + dry coolers, lumped (D-067) |
| `chiller_area_evap` | 0.2 | sqft/kW IT | future | chillers + cooling towers, lumped (D-067) |

## Hourly model

| Name | Value | Units | Editable | Used in |
|---|---|---|---|---|
| `it_parasitic_frac` | 0.10 | fraction of IT | yes | parasitics, cooling load |
| `t_approach_c` | 10 | °C | yes | free vs. mechanical split (ambient + approach < supply) |
| `t_pinch_c` | 5 | °C | yes | Carnot COP (evaporator = supply − pinch) |
| `carnot_fraction` | 0.40 | — | yes | mechanical COP |
| `t_cond_approach_dry_c` | 10 | °C | yes | Carnot hot side = ambient + this (dry) |
| `t_cond_approach_evap_c` | 5 | °C | yes | Carnot hot side = ambient + this (evaporative) |
| `cop_max` | 10 | — | yes | COP clamp |
| `cop_min` | 0 | — | no | COP clamp |
| `cop_free_dry` | 50 | — | yes | free-cooling electrical load |
| `cop_free_evap` | 100 | — | yes | free-cooling electrical load |
| `heat_offtake_kwth` | 0 | kW_th | future (from co-located systems) | cooling load |

## Site setup (UI inputs and placement)

| Name | Value | Units | Used in |
|---|---|---|---|
| `it_load_peak_mw` range / default | 0.1–2000 / 10 | MW | IT load input |
| `min_aspect` / `max_aspect` | 0.1 / 10 | length ÷ width | facility block width limits |
| `edge_tolerance_m` | 0.01 | m | block touching the boundary edge counts as inside |
| Geocoder | US Census (benchmark `Public_AR_Current`), then Nominatim; 10 s timeout | — | address lookup |

## Solar PV module (PVWatts V8 inputs)

| Name | Range / default | Units |
|---|---|---|
| `power_density_w_sqft` | 5–9 (step 0.25) / 6.5 | W/sqft of land → DC kW = area × density |
| `array_type` | fixed open rack | — |
| `module_type` | standard | — |
| `tilt_deg` | 0–90 / **site latitude** (|lat|; 20 without a location) | ° |
| `azimuth_deg` | 0–359 / **equator-facing**: 180 north of the equator, 0 south of it (180 without a location) | ° |
| `losses_pct` | −5–99 / 14.08 | % |
| `dc_ac_ratio` | 0.5–2.0 / 1.2 | — |
| `gcr` | 0.01–0.99 / 0.4 | — |
| `inv_eff_pct` | 90–99.5 / 96 | % |
| `cover_data_center` | off (adds the data center block area at the same density, D-073) | — |

PVWatts web defaults; size from the drawn area. Snapped area pieces smaller
than `min_piece_m2` = 1 m² are dropped as slivers (`SiteAreaSettings`);
overlaps under 0.01 m² are rounding; a new block is placed 5 m beside the data
center (`block_gap_m`). "Snap edges to N/S/E/W": 45° steps
(`compass_step_deg`); an edge is fixed if both ends and its midpoint are within
0.5 m of the boundary, a block or another area (`edge_contact_tol_m`); a corner
that would move more than 3× its edges stays put. Hole healing (D-074) ignores
freed slivers narrower than 0.5 m (`heal_sliver_m` = 0.25 m opening radius). See [models/solar-pv.md](models/solar-pv.md).

## Ice storage module

| Name | Default | Units |
|---|---|---|
| `ice_maker_size_tr` | 65 TR per MW of IT load (`tr_per_mw_it`); 10–200,000, log slider | TR (1 TR = 3.516853 kW_th, `KW_PER_TR`) |
| `tank_charge_time_h` | 24 (6–72) | h of nameplate |
| `soc_start_frac` | 0.0 | ice tank fraction at hour 0 (empty: ice + water start as one full tank, D-058) |
| `water_soc_start_frac` | 1.0 | water tank fraction at hour 0 (same size as the ice tank) |
| `ICE_LATENT_HEAT_KJ_KG` | 330 | kJ/kg, ice flows ↔ duties |
| `energy_density_kwh_sqft` | 15 (1–100) | kWh_th/sqft → footprint = tank / density |
| `cop_max` / `capacity_factor_max` | 6.0 / 1.23 | at min. discharge pressure |
| COP fit a, b, c | 0.0011, −0.1503, 6.562 | of ambient °C |
| Capacity fit a, b, c | −0.001, −0.0023, 1.2453 | of ambient °C, clamped ≥ 0 |
| Control | by the state's THENs: cleared to run, sends ice to the mixer, takes recovered water after melt water (rest drains) | D-054 |

See [models/ice-storage.md](models/ice-storage.md).

## Power generation module (transcritical CO2)

| Name | Default | Units |
|---|---|---|
| `carnot_pct` | 30 (10–50) | % of Carnot |
| `rated_pct_of_it` | 2 (slider 0.5–150, D-063); rated kWe = this % × IT load peak | % of IT load (rating at the max cold-side temp) |
| `t_cold_max_c` | 10 (0 → free-cooling cutoff in the UI) | °C |
| `power_density_sqft_mwe` | 2,000 (1,000–3,000, step 50) | sqft/MWe → footprint |
| Hot side (design) | data center return water (`t_return_c`); Q_design = rated / η there at `t_cold_max_c` | °C |
| Heat sources (THEN order) | data center return water; hot water storage at hot tank − pinch; brine condenser steam at T_sat − condenser pinch | °C |
| Cold side (first listed) | supply coolant `t_coolant_c` (D-047), its rejection free-cooled when possible else on the chillers; or the ice mixer's temperature, its rejection carried by the mixer | °C |
| Run at % of design | 100 (0–100): heat in ≤ % × Q_design, power ≤ % × rated | % |
| Dispatch | whenever the state runs it and η > 0 (no free-cooling rule) | D-054 |

See [models/power-generation.md](models/power-generation.md).

## Hot water storage module

| Name | Default | Units |
|---|---|---|
| `storage_hours` | 12 (4–72) | h of IT heat |
| Tank volume | IT kW × (1 + `it_parasitic_frac`) × h × 3600 / ((T_return − T_supply) × cp × ρ) | m³ per tank |
| `WATER_CP_KJ_KGK` / `WATER_RHO_KG_M3` | 4.18 / 992 (40 °C) | kJ/kg·K, kg/m³ |
| Pinch | direct 0, **indirect 2** | K |
| `tank_height_m` | 12 (3–30) | m |
| Block buffer | 20 ft each side | ft |
| Initial state | cold tank full at supply temp, hot tank empty | — |
| Control | by the state: charges from the data center (in THEN order), discharges to power generation against the supply temp; charge first | D-054 |

See [models/hot-water-storage.md](models/hot-water-storage.md).

## Floating coolant (supply) temperature

| Name | Default | Units |
|---|---|---|
| `t_supply_min_c` | 5 (two-sided slider with the setpoint, 5–80) | °C |
| Free cooling | clamp(heat-rejection ambient + `t_approach_c` (10), min, setpoint) | °C |
| Chillers on | setpoint (`t_supply_c`, 40) | °C |

## Brine separation module

| Name | Default | Units |
|---|---|---|
| Brine | potassium acetate: a_w = 1.6292c³ − 2.678c² − 0.0096c + 0.9979; ρ = 642.08c + 980.82 | c = mass fraction |
| Concentration range | 20 → 40 (0–50) | wt% |
| Time to concentrate | 24 (6–72) | h of IT × (1 + parasitic) heat |
| `h_vap_kj_kg` | 2,382 (50 °C) | kJ/kg |
| Boiler / condenser pinch | 2 / 2 | K |
| Antoine B, C (water) | 1730.63, 233.426 | °C, mmHg |
| Tank height / block buffer | 12 m / 20 ft each side | — |
| Heat THEN | accepts 100 (0–100) % of the data center's heat, in THEN order | % |
| Condenser | rejects into the supply coolant (free when possible, else chillers), or to the ice mixer when it cools brine separation; power generation may take condenser heat first | D-054 |
| Recovered water | to ice storage's water tank (after melt water) or the drain | D-054 |
| `GAL_PER_KG_WATER` | 0.264172 (1 kg of water ≈ 1 L); water produced is shown in gal/yr | gal/kg |

See [models/brine-separation.md](models/brine-separation.md).

## Ice mixer module

| Name | Default | Units |
|---|---|---|
| `fluid` | water (water / brine) | — |
| `recup_eta_pct` | 70 (50–90); brine only — water is made, stored and melted at 0 °C | % |
| `mix_eta_pct` | 80 (50–90; 100 % is impossibly ideal) | % |
| h_f(0) (`ICE_LATENT_HEAT_KJ_KG`) | 330 | kJ/kg |
| h_f(t) cp's (`ICE_PROPS`) | pure 2.2 (ice) / 4.18 (water); fits cp_i = 0.0067t + 2.0725, cp_w = 0.0016t² + 0.0251t + 4.2441 | kJ/kg·K |
| Potassium acetate fp(c), c(t) | −137.95, −173.45, −11.85, −0.2351 / −0.000004, −0.000468, −0.0211, 0.01346 | °C, mass fraction |
| Potassium acetate h_solv coefficient | −64 (heat generated; h = h_f + h_solv) | kJ per kg of ice |
| Control | cools the consumers the state links (data center: its mechanical load only; power generation; brine separation's condenser) in THEN order | D-054 |

See [models/ice-mixer.md](models/ice-mixer.md).

## Greenhouse module (D-061, D-062, D-064)

| Name | Default | Units |
|---|---|---|
| `transmissivity_pct` | 90 (slider 80–100, owner) | % |
| `u_w_m2k` | 7.5 (slider 5–10, owner); overall U of the covering. Texas A&M AgriLife Table 1: single glass 1.13 Btu/h·ft²·°F = 6.4 W/m²K, double glass 0.65 = 3.7, single PE 1.15 = 6.5, double PE 0.70 = 4.0 | W/m²K |
| `t_set_c` | 20 (slider 15–40, owner) | °C |
| `cover_to_floor_ratio` | 1.3 — roof + walls of a gutter-connected house (owner) | — |
| `W_M2K_PER_BTU_HFT2F` | 5.678263 (1 Btu/h·ft²·°F in W/m²K) | — |
| `coil_approach_c` | 10 — water → air heating coil (owner, D-064, as the other air coils): a source heats only if its water > setpoint + 10; hot water storage cools its water to setpoint + 10 | K |
| Heat sources | data center return water, hot water storage (THEN order) | — |

See [models/greenhouse.md](models/greenhouse.md).

## Saving (app behaviour)

| Name | Value |
|---|---|
| Automatic snapshot interval | at most every 300 s (forced before a restore) |
| Snapshots kept per project | 50 |
| New-project file suffix | 6 hex characters |
| Disconnected session kept (`server.disconnectedSessionTTL`) | 12 h (Streamlit default 2 min) |

## Utility tariff (D-043)

| Name | Default | Units |
|---|---|---|
| Off peak | 0.10 / 10 | $/kWh / $/kW |
| Shoulder | 0.15 / 10 | $/kWh / $/kW |
| Peak | 0.20 / 10 | $/kWh / $/kW |
| New rate (added) | 0.12 / 10 | $/kWh / $/kW |
| Schedule | all off peak | 12 × 24 |
| Weekend energy prices | Follow schedule | — |
| Ranking / colour weight | energy × 100 + demand | — |
| Limits | 0–10 $/kWh, 0–1,000 $/kW | — |

See [models/utility.md](models/utility.md).

## Weather

| Name | Value |
|---|---|
| Dataset | NSRDB GOES TMY v4, `names=tmy-2024` (pinned), hourly, all attributes |
| Time | local standard time, leap day removed, 8760 rows, `:30` stamp → hour-beginning slot |
| Cache key rounding | 2 decimal places of lat/lon (~1 km) |
| Request retries | 3 attempts on 429/5xx/timeout, backoff 2 s doubling; timeout 120 s |
| Wet bulb | derived: ASHRAE Fundamentals ch. 1, bisection on [tdb − 60 K, tdb], 40 iterations |
| Pressure fallback | standard atmosphere from elevation, sea level 101,325 Pa |

Any change here must be reflected in `defaults.py`, the relevant model doc, and
tests' expected values in the same commit.

## Hourly solver

| Name | Default | Units |
|---|---|---|
| `stick_after` | 6 iterations, then answers stick at their value closest to zero (was 3, D-054) | — |
| `stick_window` | 3: the lowest of the last 3 iterations (owner) | — |
| `max_iter` | 12 (6 more after sticking), then `SolverError` | — |
| Settled when | \|new − old\| ≤ `abs_tol` + `rel_tol`·\|old\|, 1e-6 + 1e-6 (was 1e-9, D-054) | kW, kg/s |

See [solver.md](solver.md).

## State machine

| Name | Default | Units |
|---|---|---|
| Unlisted IT load | 100 (THEN 0–100) | % of the planned profile |
| Unlisted module | off (each state is a complete description) | — |
| Cooling | free cooling when possible, mechanical when needed (fixed) | — |
| Brine separation heat THEN | 100 (0–100) | % of the data center's heat |
| Power generation run THEN | 100 (0–100) | % of design |
| "Full load" (IT load IF) | the data center's peak IT load | kW |

See [control.md](control.md).

