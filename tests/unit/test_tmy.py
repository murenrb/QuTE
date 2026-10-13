import numpy as np
import pandas as pd
import pytest

from core.config.defaults import PSYCHRO
from core.timeseries import columns as col
from core.timeseries.frame import year_index
from core.weather.tmy import (
    WEATHER_COLUMNS,
    RawTmy,
    WeatherFormatError,
    local_shift_hours,
    normalize_tmy,
)


def _raw_rows(leap: bool = False) -> pd.DataFrame:
    """One hourly year; tdb encodes the row's position so shifts are traceable."""
    stamps = pd.date_range(
        "2024-01-01" if leap else "2023-01-01", periods=8784 if leap else 8760, freq="h"
    )
    n = len(stamps)
    return pd.DataFrame(
        {
            "month": stamps.month,
            "day": stamps.day,
            "hour": stamps.hour,
            col.TDB_C: np.arange(n, dtype=float) / 1000,
            col.TDP_C: np.zeros(n),
            col.RH_PCT: np.full(n, 50.0),
            col.GHI_W_M2: np.zeros(n),
            col.DNI_W_M2: np.zeros(n),
            col.DHI_W_M2: np.zeros(n),
            col.WIND_M_S: np.full(n, 3.0),
            "pressure_pa": np.full(n, 101325.0),
        }
    )


def test_leap_day_removed() -> None:
    rows = _raw_rows(leap=True)
    out = normalize_tmy(RawTmy(rows, -7, -7), PSYCHRO)
    assert len(out) == 8760
    assert out.index.equals(year_index())
    feb29 = (rows["month"] == 2) & (rows["day"] == 29)
    assert not np.isin(out[col.TDB_C], rows.loc[feb29, col.TDB_C]).any()
    # Mar 1 00:00 follows Feb 28 23:00 directly
    mar1 = out.index.get_loc(pd.Timestamp("2025-03-01 00:00"))
    mar1_raw = rows.loc[(rows.month == 3) & (rows.day == 1), col.TDB_C].iloc[0]
    assert out[col.TDB_C].iloc[mar1] == mar1_raw


def test_utc_data_shifted_to_local_standard_time() -> None:
    rows = _raw_rows()
    out = normalize_tmy(RawTmy(rows, data_utc_offset_h=0, local_utc_offset_h=-6), PSYCHRO)
    tdb = out[col.TDB_C].to_numpy()
    # Local 00:00 Jan 1 = 06:00 UTC; the last 6 local hours wrap from UTC Jan 1.
    assert tdb[0] == rows[col.TDB_C].iloc[6]
    np.testing.assert_array_equal(tdb[-6:], rows[col.TDB_C].iloc[:6].to_numpy())


def test_local_data_not_shifted() -> None:
    rows = _raw_rows()
    out = normalize_tmy(RawTmy(rows, -7, -7), PSYCHRO)
    np.testing.assert_array_equal(out[col.TDB_C].to_numpy(), rows[col.TDB_C].to_numpy())


def test_rows_sorted_regardless_of_source_year_order() -> None:
    rows = _raw_rows()
    shuffled = rows.sample(frac=1.0, random_state=0)
    out = normalize_tmy(RawTmy(shuffled, -7, -7), PSYCHRO)
    np.testing.assert_array_equal(out[col.TDB_C].to_numpy(), rows[col.TDB_C].to_numpy())


def test_output_columns_and_derived_wet_bulb() -> None:
    out = normalize_tmy(RawTmy(_raw_rows(), -7, -7), PSYCHRO)
    assert tuple(out.columns) == WEATHER_COLUMNS
    assert (out[col.TWB_C] <= out[col.TDB_C] + 1e-9).all()


def test_provided_wet_bulb_is_kept() -> None:
    rows = _raw_rows().drop(columns="pressure_pa").assign(**{col.TWB_C: -1.0})
    out = normalize_tmy(RawTmy(rows, -7, -7), PSYCHRO)
    assert (out[col.TWB_C] == -1.0).all()


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda r: r.drop(columns=col.GHI_W_M2), "missing columns"),
        (lambda r: r.drop(columns="pressure_pa"), "pressure"),
        (lambda r: r.iloc[:-1], "8760"),
        (lambda r: r.assign(hour=np.where(r.index == 5, 4, r["hour"])), "complete hourly year"),
        (
            lambda r: r.assign(**{col.TDB_C: np.where(r.index == 9, np.nan, r[col.TDB_C])}),
            "non-num",
        ),
    ],
)
def test_bad_input_raises(mutate, match: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(WeatherFormatError, match=match):
        normalize_tmy(RawTmy(mutate(_raw_rows()), -7, -7), PSYCHRO)


def test_half_hour_zone_rounds() -> None:
    assert local_shift_hours(0, -3.5) == -4
    assert local_shift_hours(-5, -5) == 0
