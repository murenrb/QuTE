# Hourly Module Solver

Code: `core/timeseries/solver.py` (`HourlySolver`, `HourlyNode`, `StreamSpec`,
`NodeStep`, `ColumnStream`, `SolverError`); stream names in
`core/timeseries/streams.py`; wiring in `coupled_nodes()`
(`core/models/site_model.py`); settings `SolverSettings` in `defaults.py`
(D-052, D-054).

## Why
Modules that exchange flows *within an hour* can't run one after another for
the whole year. Since D-054 the hour's state decides who exchanges what with
whom (its link THENs, [control.md](control.md)), so the loops are whatever
the user builds, e.g.:

```
data center ──heat (THEN order)──► greenhouse / brine separation / power generation / hot water storage
brine separation condenser ──heat──► power generation ──rejected heat──► ice mixer
ice mixer ──cooling (THEN order)──► data center / power generation / brine separation condenser
ice storage ──ice──► ice mixer ──melt water──► ice storage
brine separation ──brine──► ice mixer ──diluted brine──► brine separation
hot water storage ──hot water──► power generation
```

## Nodes
The data center and every enabled module are **nodes** (their layer 2), in
this order each hour:

| Node | What it does in the hour |
|---|---|
| `DataCenterNode` | IT load (planned × THEN); hands its heat to linked modules in THEN order; cools the rest plus modules' coolant rejection (free / chillers, minus the ice mixer's share); cooling electricity |
| `BrineSeparation` | heat from the data center; condenser to power generation, the ice mixer or the coolant; brine with the ice mixer; recovered water to ice storage |
| `HotWaterStorage` | charges from the data center, discharges to power generation |
| `IceMixer` | cools its consumers in THEN order with ice (and brine) |
| `PowerGeneration` | heat sources in THEN order; cold side coolant or ice mixer |
| `IceStorage` | ice to the mixer; melt water and recovered water in |
| `GreenhouseHeating` | asks the data center for the hour's heating demand (when linked and the return water is warm enough); the rest is unmet |
| `PvOutput` | PV generation when the state says so |
| `GridDraw` | sums the electrical streams; keeps the draw for the next hour's IF |

A node's `step(data, state, h, flows, plan)` returns a `NodeStep(end, flows,
columns)` and changes nothing; the solver commits the last step of each node
when the hour settles. Columns are read once per run (`prepare`), stream
values per step. `None` means "not written yet": a request nobody made gets no
answer (None), and a module treats an unanswered request as "I get what I
ask for" (pass 1).

## Links: want → answer → used (D-054)
Every exchange has three streams:

| Stream | Written by | Meaning |
|---|---|---|
| **want** (`heat_req`, `cool_req`, ice / brine call, melt water, brine return) | receiver | what it would take, **never limited by an answer it depends on** |
| **answer** (`heat_sent`, `cool_sent`, supplied, accepted) | sender | what it can give of the want (≤ want). **Sticky.** |
| **used** (`heat_used`, `cool_used`, ice / brine / melt / return used) | receiver | what it actually took (≤ answer), after its other limits |

The sender balances its own state on **used**, so every kW and kg is counted
exactly once, even when a receiver takes less than it was offered (e.g. power
generation limited by the ice it gets for its cold side). Wants are never cut
by answers because that ratchets flows down: once a want shrinks to what was
offered, it can't rise again when supply frees up later in the hour's
iterations. Where several receivers share a sender (the data center's heat,
the ice mixer's cooling), the sender serves them in THEN order, each getting
what the ones before it **used** left.

**Node contract:** an answer never exceeds the want it answers; every node
applies its own physical limits (min()s), so no tank can overfill or run
below empty in any iteration; when no limit binds it gives its input back
exactly (D-051).

## Each hour
1. The state machine picks the hour's state and its `Plan` ([control.md](control.md)).
2. Run the nodes in order. Each reads the latest streams. A node whose inputs
   didn't change since its last run isn't re-run.
3. Repeat until no stream changes: |new − old| ≤ 1e-6 + 1e-6·|old| (kW, kg/s).
4. **Sticky rule** (owner, D-052; numbers D-054): if not settled after **6**
   iterations, each *answer* stream is capped at its value closest to zero over
   the last **3** iterations. The cap applies to the answer as the other
   modules read it: they use no more than the cap and report what they used,
   and the sender balances on that, so the balances still close. Wants and
   used flows are never capped. Flows that can go either way (`signed`) are
   capped by magnitude, toward zero.
5. Up to **12** iterations; if still not settled → `SolverError` naming the
   hour and the streams still moving (shown as a model error in the app).
6. Commit: each node's end state starts the next hour; its columns are written.

**Why 6 and 1e-6 (D-054, were 3 and 1e-9).** Each iteration carries
information one link along a chain, and states now build chains up to about
six links long (data center → brine separation → ice mixer → power generation
→ ice mixer → ice storage). Some loops are real couplings that contract
geometrically: brine separation's heat sets how much brine its tank can take
back, which sets how much the mixer can cool its condenser, which sets the
heat (about 50× closer each iteration). At 1e-9 those needed about 11
iterations; at 1e-6 (1 W, 1 g/s) they need at most 9. Sticking at 3 capped
flows that were still converging, and that is what made them oscillate.

Why sticking low converges: every limit is a min(), so more supply never means
less use. An oscillation needs a link where less flow brings more flow (a tank
fed by its own return); capping the answer at its lowest breaks it. Sticking
low may settle lower than necessary, which is conservative.

## In the pipeline
`HourlySolver` is one pipeline Subsystem. Before it: `CoolantTemperature`
(heat-rejection ambient, coolant temperature, chiller COP), `UtilityPrice`
`SolarPV` (available output) and `GreenhouseLoad` (heating demand), which
need only weather. After it:
`GridBalance` and `UtilityCost`. There are no hand-off placeholders any more:
the data center node writes the cooling columns itself.

Wiring checks (`coupled_nodes`): the ice mixer needs ice storage; on brine it
needs brine separation. `ColumnStream(column, stream)` feeds a DataFrame
column in as a stream (tests, or a module standing alone).

## Measured (synthetic weather, 10 MW, defaults)

| Modules / control | Iterations needed per hour (hours) | Hours sticking | Run time |
|---|---|---|---|
| No modules | 2 (all) | 0 | 0.2 s |
| All modules, "Run everything" (water mixer) | 3 (6984), 4 (1776) | 0 | 1.7 s |
| All modules, "Run everything" (brine mixer) | 3 (5961), 4 (2799) | 0 | 1.9 s |
| All modules, night / day states (water) | 2–6 | 0 | 1.8 s |
| All modules, night / day states (brine) | 2–9 (≥ 7: 12 h) | 12 | 2.4 s |

"Iterations needed" counts the final check that nothing moved. In the 12
sticking hours, annual energy totals differ from an unlimited, 1e-12 solve by
less than 2e-6 (relative); the day/night case is the `test_routed_states_balance`
integration test.

## Adding a coupled module
Write its layer 2 as a node (`name`, `control_key`, `requires`, `provides`,
`reads`, `writes`, `prepare`, `initial_state`, `step`, and `control_values`
for its IFs). For each link it can be part of, use the want / answer / used
streams in `streams.py` (`heat_req` / `heat_sent` / `heat_used`, …), declare
answers with `StreamSpec(name, answers=want)`, and balance on what was used.
Add it to `coupled_nodes()` and its key to the `ends` of the link THENs it can
be the other end of ([control.md](control.md)). Electricity it uses or makes
goes in an `elec(...)` stream so the grid draw IF sees it.
