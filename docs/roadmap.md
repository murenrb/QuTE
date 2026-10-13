# Roadmap

Current phase: **Step 1 — site setup + baseline data center model**, on the
single workspace layout (gui.md).
Design decisions today must not block the items below.

## Known upcoming
- Transient IT load: user-supplied daily profile → later full 8760 profile.
- Editable sizing transfer functions and model assumptions in the UI.
- Waste-heat offtake (`heat_offtake_kwth`) to co-located systems, using `t_return_c`.
- Co-located subsystems, each a pipeline module with its own columns/plots and
  its own inputs in the **Modules tab**: ~~solar PV~~ (done, D-035), ~~ice
  storage~~ (module done, D-037; state-machine control tab next), greenhouses, wastewater treatment, district heating,
  food processing.
- Solar PV follow-ups: PV array footprint on the map, degradation, bifacial,
  soiling/shading.
- More traces in thermal/electrical plots (offtake, heat pumps, on-site generation).

## Deferred by decision (note for later)
- **Non-NSRDB weather sources** for sites outside NSRDB coverage — e.g. EPW
  file upload, PVGIS. Keep `services/` weather access behind one interface so a
  second provider drops in. (D-012)
- **Multi-user / login / shared type library / hosted storage** — single user
  for now; local JSON + download. (D-010)
- **Multiple parcels / exclusion zones** (easements, setbacks) in the boundary. (D-011)
- Partial (economizer trim) free cooling instead of the binary split. (D-009)

## Likely / to confirm
- Multiple facilities per site; multiple sites per project.
- KPIs: PUE, WUE (evaporative water use), free-cooling hours, heat reuse factor, annual energy/cost/CO₂.
- Economics (capex/opex, tariffs), grid carbon intensity.
- Scenario comparison and parametric optimization in the workspace results area.
- Report export (PDF/Excel).
