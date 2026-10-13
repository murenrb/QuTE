"""Utility tab: time-of-use energy prices and demand charges (docs/models/utility.md, D-043).

The tariff painter edits rate categories and paints them onto a month × hour
table; the model turns it into hourly prices, energy cost and the monthly
demand charge.
"""

from typing import Any

import streamlit as st
from pydantic import ValidationError

from app import state
from app.components.tariff_editor import tariff_editor
from core.config.defaults import UTILITY
from core.domain.utility import RateCategory, UtilityTariff, WeekendPricing, new_category_id
from core.persistence.project import Project

K_WEEKEND = f"{state.WIDGET_PREFIX}weekend_pricing"
WEEKEND_LABELS = {
    WeekendPricing.FOLLOW_SCHEDULE: "Follow schedule",
    WeekendPricing.OFF_PEAK: "Off peak",
}


def apply_event(tariff: UtilityTariff, event: dict[str, Any]) -> UtilityTariff:
    """One painter action → new tariff. Raises ValueError/ValidationError if invalid."""
    kind = event.get("kind")
    if kind == "paint":
        cells = [(int(m), int(h)) for m, h in event["cells"]]
        return tariff.painted(cells, str(event["category"]))
    if kind == "update":
        c = RateCategory(
            id=str(event["id"]),
            name=str(event["name"]),
            energy_usd_kwh=float(event["energy"]),
            demand_usd_kw=float(event["demand"]),
        )
        cats = tuple(c if x.id == c.id else x for x in tariff.categories)
        return tariff.model_copy(update={"categories": cats})
    if kind == "add":
        d = UTILITY.new_category
        c = RateCategory(
            id=new_category_id(),
            name=d.name,
            energy_usd_kwh=d.energy_usd_kwh,
            demand_usd_kw=d.demand_usd_kw,
        )
        return tariff.model_copy(update={"categories": (*tariff.categories, c)})
    if kind == "delete":
        return tariff.without_category(str(event["id"]))
    raise ValueError(f"Unknown tariff action {kind!r}")


def _set_tariff(tariff: UtilityTariff) -> None:
    p = state.get_project()
    state.set_project(p.model_copy(update={"utility": tariff}))


def _weekend_changed() -> None:
    tariff = state.get_project().utility
    _set_tariff(tariff.model_copy(update={"weekend": WeekendPricing(st.session_state[K_WEEKEND])}))


def render(project: Project) -> None:
    tariff = project.utility
    st.caption(
        "Energy price and demand charge by month and hour. Demand is billed once a month, "
        "at the hour with the highest demand charge × net grid load. Exports are credited "
        "at the energy price."
    )
    state.show_flash("utility")
    event = tariff_editor(tariff, key="tariff_editor")
    if event is not None and state.edit_is_new(str(event.get("event_id"))):
        try:
            _set_tariff(apply_event(tariff, event))
        except (ValueError, ValidationError, StopIteration, KeyError, TypeError) as e:
            state.flash("utility", "error", f"Couldn't apply that change: {e}")
        st.rerun()
    state.seed(K_WEEKEND, tariff.weekend.value)
    st.radio(
        "Weekend energy prices",
        [w.value for w in WeekendPricing],
        format_func=lambda v: WEEKEND_LABELS[WeekendPricing(v)],
        key=K_WEEKEND,
        horizontal=True,
        on_change=_weekend_changed,
        help="Off peak: every weekend hour uses the cheapest rate (energy × 100 + demand).",
    )
