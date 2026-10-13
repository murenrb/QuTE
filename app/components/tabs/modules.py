"""Modules tab: add modules to the site, pick one, draw its area, set its inputs
(01-setup-tabs.md §5).

Only the modules on the site get a tab; "Add module" picks another from a list
and "Remove from the site" takes one off (D-056), so what is listed is what is
modelled. Generic for every module in app/components/modules.MODULES: the
selected module decides the map tool (polygon for its area), and its area is
snapped to the free land when closed (D-036).
"""

import streamlit as st

from app import state
from app.components.modules import BY_KEY, LABELS, MODULES, ModuleUI
from core.config.defaults import SQFT_PER_ACRE
from core.geometry.areas import AreaError, area_sqft
from core.persistence.project import Project
from core.site_layout import clear_module_area, layout_warnings, square_up_module_area

K_MODULE = f"{state.WIDGET_PREFIX}module"
K_ADD = f"{state.WIDGET_PREFIX}module_add"


def on_site(project: Project) -> list[str]:
    """Keys of the modules added to the site, in registry order."""
    keys = project.modules.enabled_keys()
    return [m.key for m in MODULES if m.key in keys]


def _set_enabled(key: str, enabled: bool) -> None:
    p = state.get_project()
    state.set_project(p.model_copy(update={"modules": p.modules.with_enabled(key, enabled)}))
    state.bump_map_version()  # its block / area appears or disappears


def _add() -> None:
    key = st.session_state.get(K_ADD)
    if key is None:
        return
    _set_enabled(key, True)
    st.session_state[K_MODULE] = key  # open its tab
    st.session_state[K_ADD] = None


def _remove(key: str) -> None:
    _set_enabled(key, False)  # inputs, area and block are kept for adding it back


def _add_module(available: list[str]) -> None:
    """Popover: pick a module that isn't on the site yet, then add it."""
    if st.session_state.get(K_ADD) not in available:
        st.session_state[K_ADD] = None
    with st.popover("Add module", width="stretch", disabled=not available):
        pick = st.selectbox(
            "Module",
            available,
            index=None,
            format_func=lambda k: LABELS[k],
            key=K_ADD,
            placeholder="Pick a module",
        )
        if pick is not None:
            st.caption(BY_KEY[pick].description)
        st.button("Add to the site", key=f"{K_ADD}_go", on_click=_add, disabled=pick is None)


def _square_up(key: str) -> None:
    try:
        state.set_project(square_up_module_area(state.get_project(), key))
    except AreaError as e:
        state.flash("modules", "error", str(e))
    state.bump_map_version()  # remount the vertex editor on the new outline


def _clear_area(key: str) -> None:
    state.set_project(clear_module_area(state.get_project(), key))
    state.bump_map_version()  # remount with the polygon tool armed again


def _area_section(project: Project, module: ModuleUI) -> None:
    """Scaled-in-map modules only: draw / review / clear the area."""
    params = project.modules.sited().get(module.key)
    if params is None:
        return  # scaled in inputs (block): handled in the module's own panel
    if len(project.site.boundary) < 3:
        st.info("Draw the property boundary first (Property tab).")
        return
    if not params.placed:
        st.caption(module.draw_note)
        return
    st.caption(
        "Drag a corner handle on the map to reshape the area; it snaps to the free land "
        "when you let go."
    )
    sqft = area_sqft(params.area)
    c1, c2, c3 = st.columns(3)
    c1.metric("Area", f"{sqft / SQFT_PER_ACRE:,.2f} acres")
    c2.metric("Area", f"{sqft:,.0f} sqft")
    c3.metric("Pieces", len(params.area))
    c1, c2 = st.columns(2)
    with c1:
        st.button(
            "Snap edges to N/S/E/W",
            key=f"square_{module.key}",
            on_click=_square_up,
            args=(module.key,),
            width="stretch",
            help="Turn every free edge (not against the property line, a block or another "
            "area) to the nearest of N, S, E, W, NE, NW, SE, SW.",
        )
    with c2:
        st.button(
            "Clear area and redraw",
            key=f"clear_{module.key}",
            on_click=_clear_area,
            args=(module.key,),
            width="stretch",
        )


def render(project: Project) -> str | None:
    """Render the tab; return the selected module key (sets the map tool), or
    None while no module is on the site."""
    keys = on_site(project)
    if st.session_state.get(K_MODULE) not in keys:  # e.g. just removed
        st.session_state[K_MODULE] = keys[0] if keys else None
    pick_col, add_col = st.columns([4, 1], vertical_alignment="center")
    with add_col:
        _add_module([m.key for m in MODULES if m.key not in keys])
    with pick_col:
        if not keys:
            st.caption("No modules on the site yet. Use **Add module** to add one.")
            key = None
        else:
            key = (
                st.segmented_control(
                    "Module",
                    keys,
                    format_func=lambda k: LABELS[k],
                    key=K_MODULE,
                    label_visibility="collapsed",
                )
                or keys[0]
            )
    state.show_flash("modules")
    for warning in layout_warnings(project, LABELS):
        st.warning(warning)
    if key is not None:
        module = BY_KEY[key]
        _area_section(project, module)
        module.render_inputs(project)
        st.button(
            f"Remove {module.label.lower()} from the site",
            key=f"remove_{key}",
            on_click=_remove,
            args=(key,),
            help="Its inputs are kept: add it again to bring them back.",
        )
    st.divider()
    st.caption("Coming next: greenhouses, wastewater treatment, district heating, food processing.")
    return key
