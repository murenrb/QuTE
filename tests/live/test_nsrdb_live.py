"""Opt-in live check against the real NSRDB API: `pytest -m live`.

Needs NSRDB_API_KEY / NSRDB_EMAIL (env or .streamlit/secrets.toml). Uses a
temporary cache so it always hits the network.
"""

from pathlib import Path

import pytest

from core.timeseries import columns as col
from core.weather.tmy import WEATHER_COLUMNS
from services.cache import DiskCache
from services.nsrdb import NsrdbClient, load_credentials
from services.weather import WeatherNotAvailableError

pytestmark = pytest.mark.live


def test_live_phoenix(tmp_path: Path) -> None:
    w = NsrdbClient(load_credentials(), cache=DiskCache(tmp_path)).fetch_tmy(33.448, -112.074)
    assert tuple(w.frame.columns) == WEATHER_COLUMNS
    assert len(w.frame) == 8760
    assert w.meta.utc_offset_h == -7
    assert w.frame[col.TDB_C].max() > 40


def test_live_out_of_coverage(tmp_path: Path) -> None:
    client = NsrdbClient(load_credentials(), cache=DiskCache(tmp_path))
    with pytest.raises(WeatherNotAvailableError):
        client.fetch_tmy(50.0, 10.0)


def test_live_pysam_matches_pvwatts_api(tmp_path: Path) -> None:
    """Local PVWatts V8 (PySAM, our tmy-2024) vs the web API (its tmy-2020): annual
    energy should agree within a few percent; exact match is impossible because
    the typical years differ (D-035)."""
    import pandas as pd
    import requests

    from core.domain.modules import SolarPVParams
    from core.models.solar_pv import PvSite, pvwatts_ac_kw

    creds = load_credentials()
    w = NsrdbClient(creds, cache=DiskCache(tmp_path)).fetch_tmy(33.448, -112.074)
    p, kw = SolarPVParams(tilt_deg=20, azimuth_deg=180), 1000.0
    f, idx = w.frame, pd.DatetimeIndex(w.frame.index)
    local_kwh = pvwatts_ac_kw(
        idx.month.to_numpy(),
        idx.day.to_numpy(),
        idx.hour.to_numpy(),
        f[col.DNI_W_M2].to_numpy(),
        f[col.DHI_W_M2].to_numpy(),
        f[col.GHI_W_M2].to_numpy(),
        f[col.TDB_C].to_numpy(),
        f[col.WIND_M_S].to_numpy(),
        PvSite.from_weather(w.meta),
        p,
        kw,
    ).sum()
    r = requests.get(
        "https://developer.nlr.gov/api/pvwatts/v8.json",
        params={
            "api_key": creds.api_key,
            "lat": 33.448,
            "lon": -112.074,
            "system_capacity": kw,
            "module_type": int(p.module_type),
            "losses": p.losses_pct,
            "array_type": int(p.array_type),
            "tilt": p.tilt_deg,
            "azimuth": p.azimuth_deg,
            "dc_ac_ratio": p.dc_ac_ratio,
            "gcr": p.gcr,
            "inv_eff": p.inv_eff_pct,
        },
        timeout=60,
    )
    r.raise_for_status()
    api_kwh = r.json()["outputs"]["ac_annual"]
    assert local_kwh == pytest.approx(api_kwh, rel=0.03)
