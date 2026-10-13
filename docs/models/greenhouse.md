# Greenhouse Module (heating load)

Code: `core/models/greenhouse.py`. Layer 1 is plain numpy (`heat_loss_kwth`,
`solar_gain_kwth`, `greenhouse_load`), one equation per function. Layer 2 has two parts, like solar PV:
`GreenhouseLoad` (a pipeline subsystem before the solver; weather only) writes
the hourly demand, and `GreenhouseHeating` (a solver node) takes heat from the
data center when the state links them. Inputs: `GreenhouseParams`
(`core/domain/modules.py`), defaults `GreenhouseInputs` in `defaults.py`. UI:
Modules tab → Greenhouse. **Scaled in map** (D-041): the drawn area is the
floor area. Decisions D-061, D-062, D-064.

## What it models (owner)
Only the **heating requirement**. Steady state each hour: no thermal mass,
nothing carried from hour to hour. The covering's overall **U-value is an
input** (from an extension guide's table, D-062) between the inside air at
the setpoint and the outside air, plus the sun through the glass. Heat it
needs is asked of the data center's return water; surplus heat is vented (it
goes nowhere).

## Equations (each hour)
```
A_cover  = A_floor · 1.3                              covering area [m²] (roof + walls)
Q_loss   = U · A_cover · (T_set − T_amb)              [kW_th] (< 0 when warmer outside)
Q_solar  = τ · GHI · A_floor                          [kW_th]
Q_net    = Q_loss − Q_solar
demand   = max(Q_net, 0)                              heat to hold the setpoint
vented   = max(−Q_net, 0)                             surplus, vented
```
T_amb is the dry bulb. GHI falls on the house's horizontal footprint, so the
solar term uses the floor area. The guide's U already includes everything
that moves heat through the covering (films, radiation, leaks), so nothing
else is added.

## Inputs and fixed values

| Field | Default | Range / note |
|---|---|---|
| `transmissivity_pct` τ | 90 % | slider 80–100 (owner) |
| `u_w_m2k` U | 7.5 W/m²K | slider 5–10 (owner); link under the slider to the guide |
| `t_set_c` T_set | 20 °C | slider 15–40 (owner) |
| cover / floor area | 1.3 | roof + walls of a gutter-connected house (owner) |
| coil approach | 10 K | water → air heating coil (owner, D-064) |

Typical U-values, [Texas A&M AgriLife — Greenhouse heating
requirements](https://aggie-horticulture.tamu.edu/ornamental/greenhouse-management/greenhouse-heating/),
Table 1 (Btu/h·ft²·°F; × 5.678 = W/m²K): single glass 1.13 (6.4), double
glass 0.65 (3.7), single PE film 1.15 (6.5), double PE 0.70 (4.0),
fiberglass 1.00 (5.7). The owner's default 7.5 W/m²K (1.32 Btu/h·ft²·°F) is
above the guide's single glass.

## Coupling (set by the state, D-054, D-064)
- **THEN "Greenhouse: Takes heat from Data center / Hot water storage"** (links;
  entered at the greenhouse end). The sources are asked in THEN order: the
  first for the hour's demand, the next for what is still open. Each answers
  with what it can give (the data center hands out its heat in THEN order with
  its other heat users; hot water storage up to what its hot tank holds, and
  only if it also has "Sends hot water to Greenhouse"). Heat from the data
  center leaves its own cooling, so free cooling / chillers drop by the same
  amount; heat from storage is a hatched band on top of the thermal stack,
  above the data center's heat (D-065).
- The heat goes through a **water → air coil, 10 K approach** (owner, as the
  other air coils): a source gives heat only if its water is warmer than
  `T_set + 10` (data center: the return water; storage: hot tank − pinch);
  otherwise it is asked for nothing (the panel warns for the data center).
  Storage's hot water leaves the coil at `T_set + 10` and goes back to its
  cold tank (+ HX pinch), which floats colder than the supply water.
- What the sources don't cover is **`greenhouse_unmet_kwth`** (a boiler or
  other backup's job; not modelled).
- **"Greenhouse heating is off"**: it takes nothing; the demand is all unmet.
- **IF "Greenhouse: Heating demand (kW_th)"**: the hour's demand from the
  weather (before any heat is given).
- "Run everything in Default" heats the greenhouse first, before brine
  separation, power generation and hot water storage.

## Columns

| Column | Unit | Meaning |
|---|---|---|
| `greenhouse_loss_kwth` | kW_th | Q_loss through the covering (< 0 when warmer outside than the setpoint) |
| `greenhouse_solar_kwth` | kW_th | Q_solar |
| `greenhouse_demand_kwth` | kW_th | heat needed |
| `greenhouse_vented_kwth` | kW_th | surplus vented |
| `greenhouse_heat_kwth` | kW_th | heat from the data center (thermal stack, order 7) |
| `greenhouse_heat_hws_kwth` | kW_th | heat from hot water storage (thermal stack, hatched, on top; D-065) |
| `greenhouse_unmet_kwth` | kW_th | demand − heat from both sources |

## Worked example and spot check (unit tests)
- A cold night, 1,000 m² floor (1,300 m² covering), U = 7.5, 20 °C inside,
  −10 °C outside, no sun: Q = 7.5 × 1,300 × 30 / 1000 = **292.5 kW_th**.
- **Purdue CEA**, "Calculating greenhouse heating requirements" (owner's spot
  check): Q = U·A·ΔT, U = 0.55 Btu/h·ft²·°F (double polycarbonate), 66.6 °F
  in, 30 °F out → 135,878 Btu/h (A-frame) and 170,860 Btu/h (Quonset). The
  model reproduces both; the surface areas are only in the article's figure
  (an image), so the test uses the areas its results imply (6,750 and 8,488
  ft²), which checks the formula and the units.

## The year (example: Toledo, Ohio, NSRDB TMY)
1 acre, 20 °C, τ = 90 %:

| U | Heating demand | Intensity | Peak |
|---|---|---|---|
| 7.5 W/m²K (default) | 2,641 MWh_th/yr | 207 kBtu/sqft/yr (653 kWh/m²) | 332 W/m² of floor |
| 6.4 W/m²K (single glass, guide) | 2,219 MWh_th/yr | 174 kBtu/sqft/yr (548 kWh/m²) | 283 W/m² of floor |

## Not modelled
Thermal screens, thermal mass of the soil / structure, latent loads (transpiration), ventilation for
humidity or CO2, cooling in summer (surplus is simply vented), fans / pumps
electricity.
