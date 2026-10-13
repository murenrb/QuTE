# Power Generation Module (transcritical CO2)

Code: `core/models/power_generation.py`: layer 1 `power_generation`
(vectorized, one source) and `cycle_hour` (one hour, several sources), helpers
`carnot_efficiency`, `design_heat_kwth`; layer 2 `PowerGeneration`, a solver
node ([../solver.md](../solver.md)). Inputs:
`PowerGenerationParams` (`core/domain/modules.py`), defaults
`PowerGenerationInputs` in `defaults.py`. UI: Modules tab → Add module → Power generation. **Scaled in inputs** (D-041): a block on
the map with area = rated MWe × power density. Decisions D-045, D-054.

## What it runs on (the state's THENs, D-054)
- **Runs at [x] % of design** (default 100): heat in ≤ x % × Q_design and
  power ≤ x % × rated.
- **Accepts heat from** (in THEN order), each source at its own hot side:

  | Source | T_hot |
  |---|---|
  | data center return water | `t_return_c` |
  | hot water storage | hot tank (start of hour) − HWS pinch |
  | brine separation condenser steam | condensing temperature − condenser pinch |

  It asks each source for what the caps leave after the sources before it
  (power-limited sources ask less heat), takes what the source can give, and
  reports what it used.
- **Accepts cooling from** (cold side; the first listed is used):

  | Cold side | T_cold | Where the rejected heat goes |
  |---|---|---|
  | supply coolant | `t_coolant_c` | joins the data center's cooling: free cooling when possible, **the chillers otherwise** |
  | ice mixer | the mixer's temperature (0 °C on water, fp(c)·mix_eta on brine) | the mixer; the cycle takes no more heat than the mixer can carry away |

- No heat source or no cold side: it doesn't run (the editor warns). There is
  no free-cooling-hours rule any more (owner: no rules in the background), so
  a state that runs it on the supply coolant in hot hours loads the chillers
  with its rejected heat.
- Heat in = power + rejected. The power is negative on the electrical plot and
  is the thermal stack's "Converted to power" band, so the stack still totals
  the data center's heat.

## Hourly calculation
```
T_hot,i   = source i's hot side (table above); T_cold = the cold side
η_i       = %Carnot × (1 − T_cold / T_hot,i)               (kelvin; 0 if T_cold ≥ T_hot)
η_design  = η at T_hot = t_return_c, T_cold = max cold-side temperature
Q_design  = rated / η_design                                 (heat input the plant is sized for)
caps      heat ≤ run % × Q_design,  power ≤ run % × rated,  rejected ≤ ice mixer's cooling (ice cold side)
Q_i       = min(source i's heat, heat cap left, power cap left / η_i, reject cap left / (1 − η_i))
              colder than design → power-limited: rated output from less heat
              warmer than design → heat-limited: Q_design in, below rated output
P         = Σ η_i × Q_i ;   rejected = Σ Q_i − P
```
If the max cold-side temperature is not below the hot water, there is no
cycle (zero output).

**Example (defaults, 10 MW IT, dry cooling):** rated 200 kWe; η_design =
0.30 × (1 − 283.15/323.15) = 3.71 %; Q_design = 5,386 kW_th. At 0 °C ambient
(cold side 10 °C) it makes 200 kWe from 5,386 kW_th and rejects 5,186. At 15 °C
ambient (cold side 25 °C), η = 2.32 %: 125 kWe from 5,386 kW_th.

## Inputs and defaults

| Field | Default | Units |
|---|---|---|
| `enabled` | off | — |
| `carnot_pct` | 30 (10–50, slider) | % of Carnot |
| `rated_pct_of_it` | **2 % of the IT load peak** (slider 0.5–150, D-063; the MWe it gives is shown in grey under it) | % of IT load → kWe at the max cold-side temp (`rated_kw`, derived, not saved) |
| `t_cold_max_c` | 10 (slider 0 → free-cooling cutoff, `t_supply − t_approach`) | °C, cold side |
| `power_density_sqft_mwe` | 2,000 (1,000–3,000, slider) | sqft per MWe rated |
| → footprint area | rated MWe × density (400 sqft with defaults) | sqft |

## Columns

| Column | Unit | Plot |
|---|---|---|
| `power_gen_power_kwth` | kW_th converted to power (= generation) | thermal stack 5 (brown) |
| `power_gen_reject_kwth` | kW_th, to its cold side | — (in free cooling / chillers / ice mixer) |
| `power_gen_heat_in_kwth` | kW_th, all sources | — |
| `power_gen_eff` | — (power / heat in; 0 when off) | — |
| `power_gen_kw` | kW_e, **negative** | electrical, below zero (brown) |

Metrics: Annual power generation (MWh/yr), Power generation hours.

## Confirmed by the owner (2026-10-05, D-045)
- Heat input capped at Q_design above the design cold-side temperature.
- T_hot is the hot water temperature itself (no hot-side pinch); the
  % of Carnot absorbs the heat-exchanger losses.
- The max cold-side slider stops at the free-cooling cutoff, an *ambient*
  value (30 °C), although the cold side is ambient + approach.

## Open points
- Proposed (D-054), to confirm: several sources each at their own Carnot
  efficiency under one cap; condenser steam at T_sat − condenser pinch; heat
  rejected into the supply coolant loads the chillers outside free-cooling
  hours.
- It does not use the chillers' condenser heat.
