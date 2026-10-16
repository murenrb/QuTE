"""Solar PV inputs (docs/models/solar-pv.md). Size comes from the drawn area."""

from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from app import state
from app.components.metrics import Metric
from app.components.module_outputs import MW_PER_KW, ModuleOutputs, Panel, Trace, fmt
from core.config.defaults import KW_PER_MW, PV_INPUTS, PvArrayType, PvModuleType, SliderSpec
from core.domain.modules import SolarPVParams
from core.models.solar_pv import pv_capacity_kw, resolve_orientation
from core.persistence.project import Project
from core.timeseries import columns as col
from core.timeseries.columns import SERIES_4

P = f"{state.WIDGET_PREFIX}pv_"
ARRAY_LABELS = {
    PvArrayType.FIXED_OPEN_RACK: "Fixed, open rack",
    PvArrayType.FIXED_ROOF_MOUNT: "Fixed, roof mount",
    PvArrayType.ONE_AXIS: "1-axis tracking",
    PvArrayType.ONE_AXIS_BACKTRACKING: "1-axis backtracking",
    PvArrayType.TWO_AXIS: "2-axis tracking",
}
MODULE_LABELS = {
    PvModuleType.STANDARD: "Standard",
    PvModuleType.PREMIUM: "Premium",
    PvModuleType.THIN_FILM: "Thin film",
}
# Inputs that follow the site until the user types a value (None = follow).
_SITE_DEFAULTED = ("tilt_deg", "azimuth_deg")
# Fields edited by the generic callback; `area` comes from the map.
_FIELDS = tuple(
    f for f in SolarPVParams.model_fields if f not in ("enabled", "area", *_SITE_DEFAULTED)
)


def _changed() -> None:
    p = state.get_project()
    values: dict[str, Any] = {f: st.session_state[P + f] for f in _FIELDS}
    pv = p.modules.solar_pv
    try:
        kept = {f: getattr(pv, f) for f in ("enabled", "area", *_SITE_DEFAULTED)}
        params = SolarPVParams(**kept, **values)
    except ValidationError as e:
        state.flash("modules", "error", str(e.errors()[0]["msg"]))
        return
    state.set_project(
        p.model_copy(update={"modules": p.modules.model_copy(update={"solar_pv": params})})
    )


def _set_pv(**changes: Any) -> None:
    p = state.get_project()
    pv = p.modules.solar_pv.model_copy(update=changes)
    state.set_project(
        p.model_copy(update={"modules": p.modules.model_copy(update={"solar_pv": pv})})
    )


def _typed(field: str) -> None:
    _set_pv(**{field: float(st.session_state[P + field])})  # user's own value from now on


def _follow_site(field: str) -> None:
    _set_pv(**{field: None})


def _site_defaulted(
    label: str,
    field: str,
    spec: SliderSpec,
    effective: float,
    stored: float | None,
    follow_note: str,
    reset_label: str,
    has_location: bool,
    help: str,
) -> None:
    """Number input that shows the site-derived default until the user types a value."""
    key = P + field
    if st.session_state.get(key) != effective:  # mirror the effective value
        st.session_state[key] = effective
    st.number_input(
        f"{label} ({spec.units})",
        float(spec.min),
        float(spec.max),
        step=float(spec.step),
        format="%.1f",
        key=key,
        on_change=_typed,
        args=(field,),
        help=help,
    )
    if stored is None:
        st.caption(follow_note if has_location else "Set a location for the site default")
    else:
        st.button(
            reset_label,
            key=f"reset_{field}",
            on_click=_follow_site,
            args=(field,),
            disabled=not has_location,
        )


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


def render_inputs(project: Project) -> None:
    pv = project.modules.solar_pv
    for f in _FIELDS:
        state.seed(P + f, getattr(pv, f))
    lat = project.site.lat
    resolved = resolve_orientation(pv, lat)
    i = PV_INPUTS
    d = i.power_density_w_sqft
    st.slider(
        f"Power density ({d.units})",
        float(d.min),
        float(d.max),
        step=float(d.step),
        format="%.2f",
        key=P + "power_density_w_sqft",
        on_change=_changed,
        help="DC kW per square foot of land. DC size = area × density.",
    )
    st.checkbox(
        "Cover the data center",
        key=P + "cover_data_center",
        on_change=_changed,
        help="Panels on the data center roof too: its block area × the same density "
        "is added to the drawn area.",
    )
    if pv.placed:
        st.metric("DC capacity", f"{pv_capacity_kw(pv, dc_roof_m2(project)):,.0f} kW")
    c1, c2 = st.columns(2)
    with c1:
        st.selectbox(
            "Array type",
            list(PvArrayType),
            format_func=lambda v: ARRAY_LABELS[PvArrayType(v)],
            key=P + "array_type",
            on_change=_changed,
        )
    with c2:
        st.selectbox(
            "Module type",
            list(PvModuleType),
            format_func=lambda v: MODULE_LABELS[PvModuleType(v)],
            key=P + "module_type",
            on_change=_changed,
        )
    c1, c2 = st.columns(2)
    with c1:
        _site_defaulted(
            "Tilt",
            "tilt_deg",
            i.tilt_deg,
            float(resolved.tilt_deg or 0),
            pv.tilt_deg,
            "= site latitude",
            "Use site latitude",
            lat is not None,
            "Defaults to the site latitude. 0 = horizontal, 90 = vertical.",
        )
    with c2:
        _site_defaulted(
            "Azimuth",
            "azimuth_deg",
            i.azimuth_deg,
            float(resolved.azimuth_deg or 0),
            pv.azimuth_deg,
            "= facing the equator",
            "Face the equator",
            lat is not None,
            "Defaults to facing the equator: 180 (south) north of it, 0 (north) south of it. "
            "90 = E, 270 = W.",
        )
    with st.expander("Advanced"):
        _number("System losses", "losses_pct", i.losses_pct, "%.2f", "PVWatts default 14.08 %")
        c1, c2 = st.columns(2)
        with c1:
            _number("DC/AC ratio", "dc_ac_ratio", i.dc_ac_ratio, "%.2f")
            _number("Inverter efficiency", "inv_eff_pct", i.inv_eff_pct, "%.1f")
        with c2:
            _number(
                "Ground coverage ratio",
                "gcr",
                i.gcr,
                "%.2f",
                "Row spacing for PVWatts shading/backtracking (independent of density)",
            )
    st.caption("PVWatts V8 (NREL), run on this site's weather — hour-aligned with the model.")


def dc_roof_m2(project: Project) -> float:
    """Data center block area, the roof PV can cover (D-073)."""
    fp = project.facilities[0].footprint if project.facilities else None
    return fp.area_m2 if fp is not None else 0.0


# --- module output (02-results.md → Module output) --------------------------------


def _text(df: pd.DataFrame) -> list[Metric]:
    mwh = -float(df[col.PV_KW].sum()) / KW_PER_MW  # generation is stored negative
    return [Metric("Energy produced", fmt(mwh, "MWh/yr"))]


OUTPUTS = ModuleOutputs(
    panels=(Panel("PV power production", "MW", (Trace(col.PV_KW, "PV", SERIES_4, -MW_PER_KW),)),),
    text=_text,
)
