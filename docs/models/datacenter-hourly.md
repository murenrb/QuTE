# Hourly Data Center Model

Linear model evaluated for each of 8760 hours. Uses the **hourly** IT column.
Code: `core/models/datacenter.py`. The weather-only parts (`CoolantTemperature`:
§1 and the COP in §5) are a vectorized pipeline `Subsystem`. The rest is the
`DataCenterNode` in the hourly solver (D-054, [../solver.md](../solver.md)):
the state decides which modules take its heat, so the cooling split must be
settled together with them each hour. Constants:
[../assumptions.md](../assumptions.md).

Inputs per hour: `it_load_kw` (the actual IT load: planned profile × the
state machine's IT load THEN, D-053), `tdb_c`, `twb_c`, plus type/assumption params.

## 1. Rejection ambient and coolant temperature (`CoolantTemperature`)
```
t_amb = tdb_c if cooling_type == "dry" else twb_c          -> t_ambient_rej_c
t_coolant_c = clip(t_amb + t_approach, t_supply_min, t_supply)   if free cooling
            = t_supply (setpoint)                                otherwise
```
The cold supply water floats with the weather in free cooling (D-047). Modules
that reject into the cooling loop (power generation's cold side, the brine
condenser) use `t_coolant_c`. Chillers and the ice maker reject to the air
and keep using `t_ambient_rej_c`. This subsystem needs only weather, so
modules in front of the data center model (brine separation) can read it.

## 2. IT parasitics
```
it_parasitic_kw = it_parasitic_frac × it_load_kw           # 10 %
```

## 3. Heat and who takes it (D-054)
```
cooling_total_kwth = it_load_kw + it_parasitic_kw          # all of it must go somewhere
```
The modules the state links to the data center's heat (brine separation, power
generation, hot water storage) are served in **THEN order**: each is offered
min(what it wants, what the ones before it used left, its % of the heat if the
THEN gives one) and reports what it used. `heat_offtake_kwth` = the sum used.
What is left is the data center's own cooling load.

## 4. Free vs. mechanical split (all-or-nothing per hour)
Free cooling must be able to deliver **supply** water temperature without a
temperature cross: `t_amb + t_approach_c < t_supply_c` (D-003).
```
load = heat left + heat modules rejected into the supply coolant
if t_amb + t_approach_c < t_supply_c:    # free cooling possible
    cooling_free_kwth = load ; cooling_mech_kwth = 0
else:
    cooling_mech_kwth = load ; cooling_free_kwth = 0
```
With defaults (supply 40 °C, approach 10 °C) the mechanical cutoff is 30 °C ambient.
The split is intentionally binary — no partial economizer trim (D-009). Heat
modules reject into the supply coolant (power generation's cold side, brine
separation's condenser) is part of the load (D-054).

## 5. Mechanical COP (% of Carnot)
```
T_cold = t_supply_c − t_pinch_c + 273.15            # K  coldest point: evaporator below supply (D-007)
T_hot  = t_amb + t_cond_approach_c + 273.15          # K  condenser above ambient (D-008)
         # t_cond_approach_c = 10 (dry) / 5 (evaporative)
cop_carnot = T_cold / (T_hot − T_cold)
cop_mech   = clamp(carnot_fraction × cop_carnot, 0, cop_max)   # carnot_fraction = 0.40
```
When `T_hot ≤ T_cold` the Carnot COP is infinite/negative → set to `cop_max`.
With defaults (dry): T_cold = 35 °C; at the 30 °C mechanical cutoff T_hot = 40 °C →
COP 24.7 → clamped to 10. COP drops below 10 at ambient ≈ 37.3 °C; at 40 °C
ambient COP = 0.4 × 308.15 / 15 = 8.22.
Computed for every hour (column `cop_mech`) even when mechanical load is 0.

## 6. Chillers and the ice mixer (D-054)
`cooling_mech_kwth` is the heat needing mechanical cooling. When the state has
the ice mixer cool the data center, it asks the mixer for its **own** share
(the heat left in §3, in mechanical hours; never free-coolable heat) and the
chillers carry the rest:
```
cooling_chiller_kwth = cooling_mech_kwth − ice mixer cooling to the data center
```

## 7. Cooling electrical load
```
cop_free = 50 if dry else 100
cooling_elec_kw = cooling_chiller_kwth / cop_mech + cooling_free_kwth / cop_free
```
`cooling_free_kwth` already includes the modules' coolant rejection in
free-cooling hours. Guard against `cop_mech == 0`.

## 8. Net grid load
```
grid_net_kw = it_load_kw + it_parasitic_kw + cooling_elec_kw + module loads − generation
```
Implemented by `GridBalance` (`core/models/grid.py`), which sums **every stacked
electrical column in the registry** — new loads/generation are picked up
automatically. The `GridDraw` solver node sums the same terms hour by hour so
the state machine can test the previous hour's draw. The full site run is
`core/models/site_model.py::run_site_model`.

## Invariants (tested every run)
- Thermal stack (D-054): `cooling_free_kwth + cooling_chiller_kwth + ice_mix_q_kwth + power_gen_power_kwth + hws_stack_kwth + greenhouse_heat_kwth == cooling_total_kwth` (D-065; hatched bands such as `greenhouse_heat_hws_kwth` sit on top, outside this sum) (to the solver tolerance)
- `cooling_total_kwth == 1.1 × it_load_kw`
- No modules: `cooling_mech_kwth + cooling_free_kwth == cooling_total_kwth`, `cooling_chiller_kwth == cooling_mech_kwth`
- Exactly one of mech/free is non-zero per hour (no modules)
- `cooling_elec_kw == chillers / cop_mech + free / cop_free`
- `0 ≤ cop_mech ≤ cop_max`, no NaN/inf anywhere
- `grid_net_kw == sum of electrical stack`
- 8760 rows
