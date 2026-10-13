# State Machine Control

Code: settings, specs and `Plan` in `core/domain/control.py`; catalog of IF
sources / THEN targets `core/control/catalog.py`; engine
`core/control/engine.py` (`Controller`, `resolve`, `warnings`); UI
`app/components/tabs/control.py` + `app/components/control_diagram.py`;
defaults `ControlDefaults` in `defaults.py` (D-053, D-054). Saved in
`Project.control` (additive: older files load with only the Default state).
The owner's write-up of every IF / THEN: `IF and THENs.docx` (project root).

## Concept
The user builds states in the **Control** tab (after Modules). Each state has
**IFs** (conditions to enter / stay) and **THENs** (what the data center and
each module do while it is active). Every hour exactly one state is active.
A rule reads as a sentence: the first blank is always the component (module,
data center, ambient, utility, time), and the remaining blanks are the options
that component declares, e.g. *IF Brine separation: brine concentration is
> 40 wt%  THEN Ice mixer: provides cooling to Power generation.*

**Each state is a complete description (owner, D-054).** Nothing runs behind
the user's back:
- A module runs only if one of the state's THENs names it, as the target or
  as the other end of a link, and no THEN switches it off ("… is off").
- Anything the state doesn't list is off. The IT load is 100 % of plan
  unless set. The data center is always cooled free when possible and
  mechanically when needed (owner).
- **Default state:** no IFs; active whenever no other state's IFs hold.
  Nothing listed means IT at 100 % and every module off (owner). Its THENs
  are editable. A **new state starts with a copy of Default's THENs**, so
  something meant to happen always (e.g. *PV generates power*) only has to be
  set up once. The "Run everything in Default" preset fills Default with
  `RUN_EVERYTHING` (catalog), which wires every module the way it ran before
  the state machine.

## IFs
`IF <source>: <variable> is <op> <value | statistic>`; ops `< ≤ > ≥ = ≠`.
All IFs of a state must hold (AND); for OR, make two states with the same
THENs.

| Source | Variables | Compared with |
|---|---|---|
| Ambient | dry bulb, wet bulb, dew point, RH, heat-rejection ambient, GHI, DNI, DHI, wind | a value. The editor notes the free-cooling cutoff (supply − approach, on the heat-rejection ambient) |
| Utility | energy price, demand charge | a value, or the daily average / median / lower quartile / upper quartile, annual average / median, or **a rate category** of the Utility tab (Off peak / Shoulder / Peak by default): that category's $/kWh, or $/kW for the demand charge (D-059) |
| Utility | grid draw (previous hour), kW | a value |
| Time | time (hour 0–23), date (MM-DD, any year), month, weekend, **Always** (on / off) | a value |
| Data center | planned IT load, % of full load (= planned / peak) | a value |
| Solar PV | PV output (available), kW: what the array can make this hour | a value |
| Ice storage | ice tank level, ice maker water tank level (% 0–100) | a value |
| Hot water storage | hot water tank level, cold water tank level (% of the water mass) | a value |
| Brine separation | brine concentration (wt%) | a value |
| Greenhouse | heating demand, kW_th (from the weather, before any heat is given) | a value |
| Ice mixer, power generation | none | — |

- Ambient, utility prices, time, planned IT load and PV output come from the
  hourly columns. Module values and the grid draw are read **at the start of
  the hour** (each node's `control_values(state)`), so the state never
  depends on the hour being solved.
- An IF whose value isn't available (e.g. its module is not on the site, or
  the grid draw in the first hour) never holds. (Until D-061 an IF on PV
  output with no PV on the site stopped the model run instead.)
- **Always:** on = always holds, so the state is always eligible and only
  higher-priority states can beat it. Off = never holds, which parks a state
  without deleting it.
- **Dates** compare as MM-DD (stored as month·100 + day). A window that wraps
  the year (Nov–Feb) needs two states.
- Monthly mean / median are no longer offered; files saved with them still load.
- **Rate categories (owner, D-059):** the "Than" list adds one entry per
  category on the Utility tab, e.g. *IF Utility: Energy price is ≥ the Peak
  rate (0.2 $/kWh)*. Saved as `reference = rate` plus the category's id
  (`Condition.category`), so renaming or repricing the category on the Utility
  tab carries through. "= the Peak rate" picks the hours painted Peak, provided
  no other category has the same price (the defaults all share a 10 $/kW
  demand charge, so use the energy price to tell them apart). On weekends with
  "weekend = cheapest rate" the cheapest category's price applies. A category
  deleted from the tariff leaves the IF in place, shown as "a rate no longer
  in the utility tariff", and it never holds.
- **Statistics on a stepped tariff:** a quartile is a price that occurs, not
  "the top quarter of hours". With 4 peak hours a day, the daily upper
  quartile *is* the off-peak price, so "≥ upper quartile" holds every hour and
  "< upper quartile" never. Use "> upper quartile" / "≤ upper quartile" (or
  the daily average) to split peak from off-peak.

## THENs
Declared by each target in its model file (`CONTROL_SPEC.thens`). The kinds:
a number, a flag (no blanks), "… is off", or a **link** (to / from another
module; some carry a number).

| Target | THENs |
|---|---|
| Data center | IT load is set to [x] % of planned load |
| Solar PV | Generates power · PV is off |
| Ice storage ("ice maker") | Ice maker cleared to run · Sends ice to [ice mixer] · Receives water from [brine separation] · Ice maker is off |
| Power generation | Runs at [x] % of design · Accepts heat from [data center return water / hot water storage / brine separation condenser steam] · Accepts cooling from [supply coolant / ice mixer] · Power generation is off |
| Hot water storage | Sends hot water to [power generation, greenhouse] · Receives hot water from [data center] · Hot water storage is off |
| Brine separation | Sends brine flow to [ice mixer] · Accepts [x] % of heat from [data center] · Sends water to [ice storage / drain] · Brine separation is off |
| Ice mixer | Provides cooling to [data center / power generation / brine separation] · Ice mixer is off. The fluid (water / brine) is the module's input, not a THEN (owner) |
| Greenhouse | Takes heat from [data center, hot water storage] · Greenhouse heating is off |

- **A link is one connection**, entered at either end ("hot water storage
  sends hot water to power generation" = "power generation accepts heat from
  hot water storage"). It shows at the end where it was entered and counts
  once.
- **THEN order matters.** Where several modules share a source, they are
  served in the order the state lists the links. This applies to the data
  center's heat, the ice mixer's cooling and power generation's heat sources.
  The editor has ↑ / ↓ on every THEN.
- **Automatic returns (owner):** the ice mixer's melt water goes back to ice
  storage, and its diluted brine back to brine separation, whenever it gets
  ice / brine from them.
- What "off" means: ice storage keeps its contents (no ice made, none given,
  no water taken); the ice mixer asks for nothing; hot water storage moves no
  heat; brine separation takes no heat and exchanges no brine; power
  generation makes nothing; PV is curtailed.
- A THEN naming a module that isn't on the site is ignored. The editor warns,
  and also flags combinations that can't run: power generation without a heat
  source or a cold side, an ice mixer with no ice or no consumer, an ice
  mixer set to brine that gets no brine from brine separation (D-063: it stays
  off, and so does what it cools — power generation, then hot water storage), a
  module that is both switched off and given other THENs.

### What the links mean physically
- **Data center heat** (IT + parasitics) goes to the linked modules in THEN
  order. Each is offered min(what it wants, what is left, its % of the heat if
  the THEN gives one). The rest is the data center's own cooling: free cooling
  if the ambient allows, else mechanical.
- **Supply coolant** (power generation's cold side; brine separation's
  condenser unless the ice mixer cools it) is at `t_coolant_c`. The heat
  rejected into it joins the data center's cooling: free cooling when
  possible, the chillers otherwise.
- **Ice mixer cooling:**
  - to the data center: its *mechanical* load only, so it never replaces free
    cooling;
  - to power generation: its cold side at the mixer's temperature, carrying
    the rejected heat;
  - to brine separation: the condenser works against the mixer's temperature
    and can reject no more than the mixer (plus power generation) takes.
- **Power generation's heat sources:**
  - data center return water at `t_return_c`;
  - hot water storage at hot tank − pinch;
  - brine separation's condenser steam at its condensing temperature −
    condenser pinch.

  Each source runs at its own Carnot efficiency, with all of them under one
  cap: heat ≤ run % × design heat and power ≤ run % × rated. It needs a cold
  side; with several listed, the first is used.
- **Greenhouse** takes its heating demand from the data center's return
  water and / or hot water storage, in THEN order (the first covers what it
  can, the next the rest), each only while its water is warmer than setpoint
  + 10 K coil approach (D-064); what isn't covered is `greenhouse_unmet_kwth`
  ([models/greenhouse.md](models/greenhouse.md)).
- **Hot water storage** charges from the data center and discharges to power
  generation and / or the greenhouse (THEN order), both in the same hour if the
  state says so (charge first).
- **Brine separation's recovered water** goes to ice storage's water tank
  after the melt water, as far as it fits; the rest drains. With no water
  link, it all drains.

## Choosing the state each hour
1. Candidates: the user's states in **priority order** (their order in the
   list; the number in the diagram). A state qualifies if the current state
   may move to it (or it *is* the current state) and all its IFs hold.
2. The first qualifying state wins; if none, Default.
3. A state stays active only while its IFs hold. **Default is always
   reachable** (from and to every state), so the machine can't get stuck.
4. The state is fixed for the hour; then the hour is solved
   ([solver.md](solver.md)).

**Allowed moves:** a new state may move to any other state (`next_states =
None`); the user narrows it with "Can move to". Ticking every state again
means "any", which also covers states added later.

## Model hooks
- `resolve(actions, specs)` turns a state's THENs into a `Plan`: the modules
  that run, flag / number values, and the links in THEN order (only between
  ends that run). Every node gets the hour's plan:
  `step(data, state, h, flows, plan)`.
- The planned IT profile is `it_load_plan_kw` (the frame). The data center
  node writes the actual `it_load_kw` = planned × the state's IT load %.
- Column: `control_state` (0 = Default, then priority order).

## Adding IFs / THENs to a module
In the module's model file, add to `CONTROL_SPEC`:
- an IF: `ControlVariable(key, label, unit)` in `ifs`, and in its node
  `control_values(self, state) -> {key: value}` read from the start-of-hour
  state;
- a THEN: `ControlSetting(key, label, kind, …)` in `thens`, where `label` is
  the sentence with `{value}` / `{to}` for the blanks. For a link, give
  `commodity`, `receives` and `ends` (the other end's options), and add the
  module's key to the `ends` of the matching THEN at the other end. Honour it
  in the node's `step` through the plan (`plan.runs`, `plan.flag`,
  `plan.value`, `plan.link`, `plan.to`, `plan.sent_by`) and the want / answer
  / used streams ([solver.md](solver.md)).

The Control tab picks both up automatically.

## UI
- **Diagram** (Plotly, in a small keyed component that reports a click on a
  state straight to the editor, D-066): Default and the user's states are the corners of a
  regular polygon (Default at the top, states clockwise by priority; D-063), so
  no arrow passes through another node or overlaps another arrow; arrows = allowed moves (double-headed both ways), dashed = fall back to
  Default; square greyscale nodes, the selected one filled. Click a state (or
  pick it in the list) to edit it.
- **Above** the diagram, pinned to the top of the tab while the rest scrolls
  (D-063, so you always see which state you are editing): the state picker, a
  **new state name** box and **Add state** (the new state takes the typed
  name, else "State n").
- Clicking a state scrolls the page so the diagram sits just below the pinned
  picker and the editor fills the rest, so the change is in view (owner).
- **Editor** below: name; higher / lower priority; delete; "Can move to"; how
  many hours the state was active in the current results (spots a state whose
  IFs always or never hold); the IF list with **Edit** / **Remove** and an add
  row (component → variable → operator → value / date / statistic, or on / off
  for Always); the THEN list with ↑ / ↓ / **Edit** / **Remove** and an add row
  (component → THEN sentence → number and / or the other end). **Edit** takes
  the rule out and fills the add row with it; **Add** puts it back in its
  place. Adding an IF or THEN the state already has is refused.
  Components offered: the data center and the modules on the site.
- Default: the THEN list and add row, plus the "Run everything in Default"
  preset.

## Open (owner)
- Suggestions not built: minimum hours in a state (anti-chatter, "let's see
  how stable it ends up"); OR groups inside a state. (The active state is now
  a view of the results' Operation row, D-057, D-060.)
