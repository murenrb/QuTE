# Ice Storage Module

Code: `core/models/ice_storage.py` — layer 1 `ice_step` (one hour, scalars;
physics written by the owner), helpers `ice_maker_cop`,
`ice_maker_capacity_factor`; layer 2 `IceStorage`, a solver node (the
hourly solver threads both tanks' state hour to hour, docs/solver.md). Inputs: `IceStorageParams`
(`core/domain/modules.py`), defaults `IceStorageInputs` in `defaults.py`.
UI: Modules tab → Add module → Ice storage. **Scaled in
inputs** (D-041): a block on the map with area = tank capacity / energy density.

## Coupling (D-049, replaces D-037's ice → chiller hand-off)
Ice storage no longer serves the data center's mechanical demand directly. It
has an **ice tank** and a **water tank** (same size, both in kWh_th of ice) so
other modules can **request ice** and **return water** as mass flows:
```
<consumer> ─► ice request [kg/s] ─► IceStorage ─► ice_supplied_kg_s ─► <consumer>
<producer> ─► water in   [kg/s] ─►            ─► ice_water_in_kg_s (accepted)
```
`IceStorage(params)` is a solver node ([../solver.md](../solver.md)). It
answers the mixer's wants (`ice_call_kg_s` → `ice_supplied_kg_s`,
`melt_water_kg_s` → `melt_water_accepted_kg_s`; None until asked) and
balances its tanks on what the mixer actually used (`ice_used_kg_s`,
`melt_water_used_kg_s`). Ice maker electricity is its own stacked electrical
column, so net grid load includes it.

**Control (D-054, [../control.md](../control.md)):** the state's THENs ("ice
maker" in the owner's write-up):
- **Ice maker cleared to run:** the maker runs (as far as the tanks allow).
- **Sends ice to the ice mixer:** the tank answers the mixer's calls; its melt
  water comes back automatically.
- **Receives water from brine separation:** the recovered water fills the water
  tank after the melt water, as far as it fits (the rest drains).
- **Ice maker is off:** nothing moves; the tanks keep their contents.
- IFs: ice tank level, ice maker water tank level (%).

Cleared with nothing asking for ice, the ice tank fills from the water tank,
then idles.

## One step (Δt = 1 h)
State `IceTankState(soc_ice, soc_water)`, passed in as `start` and used as `s`
(same pattern as hot water storage / brine). Flows become duties with the
latent heat h_f = 330 kJ/kg (`ICE_LATENT_HEAT_KJ_KG`): Q = ṁ · h_f.
Fits are of t = heat-rejection ambient (`t_ambient_rej_c`: dry bulb for dry
cooling, wet bulb for evaporative), capped at their value at minimum compressor
discharge pressure:
```
COP_im      = min(cop_max,             a_cop·t² + b_cop·t + c_cop)
cap_factor  = clamp(a_cap·t² + b_cap·t + c_cap, 0, capacity_factor_max)
P_maker     = size_TR × 3.516853                      # kW_th nameplate
E_tank      = P_maker × tank_charge_time_h            # kWh_th, each tank
Q_req       = ṁ_ice_req · h_f ;  Q_w,offered = ṁ_water_in · h_f

if cleared_to_run:
    duty    = min(P_maker × cap_factor,
                  (1 − s.soc_ice)·E_tank/Δt + Q_req,         # room for ice
                  s.soc_water·E_tank/Δt + Q_w,offered)       # water to freeze
    P_elec  = duty / COP_im
else:
    duty = P_elec = 0
Q_w,in      = min(Q_w,offered, (1 − s.soc_water)·E_tank/Δt + duty)   # accepted water
soc_water₁  = (s.soc_water·E_tank + (Q_w,in − duty)·Δt) / E_tank
Q_ice       = min(s.soc_ice·E_tank/Δt + duty, Q_req)                # ice supplied
soc_ice₁    = (s.soc_ice·E_tank + (duty − Q_ice)·Δt) / E_tank
Q_instant   = min(duty, Q_ice)                        # made and taken this hour (used first)
Q_discharge = Q_ice − Q_instant                       # taken from storage
Q_charge    = duty − Q_instant                        # into the ice tank
Q_missed    = Q_req − Q_ice                           # requested, not supplied
ṁ_ice_supplied = Q_ice / h_f ; ṁ_ice_instant = Q_instant / h_f ; ṁ_water_in = Q_w,in / h_f
```
Accepted flows that no min limited are returned exactly as given (no
kg/s → kW → kg/s round-off), so a solver sees them as unchanged (D-051).
No iteration is needed for the water tank: if the duty was water-limited the
tank ends empty and all offered water is accepted; otherwise the duty doesn't
depend on how much water is accepted.

Balances (tested): ice tank `soc_ice₁·E = soc_ice₀·E + Q_charge − Q_discharge`;
water tank `soc_water₁·E = soc_water₀·E + Q_w,in − duty`;
`Q_instant + Q_discharge + Q_missed = Q_req`; all flows ≥ 0; both SOCs in 0..1.

Changes from the owner's draft (2026-10-06): Q_req = ṁ·h_f (draft divided);
the water tank balance subtracts the water frozen and the accepted water has a
closed form (replaces the `while` loop, where `m_dot_water_in_accepted` was
undefined when the tank didn't overflow); h_f moved to `defaults.py`.
`ice_hf(t_melt)` moved to `core/domain/ice.py` (used by the ice mixer).
Earlier changes (2026-10-01): duty `max` → `min`; `Q_instant = min(duty,
Q_ice)`; capacity factor clamped at 0; TR conversion 3.516853.

## Inputs and defaults

| Field | Default | Units |
|---|---|---|
| `enabled` | off | — |
| `ice_maker_size_tr` | **None = 65 TR per MW of IT load** (10–200,000, log slider) | TR |
| `tank_charge_time_h` | **24** (6–72, slider) | h of nameplate |
| `soc_start_frac` | 0.0 (0–1) | ice tank fraction, hour 0 (D-058) |
| `water_soc_start_frac` | 1.0 (0–1) | water tank fraction, hour 0 |
| h_f (`ICE_LATENT_HEAT_KJ_KG`) | 330 | kJ/kg |
| `energy_density_kwh_sqft` | 15 (1–100) | kWh_th per sqft of footprint |
| → footprint area | tank kWh_th / density (234.5 sqft with defaults) | sqft |
| `cop_max` | 6.0 | — |
| `capacity_factor_max` | 1.23 | — |
| COP fit a, b, c | 0.0011, −0.1503, 6.562 | — |
| Capacity fit a, b, c | −0.001, −0.0023, 1.2453 | — |

Defaults changed 2026-10-05 (D-042); project schema v3 migrates the old ones
(1,000 TR → follow the IT load; tanks under 6 h → 24 h). The size is filled in
per run by `IceStorageParams.resolved(ModuleContext(it_peak_mw=…))`.

## Worked example (unit test, owner's first case: 1,000 TR, 1 h tank)
t = 20 °C, 5,000 kW of ice requested (15.15 kg/s), soc_ice 0.1, water tank
full: COP 3.996, capacity factor 0.7993, P_maker 3,516.85 kW, duty 2,811.0 kW
(machine-limited), P_elec 703.5 kW, Q_instant 2,811.0, Q_discharge 351.7
(whole tank), Q_charge 0, Q_missed 1,837.3, ṁ_ice_supplied 9.58 kg/s,
soc_ice₁ = 0, soc_water₁ = 0.2007.

## Columns

| Column | Unit | Plot |
|---|---|---|
| `ice_instant_kwth` | kW_th | — (FYI; the mixer's cooling is what the DC sees, D-050) |
| `ice_discharge_kwth` | kW_th | — (FYI) |
| `ice_charge_kwth` | kW_th | — |
| `ice_soc_frac`, `ice_water_soc_frac` | — | — |
| `ice_supplied_kg_s`, `ice_water_in_kg_s` | kg/s | — |
| `ice_maker_elec_kw` | kW_e | electrical stack 5 |

Metrics: Annual cooling from ice (MWh_th), Annual ice maker electricity (MWh).

## Open points
- The capacity fit reaches 0 at ≈ 34.2 °C ambient (no ice making above it) —
  confirm the fit.
- Ice-maker heat rejection and tank losses are not modelled yet.
