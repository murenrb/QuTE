"""The workspace: tabbed inputs + map on top, charts + metrics below.

Layout: docs/gui.md → Layout (D-024, D-025). Map tools per tab: D-027.
"""

import streamlit as st

from app import state
from app.components import metrics as metrics_panel
from app.components.edits import set_site
from app.components.map_view import (
    MAP_HEIGHT_PX,
    MapEvents,
    MapMode,
    render_site_map,
    selection_for,
)
from app.components.modules import BY_KEY, LABELS
from app.components.plots import FIGURE_HEIGHT_PX, build_results_figure
from app.components.project_bar import render_project_bar
from app.components.results_chart import results_chart
from app.components.run_model import LiveResults, live_results
from app.components.style import placeholder, section_rule
from app.components.tabs import control, data_center, location, modules, property, utility
from core.geometry.areas import AreaError
from core.geometry.boundary import BoundaryError, boundary_metrics
from core.persistence.project import Project, ProjectFileError
from core.site_layout import place_module_area, reshape_module_area, set_block_footprint

K_TAB = f"{state.WIDGET_PREFIX}tab"
K_OUTPUT_MODULE = f"{state.WIDGET_PREFIX}output_module"
K_FIGURE = "results_figure"
METRICS_PER_ROW = 6  # full page width
TAB_HEADER_PX = 42  # tab strip height, so the inputs panel lines up with the map


def _inputs_panel(project: Project) -> tuple[state.Tab, str | None]:
    """Render the tabs; only the open tab's content runs.

    Returns the open tab and, on the Modules tab, the selected module (both set
    the map's tools).
    """
    # Seed once from the project (a changing `default` would rebuild the widget
    # and drop the user's tab click).
    state.seed(K_TAB, state.tab_for(project.step).label)
    pending = state.pop_selection()  # an object clicked on the map (D-042)
    if pending is not None:
        tab, module = pending
        st.session_state[K_TAB] = tab.label
        if module is not None:
            st.session_state[modules.K_MODULE] = module
    tabs = st.tabs(
        [t.label for t in state.Tab],
        key=K_TAB,
        on_change="rerun",
        height=MAP_HEIGHT_PX - TAB_HEADER_PX,
    )
    active = next((t for t, c in zip(state.Tab, tabs, strict=True) if c.open), state.Tab.LOCATION)
    module: str | None = None
    with tabs[list(state.Tab).index(active)]:
        if active is state.Tab.LOCATION:
            location.render(project.site)
        elif active is state.Tab.PROPERTY:
            property.render(project.site)
        elif active is state.Tab.DATA_CENTER:
            data_center.render(project)
        elif active is state.Tab.UTILITY:
            utility.render(project)
        elif active is state.Tab.CONTROL:
            control.render(project)
        else:
            module = modules.render(project)
    if project.step != active.value:
        p = state.get_project()
        state.set_project(p.model_copy(update={"step": active.value}))
    return active, module


@st.fragment
def _map_panel(active: state.Tab, module: str | None) -> None:
    """Map as a fragment: panning on the Location tab reruns only the map.

    Changes that affect the inputs or results (boundary drawn, block moved)
    trigger a full-app rerun from `_handle_map`.
    """
    events = render_site_map(state.get_project(), MapMode(active.value), module)
    _handle_map(events, state.get_project(), active, module)


def _handle_map(events: MapEvents, project: Project, active: state.Tab, module: str | None) -> None:
    site = project.site
    v = events.view
    if v is not None and (v.bounds, v.center, v.zoom) != (
        site.map_view,
        site.map_center,
        site.map_zoom,
    ):  # Location tab: remember the framed view exactly
        set_site(map_view=v.bounds, map_center=v.center, map_zoom=v.zoom)
    ring = events.drawn_ring
    if ring is not None and active is state.Tab.PROPERTY and ring != site.boundary:
        try:
            boundary_metrics(ring)
        except BoundaryError as e:
            state.flash("property", "error", str(e))
        else:
            set_site(boundary=ring)
        state.bump_map_version()  # remount: shows the boundary, or re-arms after an error
        st.rerun(scope="app")
    if events.drawn_ring is not None and active is state.Tab.MODULES and module is not None:
        try:  # snap to the free land inside the property (D-036)
            state.set_project(place_module_area(project, module, events.drawn_ring))
        except AreaError as e:
            state.flash("modules", "error", str(e))
        state.bump_map_version()  # remount: shows the snapped area, or re-arms after an error
        st.rerun(scope="app")
    if events.select is not None and state.edit_is_new(events.select[0]):
        tab, module = selection_for(events.select[1])  # clicked object → its tab/module
        state.request_selection(tab, module)
        st.rerun(scope="app")
    if events.block_edit is not None and state.edit_is_new(events.block_edit[0]):
        _, owner, fp = events.block_edit  # validated in Python; area stays the set area
        state.set_project(set_block_footprint(project, owner, fp))
        st.rerun(scope="app")
    if events.polygon_edit is not None and state.edit_is_new(events.polygon_edit[0]):
        _, owner, rings = events.polygon_edit
        try:  # vertex edit: same snapping rules as a new drawing (D-041)
            state.set_project(reshape_module_area(project, owner, rings))
        except AreaError as e:
            state.flash("modules", "error", str(e))
        state.bump_map_version()  # remount on the stored (snapped) shape
        st.rerun(scope="app")


def _output_module(project: Project) -> str | None:
    """Module output selector: the modules on the site, the same control as the
    Modules tab (D-055, D-056). None while no module is on the site."""
    keys = modules.on_site(project)
    if st.session_state.get(K_OUTPUT_MODULE) not in keys:
        st.session_state[K_OUTPUT_MODULE] = keys[0] if keys else None
    if not keys:
        return None
    return (
        st.segmented_control(
            "Module output",
            keys,
            format_func=lambda k: LABELS[k],
            key=K_OUTPUT_MODULE,
            label_visibility="collapsed",
        )
        or keys[0]
    )


def _results_figure(live: LiveResults, project: Project) -> None:
    """Module output (left) + results rows (right) in one figure, so every
    time axis zooms together (D-055)."""
    if live.results is None:
        if live.is_error:
            st.error(live.message)
        placeholder(live.message or "", FIGURE_HEIGHT_PX // 3)
        return
    left, _ = st.columns(2, gap="medium")
    with left:
        key = _output_module(project)
    module = None if key is None else (BY_KEY[key].label, BY_KEY[key].outputs)
    names = [s.name for s in project.control.all_states]
    # A keyed component, not st.plotly_chart: the zoom and each row's view
    # survive every model run (D-060).
    results_chart(
        build_results_figure(live.results.frame, module, names),
        key=K_FIGURE,
        config={"displaylogo": False, "modeBarButtonsToRemove": ["select2d", "lasso2d"]},
    )


def _metrics(live: LiveResults) -> None:
    """Text output, under all the plots (D-055)."""
    if live.results is None:
        return
    st.markdown("**Output metrics**")
    metrics_panel.render_metrics(
        metrics_panel.output_metrics(live.results.frame, live.results.weather),
        per_row=METRICS_PER_ROW,
    )


def _ensure_open_project() -> None:
    """The project is in the URL (?project=<stem>, D-069), so a reload, a shared
    link or a session Streamlit dropped while the browser was away reopens that
    project. Without one (or if it isn't saved) go to Start: never start blank
    and autosave over real work (D-040). Then keep the URL on this project."""
    stem = state.autosave_stem()
    if stem is None:
        wanted = st.query_params.get(state.PROJECT_PARAM)
        try:
            if not wanted:
                raise ProjectFileError("no project in the link")
            project = state.store().load_project(wanted)
        except ProjectFileError:
            st.switch_page(state.START_PAGE)
        state.open_project(project, wanted)
        stem = wanted
    if st.query_params.get(state.PROJECT_PARAM) != stem:
        st.query_params[state.PROJECT_PARAM] = stem


# --- page -----------------------------------------------------------------------
# Input layer: tabbed inputs | map. A line. Output layer, starting below the
# map: module output (selector, plot, text) | results figure — three rows with
# view buttons on one shared time axis, all in one figure (D-029, D-032, D-055,
# D-060). Text output
# (metrics) under all the plots.

_ensure_open_project()
render_project_bar()

input_left, input_right = st.columns(2, gap="medium")
with input_left:
    active_tab, active_module = _inputs_panel(state.get_project())
with input_right:
    _map_panel(active_tab, active_module)

section_rule()

live = live_results(state.get_project())
_results_figure(live, state.get_project())
_metrics(live)
