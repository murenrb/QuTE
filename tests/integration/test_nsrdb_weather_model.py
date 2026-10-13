"""Recorded NSRDB weather → hourly frame → full site model (no live API)."""

from pathlib import Path

import numpy as np
import pytest

from core.config.defaults import ASSUMPTIONS, PSYCHRO, CoolingType
from core.control.catalog import ALL_ON
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.models.site_model import run_site_model
from core.timeseries import columns as col
from services.nsrdb import parse_nsrdb_csv

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nsrdb"


@pytest.mark.parametrize("fixture", ["phoenix_tmy_local.csv", "houston_tmy_utc.csv"])
@pytest.mark.parametrize("cooling", [CoolingType.DRY, CoolingType.EVAPORATIVE])
def test_real_weather_runs_through_model(fixture: str, cooling: CoolingType) -> None:
    weather = parse_nsrdb_csv((FIXTURES / fixture).read_text(), fixture, "NSRDB", PSYCHRO)
    dc = DataCenter(dc_type=DataCenterType(cooling_type=cooling), it_load_peak_mw=10)
    df = run_site_model(dc, weather.frame, ASSUMPTIONS)
    assert len(df) == 8760
    assert np.isfinite(df.to_numpy(dtype=float)).all()
    expected_amb = col.TDB_C if cooling is CoolingType.DRY else col.TWB_C
    np.testing.assert_array_equal(df[col.T_AMBIENT_REJ_C], df[expected_amb])
    free_hours = int((df[col.COOLING_FREE_KWTH] > 0).sum())
    assert free_hours > 0
    if cooling is CoolingType.DRY:
        assert free_hours < 8760  # hot hours need mechanical cooling


def test_evaporative_gets_more_free_cooling_in_dry_climate() -> None:
    weather = parse_nsrdb_csv(
        (FIXTURES / "phoenix_tmy_local.csv").read_text(), "phx", "NSRDB", PSYCHRO
    ).frame
    hours = {}
    for cooling in CoolingType:
        dc = DataCenter(dc_type=DataCenterType(cooling_type=cooling), it_load_peak_mw=10)
        df = run_site_model(dc, weather, ASSUMPTIONS)
        hours[cooling] = int((df[col.COOLING_FREE_KWTH] > 0).sum())
    assert hours[CoolingType.EVAPORATIVE] > hours[CoolingType.DRY]


def test_pv_enabled_full_pipeline_balances() -> None:
    from core.domain.modules import ModuleSettings, SolarPVParams

    weather = parse_nsrdb_csv(
        (FIXTURES / "phoenix_tmy_local.csv").read_text(), "phx", "NSRDB", PSYCHRO
    )
    dc = DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)
    from tests.unit.test_solar_pv import square_area

    pv = SolarPVParams(enabled=True, area=(square_area(5_000_000 / 6.5),))  # ≈ 5 MW DC
    modules = ModuleSettings(solar_pv=pv)
    df = run_site_model(dc, weather.frame, ASSUMPTIONS, modules, weather.meta, control=ALL_ON)
    assert col.PV_KW in df.columns and np.isfinite(df.to_numpy(dtype=float)).all()
    loads = df[col.IT_LOAD_KW] + df[col.IT_PARASITIC_KW] + df[col.COOLING_ELEC_KW]
    np.testing.assert_allclose(df[col.GRID_NET_KW], loads + df[col.PV_KW])
    assert (df[col.GRID_NET_KW] < loads).sum() > 3000  # PV offsets daytime load
    off = run_site_model(dc, weather.frame, ASSUMPTIONS, ModuleSettings(), weather.meta)
    assert col.PV_KW not in off.columns
