# QuTE (Data Center System) — Claude Instructions

Streamlit app for **systems engineering of data centers co-located with other
technologies** (greenhouses, wastewater treatment, district heating, food
processing, …). The user sites a data center on a map, sizes it from simple
transfer functions, then runs an **8760-hour performance model** built on a
single pandas DataFrame. Future steps add co-located systems that exchange
heat/power with the data center.

This file is loaded every session. Keep it short; details live in `docs/`.
Read the linked doc **before** working in its area.

## Doc map

| Doc | Read when… |
|---|---|
| [docs/overview.md](docs/overview.md) | Starting any new feature; need the big picture or glossary |
| [docs/architecture.md](docs/architecture.md) | **Writing a module** (two-layer pattern, stateless vs. stateful, checklist), deciding where code lives, session state |
| [docs/data-model.md](docs/data-model.md) | Touching the DataCenterType schema, saved files, or hourly DataFrame columns |
| [docs/assumptions.md](docs/assumptions.md) | Any hard-coded engineering constant or default value |
| [docs/workflow/01-setup-tabs.md](docs/workflow/01-setup-tabs.md) | Start screen; Location / Property / Data center / Modules tabs; live model run |
| [docs/workflow/02-results.md](docs/workflow/02-results.md) | Results figure (3 rows with view buttons, module output panel, shared time axis, zoom kept across runs) and output metrics |
| [docs/models/sizing.md](docs/models/sizing.md) | Facility area calculations (data hall, backup power, chillers) |
| [docs/models/datacenter-hourly.md](docs/models/datacenter-hourly.md) | Hourly cooling / COP / electrical model |
| [docs/models/solar-pv.md](docs/models/solar-pv.md) | Solar PV module (PVWatts V8 via PySAM) |
| [docs/models/ice-storage.md](docs/models/ice-storage.md) | Ice storage module (one-hour step, ice + water tanks, mass-flow interface) |
| [docs/models/power-generation.md](docs/models/power-generation.md) | CO2 power generation module (free-cooling hand-off, 1:1 heat→power) |
| [docs/models/hot-water-storage.md](docs/models/hot-water-storage.md) | Hot water storage (two tank / thermocline, mech. demand chain) |
| [docs/models/brine-separation.md](docs/models/brine-separation.md) | Brine separation (evaporator, front of the heat stack, floating coolant) |
| [docs/models/ice-mixer.md](docs/models/ice-mixer.md) | Ice mixer (ice into water/brine, two-pass calls, salt balance) |
| [docs/models/greenhouse.md](docs/models/greenhouse.md) | Greenhouse (drawn floor, covering U-value input, heating demand from data center return water) |
| [docs/control.md](docs/control.md) | **State machine**: Control tab, IFs / THENs (links between modules, THEN order), each state a complete description, how a state is chosen, adding a module's IFs / THENs |
| [docs/solver.md](docs/solver.md) | **Hourly solver**: data center + modules as nodes, want → answer → used links, sticky rule — any stateful or coupled module |
| [docs/models/utility.md](docs/models/utility.md) | Utility tariff: painted TOU rates, energy cost, monthly demand charge |
| [docs/integrations/nsrdb-weather.md](docs/integrations/nsrdb-weather.md) | Weather API, caching, timestamp handling |
| [docs/deployment.md](docs/deployment.md) | Publishing: Streamlit Community Cloud, the public Postgres database (`DATABASE_URL`), secrets |
| [docs/gui.md](docs/gui.md) | **Canonical** visual style (greyscale, Arial-like 12/14 pt, square corners) and layout — any UI / map / plot work |
| [docs/testing.md](docs/testing.md) | **Before declaring any change done** |
| [docs/conventions.md](docs/conventions.md) | Code style, naming, units, dependencies |
| [docs/open-questions.md](docs/open-questions.md) | Spec ambiguities awaiting a decision — check before implementing a model |
| [docs/roadmap.md](docs/roadmap.md) | Planned future features the design must not block |
| [docs/decisions.md](docs/decisions.md) | Log of architecture/spec decisions (append, don't rewrite) |

Source of the original spec: `Project Scope Musings/Datacenter system, Step 1.docx`;
layout/style source: `docs/App asthetics guide.docx` + `docs/Layout example.png`.
The Markdown docs are now canonical; if they disagree with the .docx, the docs win.

## Non-negotiable rules

1. **Engineering logic never imports Streamlit.** All calcs live in `core/` as
   pure, typed functions so they are testable and reusable. `app/` is UI only.
2. **The hourly DataFrame is the backbone.** Every subsystem adds columns to it
   through the registered pipeline — never a side table. Columns carry units in
   their names (e.g. `it_load_kw`, `cooling_mech_kwth`). See data-model.md.
3. **No magic numbers.** Every constant/default lives in `core/config/defaults.py`
   and is documented in `docs/assumptions.md`. Hard-coded now ≠ hard-coded later.
4. **Size on peak, simulate on hourly.** Sizing uses peak IT MW; performance
   uses the hourly IT column (even while it is constant).
5. **Design for more subsystems.** New co-located tech = new model module + new
   columns + new plot traces registered, with no edits to existing models.
6. **Run the test gate** in [docs/testing.md](docs/testing.md) after every
   major change and report the results honestly.
7. When the spec is ambiguous, check `docs/open-questions.md`; if not resolved
   there, ask rather than guess, and record the answer in `docs/decisions.md`.
8. **Supply = cold, return = warm.** The owner sometimes swaps these words;
   use the coldest physically sensible combination and confirm if unsure.
9. Keep docs in sync: if you change behavior, schema, a default, or the layout,
   update the matching doc in the same change.

## Environment

- Python 3.13, virtualenv at `.venv/` (`source .venv/bin/activate`).
- Run app: `streamlit run streamlit_app.py`
- Add deps with `uv add <pkg>`, then re-export: `uv export --no-dev --no-hashes --format requirements-txt -o requirements.txt`
- Test gate: see docs/testing.md (`pytest`, `ruff`, type check).
- Git remote: `github.com/murenrb/QuTE` (`main`), intended
  for Streamlit Community Cloud deployment. Secrets go in Streamlit secrets,
  never in the repo.
- Saved projects / types live in a database (`services/store.py`): local
  SQLite `data/dcs.sqlite` unless `DATABASE_URL` is set. All projects are public.
- Project sits in OneDrive: keep `.venv/`, caches, and weather downloads out of
  sync/git where possible.
