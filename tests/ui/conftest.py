from pathlib import Path

import pandas as pd
import pytest

from app.components import weather as weather_component
from core.timeseries.frame import year_index
from core.weather.tmy import WeatherData, WeatherMeta


@pytest.fixture(autouse=True)
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """UI tests never touch the real data/ folder or the NSRDB API."""
    monkeypatch.setenv("DCS_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def fake_weather(synthetic_weather: pd.DataFrame, monkeypatch: pytest.MonkeyPatch) -> None:
    meta = WeatherMeta("fake", "0", 33.45, -112.07, 300.0, -7.0, "fake/key.csv")
    data = WeatherData(synthetic_weather.set_axis(year_index()), meta)
    monkeypatch.setattr(weather_component, "_fetch_tmy", lambda lat, lon: data)
