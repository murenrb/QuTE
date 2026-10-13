# NSRDB Weather Integration

API docs: https://developer.nlr.gov/docs/solar/nsrdb/nsrdb-GOES-tmy-v4-0-0-download/

| Piece | Code |
|---|---|
| Provider interface + user-facing errors | `services/weather.py` (`WeatherProvider`, `WeatherError` subclasses) |
| NSRDB client, CSV parser, credentials | `services/nsrdb.py` (`NsrdbClient`, `parse_nsrdb_csv`, `load_credentials`) |
| Raw-response disk cache | `services/cache.py` (`DiskCache`) |
| Provider-independent cleanup (time, leap day, wet bulb) | `core/weather/tmy.py` (`normalize_tmy`, `WeatherData`) |
| Wet-bulb psychrometrics | `core/weather/psychrometrics.py` |
| UI loader (`st.cache_data` + `st.error`) | `app/components/weather.py` (`load_weather`) |
| Settings | `NsrdbSettings`, `PsychrometricSettings` in `core/config/defaults.py` |

A second source (EPW upload, PVGIS — D-012) = a new `WeatherProvider` that
parses its file into `RawTmy` and reuses `normalize_tmy`.

## Request
- Endpoint: `GET .../api/nsrdb/v2/solar/nsrdb-GOES-tmy-v4-0-0-download.csv`
  (GOES TMY v4, 4 km, Americas only). PSM3 TMY is deprecated.
- `names=tmy-2024` (pinned, D-015), `interval=60`, `utc=false`,
  `leap_day=false`, `wkt=POINT(<lon> <lat>)` with coords rounded to 2 decimals.
- All attributes are returned (no `attributes` param); we use five.
- Credentials: `NSRDB_API_KEY`, `NSRDB_EMAIL` from env vars (Streamlit Cloud
  exposes root-level secrets as env vars) else `.streamlit/secrets.toml`.
  **Never commit keys.** Error messages never echo request URLs (they carry the key).
- Limits: CSV 10,000 requests/day, 1 per second, 20 in flight.

## Response format (as recorded 2026-09-30)
```
line 1: metadata keys   Source,Location ID,…,Latitude,Longitude,Time Zone,Elevation,Local Time Zone,…,Temperature Units,…
line 2: metadata values NSRDB,323705,…,33.45,-112.06,-7,334,-7,…,c,…
line 3: column header   Year,Month,Day,Hour,Minute,Temperature,…,Dew Point,…,GHI,…,Relative Humidity,…,Pressure,…
8760 data rows          Minute is always 30; Year differs per month (TMY stitching)
```
`Time Zone` = offset the timestamps are in (0 if `utc=true`); `Local Time Zone`
= site standard-time offset. Units are checked (`c`, `%`, `w/m2`, `mbar`).
**No wet bulb** is provided.

## Post-processing (`normalize_tmy`)
1. Drop Feb 29 (defensive — `leap_day=false` already omits it).
2. Sort by (month, day, hour) and require exactly one complete hourly year.
3. Map each row to the hour-beginning slot of reference year 2025 (the `:30`
   stamp belongs to hour `h`). Source years are ignored.
4. Shift to local standard time: roll rows by `Local Time Zone − Time Zone`
   hours, wrapping Dec 31 ↔ Jan 1. Zero with `utc=false`; half-hour zones round.
5. Columns kept: `tdb_c`, `twb_c`, `tdp_c`, `rh_pct`, `ghi_w_m2`, plus
   `dni_w_m2`, `dhi_w_m2`, `wind_m_s` for the PV module (D-034, revising
   D-014). Everything else is dropped (the raw CSV stays in the cache). The
   `Minute` stamp (30) is kept as `WeatherMeta.data_minute` for solar models.
6. `twb_c` derived from TDB + RH + pressure (mbar → Pa; standard atmosphere
   from elevation if pressure is absent) by vectorized ASHRAE psychrometrics —
   matches `psychrolib` within 0.01 °C except within ~0.5 °C of twb = 0 °C (D-016).

## Caching & reliability
- Raw CSV cached at `data/cache/nsrdb/<lat>_<lon>_tmy-2024.csv` (gitignored);
  set `DCS_CACHE_DIR` to put it elsewhere (e.g. outside OneDrive). The key is
  the Site's `weather_ref`. Unreadable cache entries are re-downloaded.
- Retries HTTP 429 / 5xx / timeouts up to 3 attempts, backoff 2 s then 4 s.
- Errors (all `WeatherError`, `str(e)` is shown to the user):
  | Case | Response | Error |
  |---|---|---|
  | No key/email | — | `WeatherConfigError` |
  | Bad key | 403, CSV body `API_KEY_INVALID` | `WeatherAuthError` |
  | Outside coverage | 400, JSON `errors: ["No data available at the provided location", …]` | `WeatherNotAvailableError` |
  | Rate limited after retries | 429 | `WeatherRateLimitError` |
  | Timeout / network / 5xx / other 400 / unreadable CSV | — | `WeatherServiceError` |

## Tests
- `tests/fixtures/nsrdb/`: recorded 2026-09-30, trimmed to the columns we
  parse (metadata rows kept whole; re-trimmed 2026-10-01 from the same
  downloads to add DNI, DHI, Wind Speed). `phoenix_tmy_local.csv` (dry, `utc=false`),
  `houston_tmy_utc.csv` (humid, `utc=true` — exercises the time shift; verified
  identical to Houston's `utc=false` download when recorded).
- `tests/unit/test_nsrdb.py` uses a fake HTTP session; leap-day case is built
  by inserting Feb 29 into the Phoenix fixture.
- Live: `pytest -m live` (`tests/live/`) — needs real credentials.
