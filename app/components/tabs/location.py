"""Location tab: address or lat/lon, and framing the map (01-setup-tabs.md §1).

The map is free to pan/zoom on this tab only; the framed view is saved and
becomes the fixed view on every other tab (D-027).
"""

import streamlit as st

from app import state
from app.components.edits import set_site
from core.domain.site import Site
from services.geocode import GeocodeError, GeocodeResult, geocode

P = state.WIDGET_PREFIX
K_ADDRESS, K_LAT, K_LON = f"{P}address", f"{P}lat", f"{P}lon"
NOTE = "Select a location for the project. Ensure the map shows the entire property in question."


@st.cache_data(show_spinner="Looking up address…")
def _geocode(address: str) -> GeocodeResult | None:
    return geocode(address)


def _relocate(lat: float, lon: float, address: str) -> None:
    """New location: recentre the map there; the old framed view no longer applies."""
    set_site(lat=lat, lon=lon, address=address, map_view=None, map_center=None, map_zoom=None)
    st.session_state[K_LAT], st.session_state[K_LON] = lat, lon
    state.bump_map_version()


def _find_address() -> None:
    try:
        r = _geocode(str(st.session_state.get(K_ADDRESS, "")))
    except GeocodeError as e:
        state.flash("location", "error", str(e))
        return
    if r is None:
        state.flash("location", "warning", "No match for that address. Try lat/lon.")
        return
    _relocate(r.lat, r.lon, r.label)
    state.flash("location", "success", r.label)


def _coords_changed() -> None:
    lat, lon = st.session_state.get(K_LAT), st.session_state.get(K_LON)
    if lat is not None and lon is not None:
        _relocate(float(lat), float(lon), "")


def _use_map_center() -> None:
    view = state.get_project().site.map_view
    if view is None:
        return
    s, w, n, e = view
    lat, lon = (s + n) / 2, (w + e) / 2
    # Keep the user's framing: only the location marker moves.
    set_site(lat=lat, lon=lon, address="")
    st.session_state[K_LAT], st.session_state[K_LON] = lat, lon


def render(site: Site) -> None:
    st.caption(NOTE)
    state.seed(K_ADDRESS, site.address)
    state.seed(K_LAT, site.lat)
    state.seed(K_LON, site.lon)
    c1, c2 = st.columns([0.75, 0.25], vertical_alignment="bottom")
    with c1:
        st.text_input("Street address", key=K_ADDRESS, placeholder="Address, city, state")
    with c2:
        st.button("Find", on_click=_find_address, width="stretch")
    state.show_flash("location")
    c1, c2 = st.columns(2)
    with c1:
        st.number_input(
            "Latitude (°)", -90.0, 90.0, key=K_LAT, format="%.6f", on_change=_coords_changed
        )
    with c2:
        st.number_input(
            "Longitude (°)", -180.0, 180.0, key=K_LON, format="%.6f", on_change=_coords_changed
        )
    st.button(
        "Use map center as location",
        on_click=_use_map_center,
        disabled=site.map_view is None,
        help="Pan the map to the site, then set the location to the map's center.",
    )
    if site.location is not None:
        st.caption(
            "Pan and zoom until the whole property is in view — the Property and Data center "
            "tabs use this view."
        )
