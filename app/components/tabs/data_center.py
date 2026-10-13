"""Data center tab: type, IT load, area breakdown, placement (01-setup-tabs.md §3).

The map is locked here; the facility block is the only thing that moves — by
dragging it in the footprint editor (D-030) or with the precise inputs below,
which stay in sync with it.
"""

import math

import streamlit as st

from app import state
from app.components.block_controls import render_block_controls
from app.components.dc_type_form import dc_type_form, dc_type_summary
from app.components.edits import move_block
from app.components.modules import LABELS as MODULE_LABELS
from core.config.defaults import DC_INPUTS, SIZING, SQFT_TO_M2
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.domain.site import Footprint, LatLon, Site
from core.geometry.boundary import BoundaryError, boundary_metrics
from core.geometry.footprint import square_footprint, with_area
from core.persistence.project import Project
from core.site_layout import DATA_CENTER, layout_warnings
from core.sizing.datacenter_area import AreaBreakdown, size_datacenter

P = state.WIDGET_PREFIX
K_TYPE, K_IT = f"{P}dc_type", f"{P}it_load_mw"
PENDING_TYPE = "pending_dc_type"  # set after creating a type; applied before the selectbox
NEW_TYPE = "➕ Create new type…"


def _type_section(current: DataCenterType | None) -> DataCenterType | None:
    st.markdown("**Type**")
    types = state.store().list_types()
    if current is not None and current.name not in {t.name for t in types}:
        types.append(current)  # snapshot from an opened project, not in this library
    by_name = {t.name: t for t in types}
    if PENDING_TYPE in st.session_state:
        st.session_state[K_TYPE] = st.session_state.pop(PENDING_TYPE)
    options = [*by_name, NEW_TYPE]
    state.seed(K_TYPE, current.name if current else options[0])
    if st.session_state[K_TYPE] not in options:
        st.session_state[K_TYPE] = options[0]
    choice = st.selectbox(
        "Choose a saved type or create one", options, key=K_TYPE, label_visibility="collapsed"
    )
    state.show_flash("dc_type")
    if choice == NEW_TYPE:
        outcome = dc_type_form()
        if outcome is not None:
            if outcome.created:
                state.flash("dc_type", "success", f"Saved new type: {outcome.type.name}")
            else:
                state.flash(
                    "dc_type",
                    "info",
                    "An identical type is already saved, so the saved version will be used: "
                    f"{outcome.type.name}",
                )
            st.session_state[PENDING_TYPE] = outcome.type.name
            st.rerun()
        return None
    t = by_name[choice]
    with st.expander("Type details"):
        summary = dc_type_summary(t)
        st.table({"": list(summary), "Value": list(summary.values())})
    return t


def _it_load_section(current_mw: float | None) -> float:
    spec = DC_INPUTS.it_load_peak_mw
    state.seed(K_IT, current_mw if current_mw is not None else float(spec.default))
    mw = st.number_input(
        f"Peak IT load ({spec.units})",
        float(spec.min),
        float(spec.max),
        step=float(spec.step),
        format="%.1f",
        key=K_IT,
        help="Step 1 runs a constant load at this peak every hour.",
    )
    return float(mw)


def _area_section(area: AreaBreakdown) -> None:
    st.markdown("**Area breakdown**")
    rows = {
        "Data hall": area.data_hall_sqft,
        "Backup power": area.backup_power_sqft,
        "Chillers": area.chiller_sqft,  # lumped: chillers + heat rejection (owner)
        "Total": area.total_sqft,
    }
    st.table(
        {
            "Area": list(rows),
            "sqft": [f"{v:,.0f}" for v in rows.values()],
            "m²": [f"{v * SQFT_TO_M2:,.0f}" for v in rows.values()],
        }
    )


def _placement_section(
    previous: Footprint | None, area_m2: float, site: Site, default_center: LatLon
) -> Footprint:
    st.markdown("**Placement**")
    if previous is None:
        fp = square_footprint(default_center, area_m2)
    elif not math.isclose(previous.area_m2, area_m2, rel_tol=1e-9):
        fp = with_area(previous, area_m2)  # sizing changed: keep shape, new area
    else:
        fp = previous
    render_block_controls(
        DATA_CENTER,
        fp,
        key_prefix=f"{P}block_",
        reposition_label="Center in boundary" if len(site.boundary) >= 3 else "Center on location",
        reposition=lambda: move_block(default_center),
    )
    for warning in layout_warnings(state.get_project(), MODULE_LABELS):
        st.warning(warning)
    return fp


def _default_center(site: Site) -> LatLon | None:
    if len(site.boundary) >= 3:
        try:
            return boundary_metrics(site.boundary).centroid
        except BoundaryError:
            pass
    return site.location


def render(project: Project) -> None:
    facility = project.facilities[0] if project.facilities else None
    dc_type = _type_section(facility.dc_type if facility else None)
    it_mw = _it_load_section(facility.it_load_peak_mw if facility else None)
    if dc_type is None:
        return
    try:
        area = size_datacenter(DataCenter(dc_type=dc_type, it_load_peak_mw=it_mw), SIZING)
    except ValueError as e:
        st.error(str(e))
        return
    _area_section(area)

    center = _default_center(project.site)
    if center is None:
        st.caption("Set the project location to place the facility.")
        fp = None
    else:
        fp = _placement_section(
            facility.footprint if facility else None, area.total_m2, project.site, center
        )
    dc = DataCenter(dc_type=dc_type, it_load_peak_mw=it_mw, footprint=fp)
    state.set_project(project.model_copy(update={"facilities": (dc, *project.facilities[1:])}))
