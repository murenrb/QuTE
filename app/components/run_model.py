"""Live model run (docs/workflow/01-setup-tabs.md §6, D-025).

Called on every rerun of the workspace. Weather is cached per location and the
model result per (inputs_hash, weather), so only real input changes recompute.
"""

from dataclasses import dataclass

from app import state
from app.components.weather import fetch_weather
from core.models.site_model import run_site_model
from core.persistence.project import Project, inputs_hash
from core.timeseries.pipeline import PipelineError
from services.weather import WeatherError

INCOMPLETE_MESSAGE = "Set a location and a data center to see results."


@dataclass(frozen=True)
class LiveResults:
    results: state.SiteResults | None
    message: str | None = None  # why there are no results
    is_error: bool = False


def live_results(project: Project) -> LiveResults:
    """Results for the current inputs, re-running the model only when they changed.

    Step 1 models the first facility only.
    """
    location = project.site.location
    if location is None or not project.facilities:
        return LiveResults(None, INCOMPLETE_MESSAGE)
    try:
        weather = fetch_weather(*location)
    except WeatherError as e:
        return LiveResults(None, str(e), is_error=True)

    key = f"{inputs_hash(project)}|{weather.meta.cache_key}"
    cached = state.get_results()
    if cached is not None and cached.inputs_hash == key:
        return LiveResults(cached)
    try:
        frame = run_site_model(
            project.facilities[0],
            weather.frame,
            project.assumptions,
            modules=project.modules,
            weather_meta=weather.meta,
            site_lat=project.site.lat,
            tariff=project.utility,
            control=project.control,
        )
    except (ValueError, PipelineError) as e:
        return LiveResults(None, f"Model run failed: {e}", is_error=True)
    results = state.SiteResults(frame, weather.meta, key)
    state.set_results(results)
    if project.site.weather_ref != weather.meta.cache_key:
        site = project.site.model_copy(update={"weather_ref": weather.meta.cache_key})
        state.set_project(project.model_copy(update={"site": site}))
    return LiveResults(results)
