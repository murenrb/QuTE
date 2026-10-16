"""Waste heat to power inputs (docs/models/power-generation.md, D-045).

Scaled in inputs (D-041): its block on the map has area = rated MWe × power
density, and is dragged / resized / rotated like the data center block.
"""

from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from app import state
from app.components.block_controls import render_block_controls
from app.components.metrics import Metric
from app.components.module_outputs import MW_PER_KW, PCT_PER_FRAC, ModuleOutputs, Panel, Trace, fmt
from core.config.defaults import ASSUMPTIONS, KW_PER_MW, POWER_GEN_INPUTS, SliderSpec
from core.domain.modules import PowerGenerationParams
from core.persistence.project import Project
from core.site_layout import module_context
from core.timeseries import columns as col
from core.timeseries.columns import SERIES_2, SERIES_6

P = f"{state.WIDGET_PREFIX}pgen_"
# Footprint comes from the map; rated_kw is derived from the % of IT load.
_FIELDS = tuple(
    f for f in PowerGenerationParams.model_fields if f not in ("enabled", "footprint", "rated_kw")
)
KEY = "power_generation"


def _changed() -> None:
    values: dict[str, Any] = {f: st.session_state[P + f] for f in _FIELDS}
    current = state.get_project().modules.power_generation
    try:
        params = PowerGenerationParams(
            enabled=current.enabled,
            footprint=current.footprint,
            **values,
        )
    except ValidationError as e:
        state.flash("modules", "error", str(e.errors()[0]["msg"]))
        return
    _store(params)


def _store(params: PowerGenerationParams) -> None:
    p = state.get_project()
    state.set_project(p.model_copy(update={"modules": p.modules.model_copy(update={KEY: params})}))


def _reposition() -> None:
    """Drop the footprint; the layout rules place it beside the data center again."""
    p = state.get_project()
    state.set_project(p.model_copy(update={"modules": p.modules.with_footprint(KEY, None)}))


def _slider(label: str, field: str, spec: SliderSpec, fmt: str, help: str, hi: float) -> None:
    st.slider(
        label,
        float(spec.min),
        float(hi),
        step=float(spec.step),
        format=fmt,
        key=P + field,
        on_change=_changed,
        help=help,
    )


def _free_cooling_cutoff_c(project: Project) -> float | None:
    """Ambient above which there is no free cooling: t_supply − approach."""
    if not project.facilities:
        return None
    return project.facilities[0].dc_type.t_supply_c - ASSUMPTIONS.t_approach_c


def _kw(v: float) -> str:
    return f"{v / 1000:,.2f} MWe" if v >= 1000 else f"{v:,.0f} kWe"


def render_inputs(project: Project) -> None:
    pg = project.modules.power_generation
    for f in _FIELDS:
        state.seed(P + f, getattr(pg, f))
    i = POWER_GEN_INPUTS
    resolved = pg.resolved(module_context(project))
    rated = float(resolved.rated_kw or 0)
    _slider(
        "Rated power (% of IT load)",
        "rated_pct_of_it",
        i.rated_pct_of_it,
        "%.1f%%",
        "Generator size as a share of the data center's IT load peak, reached at the max "
        f"cold-side temperature (default {i.rated_pct_of_it.default:g} %). Follows the IT load.",
        i.rated_pct_of_it.max,
    )
    st.caption(f"= {rated / KW_PER_MW:,.2f} MWe")  # grey, right under the slider (owner)
    _slider(
        "Cycle efficiency (% of Carnot)",
        "carnot_pct",
        i.carnot_pct,
        "%.0f%%",
        "Efficiency = this × (1 − T_cold / T_hot), T_hot = data center hot water.",
        i.carnot_pct.max,
    )
    cutoff = _free_cooling_cutoff_c(project)
    hi = i.t_cold_max_c.max if cutoff is None else max(cutoff, pg.t_cold_max_c, i.t_cold_max_c.min)
    _slider(
        "Max cold-side temperature (°C)",
        "t_cold_max_c",
        i.t_cold_max_c,
        "%.1f °C",
        "The generator is rated here. Colder: rated power from less heat. Warmer: the "
        "design heat input, so below rated power. Cold side = heat-rejection ambient + "
        "condenser approach. Upper limit: the free-cooling cutoff.",
        hi,
    )
    if cutoff is not None and pg.t_cold_max_c > cutoff:
        st.caption(f"Above the free-cooling cutoff ({cutoff:g} °C) — consider lowering it.")
    _slider(
        "Power density (sqft/MWe)",
        "power_density_sqft_mwe",
        i.power_density_sqft_mwe,
        "%.0f",
        "Footprint per MWe of rated output. Footprint = rated MWe × density.",
        i.power_density_sqft_mwe.max,
    )
    c1, c2 = st.columns(2)
    c1.metric("Rated", _kw(rated))
    c2.metric("Footprint", f"{resolved.footprint_sqft:,.0f} sqft")
    if pg.placed and pg.footprint is not None:
        st.markdown("**Placement**")
        render_block_controls(
            KEY,
            pg.footprint,
            key_prefix=f"{P}block_",
            reposition_label="Place beside data center",
            reposition=_reposition,
        )
    elif project.site.location is None:
        st.caption("Set the project location to place the waste heat to power block.")
    st.caption(
        "Runs whenever free cooling is available, taking the data center's heat before "
        "the dry coolers / towers do (fewer free-cooling hours)."
    )


# --- module output (02-results.md → Module output) --------------------------------


def _text(df: pd.DataFrame) -> list[Metric]:
    gen = -df[col.POWER_GEN_KW]  # generation is stored negative
    return [
        Metric("Power generated", fmt(float(gen.sum()) / KW_PER_MW, "MWh/yr")),
        Metric("Hours running", fmt(float((gen > 0).sum()), "h")),
    ]


OUTPUTS = ModuleOutputs(
    panels=(
        Panel(
            "Waste heat to power",
            "MW / MW_th",
            (
                Trace(col.POWER_GEN_KW, "Power out", SERIES_6, -MW_PER_KW),
                Trace(col.POWER_GEN_HEAT_IN_KWTH, "Heat in", SERIES_2, MW_PER_KW),
            ),
        ),
        Panel(
            "Cycle efficiency",
            "%",
            (Trace(col.POWER_GEN_EFF, "Efficiency", SERIES_6, PCT_PER_FRAC),),
        ),
    ),
    text=_text,
)
