"""Address → lat/lon (docs/workflow/01-setup-tabs.md §1).

Tries the US Census geocoder first (exact US street addresses, no key), then
OpenStreetMap Nominatim (towns, places, non-US). OSM often lacks rural house
numbers, which is why Census goes first (D-022). The UI caches results and
only geocodes when the user presses "Find".
"""

import ssl
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import certifi
import requests
from geopy.exc import GeopyError
from geopy.geocoders import Nominatim

from core.config.defaults import GEOCODE, GeocodeSettings


class GeocodeError(RuntimeError):
    """Lookup failed (network/service). `str(e)` is user-facing."""


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lon: float
    label: str  # the service's full address for what it matched


Provider = Callable[[str], GeocodeResult | None]


def census_provider(
    settings: GeocodeSettings = GEOCODE, session: requests.Session | None = None
) -> Provider:
    http = session or requests.Session()

    def lookup(query: str) -> GeocodeResult | None:
        params = {"address": query, "benchmark": settings.census_benchmark, "format": "json"}
        try:
            r = http.get(settings.census_url, params=params, timeout=settings.timeout_s)
            r.raise_for_status()
            matches: list[dict[str, Any]] = r.json()["result"]["addressMatches"]
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            raise GeocodeError(f"US Census geocoder unavailable ({type(e).__name__})") from e
        if not matches:
            return None
        m = matches[0]
        c = m["coordinates"]
        return GeocodeResult(lat=float(c["y"]), lon=float(c["x"]), label=str(m["matchedAddress"]))

    return lookup


def nominatim_provider(settings: GeocodeSettings = GEOCODE) -> Provider:
    g = Nominatim(
        user_agent=settings.user_agent,
        timeout=settings.timeout_s,
        # certifi's CA bundle: python.org/uv builds on macOS ship without system
        # CAs, so the default SSL context fails certificate verification (D-022).
        ssl_context=ssl.create_default_context(cafile=certifi.where()),
    )

    def lookup(query: str) -> GeocodeResult | None:
        try:
            loc = g.geocode(query, exactly_one=True)
        except GeopyError as e:
            raise GeocodeError(f"OpenStreetMap geocoder unavailable ({type(e).__name__})") from e
        if loc is None:
            return None
        return GeocodeResult(float(loc.latitude), float(loc.longitude), str(loc.address))

    return lookup


def geocode(address: str, providers: Sequence[Provider] | None = None) -> GeocodeResult | None:
    """First match across providers, or None if none matched.

    A provider that errors is skipped; GeocodeError only if every provider errored.
    """
    query = address.strip()
    if not query:
        return None
    chain = providers if providers is not None else (census_provider(), nominatim_provider())
    errors: list[str] = []
    for lookup in chain:
        try:
            result = lookup(query)
        except GeocodeError as e:
            errors.append(str(e))
            continue
        if result is not None:
            return result
    if errors and len(errors) == len(chain):
        raise GeocodeError(
            f"Address lookup failed: {'; '.join(errors)}. Try again, or enter lat/lon."
        )
    return None
