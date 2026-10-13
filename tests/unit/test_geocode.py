from dataclasses import dataclass
from typing import Any

import pytest
import requests
from geopy.exc import GeocoderUnavailable

from services import geocode as geo
from services.geocode import GeocodeError, GeocodeResult, census_provider, geocode

# Recorded 2026-09-30 from the Census onelineaddress endpoint (trimmed).
CENSUS_MATCH = {
    "result": {
        "addressMatches": [
            {
                "coordinates": {"x": -105.168601020241, "y": 39.740745743393},
                "matchedAddress": "15013 DENVER WEST PKWY, GOLDEN, CO, 80401",
            }
        ]
    }
}
CENSUS_NO_MATCH: dict[str, Any] = {"result": {"addressMatches": []}}
HIT = GeocodeResult(1.0, 2.0, "hit")


class FakeResponse:
    def __init__(self, body: Any, status: int = 200) -> None:
        self.body, self.status_code = body, status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self) -> Any:
        return self.body


class FakeSession:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.params: dict[str, Any] = {}

    def get(self, url: str, params: dict[str, Any], timeout: float) -> FakeResponse:
        self.params = params
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _census(response: FakeResponse | Exception) -> geo.Provider:
    return census_provider(session=FakeSession(response))  # type: ignore[arg-type]


def _raise(query: str) -> GeocodeResult | None:
    raise GeocodeError("down")


# --- Census provider -------------------------------------------------------------


def test_census_exact_rural_address() -> None:
    session = FakeSession(FakeResponse(CENSUS_MATCH))
    r = census_provider(session=session)("15013 Denver West Pkwy, Golden, CO 80401")  # type: ignore[arg-type]
    assert r == GeocodeResult(
        39.740745743393, -105.168601020241, "15013 DENVER WEST PKWY, GOLDEN, CO, 80401"
    )
    assert session.params["benchmark"] == "Public_AR_Current"


def test_census_no_match() -> None:
    assert _census(FakeResponse(CENSUS_NO_MATCH))("Paris, France") is None


@pytest.mark.parametrize(
    "response",
    [requests.ConnectionError("x"), FakeResponse({}, 503), FakeResponse({"oops": 1})],
    ids=["network", "http-error", "bad-body"],
)
def test_census_errors(response: FakeResponse | Exception) -> None:
    with pytest.raises(GeocodeError, match="Census"):
        _census(response)("x")


# --- Nominatim provider ----------------------------------------------------------


@dataclass
class _Loc:
    latitude: float
    longitude: float
    address: str


def test_nominatim_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeNominatim:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["ssl_context"] is not None  # certifi bundle passed through

        def geocode(self, query: str, exactly_one: bool = True) -> Any:
            if query == "down":
                raise GeocoderUnavailable("ssl")
            return _Loc(39.7, -105.2, "Golden, CO") if query == "Golden" else None

    monkeypatch.setattr(geo, "Nominatim", FakeNominatim)
    lookup = geo.nominatim_provider()
    assert lookup("Golden") == GeocodeResult(39.7, -105.2, "Golden, CO")
    assert lookup("nowhere") is None
    with pytest.raises(GeocodeError, match="OpenStreetMap"):
        lookup("down")


# --- chain -------------------------------------------------------------------------


def test_first_match_wins() -> None:
    calls: list[str] = []

    def second(q: str) -> GeocodeResult | None:
        calls.append(q)
        return None

    assert geocode("  x ", [lambda q: HIT, second]) == HIT
    assert calls == []


def test_falls_back_when_first_has_no_match_or_errors() -> None:
    assert geocode("x", [lambda q: None, lambda q: HIT]) == HIT
    assert geocode("x", [_raise, lambda q: HIT]) == HIT


def test_no_match_anywhere() -> None:
    assert geocode("x", [lambda q: None, _raise]) is None


def test_all_providers_error() -> None:
    with pytest.raises(GeocodeError, match="down; down"):
        geocode("x", [_raise, _raise])


def test_blank_skips_lookup() -> None:
    assert geocode("   ", [_raise]) is None
