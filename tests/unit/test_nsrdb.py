"""NSRDB client against recorded fixtures and a fake HTTP session — never the live API."""

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import requests

from core.config.defaults import NSRDB, PSYCHRO
from core.timeseries import columns as col
from core.timeseries.frame import year_index
from core.weather.tmy import WEATHER_COLUMNS, WeatherFormatError
from services.cache import DiskCache
from services.nsrdb import NsrdbClient, NsrdbCredentials, load_credentials, parse_nsrdb_csv
from services.weather import (
    WeatherAuthError,
    WeatherConfigError,
    WeatherNotAvailableError,
    WeatherProvider,
    WeatherRateLimitError,
    WeatherServiceError,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nsrdb"
PHOENIX = (FIXTURES / "phoenix_tmy_local.csv").read_text()  # dry, utc=false
HOUSTON_UTC = (FIXTURES / "houston_tmy_utc.csv").read_text()  # humid, utc=true
CREDS = NsrdbCredentials(api_key="SECRETKEY123", email="me@example.com")


class FakeResponse:
    def __init__(self, status: int, text: str = "", json_body: Any = None) -> None:
        self.status_code = status
        self.text = text
        self._json = json_body

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    def __init__(self, *responses: FakeResponse | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, Any], timeout: float) -> FakeResponse:
        self.calls.append(params)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _client(tmp_path: Path, session: FakeSession) -> tuple[NsrdbClient, list[float]]:
    sleeps: list[float] = []
    client = NsrdbClient(
        CREDS,
        cache=DiskCache(tmp_path),
        session=session,  # type: ignore[arg-type]
        sleep=sleeps.append,
    )
    return client, sleeps


# --- parsing -----------------------------------------------------------------


@pytest.mark.parametrize("text", [PHOENIX, HOUSTON_UTC], ids=["phoenix", "houston"])
def test_fixture_parses_to_clean_year(text: str) -> None:
    w = parse_nsrdb_csv(text, "key", "NSRDB test", PSYCHRO)
    assert tuple(w.frame.columns) == WEATHER_COLUMNS
    assert w.frame.index.equals(year_index())
    assert np.isfinite(w.frame.to_numpy()).all()
    assert (w.frame[col.TWB_C] <= w.frame[col.TDB_C] + 1e-9).all()
    assert (w.frame[col.TWB_C] >= w.frame[col.TDP_C] - 0.5).all()


def test_phoenix_metadata_and_climate() -> None:
    w = parse_nsrdb_csv(PHOENIX, "key", "NSRDB test", PSYCHRO)
    assert (w.meta.lat, w.meta.lon, w.meta.elevation_m) == (33.45, -112.06, 334.0)
    assert w.meta.utc_offset_h == -7
    assert w.meta.cache_key == "key"
    assert w.frame[col.TDB_C].max() > 43  # hot and dry
    assert w.frame[col.RH_PCT].median() < 35


def test_houston_is_humid_and_shifted_from_utc() -> None:
    w = parse_nsrdb_csv(HOUSTON_UTC, "key", "NSRDB test", PSYCHRO)
    assert w.meta.utc_offset_h == -6
    assert w.frame[col.RH_PCT].median() > 65
    # UTC fixture: row 6 (06:30 UTC Jan 1) is local midnight.
    raw = pd.read_csv(FIXTURES / "houston_tmy_utc.csv", skiprows=2)
    assert w.frame[col.TDB_C].iloc[0] == raw["Temperature"].iloc[6]
    # GHI peaks near local solar noon (~12–13 h), not at 18 h UTC.
    peak_hour = w.frame[col.GHI_W_M2].groupby(w.frame.index.hour).mean().idxmax()
    assert 11 <= peak_hour <= 13


def _with_leap_day(text: str) -> str:
    """Insert Feb 29 rows (copies of Feb 28) as a leap_day=true TMY would have."""
    lines = text.splitlines(keepends=True)
    header, rows = lines[:3], lines[3:]
    feb28 = [r for r in rows if r.split(",")[1:3] == ["2", "28"]]
    feb29 = []
    for r in feb28:
        fields = r.split(",")
        fields[2], fields[5] = "29", "999"  # day, marker temperature
        feb29.append(",".join(fields))
    i = rows.index(feb28[-1]) + 1
    return "".join(header + rows[:i] + feb29 + rows[i:])


def test_leap_day_fixture_removed_and_local_time() -> None:
    leap = _with_leap_day(PHOENIX)
    assert leap.count("\n") == PHOENIX.count("\n") + 24
    w = parse_nsrdb_csv(leap, "key", "NSRDB test", PSYCHRO)
    assert len(w.frame) == 8760
    assert w.frame[col.TDB_C].max() < 100
    normal = parse_nsrdb_csv(PHOENIX, "key", "NSRDB test", PSYCHRO)
    pd.testing.assert_frame_equal(w.frame, normal.frame)


def test_unexpected_units_rejected() -> None:
    bad = PHOENIX.replace(",c,mbar,", ",f,mbar,", 1)
    with pytest.raises(WeatherFormatError, match="Temperature Units"):
        parse_nsrdb_csv(bad, "key", "s", PSYCHRO)


def test_garbage_rejected() -> None:
    with pytest.raises(WeatherFormatError):
        parse_nsrdb_csv("hello", "key", "s", PSYCHRO)


# --- client: request, caching, errors ---------------------------------------


def test_client_is_a_weather_provider(tmp_path: Path) -> None:
    client: WeatherProvider = _client(tmp_path, FakeSession())[0]
    assert client.name == "NSRDB"


def test_download_then_cache(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(200, PHOENIX))
    client, _ = _client(tmp_path, session)
    first = client.fetch_tmy(33.44812, -112.07404)
    p = session.calls[0]
    assert p["wkt"] == "POINT(-112.07 33.45)"  # rounded, lon first
    assert (p["names"], p["interval"], p["utc"], p["leap_day"]) == (
        NSRDB.dataset_name,
        60,
        "false",
        "false",
    )
    assert first.meta.cache_key == f"nsrdb/33.45_-112.07_{NSRDB.dataset_name}.csv"
    assert (tmp_path / first.meta.cache_key).read_text() == PHOENIX
    # Nearby point rounds to the same key: served from disk, no second request.
    second = client.fetch_tmy(33.4499, -112.0701)
    assert len(session.calls) == 1
    pd.testing.assert_frame_equal(first.frame, second.frame)


def test_corrupt_cache_refetched(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(200, PHOENIX))
    client, _ = _client(tmp_path, session)
    DiskCache(tmp_path).write(f"nsrdb/33.45_-112.07_{NSRDB.dataset_name}.csv", "junk")
    client.fetch_tmy(33.45, -112.07)
    assert len(session.calls) == 1


def test_out_of_coverage(tmp_path: Path) -> None:
    body = {"errors": ["No data available at the provided location", "Data processing failure."]}
    client, _ = _client(tmp_path, FakeSession(FakeResponse(400, "{}", body)))
    with pytest.raises(WeatherNotAvailableError, match="no data at this location"):
        client.fetch_tmy(50.0, 10.0)
    assert not list(tmp_path.rglob("*.csv"))


def test_bad_key(tmp_path: Path) -> None:
    text = 'Error Code,Error Message\n"API_KEY_INVALID","An invalid api_key was supplied."'
    client, _ = _client(tmp_path, FakeSession(FakeResponse(403, text)))
    with pytest.raises(WeatherAuthError, match="API key"):
        client.fetch_tmy(33.45, -112.07)


def test_other_400_reports_detail(tmp_path: Path) -> None:
    body = {"errors": ["wkt is invalid"]}
    client, _ = _client(tmp_path, FakeSession(FakeResponse(400, "{}", body)))
    with pytest.raises(WeatherServiceError, match="wkt is invalid"):
        client.fetch_tmy(33.45, -112.07)


def test_rate_limit_retried_then_succeeds(tmp_path: Path) -> None:
    session = FakeSession(FakeResponse(429), FakeResponse(503), FakeResponse(200, PHOENIX))
    client, sleeps = _client(tmp_path, session)
    client.fetch_tmy(33.45, -112.07)
    assert len(session.calls) == 3
    assert sleeps == [NSRDB.retry_backoff_s, 2 * NSRDB.retry_backoff_s]


def test_rate_limit_exhausted(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, FakeSession(*[FakeResponse(429)] * NSRDB.max_attempts))
    with pytest.raises(WeatherRateLimitError):
        client.fetch_tmy(33.45, -112.07)


def test_timeout_message_never_leaks_key(tmp_path: Path) -> None:
    exc = requests.Timeout(f"GET ...?api_key={CREDS.api_key}")
    client, _ = _client(tmp_path, FakeSession(*[exc] * NSRDB.max_attempts))
    with pytest.raises(WeatherServiceError) as info:
        client.fetch_tmy(33.45, -112.07)
    assert CREDS.api_key not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_unreadable_200_is_service_error(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, FakeSession(FakeResponse(200, "Source,oops\n")))
    with pytest.raises(WeatherServiceError):
        client.fetch_tmy(33.45, -112.07)


# --- credentials -------------------------------------------------------------


def test_credentials_from_env(tmp_path: Path) -> None:
    env = {"NSRDB_API_KEY": "k", "NSRDB_EMAIL": "e@x.com"}
    assert load_credentials(env, tmp_path / "none.toml") == NsrdbCredentials("k", "e@x.com")


def test_credentials_from_secrets_file(tmp_path: Path) -> None:
    f = tmp_path / "secrets.toml"
    f.write_text('NSRDB_API_KEY = "k2"\nNSRDB_EMAIL = "f@x.com"\n')
    assert load_credentials({}, f) == NsrdbCredentials("k2", "f@x.com")


def test_env_overrides_secrets_file(tmp_path: Path) -> None:
    f = tmp_path / "secrets.toml"
    f.write_text('NSRDB_API_KEY = "file"\nNSRDB_EMAIL = "f@x.com"\n')
    assert load_credentials({"NSRDB_API_KEY": "env"}, f).api_key == "env"


def test_missing_credentials_clear_error(tmp_path: Path) -> None:
    f = tmp_path / "secrets.toml"
    f.write_text('NSRDB_API_KEY = ""\nNSRDB_EMAIL = ""\n')
    with pytest.raises(WeatherConfigError, match="NSRDB_API_KEY"):
        load_credentials({}, f)
