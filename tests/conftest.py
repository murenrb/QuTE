from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.config.defaults import HOURS_PER_YEAR
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.timeseries import columns as col
from services.store import Store, default_store


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    """Every test gets its own SQLite database and data folder, so no test can
    reach a real database (DATABASE_URL in env or secrets.toml) or data/."""
    monkeypatch.setenv("DCS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.sqlite'}")
    return default_store()


@pytest.fixture
def dc_type() -> DataCenterType:
    return DataCenterType()


@pytest.fixture
def dc_10mw(dc_type: DataCenterType) -> DataCenter:
    return DataCenter(dc_type=dc_type, it_load_peak_mw=10)


@pytest.fixture
def synthetic_weather() -> pd.DataFrame:
    """Deterministic 8760-h weather spanning -5..45 °C dry bulb, both sides of every threshold."""
    h = np.arange(HOURS_PER_YEAR)
    tdb = 20 - 15 * np.cos(2 * np.pi * h / HOURS_PER_YEAR) + 10 * np.sin(2 * np.pi * h / 24)
    ghi = np.clip(800 * np.sin(2 * np.pi * (h % 24 - 6) / 24), 0, None)
    return pd.DataFrame(
        {
            col.TDB_C: tdb,
            col.TWB_C: tdb - 6,
            col.TDP_C: tdb - 10,
            col.RH_PCT: np.full(HOURS_PER_YEAR, 50.0),
            col.GHI_W_M2: ghi,
            col.DNI_W_M2: 0.9 * ghi,
            col.DHI_W_M2: 0.2 * ghi,
            col.WIND_M_S: np.full(HOURS_PER_YEAR, 3.0),
        }
    )
