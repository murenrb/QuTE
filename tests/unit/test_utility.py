"""Utility tariff, hourly prices and monthly demand charge (D-043)."""

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from core.config.defaults import ASSUMPTIONS
from core.domain.utility import RateCategory, UtilityTariff, WeekendPricing
from core.models.site_model import run_site_model
from core.models.utility import (
    UtilityCost,
    UtilityPrice,
    hourly_rates,
    monthly_peak_only,
    rate_tables,
)
from core.timeseries import columns as col
from core.timeseries.frame import year_index

T = UtilityTariff()  # defaults: off peak / shoulder / peak, all hours off peak


def _peak_afternoons(t: UtilityTariff = T) -> UtilityTariff:
    """Peak 14–18 h June–September, shoulder 10–14 h all year."""
    cells_peak = [(m, h) for m in range(5, 9) for h in range(14, 19)]
    cells_shoulder = [(m, h) for m in range(12) for h in range(10, 14)]
    return t.painted(cells_shoulder, "shoulder").painted(cells_peak, "peak")


def test_defaults() -> None:
    names = [(c.name, c.energy_usd_kwh, c.demand_usd_kw) for c in T.categories]
    assert names == [("Off peak", 0.10, 10.0), ("Shoulder", 0.15, 10.0), ("Peak", 0.20, 10.0)]
    assert all(cid == "offpeak" for row in T.schedule for cid in row)
    assert T.cheapest.id == "offpeak" and T.weekend is WeekendPricing.FOLLOW_SCHEDULE
    assert [c.total_value for c in T.categories] == pytest.approx([20, 25, 30])  # ×100 + demand


@pytest.mark.parametrize(
    "bad",
    [
        {"schedule": (("offpeak",) * 24,) * 11},  # 11 months
        {"schedule": (("offpeak",) * 23,) * 12},  # 23 hours
        {"schedule": (("nope",) * 24,) * 12},  # unknown category
        {"categories": ()},
    ],
)
def test_invalid_tariffs(bad: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationError):
        UtilityTariff(**bad)


def test_rates_validated() -> None:
    with pytest.raises(ValidationError):
        RateCategory(id="x", name="x", energy_usd_kwh=-0.1, demand_usd_kw=0)


def test_paint_and_delete() -> None:
    t = _peak_afternoons()
    assert t.schedule[6][15] == "peak" and t.schedule[0][11] == "shoulder"
    assert t.schedule[0][3] == "offpeak"
    no_peak = t.without_category("peak")
    assert no_peak.schedule[6][15] == "offpeak"  # → cheapest remaining
    with pytest.raises(ValueError, match="at least one"):
        UtilityTariff(categories=(T.categories[0],)).without_category("offpeak")


def test_hourly_rates_follow_month_and_hour() -> None:
    idx = year_index()
    energy, demand = hourly_rates(_peak_afternoons(), idx)
    s = pd.Series(energy, index=idx)
    assert s[pd.Timestamp("2025-07-15 15:00")] == 0.20  # peak (July, 15 h)
    assert s[pd.Timestamp("2025-01-15 11:00")] == 0.15  # shoulder
    assert s[pd.Timestamp("2025-01-15 03:00")] == 0.10  # off peak
    assert (demand == 10.0).all()
    tables = rate_tables(_peak_afternoons())
    assert tables[0].shape == (12, 24)


def test_weekend_off_peak_uses_cheapest_rate() -> None:
    t = _peak_afternoons().model_copy(update={"weekend": WeekendPricing.OFF_PEAK})
    s = pd.Series(hourly_rates(t, year_index())[0], index=year_index())
    assert s[pd.Timestamp("2025-07-19 15:00")] == 0.10  # Saturday → off peak
    assert s[pd.Timestamp("2025-07-21 15:00")] == 0.20  # Monday → schedule (peak)


def test_monthly_peak_only() -> None:
    months = np.array([1, 1, 1, 2, 2, 3])
    pot = np.array([5.0, 9.0, 9.0, -1.0, -3.0, 0.0])
    assert monthly_peak_only(pot, months).tolist() == [0, 9.0, 0, 0, 0, 0]  # first on ties; ≥ 0


def _frame(net_kw: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({col.GRID_NET_KW: net_kw}, index=year_index())


def _bill(tariff: UtilityTariff, net_kw: np.ndarray) -> pd.DataFrame:
    """Prices from the tariff, then the bill on the net load (D-053 split)."""
    return UtilityCost().run(UtilityPrice(tariff).run(_frame(net_kw)))


def test_constant_load_hand_calculation() -> None:
    out = _bill(T, np.full(8760, 10_000.0))  # 10 MW all year, off peak
    assert out[col.ENERGY_COST_USD].sum() == pytest.approx(0.10 * 10_000 * 8760)  # $8.76 M
    assert out[col.DEMAND_COST_USD].sum() == pytest.approx(12 * 10.0 * 10_000)  # $1.2 M
    assert (out[col.DEMAND_COST_USD] > 0).sum() == 12  # once per month
    np.testing.assert_allclose(
        out[col.UTILITY_COST_USD], out[col.ENERGY_COST_USD] + out[col.DEMAND_COST_USD]
    )


def test_demand_charge_picks_highest_charge_times_load() -> None:
    """Time-dependent demand charge: the billed hour is the max of charge × load,
    not simply the hour of max load."""
    expensive = RateCategory(id="dpk", name="Demand peak", energy_usd_kwh=0.1, demand_usd_kw=40)
    t = UtilityTariff(categories=(*T.categories, expensive)).painted([(0, 18)], "dpk")
    net = np.full(8760, 1_000.0)
    idx = year_index()
    net[(idx.month == 1) & (idx.day == 10) & (idx.hour == 3)] = 2_000.0  # Jan max load at 03:00
    out = _bill(t, net)
    jan = out[idx.month == 1]
    billed = jan[jan[col.DEMAND_COST_USD] > 0]
    assert len(billed) == 1
    assert billed.index[0].hour == 18  # 1,000 kW × $40 = $40k beats 2,000 kW × $10 = $20k
    assert billed[col.DEMAND_COST_USD].iloc[0] == pytest.approx(40_000)


def test_net_export_credited_at_energy_price() -> None:
    net = np.full(8760, 500.0)
    net[:24] = -300.0  # exporting on Jan 1
    out = _bill(T, net)
    assert out[col.ENERGY_COST_USD].iloc[0] == pytest.approx(-0.10 * 300)  # credit
    assert out[col.DEMAND_COST_POTENTIAL_USD].iloc[0] == 0  # exports set no demand


def test_pipeline_includes_utility(dc_10mw, synthetic_weather) -> None:  # type: ignore[no-untyped-def]
    df = run_site_model(dc_10mw, synthetic_weather, ASSUMPTIONS, tariff=_peak_afternoons())
    for c in (col.ENERGY_PRICE_USD_KWH, col.ENERGY_COST_USD, col.DEMAND_COST_USD):
        assert c in df.columns
    np.testing.assert_allclose(
        df[col.ENERGY_COST_USD], df[col.ENERGY_PRICE_USD_KWH] * df[col.GRID_NET_KW]
    )


def test_running_totals() -> None:
    out = _bill(T, np.full(8760, 10_000.0))
    np.testing.assert_allclose(out[col.CUM_ENERGY_COST_USD], out[col.ENERGY_COST_USD].cumsum())
    np.testing.assert_allclose(out[col.CUM_DEMAND_COST_USD], out[col.DEMAND_COST_USD].cumsum())
    np.testing.assert_allclose(
        out[col.CUM_UTILITY_COST_USD],
        out[col.CUM_ENERGY_COST_USD] + out[col.CUM_DEMAND_COST_USD],
    )
    assert out[col.CUM_UTILITY_COST_USD].iloc[-1] == pytest.approx(8_760_000 + 1_200_000)
    assert out[col.CUM_DEMAND_COST_USD].is_monotonic_increasing
