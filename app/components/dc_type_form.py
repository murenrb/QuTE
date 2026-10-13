"""Create-a-DataCenterType form (docs/gui.md → Forms, docs/data-model.md)."""

import streamlit as st
from pydantic import ValidationError

from app import state
from core.config.defaults import DC_TYPE_INPUTS, CoolingType, SliderSpec
from core.domain.datacenter_type import DataCenterType, redundancy_label
from services.store import SaveOutcome

COOLING_LABELS = {CoolingType.DRY: "Dry cooler", CoolingType.EVAPORATIVE: "Evaporative"}


def _slider(label: str, spec: SliderSpec, key: str, help: str | None = None) -> float:
    fmt = f"%g {spec.units}".strip()
    return float(
        st.slider(
            label,
            float(spec.min),
            float(spec.max),
            float(spec.default),
            float(spec.step),
            format=fmt,
            key=key,
            help=help,
        )
    )


def _int_slider(label: str, spec: SliderSpec, key: str, help: str | None = None) -> int:
    return int(
        st.slider(
            label,
            int(spec.min),
            int(spec.max),
            int(spec.default),
            int(spec.step),
            key=key,
            help=help,
        )
    )


def validation_messages(e: ValidationError) -> list[str]:
    msgs = []
    for err in e.errors():
        msg = str(err["msg"]).removeprefix("Value error, ")
        field = ".".join(str(x) for x in err["loc"])
        msgs.append(f"{field}: {msg}" if field else msg)
    return msgs


def dc_type_form() -> SaveOutcome | None:
    """Render the form; on submit save the design (or find the identical saved one).

    The type's name is generated from these inputs, so there is no name field.
    """
    i = DC_TYPE_INPUTS
    with st.form("dc_type_form"):
        st.caption("The type is named automatically from these settings.")
        cooling = st.radio(
            "Heat rejection",
            list(CoolingType),
            format_func=lambda c: COOLING_LABELS[CoolingType(c)],
            horizontal=True,
            key="dct_cooling",
        )
        s, m = i.t_supply_c, i.t_supply_min_c
        t_supply_min, t_supply = st.slider(
            "Supply (cold) water to IT: minimum / setpoint",
            float(s.min),
            float(s.max),
            (float(m.default), float(s.default)),
            float(s.step),
            format="%g °C",
            key="dct_t_supply",
            help="Right handle = setpoint: the supply temperature whenever the chillers "
            "run. Left handle = minimum: with free cooling the supply floats down with "
            "the weather, at heat-rejection ambient (dry bulb, or wet bulb for "
            "evaporative) + the free-cooling approach, but never below this minimum. "
            "Modules that reject heat into the cooling loop (power generation, brine "
            "separation) see this floating temperature.",
        )
        t_return = _slider("Return (warm) water from IT", i.t_return_c, "dct_t_return")
        rack = _slider("Rack density", i.rack_density_kw, "dct_rack")
        ws_pct = st.slider(
            "White space ratio",
            int(i.white_space_ratio.min * 100),
            int(i.white_space_ratio.max * 100),
            int(round(i.white_space_ratio.default * 100)),
            1,
            format="%d %%",
            key="dct_ws",
            help="Share of the data hall that is white space (racks).",
        )
        c1, c2 = st.columns(2)
        with c1:
            x = _int_slider("Redundancy X", i.redundancy_x, "dct_x", help="X in X·N + Y")
        with c2:
            y = _int_slider("Redundancy Y", i.redundancy_y, "dct_y", help="Y in X·N + Y")
        ups = _slider("UPS area", i.ups_area_sqft_per_kw, "dct_ups")
        gen = _slider("Generator area", i.generator_area_sqft_per_kw, "dct_gen")
        swg = _slider("Switchgear area", i.switchgear_area_sqft_per_kw, "dct_swg")
        submitted = st.form_submit_button("Save type", type="primary")

    if not submitted:
        return None
    try:
        t = DataCenterType(
            cooling_type=CoolingType(cooling),
            t_supply_c=float(t_supply),
            t_supply_min_c=float(t_supply_min),
            t_return_c=t_return,
            rack_density_kw=rack,
            white_space_ratio=ws_pct / 100,
            redundancy_x=x,
            redundancy_y=y,
            ups_area_sqft_per_kw=ups,
            generator_area_sqft_per_kw=gen,
            switchgear_area_sqft_per_kw=swg,
        )
    except ValidationError as e:
        for msg in validation_messages(e):
            st.error(msg)
        return None
    return state.store().save_type(t)


def dc_type_summary(t: DataCenterType) -> dict[str, str]:
    return {
        "Heat rejection": COOLING_LABELS[t.cooling_type],
        "Supply water (min / setpoint)": f"{t.t_supply_min_c:g} / {t.t_supply_c:g} °C",
        "Return water": f"{t.t_return_c:g} °C",
        "Rack density": f"{t.rack_density_kw:g} kW/rack",
        "White space ratio": f"{t.white_space_ratio:.0%}",
        "Redundancy": redundancy_label(t.redundancy_x, t.redundancy_y),
        "UPS / generator / switchgear": (
            f"{t.ups_area_sqft_per_kw:g} / {t.generator_area_sqft_per_kw:g} / "
            f"{t.switchgear_area_sqft_per_kw:g} sqft/kW"
        ),
    }
