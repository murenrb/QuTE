"""Build the 8760-hour DataFrame backbone (docs/data-model.md → Hourly DataFrame).

Timestamps are naive local standard time (no DST) on a fixed non-leap
reference year, so every TMY maps to the same 8760-row index.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from core.config.defaults import HOURS_PER_DAY, HOURS_PER_YEAR
from core.timeseries.columns import IT_LOAD_PLAN_KW, TIMESTAMP

REFERENCE_YEAR = 2025  # non-leap


def year_index() -> pd.DatetimeIndex:
    return pd.date_range(
        f"{REFERENCE_YEAR}-01-01", periods=HOURS_PER_YEAR, freq="h", name=TIMESTAMP
    )


def tile_daily_profile(index: pd.DatetimeIndex, daily_kw: Sequence[float]) -> pd.Series:
    """Repeat a 24-value daily profile for every day, matched by hour of day."""
    if len(daily_kw) != HOURS_PER_DAY:
        raise ValueError(f"Daily profile needs {HOURS_PER_DAY} values, got {len(daily_kw)}")
    values = np.asarray(daily_kw, dtype=float)[index.hour]
    return pd.Series(values, index=index, name=IT_LOAD_PLAN_KW)


def build_hourly_frame(weather: pd.DataFrame, daily_it_kw: Sequence[float]) -> pd.DataFrame:
    """Start the backbone: timestamp index, planned IT load, then weather columns.
    The actual IT load comes from the state machine (D-053)."""
    if len(weather) != HOURS_PER_YEAR:
        raise ValueError(f"Weather must have {HOURS_PER_YEAR} rows, got {len(weather)}")
    index = year_index()
    df = pd.DataFrame(index=index)
    df[IT_LOAD_PLAN_KW] = tile_daily_profile(index, daily_it_kw)
    for col in weather.columns:
        df[col] = weather[col].to_numpy()
    return df
