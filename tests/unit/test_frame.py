import numpy as np
import pandas as pd
import pytest

from core.timeseries import columns as col
from core.timeseries.frame import build_hourly_frame, tile_daily_profile, year_index


def test_year_index_8760_no_leap_day() -> None:
    idx = year_index()
    assert len(idx) == 8760
    assert idx.name == col.TIMESTAMP
    assert not ((idx.month == 2) & (idx.day == 29)).any()
    assert idx[0] == pd.Timestamp("2025-01-01 00:00") and idx[-1] == pd.Timestamp(
        "2025-12-31 23:00"
    )


def test_non_constant_profile_repeats_every_day() -> None:
    profile = [float(h) for h in range(24)]
    s = tile_daily_profile(year_index(), profile)
    days = s.to_numpy().reshape(365, 24)
    assert (days == np.array(profile)).all()


def test_profile_length_checked() -> None:
    with pytest.raises(ValueError):
        tile_daily_profile(year_index(), [1.0] * 23)


def test_build_frame_column_order(synthetic_weather: pd.DataFrame) -> None:
    df = build_hourly_frame(synthetic_weather, [5.0] * 24)
    assert list(df.columns)[0] == col.IT_LOAD_PLAN_KW
    assert set(synthetic_weather.columns) <= set(df.columns)
    assert (df[col.IT_LOAD_PLAN_KW] == 5.0).all()


def test_build_frame_rejects_wrong_length(synthetic_weather: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="8760"):
        build_hourly_frame(synthetic_weather.iloc[: 8784 - 24 * 2], [5.0] * 24)
