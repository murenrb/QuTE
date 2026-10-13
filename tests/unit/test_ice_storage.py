"""Ice storage: the owner's one-hour step, hand-checked, plus balances (D-049)."""

import math

import numpy as np
import pytest

from core.config.defaults import ICE_LATENT_HEAT_KJ_KG, KW_PER_TR
from core.domain.modules import IceStorageParams
from core.models.ice_storage import (
    IceHour,
    IceTankState,
    ice_maker_capacity_factor,
    ice_maker_cop,
    ice_step,
)

# The owner's first-test case: 1,000 TR, 1 h tank, start 10 % (app defaults now
# follow the IT load — 65 TR/MW — with a 24 h tank, D-042).
# A 1 h tank is below the UI range (6–72 h), but the physics holds for any tank, so
# the case is built without the range check.
P = IceStorageParams.model_construct(
    **{**IceStorageParams().model_dump(), "ice_maker_size_tr": 1000, "tank_charge_time_h": 1.0}
)


def test_sizes() -> None:
    assert P.ice_maker_kwth == pytest.approx(1000 * KW_PER_TR)  # 3,516.85 kW_th
    assert P.tank_capacity_kwh == pytest.approx(1000 * KW_PER_TR * 1.0)


def test_curve_fits_by_hand() -> None:
    # 20 °C: COP = 0.0011·400 − 0.1503·20 + 6.562 = 3.996  (< cap 6)
    assert ice_maker_cop(20, P) == pytest.approx(3.996)
    # capacity = −0.001·400 − 0.0023·20 + 1.2453 = 0.7993  (< cap 1.23)
    assert ice_maker_capacity_factor(20, P) == pytest.approx(0.7993)
    # 0 °C: COP fit 6.562 → capped at 6
    assert ice_maker_cop(0, P) == 6.0
    # capacity fit hits zero near 34.6 °C and goes negative → clamped at 0
    root = (-0.0023 + math.sqrt(0.0023**2 + 4 * 0.001 * 1.2453)) / (2 * 0.001)
    assert root == pytest.approx(34.15, abs=0.5)
    assert ice_maker_capacity_factor(40, P) == 0.0


HF = ICE_LATENT_HEAT_KJ_KG  # kJ/kg: flows in kg/s ↔ duties in kW_th
FULL_WATER = 1.0


def _st(soc_ice: float, soc_water: float = FULL_WATER) -> IceTankState:
    return IceTankState(soc_ice=soc_ice, soc_water=soc_water)


def test_default_step_by_hand() -> None:
    """t_amb 20 °C, 5,000 kW of ice requested, ice tank 0.1, water tank full."""
    h = ice_step(_st(0.1), 5000 / HF, 0, 20, True, P)
    maker = 1000 * KW_PER_TR
    duty = min(maker * 0.7993, 0.9 * maker + 5000, maker)  # = 2,811.0 (machine-limited)
    stored = 0.1 * maker  # 351.7 kWh in the tank at the start
    q_ice = min(stored + duty, 5000)  # = 3,162.7
    assert h.maker_elec_kw == pytest.approx(duty / 3.996)  # 703.5 kW
    assert h.q_instant_kwth == pytest.approx(duty)  # all of this hour's ice is taken
    assert h.q_discharge_kwth == pytest.approx(stored)  # plus the whole tank
    assert h.q_charge_kwth == pytest.approx(0)
    assert h.q_missed_kwth == pytest.approx(5000 - q_ice)  # 1,837.3 kW not supplied
    assert h.m_ice_supplied_kg_s == pytest.approx(q_ice / HF)  # 9.58 kg/s
    assert h.m_ice_instant_kg_s == pytest.approx(duty / HF)
    assert h.end.soc_ice == pytest.approx(0, abs=1e-12)  # ice tank emptied
    assert h.end.soc_water == pytest.approx(1 - duty / maker)  # water frozen this hour


def test_not_cleared_only_supplies_stored_ice() -> None:
    h = ice_step(_st(0.5), 5000 / HF, 0, 20, False, P)
    assert (h.maker_elec_kw, h.q_instant_kwth, h.q_charge_kwth) == (0, 0, 0)
    assert h.q_discharge_kwth == pytest.approx(0.5 * P.tank_capacity_kwh)
    assert h.end == _st(0.0)


def test_full_tank_and_no_request_idles() -> None:
    h = ice_step(_st(1.0), 0, 0, 20, True, P)
    assert h == IceHour(_st(1.0), 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_no_request_fills_until_full() -> None:
    h = ice_step(_st(0.0), 0, 0, 20, True, P)
    assert h.q_charge_kwth == pytest.approx(P.ice_maker_kwth * 0.7993)  # machine-limited
    h = ice_step(_st(0.95), 0, 0, 20, True, P)
    assert h.q_charge_kwth == pytest.approx(0.05 * P.tank_capacity_kwh)  # room-limited
    assert h.end.soc_ice == pytest.approx(1.0)
    assert h.end.soc_water == pytest.approx(0.95)


def test_water_limits_ice_making() -> None:
    h = ice_step(_st(0.0, 0.1), 0, 0, 20, True, P)  # machine could make 0.8 of a tank
    assert h.q_charge_kwth == pytest.approx(0.1 * P.tank_capacity_kwh)
    assert h.end == _st(pytest.approx(0.1), pytest.approx(0.0, abs=1e-12))
    # incoming water is frozen in the same hour
    h = ice_step(_st(0.0, 0.0), 0, 500 / HF, 20, True, P)
    assert h.q_charge_kwth == pytest.approx(500)
    assert h.m_water_in_kg_s == pytest.approx(500 / HF)
    assert h.end.soc_water == pytest.approx(0, abs=1e-12)


def test_water_tank_overflow_is_refused() -> None:
    # Full water tank, full ice tank: maker idle, no water can come in.
    h = ice_step(_st(1.0, 1.0), 0, 1000 / HF, 20, True, P)
    assert h.m_water_in_kg_s == pytest.approx(0)
    # Making ice frees room for water in the same hour.
    h = ice_step(_st(0.0, 1.0), 0, 5000 / HF, 20, True, P)  # machine-limited
    duty = P.ice_maker_kwth * 0.7993
    assert h.m_water_in_kg_s == pytest.approx(duty / HF)
    assert h.end.soc_water == pytest.approx(1.0)


def test_unlimited_flows_come_back_exactly() -> None:
    """D-051: if no min binds, the accepted flows recapitulate the inputs."""
    rng = np.random.default_rng(0)
    for _ in range(500):
        req, w_in = float(rng.uniform(0, 0.5)), float(rng.uniform(0, 0.5))
        h = ice_step(_st(0.9, 0.5), req, w_in, 20, True, P)
        assert h.m_ice_supplied_kg_s == req and h.m_water_in_kg_s == w_in


def test_room_plus_request_limit_fills_exactly() -> None:
    small_tank = P.model_copy(update={"tank_charge_time_h": 0.25})  # copy skips validation too
    h = ice_step(_st(0.8), 100 / HF, 0, 20, True, small_tank)  # machine could make more
    assert h.end.soc_ice == pytest.approx(1.0)
    assert h.q_missed_kwth == pytest.approx(0)


@pytest.mark.parametrize("seed", range(5))
def test_balances_hold_for_random_hours(seed: int) -> None:
    rng = np.random.default_rng(seed)
    cap = P.tank_capacity_kwh
    for _ in range(200):
        soc_i, soc_w = float(rng.uniform(0, 1)), float(rng.uniform(0, 1))
        req, w_in = float(rng.uniform(0, 8000)) / HF, float(rng.uniform(0, 8000)) / HF
        t, cleared = float(rng.uniform(-10, 45)), bool(rng.integers(0, 2))
        h = ice_step(_st(soc_i, soc_w), req, w_in, t, cleared, P)
        duty = h.q_instant_kwth + h.q_charge_kwth
        # ice tank: end = start + charged − taken from storage
        assert h.end.soc_ice * cap == pytest.approx(
            soc_i * cap + h.q_charge_kwth - h.q_discharge_kwth, abs=1e-6
        )
        # water tank: end = start + water in − water frozen
        assert h.end.soc_water * cap == pytest.approx(
            soc_w * cap + h.m_water_in_kg_s * HF - duty, abs=1e-6
        )
        # request: supplied + missed = requested
        assert h.q_instant_kwth + h.q_discharge_kwth + h.q_missed_kwth == pytest.approx(req * HF)
        assert h.m_ice_supplied_kg_s * HF == pytest.approx(h.q_instant_kwth + h.q_discharge_kwth)
        assert h.m_water_in_kg_s <= w_in + 1e-12
        for soc in (h.end.soc_ice, h.end.soc_water):
            assert -1e-9 <= soc <= 1 + 1e-9
        for v in (h.q_instant_kwth, h.q_discharge_kwth, h.q_charge_kwth, h.q_missed_kwth):
            assert v >= -1e-9
        assert h.m_water_in_kg_s >= -1e-12
        assert h.maker_elec_kw == pytest.approx(duty / ice_maker_cop(t, P) if duty > 0 else 0)


def test_default_size_follows_it_load() -> None:
    from core.domain.modules import ModuleContext

    ice = IceStorageParams()  # size None = follow the data center
    assert ice.resolved(ModuleContext(it_peak_mw=10)).ice_maker_size_tr == pytest.approx(650)
    assert ice.resolved(ModuleContext(it_peak_mw=100)).ice_maker_size_tr == pytest.approx(6500)
    assert ice.resolved(ModuleContext()).ice_maker_size_tr == pytest.approx(650)  # no DC: 10 MW
    assert P.resolved(ModuleContext(it_peak_mw=100)).ice_maker_size_tr == 1000  # user's own
    assert IceStorageParams().tank_charge_time_h == 24
    with pytest.raises(ValueError):
        IceStorageParams(tank_charge_time_h=5)
    with pytest.raises(ValueError, match="Resolve"):
        _ = IceStorageParams().ice_maker_kwth
