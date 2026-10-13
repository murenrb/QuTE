import numpy as np
import psychrolib as psy
import pytest

from core.config.defaults import PSYCHRO, STANDARD_PRESSURE_PA
from core.weather.psychrometrics import (
    saturation_pressure_pa,
    standard_pressure_pa,
    wet_bulb_c,
)

psy.SetUnitSystem(psy.SI)


@pytest.mark.parametrize("t_c", [-20.0, -0.5, 0.0, 0.5, 10.0, 30.0, 45.0])
def test_saturation_pressure_matches_psychrolib(t_c: float) -> None:
    assert saturation_pressure_pa(np.array([t_c]))[0] == pytest.approx(psy.GetSatVapPres(t_c))


def test_saturation_pressure_hand_value() -> None:
    # ASHRAE Fundamentals table 3: p_ws(20 °C) = 2.3392 kPa
    assert saturation_pressure_pa(np.array([20.0]))[0] == pytest.approx(2339.2, abs=0.5)


def test_wet_bulb_matches_psychrolib_over_grid() -> None:
    tdb, rh = np.meshgrid(np.arange(-10.0, 50.0, 2.5), np.arange(5.0, 101.0, 5.0))
    tdb, rh = tdb.ravel(), rh.ravel()
    p = np.full_like(tdb, 97_000.0)
    ours = wet_bulb_c(tdb, rh, p, PSYCHRO)
    ref = np.array(
        [psy.GetTWetBulbFromRelHum(t, r / 100, pp) for t, r, pp in zip(tdb, rh, p, strict=True)]
    )
    # Near twb = 0 °C the ASHRAE ice/liquid equations jump, so both solvers
    # can land on different valid roots; compare away from that band (D-016).
    away = np.abs(ref) > 1.0
    assert away.sum() > 0.9 * len(ref)
    np.testing.assert_allclose(ours[away], ref[away], atol=0.01)


def test_wet_bulb_bounds() -> None:
    tdb = np.array([35.0, 35.0, 10.0])
    rh = np.array([100.0, 20.0, 50.0])
    twb = wet_bulb_c(tdb, rh, np.full(3, STANDARD_PRESSURE_PA), PSYCHRO)
    assert twb[0] == pytest.approx(35.0, abs=1e-6)  # saturated: twb = tdb
    assert (twb <= tdb).all()
    assert twb[1] < twb[0]


def test_wet_bulb_hand_value() -> None:
    # Psychrometric chart, sea level: 35 °C / 40 % RH → twb ≈ 24.0 °C
    twb = wet_bulb_c(np.array([35.0]), np.array([40.0]), np.array([101325.0]), PSYCHRO)
    assert twb[0] == pytest.approx(24.0, abs=0.2)


def test_standard_pressure() -> None:
    assert standard_pressure_pa(0.0, STANDARD_PRESSURE_PA) == STANDARD_PRESSURE_PA
    # ASHRAE table 1: 1000 m → 89.875 kPa
    assert standard_pressure_pa(1000.0, STANDARD_PRESSURE_PA) == pytest.approx(89875, rel=1e-3)
