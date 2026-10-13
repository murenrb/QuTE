"""Brine separation inputs (docs/models/brine-separation.md, D-048).

Scaled in inputs (D-041): one 12 m tall tank; its block on the map is a square
of the tank diameter + 20 ft each side, dragged / resized / rotated like the
data center block.
"""

from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from app import state
from app.components.block_controls import render_block_controls
from app.components.metrics import Metric
from app.components.module_outputs import PCT_PER_FRAC, ModuleOutputs, Panel, Trace, fmt
from core.config.defaults import (
    BRINE_INPUTS,
    BRINES,
    GAL_PER_KG_WATER,
    KG_PER_TONNE,
    M_PER_FT,
    SQFT_TO_M2,
    BrineType,
)
from core.domain.modules import BrineSeparationParams
from core.persistence.project import Project
from core.site_layout import module_context
from core.timeseries import columns as col
from core.timeseries.columns import SERIES_9

P = f"{state.WIDGET_PREFIX}brine_"
KEY = "brine_separation"
K_CONC = P + "conc_wt_pct"  # one two-sided slider for the low and high fields
_FIELDS = ("brine_type", "concentrate_hours")


def _changed() -> None:
    values: dict[str, Any] = {f: st.session_state[P + f] for f in _FIELDS}
    lo, hi = st.session_state[K_CONC]
    current = state.get_project().modules.brine_separation
    try:
        params = BrineSeparationParams(
            enabled=current.enabled,
            footprint=current.footprint,
            conc_low_wt_pct=float(lo),
            conc_high_wt_pct=float(hi),
            **values,
        )
    except ValidationError as e:
        state.flash("modules", "error", str(e.errors()[0]["msg"]).removeprefix("Value error, "))
        return
    p = state.get_project()
    state.set_project(p.model_copy(update={"modules": p.modules.model_copy(update={KEY: params})}))


def _reposition() -> None:
    """Drop the footprint; the layout rules place it beside the data center again."""
    p = state.get_project()
    state.set_project(p.model_copy(update={"modules": p.modules.with_footprint(KEY, None)}))


def render_inputs(project: Project) -> None:
    br = project.modules.brine_separation
    for f in _FIELDS:
        state.seed(P + f, getattr(br, f))
    state.seed(K_CONC, (br.conc_low_wt_pct, br.conc_high_wt_pct))
    i = BRINE_INPUTS
    st.selectbox(
        "Brine type",
        list(BrineType),
        format_func=lambda b: BRINES[b].label,
        key=P + "brine_type",
        on_change=_changed,
    )
    c = i.conc_wt_pct
    st.slider(
        "Concentration range (wt%)",
        float(c.min),
        float(c.max),
        step=float(c.step),
        format="%g wt%%",
        key=K_CONC,
        on_change=_changed,
        help="The tank starts full at the low concentration; it stops taking heat at the "
        "high concentration (or earlier, when the coolant is too warm for the brine to "
        "boil and condense).",
    )
    h = i.concentrate_hours
    st.slider(
        f"Time to concentrate tank ({h.units})",
        float(h.min),
        float(h.max),
        step=float(h.step),
        format="%.0f h",
        key=P + "concentrate_hours",
        on_change=_changed,
        help="Hours of full data center heat (IT + parasitics) to go from the low to the "
        "high concentration. Sets the tank size.",
    )
    resolved = br.resolved(module_context(project))
    c1, c2, c3 = st.columns(3)
    c1.metric("Brine", f"{resolved.mass_kg / KG_PER_TONNE:,.0f} t")
    c2.metric("Tank", f"{resolved.tank_volume_m3:,.0f} m³")
    c3.metric("Footprint", f"{resolved.block_area_m2 / SQFT_TO_M2:,.0f} sqft")
    st.caption(
        f"One {i.tank_height_m:g} m tall tank, "
        f"{resolved.tank_diameter_m / M_PER_FT:,.0f} ft across; the block adds "
        f"{i.buffer_ft:g} ft each side."
    )
    if br.placed and br.footprint is not None:
        st.markdown("**Placement**")
        render_block_controls(
            KEY,
            br.footprint,
            key_prefix=f"{P}block_",
            reposition_label="Place beside data center",
            reposition=_reposition,
        )
    elif project.site.location is None:
        st.caption("Set the project location to place the brine separation block.")
    st.caption(
        "Control (Step 1): first in the stack — takes all the data center's heat whenever "
        "the temperatures work, until the high concentration. No brine in or out; the "
        "recovered water isn't used yet."
    )


# --- module output (02-results.md → Module output) --------------------------------


def _text(df: pd.DataFrame) -> list[Metric]:
    c = df[col.BRINE_CONC_WT_PCT]
    water_gal = float(df[col.BRINE_WATER_OUT_KG_H].sum()) * GAL_PER_KG_WATER
    return [
        Metric("Min concentration", fmt(float(c.min()), "wt%", 1)),
        Metric("Max concentration", fmt(float(c.max()), "wt%", 1)),
        Metric("Water produced", fmt(water_gal, "gal/yr")),
    ]


OUTPUTS = ModuleOutputs(
    panels=(
        Panel(
            "Brine tank state of charge",
            "%",
            (Trace(col.BRINE_SOC_FRAC, "Brine tank", SERIES_9, PCT_PER_FRAC),),
        ),
        Panel(
            "Brine concentration",
            "wt%",
            (Trace(col.BRINE_CONC_WT_PCT, "Concentration", SERIES_9),),
        ),
    ),
    text=_text,
)
