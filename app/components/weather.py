"""Site weather for the UI, cached per location (docs/integrations/nsrdb-weather.md)."""

import streamlit as st

from core.weather.tmy import WeatherData
from services.nsrdb import NsrdbClient, load_credentials


@st.cache_data(show_spinner="Downloading NSRDB weather…")
def _fetch_tmy(lat: float, lon: float) -> WeatherData:
    return NsrdbClient(load_credentials()).fetch_tmy(lat, lon)


def fetch_weather(lat: float, lon: float) -> WeatherData:
    """Typical-year weather; raises services.weather.WeatherError (user-facing text)."""
    return _fetch_tmy(lat, lon)
