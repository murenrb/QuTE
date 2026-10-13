# Coding Conventions

- Python 3.13, dependencies declared in `pyproject.toml` (pin versions).
- Format + lint with **ruff**; type-check `core/` and `services/` with mypy (strict-ish).
- Type hints everywhere in `core/`; dataclasses/pydantic for structured data,
  no loose dicts crossing module boundaries.
- Docstrings on every model function state the equation, units of each
  argument, and link to the doc section it implements.
- **Units:** internal electrical in kW, thermal in kW_th, temperature °C
  (K only inside Carnot math), area in sqft for sizing (spec units) and m² for
  map geometry. Unit goes in the variable/column name (`area_sqft`, `width_m`).
- Hourly calcs: **stateless** models are vectorized numpy over whole columns (no
  loops). **Stateful** models (inertia, e.g. storage) may loop over the hours,
  but only over numpy arrays pulled out once, calling a pure one-hour step
  function. Never `df.iterrows()` or `df.apply(axis=1)`. See
  architecture.md → Writing a module.
- No Streamlit imports outside `app/`. No network calls outside `services/`.
- JavaScript only in custom components (`app/components/*/frontend/`): plain JS,
  no build step, third-party libraries vendored with their licence. Any geometry
  duplicated in JS must have a Node-run consistency test against `core/`.
- Secrets via env or `.streamlit/secrets.toml` (gitignored).
- Saved data goes through `services/store.py` (the database), never files.
- Small, focused modules; one subsystem per file.
- Adding a dependency: justify it in decisions.md.
- Version control: git, remote `github.com/murenrb/QuTE`,
  branch `main`. Commit docs + code together. Only commit/push when asked.
- Dependencies: `uv` + `pyproject.toml` locally; keep a `requirements.txt` at
  the repo root for Streamlit Community Cloud deployment.
