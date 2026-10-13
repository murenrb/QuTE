"""Hot water storage physics (docs/models/hot-water-storage.md, D-046)."""

import math

import numpy as np
import pandas as pd
import pytest

from core.config.defaults import M_PER_FT, WATER_CP_KJ_KGK, HwsConnection, HwsTankType
from core.control.catalog import controller
from core.control.engine import Controller
from core.domain.control import DATA_CENTER, Action, ControlSettings, ControlState
from core.domain.modules import HotWaterStorageParams, ModuleContext
from core.models.hot_water_storage import (
    HotWaterStorage,
    TankState,
    initial_state,
    two_tank_step,
)
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.solver import ColumnStream, HourlySolver


def in_default(*actions: Action) -> Controller:
    """A state machine whose Default state has these THENs."""
    return controller(
        ControlSettings(default=ControlState(id="default", name="D", actions=actions))
    )


CP = WATER_CP_KJ_KGK
M = 1_000_000.0  # kg


def _full_cold(t_cold: float = 40.0) -> TankState:
    return TankState(t_cold_c=t_cold, t_hot_c=48.0, m_cold_kg=M, m_hot_kg=0.0)


def test_charge_moves_cold_to_hot_at_return_minus_pinch() -> None:
    h = two_tank_step(_full_cold(), 1000.0, 50.0, t_pinch_c=2.0)
    m = 1000.0 * 3600 / (CP * 8.0)
    assert h.q_heat_in_kwth == pytest.approx(1000.0)
    assert h.end.m_hot_kg == pytest.approx(m) and h.end.m_cold_kg == pytest.approx(M - m)
    assert h.end.t_hot_c == pytest.approx(48.0) and h.end.t_cold_c == 40.0
    assert h.soc_end == pytest.approx(m / M)


def test_charge_limited_by_cold_water_left() -> None:
    s = TankState(40.0, 48.0, m_cold_kg=1000.0, m_hot_kg=M - 1000.0)
    h = two_tank_step(s, 1e6, 50.0, t_pinch_c=2.0)
    assert h.q_heat_in_kwth == pytest.approx(1000.0 * CP * 8.0 / 3600)
    assert h.end.m_cold_kg == 0.0 and h.soc_end == pytest.approx(1.0)


def test_discharge_moves_hot_to_cold_at_supply_plus_pinch() -> None:
    s = TankState(40.0, 48.0, m_cold_kg=0.0, m_hot_kg=M)
    h = two_tank_step(s, -500.0, 40.0, t_pinch_c=2.0)
    m = 500.0 * 3600 / (CP * 6.0)  # 48 → 42
    assert h.q_heat_in_kwth == pytest.approx(-500.0)
    assert h.end.m_cold_kg == pytest.approx(m)
    assert h.end.t_cold_c == pytest.approx(42.0)  # empty cold tank takes the inflow temp
    assert h.end.t_hot_c == 48.0


def test_mixing_into_partly_full_tank() -> None:
    s = TankState(40.0, 45.0, m_cold_kg=M / 2, m_hot_kg=M / 2)
    h = two_tank_step(s, 1000.0, 50.0, t_pinch_c=0.0)
    m = 1000.0 * 3600 / (CP * 10.0)
    assert h.end.t_hot_c == pytest.approx((m * 50 + M / 2 * 45) / (M / 2 + m))


def test_no_flow_when_temperatures_dont_allow_it() -> None:
    s = TankState(t_cold_c=49.0, t_hot_c=41.0, m_cold_kg=M / 2, m_hot_kg=M / 2)
    for q, t_in in ((1000.0, 50.0), (-1000.0, 40.0)):  # pinch 2 K closes both
        h = two_tank_step(s, q, t_in, t_pinch_c=2.0)
        assert h.q_heat_in_kwth == 0.0 and h.end == s


def test_zero_request_holds_state() -> None:
    h = two_tank_step(_full_cold(), 0.0, 50.0, t_pinch_c=2.0)
    assert h.q_heat_in_kwth == 0.0 and h.end == _full_cold() and h.soc_end == 0.0


def test_energy_and_mass_balance_over_random_cycles() -> None:
    rng = np.random.default_rng(1)
    s = _full_cold()
    stored_kj = 0.0
    for q in rng.uniform(-3000, 3000, 500):
        t_in = 50.0 if q > 0 else 40.0
        h = two_tank_step(s, float(q), t_in, t_pinch_c=2.0)
        stored_kj += h.q_heat_in_kwth * 3600
        s = h.end
        assert s.m_cold_kg + s.m_hot_kg == pytest.approx(M)
        assert s.m_cold_kg >= -1e-6 and s.m_hot_kg >= -1e-6
        assert abs(h.q_heat_in_kwth) <= abs(q) + 1e-9
    # Heat stored = sensible heat of both tanks above the start (all water at 40 °C)
    sensible = CP * (s.m_cold_kg * (s.t_cold_c - 40) + s.m_hot_kg * (s.t_hot_c - 40))
    assert stored_kj == pytest.approx(sensible, rel=1e-9)


def test_tank_volume_footprint_and_pinch() -> None:
    ctx = ModuleContext(it_peak_mw=10, t_supply_c=40, t_return_c=50)
    p = HotWaterStorageParams(enabled=True).resolved(ctx)
    vol = 10_000 * 1.1 * 12 * 3600 / (10 * 4.18 * 992)  # owner's formula, IT + 10 % parasitics
    assert p.volume_m3 == pytest.approx(vol)
    d = math.sqrt(4 * vol / (math.pi * 12))
    b = 20 * M_PER_FT
    assert p.tank_type is HwsTankType.TWO_TANK
    assert p.default_dims_m() == pytest.approx((2 * d + 2 * b, d + 2 * b))
    thermo = p.model_copy(update={"tank_type": HwsTankType.THERMOCLINE})
    assert thermo.default_dims_m() == pytest.approx((d + 2 * b, d + 2 * b))
    assert p.t_pinch_c == 2.0
    assert p.model_copy(update={"connection": HwsConnection.DIRECT}).t_pinch_c == 0.0
    assert "tank_volume_m3" not in p.model_dump()  # derived, never saved
    with pytest.raises(ValueError):
        _ = HotWaterStorageParams().volume_m3


def test_volume_follows_parasitic_fraction() -> None:
    base = ModuleContext(it_peak_mw=10, t_supply_c=40, t_return_c=50)
    v_default = HotWaterStorageParams().resolved(base).volume_m3
    v_none = (
        HotWaterStorageParams()
        .resolved(ModuleContext(it_peak_mw=10, t_supply_c=40, t_return_c=50, it_parasitic_frac=0.0))
        .volume_m3
    )
    assert v_default == pytest.approx(1.1 * v_none)  # default assumptions: 10 %


def test_initial_state_cold_tank_full() -> None:
    p = HotWaterStorageParams().resolved(ModuleContext(it_peak_mw=1))
    s = initial_state(p, 40.0, 50.0)
    assert s.m_hot_kg == 0.0 and s.m_cold_kg == pytest.approx(p.volume_m3 * 992)
    assert s.t_cold_c == 40.0


def test_adapter_charges_from_the_data_center_until_full() -> None:
    p = HotWaterStorageParams(enabled=True, storage_hours=4).resolved(
        ModuleContext(it_peak_mw=1, t_supply_c=40, t_return_c=50)
    )
    df = pd.DataFrame({"offered": [1000.0] * 8})
    # the data center gives it 1 MW an hour
    feed = ColumnStream("offered", st.heat_sent(DATA_CENTER, "hot_water_storage"))
    charge = in_default(Action(target="hot_water_storage", setting="heat_in", to=DATA_CENTER))
    out = HourlySolver((feed, HotWaterStorage(p, 40.0, 50.0)), charge).run(df)
    q = out[col.HWS_CHARGE_KWTH].to_numpy()
    # 4 h of 1.1 MW (IT + parasitics) sized on 10 K; indirect delivers 8 K
    # → 3.52 MWh, filled in 3.52 h at 1 MW
    assert q.sum() == pytest.approx(3520.0)
    assert q[0] == pytest.approx(1000.0) and q[-1] == 0.0
    np.testing.assert_allclose(out[col.HWS_NET_KWTH], q)
    # not linked: nothing moves
    idle = HourlySolver((feed, HotWaterStorage(p, 40.0, 50.0)), in_default()).run(df)
    assert (idle[col.HWS_CHARGE_KWTH] == 0).all()
    assert out[col.HWS_SOC_FRAC].iloc[-1] == pytest.approx(1.0)
    assert out[col.HWS_T_HOT_C].iloc[-1] == pytest.approx(48.0)
    t_sys = out[col.HWS_T_SYS_C].to_numpy()
    assert t_sys[0] == pytest.approx(42.0)  # charging: cold tank + pinch
    assert t_sys[-1] == pytest.approx(50.0)  # full: return water passes through


def test_t_sys_owner_example_indirect() -> None:
    """Owner's example: charge off 50 °C → hot tank 48 °C; discharge against
    40 °C → cold tank fills at 42 °C, the facility sees 46 °C (not 50 or 48)."""
    s = _full_cold()
    while s.m_cold_kg > 0:  # charge to 100 %
        h = two_tank_step(s, 5000.0, 50.0, t_pinch_c=2.0)
        assert h.t_sys_c == pytest.approx(42.0)  # facility water cooled to 40 + 2
        s = h.end
    assert s.t_hot_c == pytest.approx(48.0) and h.soc_end == pytest.approx(1.0)
    d = two_tank_step(s, -1000.0, 40.0, t_pinch_c=2.0)
    assert d.end.t_cold_c == pytest.approx(42.0)
    assert d.t_sys_c == pytest.approx(46.0)


def test_t_sys_direct_is_tank_temperature() -> None:
    s = TankState(t_cold_c=40.0, t_hot_c=50.0, m_cold_kg=M / 2, m_hot_kg=M / 2)
    assert two_tank_step(s, 1000.0, 50.0, t_pinch_c=0.0).t_sys_c == 40.0
    assert two_tank_step(s, -1000.0, 40.0, t_pinch_c=0.0).t_sys_c == 50.0


def test_t_sys_passes_inflow_through_when_nothing_moves() -> None:
    assert two_tank_step(_full_cold(), 0.0, 50.0, t_pinch_c=2.0).t_sys_c == 50.0
    empty_hot = _full_cold()  # nothing to discharge
    assert two_tank_step(empty_hot, -1000.0, 40.0, t_pinch_c=2.0).t_sys_c == 40.0


def test_charge_and_discharge_in_the_same_hour() -> None:
    """D-054: charge first, then give power generation what it asks (≤ what the
    hot tank holds above the return water's need)."""
    p = HotWaterStorageParams(enabled=True, storage_hours=4).resolved(
        ModuleContext(it_peak_mw=1, t_supply_c=40, t_return_c=50)
    )
    df = pd.DataFrame({"offered": [1000.0] * 4, "wanted": [400.0] * 4})  # fills in ~5.9 h
    feeds = (
        ColumnStream("offered", st.heat_sent(DATA_CENTER, "hot_water_storage")),
        ColumnStream("wanted", st.heat_req("hot_water_storage", "power_generation")),
    )
    both = in_default(
        Action(target="hot_water_storage", setting="heat_in", to=DATA_CENTER),
        Action(target="hot_water_storage", setting="heat_out", to="power_generation"),
    )
    out = HourlySolver((*feeds, HotWaterStorage(p, 40.0, 50.0)), both).run(df)
    np.testing.assert_allclose(out[col.HWS_CHARGE_KWTH], 1000.0)
    np.testing.assert_allclose(out[col.HWS_DISCHARGE_KWTH], 400.0)
    np.testing.assert_allclose(out[col.HWS_NET_KWTH], 600.0)
