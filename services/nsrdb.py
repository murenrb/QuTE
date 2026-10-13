"""NSRDB GOES TMY v4 client (docs/integrations/nsrdb-weather.md).

Fetches one typical year as CSV, caches the raw text on disk, and parses it
into `WeatherData` via the provider-independent `core.weather.tmy`.
"""

import csv
import io
import os
import time
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd
import requests

from core.config.defaults import (
    NSRDB,
    PA_PER_MBAR,
    PSYCHRO,
    STANDARD_PRESSURE_PA,
    NsrdbSettings,
    PsychrometricSettings,
)
from core.timeseries import columns as col
from core.weather.psychrometrics import standard_pressure_pa
from core.weather.tmy import (
    RawTmy,
    WeatherData,
    WeatherFormatError,
    WeatherMeta,
    normalize_tmy,
)
from services.cache import PROJECT_ROOT, DiskCache, cache_root
from services.weather import (
    WeatherAuthError,
    WeatherConfigError,
    WeatherNotAvailableError,
    WeatherRateLimitError,
    WeatherServiceError,
)

SECRETS_FILE = PROJECT_ROOT / ".streamlit" / "secrets.toml"
API_KEY_NAME = "NSRDB_API_KEY"
EMAIL_NAME = "NSRDB_EMAIL"

# NSRDB CSV column → canonical name. Units are checked against _EXPECTED_UNITS.
_COLUMN_MAP = {
    "Year": "year",
    "Month": "month",
    "Day": "day",
    "Hour": "hour",
    "Minute": "minute",
    "Temperature": col.TDB_C,
    "Dew Point": col.TDP_C,
    "Relative Humidity": col.RH_PCT,
    "GHI": col.GHI_W_M2,
    "DNI": col.DNI_W_M2,
    "DHI": col.DHI_W_M2,
    "Wind Speed": col.WIND_M_S,
    "Pressure": "pressure_mbar",
}
_EXPECTED_UNITS = {
    "Temperature Units": "c",
    "Dew Point Units": "c",
    "Relative Humidity Units": "%",
    "GHI Units": "w/m2",
    "DNI Units": "w/m2",
    "DHI Units": "w/m2",
    "Wind Speed Units": "m/s",
    "Pressure Units": "mbar",
}
_HEADER_LINES = 2  # metadata keys, metadata values; then the column header


@dataclass(frozen=True)
class NsrdbCredentials:
    api_key: str
    email: str


def load_credentials(
    env: Mapping[str, str] | None = None, secrets_file: Path = SECRETS_FILE
) -> NsrdbCredentials:
    """From env vars (Streamlit Cloud exposes root secrets this way), else secrets.toml."""
    source: Mapping[str, object] = os.environ if env is None else env
    if not (source.get(API_KEY_NAME) and source.get(EMAIL_NAME)) and secrets_file.is_file():
        with secrets_file.open("rb") as f:
            source = {**tomllib.load(f), **{k: v for k, v in source.items() if v}}
    key, email = source.get(API_KEY_NAME), source.get(EMAIL_NAME)
    if not (isinstance(key, str) and key and isinstance(email, str) and email):
        raise WeatherConfigError(
            f"NSRDB credentials missing: set {API_KEY_NAME} and {EMAIL_NAME} in "
            ".streamlit/secrets.toml (or Streamlit Cloud secrets). "
            "Get a free key at https://developer.nlr.gov/signup/"
        )
    return NsrdbCredentials(api_key=key, email=email)


def cache_key(lat: float, lon: float, settings: NsrdbSettings) -> str:
    d = settings.coord_decimals
    return f"nsrdb/{lat:.{d}f}_{lon:.{d}f}_{settings.dataset_name}.csv"


def parse_nsrdb_csv(
    text: str, key: str, source: str, psychro: PsychrometricSettings
) -> WeatherData:
    """NSRDB CSV text → WeatherData. Raises WeatherFormatError if unreadable."""
    header = list(csv.reader(io.StringIO(text)))[:_HEADER_LINES]
    if len(header) < _HEADER_LINES or len(header[0]) != len(header[1]):
        raise WeatherFormatError("NSRDB response has no metadata header")
    meta_row = dict(zip(header[0], header[1], strict=True))
    for field, unit in _EXPECTED_UNITS.items():
        if field in meta_row and meta_row[field].lower() != unit:
            raise WeatherFormatError(f"Unexpected {field}: {meta_row[field]!r} (want {unit!r})")
    try:
        data_tz = float(meta_row["Time Zone"])
        local_tz = float(meta_row["Local Time Zone"])
        elevation_m = float(meta_row["Elevation"])
        meta = WeatherMeta(
            source=source,
            location_id=meta_row.get("Location ID", ""),
            lat=float(meta_row["Latitude"]),
            lon=float(meta_row["Longitude"]),
            elevation_m=elevation_m,
            utc_offset_h=local_tz,
            cache_key=key,
        )
    except (KeyError, ValueError) as e:
        raise WeatherFormatError(f"NSRDB metadata missing or invalid: {e}") from e

    rows = pd.read_csv(io.StringIO(text), skiprows=_HEADER_LINES)
    rows = rows.rename(columns=_COLUMN_MAP)
    rows = rows[[c for c in _COLUMN_MAP.values() if c in rows.columns]]
    if "pressure_mbar" in rows:
        rows["pressure_pa"] = rows["pressure_mbar"] * PA_PER_MBAR
    else:
        rows["pressure_pa"] = standard_pressure_pa(elevation_m, STANDARD_PRESSURE_PA)
    minutes = rows["minute"].unique() if "minute" in rows else [0]
    if len(minutes) != 1:
        raise WeatherFormatError(f"Expected one timestamp minute for hourly data, got {minutes}")
    meta = replace(meta, data_minute=int(minutes[0]))
    frame = normalize_tmy(RawTmy(rows, data_tz, local_tz), psychro)
    return WeatherData(frame=frame, meta=meta)


class NsrdbClient:
    """Implements services.weather.WeatherProvider for NSRDB GOES TMY."""

    name = "NSRDB"

    def __init__(
        self,
        credentials: NsrdbCredentials,
        settings: NsrdbSettings = NSRDB,
        psychro: PsychrometricSettings = PSYCHRO,
        cache: DiskCache | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.credentials = credentials
        self.settings = settings
        self.psychro = psychro
        self.cache = cache or DiskCache(cache_root())
        self.session = session or requests.Session()
        self.sleep = sleep

    @property
    def source(self) -> str:
        return f"NSRDB {self.settings.dataset_name}"

    def fetch_tmy(self, lat: float, lon: float) -> WeatherData:
        """Typical year at (lat, lon), from disk cache if present, else downloaded."""
        d = self.settings.coord_decimals
        lat_r, lon_r = round(lat, d), round(lon, d)
        key = cache_key(lat_r, lon_r, self.settings)
        cached = self.cache.read(key)
        if cached is not None:
            try:
                return parse_nsrdb_csv(cached, key, self.source, self.psychro)
            except WeatherFormatError:
                pass  # corrupt cache entry: fetch a fresh copy below
        text = self._download(lat_r, lon_r)
        try:
            weather = parse_nsrdb_csv(text, key, self.source, self.psychro)
        except WeatherFormatError as e:
            raise WeatherServiceError(f"NSRDB returned data we could not read: {e}") from e
        self.cache.write(key, text)
        return weather

    def _download(self, lat: float, lon: float) -> str:
        s = self.settings
        params: dict[str, str | int] = {
            "api_key": self.credentials.api_key,
            "email": self.credentials.email,
            "wkt": f"POINT({lon} {lat})",
            "names": s.dataset_name,
            "interval": s.interval_min,
            "utc": "false",
            "leap_day": "false",
        }
        delay = s.retry_backoff_s
        for attempt in range(1, s.max_attempts + 1):
            last = attempt == s.max_attempts
            try:
                r = self.session.get(s.base_url, params=params, timeout=s.timeout_s)
            except (requests.Timeout, requests.ConnectionError):
                # Never echo the exception: its URL carries the API key.
                if last:
                    raise WeatherServiceError(
                        "Could not reach NSRDB (timeout or network error). Try again shortly."
                    ) from None
                self.sleep(delay)
                delay *= 2
                continue
            if r.status_code == 200 and r.text.startswith("Source,"):
                return r.text
            if r.status_code == 429 or r.status_code >= 500:
                if last:
                    if r.status_code == 429:
                        raise WeatherRateLimitError(
                            "NSRDB rate limit reached. Wait a minute and try again."
                        )
                    raise WeatherServiceError(f"NSRDB server error (HTTP {r.status_code}).")
                self.sleep(delay)
                delay *= 2
                continue
            raise _classify_error(r)
        raise AssertionError("unreachable")  # pragma: no cover


def _classify_error(r: requests.Response) -> Exception:
    if r.status_code in (401, 403):
        return WeatherAuthError("NSRDB rejected the API key. Check NSRDB_API_KEY in your secrets.")
    messages: list[str] = []
    try:
        body = r.json()
        if isinstance(body, dict):
            messages = [str(m) for m in body.get("errors", [])]
    except ValueError:
        messages = [r.text.strip()[:200]] if r.text else []
    if any("no data available" in m.lower() for m in messages):
        return WeatherNotAvailableError(
            "NSRDB has no data at this location (GOES TMY covers the Americas). "
            "Other weather sources are on the roadmap."
        )
    detail = "; ".join(messages) or "no details"
    return WeatherServiceError(f"NSRDB request failed (HTTP {r.status_code}): {detail}")
