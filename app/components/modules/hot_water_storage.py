"""Hot water storage inputs (docs/models/hot-water-storage.md, D-046).

Scaled in inputs (D-041): its block on the map is sized from the tank
cylinder(s) plus a buffer, and is dragged / resized / rotated like the data
center block.
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
    HWS_INPUTS,
    KW_PER_MW,
    M_PER_FT,
    SQFT_TO_M2,
    HwsConnection,
    HwsTankType,
)
from core.domain.modules import HotWaterStorageParams
from core.persistence.project import Project
from core.site_layout import module_context, reset_block_shape
from core.timeseries import columns as col
from core.timeseries.columns import SERIES_1, SERIES_2, SERIES_8

P = f"{state.WIDGET_PREFIX}hws_"
_FIELDS = tuple(
    f
    for f in HotWaterStorageParams.model_fields
    if f not in ("enabled", "footprint", "tank_volume_m3")
)
KEY = "hot_water_storage"
THERMOCLINE_WARNING = (
    "Thermocline modeling assumes perfect stratification, actual performance will "
    "require degraded low SOC performance"
)
_LABELS = {
    HwsConnection.DIRECT: "Direct",
    HwsConnection.INDIRECT: "Indirect",
    HwsTankType.TWO_TANK: "Two tank",
    HwsTankType.THERMOCLINE: "Thermocline",
}


def _changed() -> None:
    values: dict[str, Any] = {f: st.session_state[P + f] for f in _FIELDS}
    current = state.get_project().modules.hot_water_storage
    try:
        params = HotWaterStorageParams(
            enabled=current.enabled, footprint=current.footprint, **values
        )
    except ValidationError as e:
        state.flash("modules", "error", str(e.errors()[0]["msg"]))
        return
    p = state.get_project()
    p = p.model_copy(update={"modules": p.modules.model_copy(update={KEY: params})})
    if params.tank_type is not current.tank_type:
        p = reset_block_shape(p, KEY)  # square ↔ 2:1 default shape
    state.set_project(p)


def _reposition() -> None:
    """Drop the footprint; the layout rules place it beside the data center again."""
    p = state.get_project()
    state.set_project(p.model_copy(update={"modules": p.modules.with_footprint(KEY, None)}))


def _radio(label: str, field: str, options: list[Any], help: str) -> None:
    st.radio(
        label,
        options,
        format_func=lambda o: _LABELS[o],
        key=P + field,
        on_change=_changed,
        horizontal=True,
        help=help,
    )


def render_inputs(project: Project) -> None:
    hws = project.modules.hot_water_storage
    for f in _FIELDS:
        state.seed(P + f, getattr(hws, f))
    i = HWS_INPUTS
    t = i.storage_hours
    st.slider(
        f"Heat storage ({t.units})",
        float(t.min),
        float(t.max),
        step=float(t.step),
        format="%.0f h",
        key=P + "storage_hours",
        on_change=_changed,
        help="Hours of data center heat (IT + parasitics) the tank holds. "
        "Volume = IT kW × (1 + parasitic frac) × h × 3600 / "
        "((T_return − T_supply) × 4.18 × 992).",
    )
    _radio(
        "Connection",
        "connection",
        list(HwsConnection),
        f"Direct: tank water is the loop water (no pinch). Indirect: through a heat "
        f"exchanger with a {i.pinch_indirect_c:g} K pinch on each end.",
    )
    _radio(
        "Tank type",
        "tank_type",
        list(HwsTankType),
        "Two tank: one cold and one hot tank, each holding the full volume. Thermocline: one tank.",
    )
    if hws.tank_type is HwsTankType.THERMOCLINE:
        st.markdown(f":red[{THERMOCLINE_WARNING}]")
    h = i.tank_height_m
    st.number_input(
        f"Tank height ({h.units})",
        float(h.min),
        float(h.max),
        step=float(h.step),
        format="%.1f",
        key=P + "tank_height_m",
        on_change=_changed,
        help=f"Sets the tank diameter. The default block adds {i.buffer_ft:g} ft each side.",
    )
    resolved = hws.resolved(module_context(project))
    c1, c2, c3 = st.columns(3)
    c1.metric("Volume per tank", f"{resolved.volume_m3:,.0f} m³")
    c2.metric("Diameter", f"{resolved.tank_diameter_m / M_PER_FT:,.0f} ft")
    c3.metric("Footprint", f"{resolved.block_area_m2 / SQFT_TO_M2:,.0f} sqft")
    if hws.placed and hws.footprint is not None:
        st.markdown("**Placement**")
        render_block_controls(
            KEY,
            hws.footprint,
            key_prefix=f"{P}block_",
            reposition_label="Place beside data center",
            reposition=_reposition,
        )
    elif project.site.location is None:
        st.caption("Set the project location to place the hot water storage block.")
    st.caption(
        "Control (Step 1): charge only — the tanks take mechanical cooling demand (before "
        "ice storage and the chillers) until the cold tank is empty."
    )


# --- module output (02-results.md → Module output) --------------------------------


def _text(df: pd.DataFrame) -> list[Metric]:
    return [
        Metric("Heat stored", fmt(float(df[col.HWS_CHARGE_KWTH].sum()) / KW_PER_MW, "MWh_th/yr")),
        Metric(
            "Heat delivered", fmt(float(df[col.HWS_DISCHARGE_KWTH].sum()) / KW_PER_MW, "MWh_th/yr")
        ),
    ]


OUTPUTS = ModuleOutputs(
    panels=(
        Panel(
            "Hot water storage state of charge",
            "%",
            (Trace(col.HWS_SOC_FRAC, "State of charge", SERIES_8, PCT_PER_FRAC),),
        ),
        Panel(
            "Tank temperatures",
            "°C",
            (
                Trace(col.HWS_T_HOT_C, "Hot tank", SERIES_2),
                Trace(col.HWS_T_COLD_C, "Cold tank", SERIES_1),
            ),
        ),
    ),
    text=_text,
)
