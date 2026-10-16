# Utility Cost

Code: `core/domain/utility.py` (`UtilityTariff`, `RateCategory`), `core/models/utility.py`
(layer 1 `rate_tables`, `hourly_rates`, `monthly_peak_only`; layer 2 `UtilityCost`).
UI: Utility tab (between Data center and Modules) — the tariff painter
(`app/components/tariff_editor/`) and "Weekend energy prices". Decision D-043.

## Tariff
- **Rate categories**: name, energy price ($/kWh), demand charge ($/kW).
  Defaults: Off peak $0.10/kWh + $10/kW, Shoulder $0.15 + $10, Peak $0.20 + $10.
  "+ Add rate" adds "New rate" $0.12 + $10; any rate can be renamed, repriced
  or deleted (at least one stays; a deleted rate's cells go to the cheapest
  remaining rate).
- **Ranking / colour**: total value = energy × 100 + demand. Each swatch sits
  linearly between the cheapest (bright blue) and the dearest (bright red)
  through purple (D-072). "Cheapest" = lowest total value.
- **Schedule**: 12 × 24 table, month of year × hour of day, each cell a rate
  category. Default: all off peak. Paint by clicking a swatch, then clicking or
  dragging over cells (or a month / hour heading for a whole row / column).
- **Weekend energy prices**: *Follow schedule* (weekends like weekdays) or
  *Off peak* (every weekend hour uses the cheapest rate). Weekends are
  Saturday/Sunday of the reference year 2025 (the typical year has no real
  calendar).

## Hourly calculation (every hour h of the frame)
```
price_h, charge_h   = rate of schedule[month_h][hour_h]   (cheapest rate on weekends if Off peak)
energy_cost_h       = price_h × grid_net_kw_h × 1 h        # negative when exporting = credit
potential_demand_h  = max(grid_net_kw_h, 0) × charge_h
demand_cost_h       = potential_demand_h  if h is the month's highest potential (first on ties)
                    = 0                    otherwise
utility_cost_h      = energy_cost_h + demand_cost_h
```
Billed load is the **net grid load** (`grid_net_kw`): data center, parasitics,
cooling and every module's load or generation — so any module that generates
(PV now, others later) reduces the bill, and net exports are credited at the
energy price. Because the demand charge can vary by hour, the billed hour is
the one with the highest *charge × load*, not necessarily the highest load.

## Columns

| Column | Unit | Plot |
|---|---|---|
| `energy_price_usd_kwh` | $/kWh | — |
| `demand_charge_usd_kw` | $/kW | — |
| `energy_cost_usd` | $ per hour | — |
| `demand_cost_potential_usd` | $ per hour | — |
| `demand_cost_usd` | $ (one hour per month) | — |
| `utility_cost_usd` | $ per hour | — |
| `cum_energy_cost_usd` | $, running sum of `energy_cost_usd` | Utility subplot, blue line |
| `cum_demand_cost_usd` | $, running sum of `demand_cost_usd` | Utility subplot, orange line (steps monthly) |
| `cum_utility_cost_usd` | $, running sum of `utility_cost_usd` | Utility subplot, black line |

Metrics: Annual utility cost, Annual energy cost, Annual demand charges,
Average utility cost ($ per MWh of imported energy).

## Checks (unit tests)
- 10 MW constant, defaults: energy $8,760,000/yr, demand 12 × $100,000 =
  $1,200,000/yr, exactly one billed hour per month.
- A $40/kW hour at 1,000 kW beats a $10/kW hour at 2,000 kW.
- Exports credited; exports set no demand.
