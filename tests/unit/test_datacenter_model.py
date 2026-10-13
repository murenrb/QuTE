"""Equations from docs/models/datacenter-hourly.md."""

import numpy as np
import pytest

from core.config.defaults import ASSUMPTIONS, CoolingType
from core.models.datacenter import (
    coolant_temperature,
    free_cooling_available,
    mechanical_cop,
)


def arr(*v: float) -> np.ndarray:
    return np.array(v, dtype=float)


def test_free_cooling_threshold_is_strict() -> None:
    # supply 40, approach 10 -> free below 30 °C, mechanical at exactly 30 °C
    assert free_cooling_available(arr(29.99, 30.0, 30.01), 40, 10).tolist() == [True, False, False]


def test_cop_dry_40c_ambient() -> None:
    # T_cold = 35 °C, T_hot = 50 °C -> 0.4 * 308.15 / 15
    cop = mechanical_cop(arr(40), 40, CoolingType.DRY, ASSUMPTIONS)
    assert cop[0] == pytest.approx(0.4 * 308.15 / 15)
    assert cop[0] == pytest.approx(8.2173, abs=1e-4)


def test_cop_evaporative_uses_smaller_condenser_approach() -> None:
    # T_hot = 40 + 5 = 45 °C -> lift 10 K
    cop = mechanical_cop(arr(40), 40, CoolingType.EVAPORATIVE, ASSUMPTIONS)
    assert cop[0] == pytest.approx(min(10, 0.4 * 308.15 / 10))


def test_cop_clamped_to_max_at_low_lift_and_when_no_lift() -> None:
    cop = mechanical_cop(arr(30, 25, -20), 40, CoolingType.DRY, ASSUMPTIONS)
    assert cop.tolist() == [10.0, 10.0, 10.0]


def test_cop_crosses_max_near_37c() -> None:
    cop = mechanical_cop(arr(37.0, 37.6), 40, CoolingType.DRY, ASSUMPTIONS)
    assert cop[0] == 10.0 and cop[1] < 10.0


def test_cop_positive_and_bounded_for_extreme_heat() -> None:
    cop = mechanical_cop(arr(60, 80), 40, CoolingType.DRY, ASSUMPTIONS)
    assert ((cop > 0) & (cop <= 10)).all()


def test_coolant_floats_with_ambient_between_min_and_setpoint() -> None:
    """D-047: free cooling → ambient + approach clamped to [min, setpoint];
    chillers → setpoint."""
    t = coolant_temperature(arr(-20.0, 0.0, 15.0, 29.9, 30.0, 40.0), 40.0, 5.0, 10.0)
    np.testing.assert_allclose(t, [5.0, 10.0, 25.0, 39.9, 40.0, 40.0])
