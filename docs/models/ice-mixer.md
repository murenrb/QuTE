# Ice Mixer Module

Code: `core/models/ice_mixer.py` — layer 1 `ice_mixer_step` (one pass of one
hour, scalars; physics written by the owner); layer 2 `IceMixer`, a solver
node ([../solver.md](../solver.md)). Property
helpers: `ice_hf` (`core/domain/ice.py`), `brine_fp`, `brine_c`,
`brine_h_solv` (`core/domain/brine.py`). Inputs: `IceMixerParams`
(`core/domain/modules.py`), defaults `IceMixerInputs` in `defaults.py`.
UI: Modules tab → Ice mixer. **No footprint** (D-050): neither scaled in map
nor in inputs; nothing is drawn on the map.

## Role
Melts ice from ice storage into **water** or **brine** to supply cooling to
the consumers the state links it to (D-054, [../control.md](../control.md)),
in THEN order:

| "Provides cooling to" | Q_request | Effect |
|---|---|---|
| data center | its own mechanical load (never free-coolable heat) | chillers carry the rest |
| power generation | its rejected heat | its cold side at the mixer's temperature |
| brine separation | its condenser heat (after power generation's share) | condenser works against the mixer's temperature |

It needs "ice storage sends ice to the ice mixer" (and on brine "brine
separation sends brine flow to the ice mixer"). The fluid is its module input.
```
consumers ──wants──► IceMixer ──ice call──► IceStorage ──ice supplied──► IceMixer
                              ──brine call──► BrineSeparation ──brine supplied (c at start of hour)──► IceMixer
IceMixer ──offers (THEN order)──► consumers ──used──► IceMixer
IceMixer ──ice / brine used, melt water, diluted brine (automatic returns)──► IceStorage / BrineSeparation
```

## Two passes per hour (the solver)
1. **Pass 1** (`m_ice_in_kg_s = m_brine_in_kg_s = None`): flows are unknown, so
   the mixer assumes the tanks give it what it wants. It returns the cooling it
   would deliver and its flows as **calls** on ice storage / brine separation.
2. **Pass 2** (the physically supplied flows): it recalculates, limited by
   whichever flow is short, and never uses more than the request needs. It
   also takes what the tanks **accepted** of its outputs
   (`m_water_out_max_kg_s`, `m_brine_out_max_kg_s`, D-051): it can't dump melt
   water or diluted brine, so it melts only as much ice as can go somewhere:
   water m_ice ≤ water out max; brine m_brine·c_in/c_mix ≤ brine out max →
   m_brine = max·c_mix/c_in, m_ice = m_brine·r. Nothing binding → the pass
   returns its inputs unchanged.

The **hourly solver** (D-052, D-054) repeats this until the flows settle. Each
iteration the node runs pass 1 on the total of its consumers' wants (its
calls), pass 2 on the supplied flows (what it can deliver), offers that to
its consumers in THEN order (each gets what the ones before it used left),
then runs pass 2 again on what they used, so it melts only that ice and
returns only that melt water / diluted brine. The columns hold the settled
values. The brine it receives is at brine separation's start-of-hour
concentration.

## One pass
**Water** (`fluid = water`): the ice melts at 0 °C.
```
h       = h_f(0) = 330 kJ/kg              (no recup_eta: made, stored, melted at 0 °C)
m_ice   = Q_req / h          (pass 2: min with the ice supplied)
Q       = m_ice · h ;  m_water_out = m_ice (back to the ice storage water tank)
```
**Brine** (`fluid = brine`), c = salt mass fraction:
```
t_mix   = fp(c_in) · mix_eta            # a perfect (impossible) mixer cools at fp(c_in)
c_mix   = c(t_mix)                      # concentration that freezes at t_mix
h       = (h_f(t_mix) + h_solv(c_mix)) · recup_eta   # h_solv < 0: heat generated
r       = c_in / c_mix − 1              # kg ice per kg brine (salt balance)
m_ice   = Q_req / h                     (pass 2: min with the ice supplied)
m_brine = m_ice / r                     (pass 2: if > supplied → m_brine = supplied, m_ice = m_brine·r)
Q       = m_ice · h
m_out   = m_brine · c_in / c_mix  (= m_brine + m_ice),  at c_mix → back to the brine tank
```
If c_mix ≤ 0 or c_mix ≥ c_in (brine too dilute; the two fits don't invert
exactly near c = 0) the pass calls nothing and delivers nothing.

### Salt balance (checked)
Ice carries no salt. Salt: m_brine·c_in = m_out·c_mix. Mass: m_out = m_brine + m_ice.
→ m_brine·(c_in − c_mix) = m_ice·c_mix → m_brine = m_ice / (c_in/c_mix − 1). ✔
Tested every hour in the integration test and on random passes.

### Properties
- h_f(t) = 330 + (cp_w,avg − cp_i,avg)·t, each cp the average of the pure value
  (4.18 / 2.2) and its fit at t: cp_i = 0.0067t + 2.0725,
  cp_w = 0.0016t² + 0.0251t + 4.2441 (Kirchhoff: less latent heat below 0 °C).
- Potassium acetate fp(c) = −137.95c³ − 173.45c² − 11.85c − 0.2351 (0 at c = 0);
  inverse c(t) = −0.000004t³ − 0.000468t² − 0.0211t + 0.01346.
- h_solv(c) = −64·(c/(1 − c))² kJ per kg of ice; negative = solvation heat
  generated, which reduces the cooling (owner, 2026-10-06).

## Inputs and defaults

| Field | Default | Units |
|---|---|---|
| `enabled` | off | — |
| `fluid` | water (radio: water / brine) | — |
| `recup_eta_pct` | 70 (50–90, slider; brine only) | % |
| `mix_eta_pct` | 80 (50–90, slider; brine only; 100 % is impossibly ideal) | % |

Water uses neither, so their sliders show only on brine (owner, D-057).

The brine type is brine separation's (`BrineSeparationParams.brine_type`); the
brine concentration in is its tank's `brine_conc_wt_pct`. Brine requires
brine separation to be on (the run reports an error otherwise).

## Worked example (unit test)
Water: Q_req 1,000 kW → ice call 3.030 kg/s, melt water 3.030 kg/s.
Brine, c_in = 0.30, defaults: t_mix = −23.13 × 0.8 = −18.50 °C, c_mix = 0.269,
h = (289.7 − 8.7) × 0.7 = 196.7 kJ/kg → ice call 5.08 kg/s, brine call
44.1 kg/s, diluted brine out 49.1 kg/s at 26.9 wt%. Ice-limited to 1 kg/s →
196.7 kW, 8.67 kg/s brine.

## Columns

| Column | Unit | Plot |
|---|---|---|
| `ice_mix_q_kwth` | kW_th, cooling used by all its consumers | thermal stack 2 ("Ice mixer") |
| `ice_mix_t_c` | °C | — |
| `ice_mix_ice_kg_s`, `ice_mix_brine_kg_s` | kg/s (used, settled) | — |
| `ice_mix_brine_out_kg_s`, `ice_mix_brine_out_wt_pct` | kg/s, wt% | — |
| `ice_mix_water_out_kg_s` | kg/s | — |

## Open points
- On brine the melt water stays in the brine; "brine separation sends water to
  ice storage" (D-054) returns the recovered water to ice storage's water tank,
  closing the loop.
- **Fit consistency:** c(fp(c)) ≠ c — 0.078 at c = 0.1, 0.190 at 0.2, 0.3006
  at 0.3, 0.369 at 0.4. The brine flow is very sensitive to c_mix
  (r = c_in/c_mix − 1), so consider inverting `brine_fp` numerically instead
  of a separate fit. Owner (2026-10-06): fine for now; the 90 % slider cap
  keeps away from the worst of it.
