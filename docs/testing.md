# Testing

## Test gate — run after every major change
A "major change" = any change to `core/`, `services/`, a schema, a default, or
a page's behavior. Run all of these and report pass/fail with output:

```bash
source .venv/bin/activate
ruff check .                 # lint
ruff format --check .        # formatting
mypy core services           # types (engineering code must be fully typed)
pytest -q                    # unit + integration + UI smoke (no live API)
```
Opt-in live API check (before releases or after touching `services/nsrdb.py`):
`pytest -m live`.

Do not mark work done with a failing gate. If a test is wrong, fix the test
and explain why in the summary — never delete/skip to get green.

## Test layers

| Layer | Location | What |
|---|---|---|
| Unit | `tests/unit/` | Every equation in models/*.md with hand-calculated values; geometry (area-preserving resize, rotation, point-in-polygon); schema validation |
| Invariants | `tests/unit/test_invariants.py` | Energy/thermal balances listed in datacenter-hourly.md; 8760 rows; no NaN/inf; COP bounds |
| Integration | `tests/integration/` | Full pipeline: fixture weather → DataFrame → all subsystems → expected annual totals |
| Regression (golden) | `tests/integration/golden/` | Reference site(s) with stored annual summary; any change in results must be intentional and the golden file updated deliberately |
| UI smoke | `tests/ui/` | Streamlit `AppTest`: Start + workspace load, every tab renders, forms submit, no exceptions |
| Persistence | `tests/unit/` | Save → load round-trip of types and sites; old `schema_version` migrates |

## Required cases (Step 1)
- Sizing worked example in models/sizing.md (10 MW → 66,495.04 sqft).
- Dry vs. evaporative: chiller area and choice of TDB vs. TWB.
- Redundancy: Y=2 → backup area ×1.2; X=2 doubles.
- Free/mech boundary exactly at `t_amb = t_supply − t_approach` (30 °C with defaults → mechanical).
- Changing `t_return` alone does not change Step 1 hourly results.
- COP: clamps at 0 and `cop_max`; `T_hot ≤ T_cold` → `cop_max`; dry at 40 °C
  ambient → 8.22; condenser approach differs for dry (10) vs evap (5).
- IT daily profile tiling: a non-constant 24-h profile repeats identically for all 365 days.
- Leap-day removal and local-time conversion on a fixture that contains Feb 29.
- `white_space_ratio < 0.10` raises a clear error.
- Project file: save → load round-trip reproduces identical model results;
  downloaded file == autosave; old `schema_version` migrates; corrupt file gives a clear error.
- `footprint_within_boundary`: inside, touching edge, partially outside, rotated cases.
- New column registered → appears in the correct plot group.
- Results figure: one figure, three rows sharing one x-axis (module axis
  matched), traces per registry group, one y-axis per view, view buttons that
  touch only their own row (D-060).
- Results component: plotly.js copied to `static/` and static serving on. Zoom
  / view persistence across a model run needs a browser: checked with a
  headless Chromium (Playwright) drag-zoom → add a state → zoom and views kept,
  also after a reload (D-060).
- Workspace: results panels show placeholders until location + data center
  exist, then fill in without any button; changing an input (e.g. IT load)
  updates results; a rerun with no input change does not re-run the model.
- Map modes (D-027): per tab, the map config has the right tools — Location:
  pan/zoom on, no Draw; Property: pan/zoom off, Draw polygon only and armed when
  no boundary; Data center: pan/zoom off, no Draw, footprint editor once a
  block exists (edits re-validated in Python);
  Modules: all off. Location view saved and restored on the other tabs.
- Footprint editor JS ↔ Python: `tests/unit/test_footprint_editor_js.py` runs
  `frontend/geometry.js` under Node and checks corners, area-locked edge resize
  (opposite edge fixed), rotation + 15° snap and the inside-boundary check
  (incl. a concave notch) against `core/geometry` within 1 cm. Skipped if Node
  isn't installed — install Node locally so this runs.
- Solar PV (`tests/unit/test_solar_pv.py`): Phoenix 1 MW regression
  (1,758,822 kWh ±0.1 %), zero at night, inverter clipping, midday peak,
  inputs move output the right way; full pipeline balance with PV enabled;
  opt-in live check vs the PVWatts web API (within 3 %).
- Module areas (`tests/unit/test_areas_layout.py`): snapping clips to the
  boundary, cuts out the block/other areas (split pieces, holes), drops
  slivers, clear errors; placement/clear on a project; layout warnings after
  later edits; Modules-tab map mode arms the polygon tool only for the selected
  module without an area; areas drawn on every tab; v1 → v2 project migration.
- Ice storage (`tests/unit/test_ice_storage.py`): owner's default step by hand,
  curve fits and caps, each branch (not cleared, full tank, charge-limited),
  tank and load balances on random hours; pipeline with ice: chiller = demand −
  ice, thermal stack = total load, cooling electricity from the chiller column,
  grid includes the ice maker; without ice: chiller = demand.
- Module map categories (D-041): categories discovered from params types; ice
  footprint = tank/density; block placed beside the data center, idempotent
  layout rules, resized with inputs (position kept); block over a drawn area
  cuts it back (notches stay, holes heal when it moves out, D-074); block–block overlap and outside-boundary flagged
  both ways; drawn areas snap around module blocks; vertex edits obey the
  snapping rules; editor routing per tab/module; block colors; browser
  convex-overlap check agrees with shapely (Node).
- D-042: compass snapping (axis and 45° cases; edges against neighbours stay
  put); ice size follows 65 TR/MW, tank range 6–72 h, v2→v3 migration; map
  labels (upper-left, outline colour, ≤ 10 px); click → tab/module selection
  (folium tooltip and editor "select" events); UI click-select flow.
- **Browser checks** (not in the gate; a scratch Playwright harness was used
  2026-10-05): drag a small block, click another object to select it, labels
  present, snap edges, drag a PV corner — all against a real Chromium. Worth
  adding as an opt-in `pytest -m browser` suite.
- Utility (D-043, `tests/unit/test_utility.py`, `test_tariff_ui.py`): defaults,
  validation, painting/deleting, hourly mapping by month/hour, weekend off
  peak, monthly peak-only demand (ties, negatives), 10 MW hand calculation,
  time-varying demand charge picks max charge × load, export credit, swatch
  colours (blue → purple → red by total value), painter actions, UI flow.
- Saving (D-040): regression — a new session landing on the workspace reopens
  the latest autosave and a click doesn't blank it; no autosave → Start; new
  projects get separate files; opened autosaves keep their file; save/restore a
  version (state snapshotted first); history throttling/forcing/pruning;
  versions never overwritten; Start lists autosaves only.
- Style: theme keeps square corners and greyscale primary color (config test).

## Fixtures
`tests/fixtures/`: small recorded NSRDB TMY CSV(s) for 1–2 locations (one dry,
one humid), sample DC types, sample site JSON.
