"""Tariff painter: swatch colours and actions (D-043)."""

import pytest

from app.components.tabs.utility import apply_event
from app.components.tariff_editor import VIRIDIS, category_colors, viridis
from core.domain.utility import UtilityTariff


def test_colors_run_purple_to_yellow_by_total_value() -> None:
    colors = category_colors(UtilityTariff())  # totals 20, 25, 30
    assert colors["offpeak"] == VIRIDIS[0]  # cheapest: dark purple
    assert colors["peak"] == VIRIDIS[-1]  # dearest: bright yellow
    assert colors["shoulder"] == viridis(0.5) == VIRIDIS[4]  # linear position


def test_single_category_color() -> None:
    t = UtilityTariff().without_category("peak").without_category("shoulder")
    assert category_colors(t) == {"offpeak": VIRIDIS[0]}


def test_actions() -> None:
    t = UtilityTariff()
    t = apply_event(t, {"kind": "paint", "category": "peak", "cells": [[6, 15], [6, 16]]})
    assert t.schedule[6][15] == t.schedule[6][16] == "peak"
    t = apply_event(t, {"kind": "add"})
    new = t.categories[-1]
    assert (new.name, new.energy_usd_kwh, new.demand_usd_kw) == ("New rate", 0.12, 10.0)
    t = apply_event(
        t, {"kind": "update", "id": new.id, "name": "Critical", "energy": 0.5, "demand": 25}
    )
    assert t.category(new.id).name == "Critical" and t.category(new.id).energy_usd_kwh == 0.5
    t = apply_event(t, {"kind": "delete", "id": "peak"})
    assert t.schedule[6][15] == "offpeak"
    with pytest.raises(ValueError):
        apply_event(t, {"kind": "explode"})
