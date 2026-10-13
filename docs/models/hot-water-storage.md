# Hot Water Storage Module (two tank / thermocline)

Code: `core/models/hot_water_storage.py`. Layer 1 is `two_tank_step` (one hour,
scalars), the owner's physics with the fixes below. `initial_state` sets the
starting tanks. Layer 2 is `HotWaterStorage`, a solver node: the hourly
solver threads tank masses and temperatures from hour to hour. Inputs:
`HotWaterStorageParams` (`core/domain/modules.py`), defaults
`HotWaterStorageInputs` in `defaults.py`. UI: Modules tab → Hot water storage.
**Scaled in inputs** (D-041). Decision D-046.

## Coupling (D-054: set by the state)
`HotWaterStorage` is a solver node ([../solver.md](../solver.md)). What it does
each hour is set by the active state's THENs ([../control.md](../control.md)):
- **Receives hot water from the data center:** charges at `T_heat_in` = the
  return (warm) water. It wants as much as the cold tank can take this hour,
  the data center offers its heat in THEN order, and it reports what it took
  (`hws_charge_kwth`). That heat is cooling the data center no longer needs.
- **Sends hot water to power generation / the greenhouse** (D-064): each
  receiver asks; the storage serves them in THEN order, each up to what the
  hot tank still holds (from the charged state), and discharges what they
  used (`hws_discharge_kwth`). They see it at hot tank − pinch (the
  start-of-hour hot tank). Each receiver cools the hot water against its own
  water (`T_in` below): power generation against the supply (cold) water, the
  greenhouse coil to its setpoint + 10 K coil approach. The cooled water goes
  back to the cold tank, whose temperature **floats** with what comes back
  (owner) — e.g. 20 °C greenhouse: 30 + 2 = 32 °C, below a 35 °C supply.
- Both in the same hour (owner): charge first, then discharge.
- IFs: hot water tank level and cold water tank level (% of the water mass;
  with two tanks, cold = 100 − hot).
- Pumps are not modelled (no electrical column).

## Initial state and tank size
- The cold tank starts full of supply-temperature water and the hot tank
  empty. Total mass = tank volume × 992 kg/m³.
- Tank volume is computed **once per run** from the inputs and the data
  center (sizing on peak, rule 4), not inside the hourly loop:
  `V = IT_kW × (1 + parasitic frac) × hours × 3600 / ((T_return − T_supply) × 4.18 × 992)` [m³],
  i.e. hours of the data center's full heat load, IT + parasitics (10 % by default; owner, 2026-10-05)
- Two tank: two tanks of V each. Thermocline: one tank of V.

## One step (Δt = 1 h, mass moved per step)
```
Charging (Q_req > 0, T_in = return):
  T_to_hot = T_in − pinch ;  ΔT = T_to_hot − T_cold
  m = min(Q_req·Δt / (cp·ΔT), m_cold)          (0 if ΔT ≤ 0)
  hot tank: m_hot += m, T_hot = mix ;  cold tank: m_cold −= m
  Q_heat_in = m·cp·ΔT / Δt
  T_sys = T_cold + pinch                       (facility water back from the HX)
Discharging (Q_req < 0, T_in = the receiver's water: supply, or greenhouse setpoint + 10 K):
  T_to_cold = T_in + pinch ;  ΔT = T_hot − T_to_cold
  m = min(−Q_req·Δt / (cp·ΔT), m_hot)          (0 if ΔT ≤ 0)
  cold tank: m_cold += m, T_cold = mix ;  hot tank: m_hot −= m
  Q_heat_in = −m·cp·ΔT / Δt
  T_sys = T_hot − pinch
No heat moved (Q_req = 0, tank empty/full, or ΔT ≤ 0): T_sys = T_in
SOC = m_hot / (m_cold + m_hot)
```
Balances (tested over random cycles): mass conserved; the heat stored equals
the sensible heat of both tanks above the start; |Q_heat_in| ≤ |Q_req|.

**T_sys (owner, 2026-10-05)** is the temperature the facility gets back on
its side of the heat exchanger. Only the storage knows it, because it depends
on the tank temperatures. Downstream processes read it from `hws_t_sys_c`, so
nothing has to switch columns after the storage. The tank temperature used is
the one at the start of the step. Owner's example, indirect: charge off 50 °C
→ hot tank 48 °C; discharge against 40 °C → the cold tank fills at 42 °C and
**the facility sees 46 °C** (not 50 or 48). Direct: T_sys is simply the cold
tank temperature (charging) or the hot tank temperature (discharging).

**Pinch:** direct 0 K, indirect 2 K. It hurts both ways, so its sign flips
with the mode: on the tank side, charging gives T_in − pinch and discharging
T_in + pinch. On the facility side, T_cold + pinch and T_hot − pinch. The pinch is lost at both ends of every
cycle, so the steady usable ΔT = (T_return − T_supply) − 2 × pinch. That is
6 K of 10 K for indirect after the first cycle; the first charge from
supply-temperature water gets 8 K. The tank is sized on the full ΔT, so an
indirect tank holds less than its "hours".

## Changes from the owner's draft (2026-10-05)
Python fixes:
- `@dataclass(hotwater=True)` → `frozen=True`.
- The result dataclass fields now match what is returned.
- `TwoTankParams` didn't exist; it is now `HotWaterStorageParams`.
- `dt_h` was ignored (`HOURLY_DT_H` used instead).
- `Q = 0` left variables unset; now nothing moves.
- Constants moved to `defaults.py`.
- Snake-case names with units.

Physics fixes:
1. **Hot tank volume:** it was `V_cold·ρ_hot/ρ_cold`, which is smaller than
   the cold tank, but warmer water needs *more* volume. The step now tracks
   **mass**, limited by the water left to move (`m_cold` / `m_hot`), so
   densities only enter the sizing.
2. **SOC precedence:** `m_hot / V*ρ` evaluated as `(m_hot/V)·ρ`. SOC is now
   `m_hot / m_total`.
3. **Discharge mixing temperature:** the mixing line used `T_in − pinch`,
   while the flow and Q lines of the same branch used `T_in + pinch`. The
   mixing line now matches them. The pinch sign still flips between charge
   (−) and discharge (+).
4. **No-flow guards:** when the temperatures don't allow heat to flow
   (ΔT ≤ 0), nothing moves instead of a negative flow or divide by zero.
   Mixing into an empty tank takes the inflow temperature.

## Inputs and defaults

| Field | Default | Units |
|---|---|---|
| `enabled` | off | — |
| `storage_hours` | **12** (slider 4–72) | h of IT heat |
| `connection` | Indirect (radio: Direct / Indirect) | pinch 0 / 2 K |
| `tank_type` | Two tank (radio: Two tank / Thermocline) | — |
| `tank_height_m` | 12 (3–30) | m |
| → diameter | √(4V / (π·H)) | m |
| → default block | thermocline: square (D + 2·20 ft); two tank: (2D + 2·20 ft) wide × (D + 2·20 ft) long | — |

Selecting **Thermocline** shows in red: *"Thermocline modeling assumes perfect
stratification, actual performance will require degraded low SOC
performance"*. Switching the tank type resets the block to that type's default
shape, keeping its center and rotation. The user can then reshape it freely,
with the area held.

10 MW IT (11 MW of heat), 40 → 50 °C, 12 h: V = 11,460 m³ per tank, D = 34.9 m (114 ft), two
tank block ≈ 41,500 sqft.

## Columns

| Column | Unit | Plot |
|---|---|---|
| `hws_net_kwth` | kW_th, charge − discharge | — |
| `hws_stack_kwth` | kW_th, charge − discharge to power generation (the greenhouse's share is its own hatched band, D-065) | thermal stack 6 (cyan), negative while power generation discharges it |
| `hws_charge_kwth` | kW_th, heat taken from the data center | — |
| `hws_discharge_kwth` | kW_th, heat given to power generation and the greenhouse | — |
| `hws_soc_frac` | hot mass / total | — |
| `hws_t_hot_c`, `hws_t_cold_c` | °C | — |
| `hws_t_sys_c` | °C, facility water back from the HX | — (for downstream processes) |

Metric: Heat into hot water storage (MWh_th/yr).

## Open points
- No standby heat loss; no flow / heat-exchanger rate limit (the request is
  bounded by the cooling load).
- Power generation sees the start-of-hour hot tank temperature; when it
  charges and discharges in the same hour, the water it gets is the mixed
  (charged) hot tank. The difference is small.
- In an indirect charge the data center water comes back at `hws_t_sys_c` =
  T_cold + pinch (42 °C), not at supply (40 °C). The model doesn't yet use it:
  the chillers' trim of that difference is not separated out.
