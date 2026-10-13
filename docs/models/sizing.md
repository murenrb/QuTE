# Sizing Model — Facility Area

Uses **peak** IT load. Code: `core/sizing/datacenter_area.py`. Constants:
[../assumptions.md](../assumptions.md). Transfer functions are hard-coded for
now but must be passed in via config so they can become editable.

Let `P` = peak IT load in kW (`it_load_peak_mw × 1000`).

## Data hall
```
ws_density    = 0.008 × rack_density_kw + 0.1216          # kW/sqft of white space
hall_density  = ws_density × white_space_ratio            # kW/sqft of data hall
A_hall        = P / hall_density                          # sqft
```

## Backup power
```
area_factor   = ups + generator + switchgear              # sqft/kW IT
A_backup      = area_factor × P × X × (1 + 0.1 × Y)       # sqft
```
Each +1 in Y adds 10 % (N+2 → ×1.2).

## Chillers
```
A_chiller = P × (0.4 if cooling_type == "dry" else 0.2)   # sqft
```
One lumped area for the cooling plant: the chillers and their heat
rejection (dry coolers or cooling towers, which also do the free cooling).
Scales on IT load only, not IT + parasitics (owner, D-067). Shown as
"Chillers" in the Data center tab's area breakdown.

## Total
```
A_total = A_hall + A_backup + A_chiller
```
Default footprint: square, side = √A_total (convert to m² for map geometry:
1 sqft = 0.09290304 m²).

## Worked example (use as a unit test)
Defaults, 10 MW IT, dry cooling:

| Quantity | Value |
|---|---|
| ws_density | 0.5216 kW/sqft |
| hall_density | 0.33904 kW/sqft |
| A_hall | 29,495.04 sqft |
| A_backup | 3.0 × 10,000 × 1 × 1.1 = 33,000 sqft |
| A_chiller | 4,000 sqft |
| **A_total** | **66,495.04 sqft** (square side ≈ 257.87 ft) |

## Edge cases
- `white_space_ratio` slider minimum is 10 %; the model still rejects values
  < 0.10 with a clear error (protects loaded/hand-edited files).
