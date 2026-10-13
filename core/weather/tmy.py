"""Normalize any typical-year weather into the 8760-row backbone format.

Provider-independent (NSRDB today, EPW/PVGIS later — D-012): a provider parses
its file into `RawTmy`, and `normalize_tmy` handles time and wet bulb.
See docs/integrations/nsrdb-weather.md → Post-processing.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.config.defaults import HOURS_PER_YEAR, PsychrometricSettings
from core.timeseries import columns as col
from core.timeseries.frame import year_index
from core.weather.psychrometrics import wet_bulb_c

# Kept in the hourly frame (D-034). Everything but twb_c must come from the provider.
WEATHER_COLUMNS: tuple[str, ...] = (
    col.TDB_C,
    col.TWB_C,
    col.TDP_C,
    col.RH_PCT,
    col.GHI_W_M2,
    col.DNI_W_M2,
    col.DHI_W_M2,
    col.WIND_M_S,
)
_PROVIDED = tuple(c for c in WEATHER_COLUMNS if c != col.TWB_C)
_TIME_COLUMNS = ("month", "day", "hour")


class WeatherFormatError(ValueError):
    """Weather data can't be turned into a clean 8760-hour year."""


@dataclass(frozen=True)
class WeatherMeta:
    source: str  # e.g. "NSRDB tmy-2024"
    location_id: str
    lat: float
    lon: float
    elevation_m: float
    utc_offset_h: float  # local standard time = UTC + offset
    cache_key: str  # stored on the Site as `weather_ref`
    # Minute past the hour each value is stamped at (NSRDB: 30). Row h of the
    # frame holds the value stamped h:minute; solar models need it for sun
    # position (D-034).
    data_minute: int = 0


@dataclass(frozen=True)
class WeatherData:
    """Clean weather: `frame` has WEATHER_COLUMNS on the reference-year index."""

    frame: pd.DataFrame
    meta: WeatherMeta


@dataclass(frozen=True)
class RawTmy:
    """Provider-parsed hourly rows before time normalization.

    `rows` has integer `month`, `day`, `hour` columns plus canonical weather
    columns; `twb_c` may be missing (derived), `pressure_pa` is required then.
    `data_utc_offset_h` is the offset the timestamps are in (0 for UTC).
    """

    rows: pd.DataFrame
    data_utc_offset_h: float
    local_utc_offset_h: float


def normalize_tmy(raw: RawTmy, psychro: PsychrometricSettings) -> pd.DataFrame:
    """Leap day removed, sorted, shifted to local standard time, wet bulb filled.

    Each row's (month, day, hour) maps to the hour-beginning slot of the
    reference year, whatever source year the TMY month came from.
    """
    rows = raw.rows
    missing = [c for c in (*_TIME_COLUMNS, *_PROVIDED) if c not in rows.columns]
    if missing:
        raise WeatherFormatError(f"Weather is missing columns: {missing}")

    rows = rows[~((rows["month"] == 2) & (rows["day"] == 29))]
    rows = rows.sort_values(list(_TIME_COLUMNS), kind="stable")
    if len(rows) != HOURS_PER_YEAR:
        raise WeatherFormatError(
            f"Expected {HOURS_PER_YEAR} hourly rows after removing Feb 29, got {len(rows)}"
        )
    index = year_index()
    stamps = rows[list(_TIME_COLUMNS)].to_numpy()
    expected = np.column_stack([index.month, index.day, index.hour])
    if not np.array_equal(stamps, expected):
        raise WeatherFormatError("Weather rows are not one complete hourly year")

    frame = pd.DataFrame(index=index)
    if col.TWB_C in rows.columns:
        frame[col.TWB_C] = rows[col.TWB_C].to_numpy(dtype=float)
    elif "pressure_pa" in rows.columns:
        frame[col.TWB_C] = wet_bulb_c(
            rows[col.TDB_C].to_numpy(dtype=float),
            rows[col.RH_PCT].to_numpy(dtype=float),
            rows["pressure_pa"].to_numpy(dtype=float),
            psychro,
        )
    else:
        raise WeatherFormatError("Need wet bulb or pressure to derive it")
    for c in _PROVIDED:
        frame[c] = rows[c].to_numpy(dtype=float)
    frame = frame[list(WEATHER_COLUMNS)]

    shift_h = local_shift_hours(raw.data_utc_offset_h, raw.local_utc_offset_h)
    if shift_h:
        # local[i] = data[i - shift]; a typical year wraps Dec 31 → Jan 1.
        frame = pd.DataFrame(
            np.roll(frame.to_numpy(), shift_h, axis=0), index=index, columns=frame.columns
        )
    if not np.isfinite(frame.to_numpy()).all():
        raise WeatherFormatError("Weather contains missing or non-numeric values")
    return frame


def local_shift_hours(data_utc_offset_h: float, local_utc_offset_h: float) -> int:
    """Rows to roll data-time values into local standard time.

    Half-hour zones (e.g. Newfoundland, −3.5) round to the nearest hour, since
    the model runs on whole hours.
    """
    return round(local_utc_offset_h - data_utc_offset_h)
