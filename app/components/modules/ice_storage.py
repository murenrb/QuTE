"""Ice storage inputs (docs/models/ice-storage.md).

Scaled in inputs (D-041): its block on the map has area = tank capacity /
energy density, and is dragged / resized / rotated like the data center block.
"""

from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from app import state
from app.components.block_controls import render_block_controls
from app.components.metrics import Metric
from app.components.module_outputs import PCT_PER_FRAC, ModuleOutputs, Panel, Trace, fmt
from app.components.modules.log_slider import log_stops
from core.config.defaults import (
    ICE_INPUTS,
    ICE_LATENT_HEAT_KJ_KG,
    KG_PER_TONNE,
    KW_PER_MW,
    KW_PER_TR,
    SECONDS_PER_HOUR,
    SliderSpec,
)
from core.domain.modules import IceStorageParams
from core.models.ice_storage import HOURLY_DT_H
from core.persistence.project import Project
from core.site_layout import module_context
from core.timeseries import columns as col
from core.timeseries.columns import SERIES_1, SERIES_2

P = f"{state.WIDGET_PREFIX}ice_"
# Footprint comes from the map / block controls, not from these inputs.
# Footprint comes from the map; the size has its own (log) slider and callback
# because None means "follow the IT load" (D-042).
_FIELDS = tuple(
    f
    for f in IceStorageParams.model_fields
    if f not in ("enabled", "footprint", "ice_maker_size_tr")
)
KEY = "ice_storage"
K_SIZE = P + "size_tr"


def size_stops(including: float) -> list[float]:
    """Log-spaced TR options across the allowed range, plus `including`."""
    spec = ICE_INPUTS.ice_maker_size_tr
    return log_stops(spec.min, spec.max, including)


def _changed() -> None:
    values: dict[str, Any] = {f: st.session_state[P + f] for f in _FIELDS}
    current = state.get_project().modules.ice_storage
    try:
        params = IceStorageParams(
            enabled=current.enabled,
            footprint=current.footprint,
            ice_maker_size_tr=current.ice_maker_size_tr,
            **values,
        )
    except ValidationError as e:
        state.flash("modules", "error", str(e.errors()[0]["msg"]))
        return
    p = state.get_project()
    state.set_project(
        p.model_copy(update={"modules": p.modules.model_copy(update={"ice_storage": params})})
    )


def _set_size(size: float | None) -> None:
    p = state.get_project()
    ice = p.modules.ice_storage.model_copy(update={"ice_maker_size_tr": size})
    state.set_project(
        p.model_copy(update={"modules": p.modules.model_copy(update={"ice_storage": ice})})
    )


def _size_moved() -> None:
    _set_size(float(st.session_state[K_SIZE]))  # the user's own size from now on


def _reposition() -> None:
    """Drop the footprint; the layout rules place it beside the data center again."""
    p = state.get_project()
    state.set_project(p.model_copy(update={"modules": p.modules.with_footprint(KEY, None)}))


def _number(label: str, field: str, spec: SliderSpec, fmt: str, help: str | None = None) -> None:
    st.number_input(
        f"{label} ({spec.units})" if spec.units else label,
        float(spec.min),
        float(spec.max),
        step=float(spec.step),
        format=fmt,
        key=P + field,
        on_change=_changed,
        help=help,
    )


def _coeff(label: str, field: str) -> None:
    st.number_input(label, key=P + field, format="%.5f", step=0.0001, on_change=_changed)


def render_inputs(project: Project) -> None:
    ice = project.modules.ice_storage
    for f in _FIELDS:
        state.seed(P + f, getattr(ice, f))
    i = ICE_INPUTS
    resolved = ice.resolved(module_context(project))
    size = float(resolved.ice_maker_size_tr or 0)
    st.session_state[K_SIZE] = round(size, 6)  # mirror (follows the IT load until moved)
    st.select_slider(
        "Ice maker size (TR)",
        options=size_stops(size),
        key=K_SIZE,
        format_func=lambda v: f"{v:,.0f} TR",
        on_change=_size_moved,
        help=f"Logarithmic scale. Default {i.tr_per_mw_it:g} TR per MW of IT load. "
        f"1 TR = {KW_PER_TR:.4f} kW_th.",
    )
    if ice.ice_maker_size_tr is None:
        st.caption(f"= {i.tr_per_mw_it:g} TR per MW of IT load")
    else:
        st.button(
            f"Use {i.tr_per_mw_it:g} TR per MW of IT load",
            key="ice_size_follow",
            on_click=_set_size,
            args=(None,),
        )
    t = i.tank_charge_time_h
    st.slider(
        f"Tank size ({t.units})",
        float(t.min),
        float(t.max),
        step=float(t.step),
        format="%.0f h",
        key=P + "tank_charge_time_h",
        on_change=_changed,
        help="Hours of ice-maker nameplate output the tank holds.",
    )
    _number(
        "Starting ice tank state of charge",
        "soc_start_frac",
        i.soc_start_frac,
        "%.2f",
        "Ice tank fullness at the first hour of the year (0–1)",
    )
    _number(
        "Starting water tank state of charge",
        "water_soc_start_frac",
        i.water_soc_start_frac,
        "%.2f",
        "Water tank fullness at the first hour of the year (0–1). The ice maker freezes "
        "this water into the ice tank.",
    )
    _number(
        "Energy density",
        "energy_density_kwh_sqft",
        i.energy_density_kwh_sqft,
        "%.1f",
        "Stored kWh_th per sqft of footprint. Footprint = tank kWh_th / density.",
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Ice maker", f"{resolved.ice_maker_kwth:,.0f} kW_th")
    c2.metric("Tank", f"{resolved.tank_capacity_kwh:,.0f} kWh_th")
    c3.metric("Footprint", f"{resolved.footprint_sqft:,.0f} sqft")
    if ice.placed and ice.footprint is not None:
        st.markdown("**Placement**")
        render_block_controls(
            KEY,
            ice.footprint,
            key_prefix=f"{P}block_",
            reposition_label="Place beside data center",
            reposition=_reposition,
        )
    elif project.site.location is None:
        st.caption("Set the project location to place the ice storage block.")
    st.caption(
        "Control (Step 1): ice making always allowed. Nothing uses ice yet, so the ice "
        "tank fills from the water tank and then waits."
    )
    with st.expander("Ice maker performance curves"):
        st.caption("y = a·t² + b·t + c, t = heat-rejection ambient °C; capped at the max.")
        st.number_input(
            "COP max (min. discharge pressure)",
            key=P + "cop_max",
            format="%.2f",
            step=0.1,
            min_value=0.01,
            on_change=_changed,
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            _coeff("COP a", "cop_coeff_a")
        with c2:
            _coeff("COP b", "cop_coeff_b")
        with c3:
            _coeff("COP c", "cop_coeff_c")
        st.number_input(
            "Capacity factor max (min. discharge pressure)",
            key=P + "capacity_factor_max",
            format="%.3f",
            step=0.01,
            min_value=0.01,
            on_change=_changed,
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            _coeff("Capacity a", "capacity_coeff_a")
        with c2:
            _coeff("Capacity b", "capacity_coeff_b")
        with c3:
            _coeff("Capacity c", "capacity_coeff_c")


# --- module output (02-results.md → Module output) --------------------------------


def _text(df: pd.DataFrame) -> list[Metric]:
    made_kwth = df[col.ICE_INSTANT_KWTH] + df[col.ICE_CHARGE_KWTH]  # ice maker duty
    t_per_kwh = SECONDS_PER_HOUR / ICE_LATENT_HEAT_KJ_KG / KG_PER_TONNE
    per_day = (made_kwth * HOURLY_DT_H * t_per_kwh).resample("D").sum()
    total = float(made_kwth.sum())
    # Production-weighted: each hour's rate counts in proportion to the ice it made.
    weighted_tr = float((made_kwth**2).sum()) / total / KW_PER_TR if total > 0 else float("nan")
    return [
        Metric("Median ice made per day", fmt(float(per_day.median()), "t/day")),
        Metric("Max ice made per day", fmt(float(per_day.max()), "t/day")),
        Metric("Ice making rate while on (production-weighted)", fmt(weighted_tr, "TR")),
        Metric(
            "Ice maker electricity",
            fmt(float(df[col.ICE_MAKER_ELEC_KW].sum()) / KW_PER_MW, "MWh/yr"),
        ),
    ]


OUTPUTS = ModuleOutputs(
    panels=(
        Panel(
            "Ice storage state of charge",
            "%",
            (
                Trace(col.ICE_SOC_FRAC, "Ice tank", SERIES_1, PCT_PER_FRAC),
                Trace(col.ICE_WATER_SOC_FRAC, "Water tank", SERIES_2, PCT_PER_FRAC),
            ),
        ),
    ),
    text=_text,
)
