"""Property tab: draw the boundary with the (only) polygon tool (01-setup-tabs.md §2)."""

import streamlit as st

from app import state
from app.components.edits import set_site
from core.config.defaults import SQFT_PER_ACRE, SQFT_TO_M2
from core.domain.site import Site
from core.geometry.boundary import BoundaryError, boundary_metrics

NOTE = "Use the polygon tool to select the limits of the property."


def _clear_boundary() -> None:
    set_site(boundary=())
    state.bump_map_version()  # remount with the polygon tool armed again


def _outside_view(site: Site) -> bool:
    if site.map_view is None:
        return False
    s, w, n, e = site.map_view
    return any(not (s <= lat <= n and w <= lon <= e) for lat, lon in site.boundary)


def render(site: Site) -> None:
    if site.location is None:
        st.info("Set the project location on the Location tab first.")
        return
    st.caption(NOTE)
    state.show_flash("property")
    if len(site.boundary) < 3:
        st.caption("Click each corner on the map; click the first corner again to close.")
        return
    try:
        m = boundary_metrics(site.boundary)
    except BoundaryError as e:
        st.error(str(e))
        m = None
    if m is not None:
        area_sqft = m.area_m2 / SQFT_TO_M2
        c1, c2, c3 = st.columns(3)
        c1.metric("Area", f"{area_sqft / SQFT_PER_ACRE:,.2f} acres")
        c2.metric("Area", f"{area_sqft:,.0f} sqft")
        c3.metric("Corners", len(site.boundary))
    if _outside_view(site):
        st.warning("Part of the boundary is outside the map view set on the Location tab.")
    st.button("Clear boundary and redraw", on_click=_clear_boundary)
