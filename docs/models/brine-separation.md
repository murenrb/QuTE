# Brine Separation Module (single-stage evaporator)

Code:
- `core/models/brine_separation.py`: layer 1 `brine_sep_step` (one hour,
  scalars), the owner's math with the fixes below; layer 2 `BrineSeparation`,
  a solver node ([../solver.md](../solver.md)) — the solver threads brine
  mass and concentration hour to hour.
- Property fits: `core/domain/brine.py` (`water_activity`, `rho_brine`,
  `vapor_sat_temp`, `brine_fp`, `brine_c`, `brine_h_solv`).
- Inputs: `BrineSeparationParams`; defaults `BrineSeparationInputs` and
  `BRINES` in `defaults.py`.
- UI: Modules tab → Brine separation.

**Scaled in inputs** (D-041). Decision D-048.

## What it does
Data center hot (return) water boils pure water out of a brine through a heat
exchanger, so the brine is at T_return − boiler pinch. The vapor condenses at
the saturation temperature of pure water at the brine's vapor pressure, and
the condenser is cooled by the floating coolant (D-047). It runs when:
```
T_coolant + condenser pinch < T_sat(T_return − boiler pinch, a_w(c))
```
As the brine concentrates, a_w falls, T_sat falls, and it gets harder to run.
There are no internal temperature changes (owner): the boiler heat equals the
condenser rejection. The water inventory is condenser limited, so it does not
discharge more in cold weather (later).

## Coupling (D-054: set by the state)
A solver node ([../solver.md](../solver.md)); the active state's THENs
([../control.md](../control.md)) decide what it exchanges:
- **Accepts [x] % of heat from the data center:** it wants as much as the brine
  can take this hour (until c_high, while the temperature stack works); the
  data center offers min(that, x % of its heat, what modules before it in THEN
  order left). Its boiler heat is `brine_heat_kwth` (a line on the thermal
  plot, since it passes the heat on).
- **Condenser:**
  - Rejects into the **supply coolant** at `t_coolant_c`, and that heat joins
    the data center's cooling (free cooling when possible, the chillers
    otherwise).
  - Or, when the state has the **ice mixer** cool brine separation, it works
    against the mixer's temperature (so it can run in hot weather and to
    higher concentrations) and rejects no more than the mixer can take.
  - **Power generation** may take condenser heat as its hot side first, at
    T_sat − condenser pinch.
- **Sends brine flow to the ice mixer:** supplies concentrated brine at the
  start-of-hour concentration and takes the diluted brine back (automatic) as
  far as it fits; the solver settles both with the mixer each hour. Taking
  diluted brine back lowers c, so it can concentrate again — the brine loop
  regenerates.
- **Sends water to ice storage / the drain:** the recovered water refills ice
  storage's water tank after the mixer's melt water, as far as it fits; the
  rest drains (`brine_water_to_ice_kg_s`).
- IF: brine concentration (wt%).

## Sizing (computed once per run, owner's method with a salt balance)
```
heat_kW  = IT_kW × (1 + parasitic frac)                  (11 MW for 10 MW IT)
W        = heat_kW × hours × 3600 / h_vap                 water to remove [kg]
m_dis    = W × c_high / (c_high − c_low)                  brine at the low concentration [kg]
V_tank   = m_dis / ρ(c_low)                               the dilute state is the largest volume
D        = √(4·V / (π·12 m)) ;  block = square (D + 2·20 ft) per side
```
10 MW IT, 20 → 40 wt%, 24 h: W = 399 t, brine 798 t, V = 719 m³,
D = 8.7 m, block ≈ 4,700 sqft. It starts full at c_low.

## One step (Δt = 1 h)
```
runs     = Q_req > 0 and T_coolant + pinch_cond < T_sat(T_in − pinch_boil, a_w(c₀))
water    = Q_req·Δt / h_vap                     (0 if not running)
salt     = m₀·c₀ + in·c_in − out·c₀ ;  m_flows = m₀ + in − out
water    = min(water, m_flows − salt / c_high)  (stop at the high concentration)
m₁ = m_flows − water ;  c₁ = salt / m₁ ;  Q_accepted = water·h_vap / Δt
```
Accepted flows (D-051, replaces "no brine in / out if it would overflow"):
```
out = min(out_req, m₀/Δt)                       (can't supply more than the tank holds)
in  = min(in_offered, most that keeps m₁/ρ(c₁) ≤ V_tank)   (bisection; volume rises with in)
→ recalculate the step with (in, out); both are returned (m_brine_in_kg_s, m_brine_out_kg_s)
```
Brine out leaves at the start concentration c₀.

## Changes from the owner's draft (2026-10-05)
Python fixes:
- The file was renamed `brine_separaiton.py` → `brine_separation.py`.
- Hot-water-storage leftovers removed: docstring, `soc` / `t_sys` result
  fields, imports.
- `s.c` → `s.c_brine`; `m_brine_in` → `m_brine_in_req`.
- Brine in/out are rates in kg/s and are multiplied by Δt.
- `m_brine_in_req**c_brine_in` → `*`.
- The function now returns its result.
- Constants moved to `defaults.py`: h_vap, pinches, Antoine B and C, fits.
- Property fits moved to `core/domain/brine.py`, because both the sizing and
  the hourly model need them.

Physics fixes (owner-approved):
1. **Water activity is a cubic:** a·c³ + b·c² + d·c + e. As written (c², c,
   c) it gave a_w = 0.53 at 20 wt% and went negative near 70 wt%.
2. **Tank sizing by salt balance:** the line-82 equation gave a negative
   volume.
3. **Stops at the high concentration** within the hour; before, it could
   concentrate on toward a_w ≤ 0.
4. **The condenser coolant is the floating supply water `t_coolant_c`**
   (D-047), not a constant.

## Inputs and defaults

| Field | Default | Units |
|---|---|---|
| `enabled` | off | — |
| `brine_type` | Potassium acetate (dropdown, the only option) | — |
| `conc_low_wt_pct` / `conc_high_wt_pct` | **20 / 40** (two-sided slider 0–50; low > 0, high > low) | wt% |
| `concentrate_hours` | **24** (slider 6–72) | h of full data center heat |
| h_vap | 2,382 (water at 50 °C) | kJ/kg |
| Boiler / condenser pinch | 2 / 2 | K |
| Tank height, block buffer | 12 m, 20 ft each side | — |
| KAc a_w fit | 1.6292, −2.678, −0.0096, 0.9979 | a·c³ + b·c² + d·c + e |
| KAc density fit | 642.08·c + 980.82 | kg/m³ |
| Antoine (water) | B 1730.63, C 233.426 | °C, mmHg, 1–100 °C |

## Columns

| Column | Unit | Plot |
|---|---|---|
| `brine_heat_kwth` | kW_th, boiler heat (= condenser rejection) | thermal plot line (plum) |
| `brine_mass_kg` | kg in the tank | — |
| `brine_conc_wt_pct` | wt% | module output (concentration) |
| `brine_soc_frac` | brine volume / tank volume (state of charge) | module output (SOC) |
| `brine_water_to_ice_kg_s` | kg/s, recovered water taken by ice storage | — |
| `brine_water_out_kg_h` | kg/h of condensed water | — |
| `brine_out_kg_s`, `brine_in_kg_s` | kg/s to / back from the ice mixer (D-052) | — |

Metrics: Heat into brine separation (MWh_th/yr), Water recovered from brine
(gal/yr), Final brine concentration (wt%).

## Open points
- With 24 h sizing and full heat it concentrates in the first operating day,
  then stops unless the ice mixer (on brine) dilutes it again.
- Route the condensed water to ice storage's water tank (see ice-mixer.md).
- No sensible heating of the brine, boiling-point elevation losses beyond a_w,
  or heat of dilution; one fixed h_vap.
- The run check uses the concentration at the start of the hour.
