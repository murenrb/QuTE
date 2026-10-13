"""Weather provider interface and errors (D-012: more providers drop in here).

Every provider returns `core.weather.tmy.WeatherData`; error messages are
written to be shown to the user as-is.
"""

from typing import Protocol

from core.weather.tmy import WeatherData


class WeatherError(RuntimeError):
    """Base class: weather could not be loaded. `str(e)` is user-facing."""


class WeatherConfigError(WeatherError):
    """Missing or invalid credentials/configuration."""


class WeatherAuthError(WeatherError):
    """The service rejected the API key."""


class WeatherNotAvailableError(WeatherError):
    """No data for this location (e.g. outside the dataset's coverage)."""


class WeatherRateLimitError(WeatherError):
    """Too many requests; retried and still refused."""


class WeatherServiceError(WeatherError):
    """Timeout, network failure, server error or unreadable response."""


class WeatherProvider(Protocol):
    @property
    def name(self) -> str: ...

    def fetch_tmy(self, lat: float, lon: float) -> WeatherData: ...
