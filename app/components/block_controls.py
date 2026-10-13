"""Precise controls for any block on the map — the data center or a
scaled-in-inputs module (D-030, D-041): width / length (area held), rotation,
reposition, align to the property edge. They mirror the block and change it
through callbacks, staying in sync with the map editor.
"""

import math
from collections.abc import Callable

import streamlit as st

from app import state
from core.config.defaults import FOOTPRINT, M_PER_FT
from core.domain.site import Footprint
from core.geometry.footprint import align_to_nearest_edge, with_length, with_width
from core.site_layout import blocks, set_block_footprint

EDITOR_HELP = (
    "On the map: drag the block to move it · drag an edge handle to resize (area stays "
    "the same) · drag the ◆ knob to rotate (hold Shift to snap to 15°)."
)


def _current(owner: str) -> Footprint | None:
    return next((b.footprint for b in blocks(state.get_project()) if b.owner == owner), None)


def _update(owner: str, change: Callable[[Footprint], Footprint]) -> None:
    fp = _current(owner)
    if fp is not None:
        p = state.get_project()
        state.set_project(set_block_footprint(p, owner, change(fp)))


def _width(owner: str, key: str) -> None:
    _update(owner, lambda fp: with_width(fp, float(st.session_state[key]) * M_PER_FT, FOOTPRINT))


def _length(owner: str, key: str) -> None:
    _update(owner, lambda fp: with_length(fp, float(st.session_state[key]) * M_PER_FT, FOOTPRINT))


def _rotation(owner: str, key: str) -> None:
    _update(owner, lambda fp: fp.model_copy(update={"rotation_deg": float(st.session_state[key])}))


def _align(owner: str) -> None:
    boundary = state.get_project().site.boundary
    if len(boundary) >= 3:
        _update(owner, lambda fp: align_to_nearest_edge(fp, boundary))


def render_block_controls(
    owner: str,
    fp: Footprint,
    key_prefix: str,
    reposition_label: str,
    reposition: Callable[[], None],
) -> None:
    """Width/length/rotation inputs + reposition/align buttons for one block."""
    k_w, k_l, k_r = f"{key_prefix}width_ft", f"{key_prefix}length_ft", f"{key_prefix}rotation_deg"
    # The footprint is the source of truth; widgets only mirror it and change it
    # through callbacks (their stored floats are lower precision than ours).
    for key, metres in ((k_w, fp.width_m), (k_l, fp.length_m)):
        ft = metres / M_PER_FT
        if not math.isclose(float(st.session_state.get(key, -1.0)), ft, rel_tol=1e-6):
            st.session_state[key] = ft
    st.session_state[k_r] = round(fp.rotation_deg) % 180

    area = fp.area_m2
    side_min_ft = math.sqrt(area / FOOTPRINT.max_aspect) / M_PER_FT
    side_max_ft = math.sqrt(area / FOOTPRINT.min_aspect) / M_PER_FT
    st.caption(EDITOR_HELP)
    c1, c2 = st.columns(2)
    with c1:
        st.number_input(
            "Width (ft)",
            side_min_ft,
            side_max_ft,
            step=5.0,
            format="%.0f",
            key=k_w,
            on_change=_width,
            args=(owner, k_w),
            help="East–west side at 0° rotation. The length adjusts so the area stays the same.",
        )
    with c2:
        st.number_input(
            "Length (ft)",
            side_min_ft,
            side_max_ft,
            step=5.0,
            format="%.0f",
            key=k_l,
            on_change=_length,
            args=(owner, k_l),
            help="North–south side at 0° rotation. The width adjusts so the area stays the same.",
        )
    st.slider(
        "Rotation (clockwise)",
        0,
        179,
        key=k_r,
        format="%d°",
        on_change=_rotation,
        args=(owner, k_r),
    )
    has_boundary = len(state.get_project().site.boundary) >= 3
    c1, c2 = st.columns(2)
    with c1:
        st.button(
            reposition_label,
            key=f"{key_prefix}reposition",
            on_click=reposition,
            width="stretch",
        )
    with c2:
        st.button(
            "Align to property edge",
            key=f"{key_prefix}align",
            on_click=_align,
            args=(owner,),
            disabled=not has_boundary,
            width="stretch",
            help="Rotate so the block's width runs parallel to the nearest boundary side.",
        )
