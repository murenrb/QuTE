"""Greenhouse inputs (docs/models/greenhouse.md, D-061). Size comes from the
drawn area (its floor area)."""

from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from app import state
from app.components.metrics import Metric
from app.components.module_outputs import MW_PER_KW, ModuleOutputs, Panel, Trace, fmt
from core.config.defaults import (
    GREENHOUSE_INPUTS,
    KW_PER_MW,
    SQFT_TO_M2,
    W_M2K_PER_BTU_HFT2F,
    SliderSpec,
)
from core.domain.modules import GreenhouseParams
from core.geometry.areas import area_m2
from core.models.greenhouse import can_heat, coil_water_c
from core.persistence.project import Project
from core.timeseries import columns as col
from core.timeseries.columns import SERIES_1, SERIES_2, SERIES_4, SERIES_8, SERIES_10

P = f"{state.WIDGET_PREFIX}gh_"
KEY = "greenhouse"
# Fields edited by the sliders; `area` comes from the map.
_FIELDS = tuple(f for f in GreenhouseParams.model_fields if f not in ("enabled", "area"))


def _changed() -> None:
    p = state.get_project()
    gh = p.modules.greenhouse
    values: dict[str, Any] = {f: st.session_state[P + f] for f in _FIELDS}
    try:
        params = GreenhouseParams(enabled=gh.enabled, area=gh.area, **values)
    except ValidationError as e:
        state.flash("modules", "error", str(e.errors()[0]["msg"]))
        return
    state.set_project(p.model_copy(update={"modules": p.modules.model_copy(update={KEY: params})}))


def _slider(label: str, field: str, spec: SliderSpec, fmt_: str, help: str) -> None:
    st.slider(
        f"{label} ({spec.units})",
        float(spec.min),
        float(spec.max),
        step=float(spec.step),
        format=fmt_,
        key=P + field,
        on_change=_changed,
        help=help,
    )


def render_inputs(project: Project) -> None:
    gh = project.modules.greenhouse
    for f in _FIELDS:
        state.seed(P + f, getattr(gh, f))
    i = GREENHOUSE_INPUTS
    if gh.placed:
        floor_m2 = area_m2(gh.area)
        c1, c2 = st.columns(2)
        c1.metric("Floor area", f"{floor_m2 / SQFT_TO_M2:,.0f} sqft")
        c2.metric("Glass area", f"{floor_m2 * i.cover_to_floor_ratio / SQFT_TO_M2:,.0f} sqft")
    _slider(
        "Glass transmissivity",
        "transmissivity_pct",
        i.transmissivity_pct,
        "%.0f%%",
        "Share of the sun (GHI) that gets through the glass.",
    )
    _slider(
        "Temperature setpoint",
        "t_set_c",
        i.t_set_c,
        "%.1f °C",
        "Inside air temperature the heating holds.",
    )
    _slider(
        "Covering U-value",
        "u_w_m2k",
        i.u_w_m2k,
        "%.1f",
        "Overall heat loss of the covering per m² of glass and K between inside and "
        "outside air. Guides list it in Btu/h·ft²·°F: × 5.678 = W/m²K.",
    )
    st.caption(  # under the slider, for users who don't know the term (owner)
        f"Typical values by covering (Table 1, Btu/h·ft²·°F): [Texas A&M AgriLife — "
        f"Greenhouse heating requirements]({i.u_guide_url}). "
        f"{gh.u_w_m2k:g} W/m²K = {gh.u_w_m2k / W_M2K_PER_BTU_HFT2F:.2f} Btu/h·ft²·°F."
    )
    t = project.facilities[0].dc_type if project.facilities else None
    if t is not None and not can_heat(t.t_return_c, gh.t_set_c):
        st.warning(
            f"The data center's return water ({t.t_return_c:g} °C) is not warmer than the "
            f"setpoint + {i.coil_approach_c:g} K coil approach "
            f"({coil_water_c(gh.t_set_c):g} °C), so it can't heat the greenhouse."
        )
    st.caption(
        "Heat comes through a water → air coil from the data center's return water and / or "
        'hot water storage, as Control-tab THENs link them ("Greenhouse: Takes heat from …", '
        f"in order). The water leaves the coil at {coil_water_c(gh.t_set_c):g} °C (setpoint + "
        f"{i.coil_approach_c:g} K); surplus sun is vented."
    )


# --- module output (02-results.md → Module output) --------------------------------


def _text(df: pd.DataFrame) -> list[Metric]:
    demand_kwh = float(df[col.GREENHOUSE_DEMAND_KWTH].sum())
    from_hws_kwh = float(df[col.GREENHOUSE_HEAT_HWS_KWTH].sum())
    from_dc_kwh = float(df[col.GREENHOUSE_HEAT_KWTH].sum())
    unmet_kwh = float(df[col.GREENHOUSE_UNMET_KWTH].sum())
    peak_mw = float(df[col.GREENHOUSE_DEMAND_KWTH].max()) / KW_PER_MW
    return [
        Metric("Heating demand", fmt(demand_kwh / KW_PER_MW, "MWh_th/yr")),
        Metric("Heat from the data center", fmt(from_dc_kwh / KW_PER_MW, "MWh_th/yr")),
        Metric("Heat from hot water storage", fmt(from_hws_kwh / KW_PER_MW, "MWh_th/yr")),
        Metric("Heat not met", fmt(unmet_kwh / KW_PER_MW, "MWh_th/yr")),
        Metric("Peak heating demand", fmt(peak_mw, "MW_th", 2)),
        Metric("Hours heating", fmt(float((df[col.GREENHOUSE_DEMAND_KWTH] > 0).sum()), "h")),
    ]


OUTPUTS = ModuleOutputs(
    panels=(
        Panel(
            "Greenhouse heating",
            "MW_th",
            (
                Trace(col.GREENHOUSE_DEMAND_KWTH, "Demand", SERIES_1, MW_PER_KW),
                Trace(col.GREENHOUSE_HEAT_KWTH, "From data center", SERIES_10, MW_PER_KW),
                Trace(col.GREENHOUSE_HEAT_HWS_KWTH, "From hot water storage", SERIES_8, MW_PER_KW),
            ),
        ),
        Panel(
            "Greenhouse heat balance",
            "MW_th",
            (
                Trace(col.GREENHOUSE_LOSS_KWTH, "Loss through glass", SERIES_2, MW_PER_KW),
                Trace(col.GREENHOUSE_SOLAR_KWTH, "Solar gain", SERIES_4, MW_PER_KW),
            ),
        ),
    ),
    text=_text,
)
