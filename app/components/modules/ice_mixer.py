"""Ice mixer inputs (docs/models/ice-mixer.md, D-050).

No footprint: the mixer is equipment inside the other blocks, so nothing is
drawn or placed on the map.
"""

from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from app import state
from app.components.metrics import Metric
from app.components.module_outputs import MW_PER_KW, ModuleOutputs, Panel, Trace, fmt
from core.config.defaults import ICE_MIXER_INPUTS, IceMixerFluid, SliderSpec
from core.domain.modules import IceMixerParams
from core.persistence.project import Project
from core.timeseries import columns as col
from core.timeseries.columns import SERIES_1, SERIES_3

P = f"{state.WIDGET_PREFIX}imix_"
_FIELDS = tuple(f for f in IceMixerParams.model_fields if f != "enabled")
KEY = "ice_mixer"
_FLUID_LABELS = {IceMixerFluid.WATER: "Water", IceMixerFluid.BRINE: "Brine"}


def _changed() -> None:
    current = state.get_project().modules.ice_mixer
    # The brine sliders aren't drawn on water: keep their saved values.
    values: dict[str, Any] = {f: st.session_state.get(P + f, getattr(current, f)) for f in _FIELDS}
    try:
        params = IceMixerParams(enabled=current.enabled, **values)
    except ValidationError as e:
        state.flash("modules", "error", str(e.errors()[0]["msg"]))
        return
    p = state.get_project()
    state.set_project(p.model_copy(update={"modules": p.modules.model_copy(update={KEY: params})}))


def _slider(label: str, field: str, spec: SliderSpec, help: str) -> None:
    st.slider(
        f"{label} ({spec.units})",
        float(spec.min),
        float(spec.max),
        step=float(spec.step),
        format="%.0f%%",
        key=P + field,
        on_change=_changed,
        help=help,
    )


def _brine_sliders() -> None:
    i = ICE_MIXER_INPUTS
    _slider(
        "Recuperation efficiency",
        "recup_eta_pct",
        i.recup_eta_pct,
        "Catch-all for imperfectly recuperated streams: cooling per kg of ice × this.",
    )
    _slider(
        "Mixing efficiency",
        "mix_eta_pct",
        i.mix_eta_pct,
        "Mixed temperature = incoming brine freeze point × this. 100 % would need "
        "unlimited brine (impossible), so the maximum is 90 %; lower is warmer and needs "
        "less brine.",
    )


def render_inputs(project: Project) -> None:
    mix = project.modules.ice_mixer
    for f in _FIELDS:
        state.seed(P + f, getattr(mix, f))
    st.radio(
        "Fluid",
        list(IceMixerFluid),
        format_func=lambda o: _FLUID_LABELS[o],
        key=P + "fluid",
        on_change=_changed,
        horizontal=True,
        help="Water: ice melts at 0 °C and the melt water returns to ice storage. Brine: "
        "concentrated brine from brine separation is diluted to cool below 0 °C.",
    )
    if mix.fluid is IceMixerFluid.BRINE:  # water: melts at 0 °C, neither applies (owner)
        _brine_sliders()
    if mix.fluid is IceMixerFluid.BRINE and not project.modules.brine_separation.enabled:
        st.warning("The brine mixer takes its brine from brine separation: add that module too.")
    if not project.modules.ice_storage.enabled:
        st.warning("The ice mixer takes its ice from ice storage: add that module too.")
    st.caption(
        "Cools what the Control tab's THENs link it to. Each hour the solver settles the "
        "ice (and brine) it actually gets; the chillers carry the rest."
    )


# --- module output (02-results.md → Module output) --------------------------------


def _text(df: pd.DataFrame) -> list[Metric]:
    t = df.loc[df[col.ICE_MIX_Q_KWTH] > 0, col.ICE_MIX_T_C]  # hours it cools
    return [
        Metric("Median cooling temperature", fmt(float(t.median()), "°C", 1)),
        Metric("Min cooling temperature", fmt(float(t.min()), "°C", 1)),
    ]


OUTPUTS = ModuleOutputs(
    panels=(
        Panel(
            "Ice mixer cooling",
            "MW_th",
            (Trace(col.ICE_MIX_Q_KWTH, "Cooling", SERIES_3, MW_PER_KW),),
        ),
        Panel(
            "Ice mixer temperature", "°C", (Trace(col.ICE_MIX_T_C, "Mixed temperature", SERIES_1),)
        ),
    ),
    text=_text,
)
