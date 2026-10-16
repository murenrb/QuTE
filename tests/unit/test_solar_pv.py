"""Solar PV module (PVWatts V8 via PySAM) on recorded Phoenix weather."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.config.defaults import PSYCHRO, SQFT_TO_M2, PvArrayType
from core.control.catalog import controller
from core.control.engine import Controller
from core.domain.control import Action, ControlSettings, ControlState
from core.domain.modules import ModuleSettings, SolarPVParams
from core.domain.site import AreaPolygon
from core.geometry.local_frame import LocalFrame
from core.models.site_model import module_subsystems
from core.models.solar_pv import (
    PvOutput,
    PvSite,
    SolarPV,
    effective_azimuth_deg,
    effective_tilt_deg,
    pv_capacity_kw,
    pvwatts_ac_kw,
    resolve_orientation,
)
from core.timeseries import columns as col
from core.timeseries.solver import HourlySolver
from core.weather.tmy import WeatherData
from services.nsrdb import parse_nsrdb_csv

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "nsrdb" / "phoenix_tmy_local.csv"
# PVWatts V8 defaults: fixed open rack, south; tilt pinned at 20° for the
# regression value (the app default follows the site latitude). Size explicit.
BASE = SolarPVParams(tilt_deg=20, azimuth_deg=180)
KW_1MW = 1000.0
# Regression value: PySAM on the raw Phoenix NSRDB file (2026-10-01). The
# PVWatts web API gave 1,764,113 kWh on its own tmy-2020 weather (0.3 % apart).
PHOENIX_1MW_KWH = 1_758_822


def in_default(*actions: Action) -> Controller:
    """A state machine whose Default state has these THENs."""
    return controller(
        ControlSettings(default=ControlState(id="default", name="D", actions=actions))
    )


@pytest.fixture(scope="module")
def phoenix() -> WeatherData:
    return parse_nsrdb_csv(FIXTURE.read_text(), "phx", "NSRDB test", PSYCHRO)


def square_area(sqft: float, center: tuple[float, float] = (33.45, -112.06)) -> AreaPolygon:
    half = (sqft * 0.09290304) ** 0.5 / 2
    ring = LocalFrame(center).to_latlon(
        [(-half, -half), (half, -half), (half, half), (-half, half)]
    )
    return AreaPolygon(exterior=tuple(ring))


def _ac_kw(w: WeatherData, p: SolarPVParams = BASE, kw: float = KW_1MW) -> np.ndarray:
    f, idx = w.frame, pd.DatetimeIndex(w.frame.index)
    return pvwatts_ac_kw(
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
    )


def test_site_from_weather(phoenix: WeatherData) -> None:
    site = PvSite.from_weather(phoenix.meta)
    assert (site.lat, site.lon, site.utc_offset_h, site.elevation_m) == (33.45, -112.06, -7, 334)
    assert site.data_minute == 30  # NSRDB stamps values at :30


def test_annual_energy_regression(phoenix: WeatherData) -> None:
    ac = _ac_kw(phoenix)
    assert len(ac) == 8760
    assert ac.sum() == pytest.approx(PHOENIX_1MW_KWH, rel=1e-3)
    capacity_factor = ac.sum() / (KW_1MW * 8760)
    assert 0.18 < capacity_factor < 0.23  # sunny desert, fixed tilt


def test_physical_behaviour(phoenix: WeatherData) -> None:
    ac = _ac_kw(phoenix)
    ghi = phoenix.frame[col.GHI_W_M2].to_numpy()
    assert np.all(np.abs(ac[ghi == 0]) < 1e-6)  # nothing at night
    ac_rating_kw = KW_1MW / BASE.dc_ac_ratio
    assert ac.max() <= ac_rating_kw + 1e-6  # inverter clipping
    peak_hour = int(np.argmax(ac.reshape(365, 24).mean(axis=0)))
    assert 11 <= peak_hour <= 13  # local solar noon (Phoenix: no DST, ~12:30)


@pytest.mark.parametrize(
    ("change", "relation"),
    [
        ({}, "double"),
        ({"azimuth_deg": 0}, "less"),  # north-facing
        ({"array_type": PvArrayType.ONE_AXIS_BACKTRACKING}, "more"),
        ({"losses_pct": 30}, "less"),
    ],
)
def test_inputs_move_output_the_right_way(
    phoenix: WeatherData, change: dict[str, object], relation: str
) -> None:
    base = _ac_kw(phoenix).sum()
    kw = 2 * KW_1MW if relation == "double" else KW_1MW
    other = _ac_kw(phoenix, BASE.model_copy(update=change), kw).sum()
    if relation == "double":
        # Proportional to ~1e-5 (PVWatts inverter/clipping math isn't perfectly linear).
        assert other == pytest.approx(2 * base, rel=1e-4)
    elif relation == "more":
        assert other > 1.1 * base
    else:
        assert other < base


def test_capacity_from_area_and_density() -> None:
    p = SolarPVParams(enabled=True, area=(square_area(100_000),))
    assert pv_capacity_kw(p) == pytest.approx(100_000 * 6.5 / 1000, rel=1e-6)  # 650 kW
    assert pv_capacity_kw(p.model_copy(update={"power_density_w_sqft": 8.0})) == pytest.approx(
        800, rel=1e-6
    )
    assert pv_capacity_kw(SolarPVParams()) == 0


def test_cover_data_center_adds_the_roof() -> None:
    """D-073: the data center block area × the same density, only when toggled
    on — and PV still needs a drawn area to run."""
    roof_m2 = 50_000 * SQFT_TO_M2
    p = SolarPVParams(enabled=True, area=(square_area(100_000),))
    assert pv_capacity_kw(p, roof_m2) == pytest.approx(650, rel=1e-6)  # toggle off
    covered = p.model_copy(update={"cover_data_center": True})
    assert pv_capacity_kw(covered, roof_m2) == pytest.approx(150_000 * 6.5 / 1000, rel=1e-6)
    roof_only = SolarPVParams(enabled=True, cover_data_center=True)
    assert module_subsystems(ModuleSettings(solar_pv=roof_only), None, None, roof_m2) == []


def test_adapter_writes_negative_generation(phoenix: WeatherData) -> None:
    p = SolarPVParams(enabled=True, area=(square_area(1_000_000 / 6.5),))  # ≈ 1 MW DC
    frame = phoenix.frame
    out = SolarPV(p, PvSite.from_weather(phoenix.meta)).run(frame)
    pv = out[col.PV_AVAILABLE_KW].to_numpy()
    assert (pv >= -1e-9).all()
    assert pv.sum() == pytest.approx(PHOENIX_1MW_KWH, rel=2e-3)
    # the state machine: generates (negative) when told to, else curtailed (D-054)
    gen = in_default(Action(target="solar_pv", setting="generate"))
    on = HourlySolver((PvOutput(),), gen).run(out)
    np.testing.assert_allclose(on[col.PV_KW], -pv)
    off = HourlySolver((PvOutput(),), in_default()).run(out)
    assert (off[col.PV_KW] == 0).all()
    assert set(frame.columns) < set(out.columns)


def test_module_subsystems_only_when_area_drawn() -> None:
    assert module_subsystems(ModuleSettings(), None) == []  # no area → no PV
    placed = ModuleSettings(solar_pv=SolarPVParams(enabled=True, area=(square_area(10_000),)))
    with pytest.raises(ValueError, match="weather site"):
        module_subsystems(placed, None)


def test_params_validated() -> None:
    with pytest.raises(ValueError):
        SolarPVParams(tilt_deg=95)
    with pytest.raises(ValueError):
        SolarPVParams(power_density_w_sqft=4.9)
    with pytest.raises(ValueError):
        SolarPVParams(power_density_w_sqft=9.25)


@pytest.mark.parametrize(
    ("tilt", "lat", "expected"),
    [(None, 33.45, 33.45), (None, -34.6, 34.6), (25.0, 33.45, 25.0), (None, None, 20.0)],
    ids=["follows-latitude", "southern-hemisphere", "user-tilt-wins", "no-location-fallback"],
)
def test_effective_tilt(tilt: float | None, lat: float | None, expected: float) -> None:
    assert effective_tilt_deg(SolarPVParams(tilt_deg=tilt), lat, 20.0) == pytest.approx(expected)


def test_default_tilt_uses_map_latitude_in_the_pipeline(phoenix: WeatherData) -> None:
    area = (square_area(1_000_000 / 6.5),)
    site = PvSite.from_weather(phoenix.meta)
    follow = SolarPV(SolarPVParams(enabled=True, area=area), site, 33.448).run(phoenix.frame)
    fixed = SolarPV(
        SolarPVParams(enabled=True, area=area, tilt_deg=33.448, azimuth_deg=180), site, None
    ).run(phoenix.frame)
    flat20 = SolarPV(SolarPVParams(enabled=True, area=area, tilt_deg=20), site, None).run(
        phoenix.frame
    )
    pv = col.PV_AVAILABLE_KW
    np.testing.assert_allclose(follow[pv], fixed[pv])
    assert follow[pv].sum() != pytest.approx(flat20[pv].sum(), rel=1e-4)


@pytest.mark.parametrize(
    ("azimuth", "lat", "expected"),
    [
        (None, 33.45, 180.0),
        (None, -34.6, 0.0),
        (None, 0.0, 180.0),
        (90.0, -34.6, 90.0),
        (None, None, 180.0),
    ],
    ids=["north-faces-south", "south-faces-north", "equator", "user-azimuth-wins", "no-location"],
)
def test_effective_azimuth(azimuth: float | None, lat: float | None, expected: float) -> None:
    p = SolarPVParams(azimuth_deg=azimuth)
    assert effective_azimuth_deg(p, lat, 180.0, 0.0) == expected


def test_resolve_orientation_fills_both() -> None:
    r = resolve_orientation(SolarPVParams(), -33.9)  # Cape Town
    assert (r.tilt_deg, r.azimuth_deg) == (pytest.approx(33.9), 0.0)
    kept = resolve_orientation(SolarPVParams(tilt_deg=10, azimuth_deg=200), -33.9)
    assert (kept.tilt_deg, kept.azimuth_deg) == (10, 200)
