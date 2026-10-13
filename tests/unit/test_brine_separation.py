"""Brine separation physics and sizing (docs/models/brine-separation.md, D-048)."""

import math

import numpy as np
import pandas as pd
import pytest

from core.config.defaults import BRINES, M_PER_FT, BrineType
from core.control.catalog import controller
from core.control.engine import Controller
from core.domain.brine import rho_brine, vapor_sat_temp, water_activity
from core.domain.control import DATA_CENTER, Action, ControlSettings, ControlState
from core.domain.modules import BrineSeparationParams, ModuleContext
from core.models.brine_separation import (
    BrineDesign,
    BrineSeparation,
    BrineState,
    brine_sep_step,
    condensing_temp_c,
)
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.solver import ColumnStream, HourlySolver


def in_default(*actions: Action) -> Controller:
    """A state machine whose Default state has these THENs."""
    return controller(
        ControlSettings(default=ControlState(id="default", name="D", actions=actions))
    )


KAC = BRINES[BrineType.POTASSIUM_ACETATE]
D = BrineDesign(props=KAC, c_max=0.4, v_max_m3=1e9)
M = 1_000_000.0


def test_property_fits() -> None:
    assert water_activity(0.0, KAC) == pytest.approx(0.9979)
    assert water_activity(0.2, KAC) == pytest.approx(0.9019, abs=1e-4)  # cubic
    assert water_activity(0.4, KAC) == pytest.approx(0.6699, abs=1e-4)
    assert rho_brine(0.2, KAC) == pytest.approx(642.08 * 0.2 + 980.82)
    assert vapor_sat_temp(48.0, 1.0) == pytest.approx(48.0)  # pure water
    assert vapor_sat_temp(48.0, 0.9019) == pytest.approx(45.97, abs=0.01)
    with pytest.raises(ValueError):
        vapor_sat_temp(48.0, 0.0)


def test_runs_when_stack_works_and_takes_all_heat() -> None:
    h = brine_sep_step(BrineState(M, 0.2), 11_000.0, 50.0, t_coolant_c=20.0, d=D)
    water = 11_000.0 * 3600 / 2382
    assert h.q_heat_in_kwth == pytest.approx(11_000.0)
    assert h.water_out_kg == pytest.approx(water)
    assert h.end.m_brine_kg == pytest.approx(M - water)
    assert h.end.c_brine == pytest.approx(M * 0.2 / (M - water))  # salt conserved


def test_stops_when_coolant_too_warm() -> None:
    t_cond = condensing_temp_c(0.2, 50.0, D)  # 45.97 °C
    on = brine_sep_step(BrineState(M, 0.2), 1000.0, 50.0, t_cond - 2.0 - 0.01, D)
    off = brine_sep_step(BrineState(M, 0.2), 1000.0, 50.0, t_cond - 2.0 + 0.01, D)
    assert on.q_heat_in_kwth > 0
    assert off.q_heat_in_kwth == 0 and off.end == BrineState(M, 0.2)


def test_harder_as_it_concentrates() -> None:
    temps = [condensing_temp_c(c, 50.0, D) for c in (0.2, 0.3, 0.4)]
    assert temps[0] > temps[1] > temps[2]


def test_caps_at_high_concentration() -> None:
    m = 1000.0
    h = brine_sep_step(BrineState(m, 0.39), 1e6, 50.0, 10.0, D)
    assert h.end.c_brine == pytest.approx(0.4)
    assert h.end.m_brine_kg == pytest.approx(m * 0.39 / 0.4)
    assert h.q_heat_in_kwth == pytest.approx(h.water_out_kg * 2382 / 3600)
    full = brine_sep_step(h.end, 1e6, 50.0, 10.0, D)
    assert full.q_heat_in_kwth == pytest.approx(0.0, abs=1e-9)


def test_brine_in_out_and_overflow_guard() -> None:
    s = BrineState(M, 0.3)
    h = brine_sep_step(
        s, 0.0, 50.0, 10.0, D, m_brine_in_kg_s=1.0, c_brine_in=0.1, m_brine_out_kg_s=2.0
    )
    salt = M * 0.3 + 3600 * 0.1 - 7200 * 0.3
    assert h.end.m_brine_kg == pytest.approx(M - 3600)
    assert h.end.c_brine == pytest.approx(salt / (M - 3600))
    assert (h.m_brine_in_kg_s, h.m_brine_out_kg_s) == (1.0, 2.0)  # nothing limited


def test_full_tank_accepts_only_what_fits() -> None:
    """D-051: brine in = min(offered, what fits); the step is recalculated with it."""
    s = BrineState(M, 0.3)
    v_max = 1.001 * M / rho_brine(0.3, KAC)  # 0.1 % room
    tight = BrineDesign(props=KAC, c_max=0.4, v_max_m3=v_max)
    g = brine_sep_step(s, 0.0, 50.0, 10.0, tight, m_brine_in_kg_s=10.0, c_brine_in=0.1)
    assert 0 < g.m_brine_in_kg_s < 10.0
    assert g.end.m_brine_kg / rho_brine(g.end.c_brine, KAC) == pytest.approx(v_max, rel=1e-9)
    # the recalculation is the same math with the accepted flow
    again = brine_sep_step(
        s, 0.0, 50.0, 10.0, tight, m_brine_in_kg_s=g.m_brine_in_kg_s, c_brine_in=0.1
    )
    assert again == g
    # taking brine out (or boiling water off) makes room for more in
    w = brine_sep_step(
        s, 0.0, 50.0, 10.0, tight, m_brine_in_kg_s=10.0, c_brine_in=0.1, m_brine_out_kg_s=5.0
    )
    assert w.m_brine_in_kg_s > g.m_brine_in_kg_s


def test_brine_out_limited_to_tank_contents() -> None:
    s = BrineState(3600.0, 0.3)  # 1 kg/s for an hour
    h = brine_sep_step(s, 0.0, 50.0, 10.0, D, m_brine_out_kg_s=5.0)
    assert h.m_brine_out_kg_s == pytest.approx(1.0)
    assert h.end.m_brine_kg == pytest.approx(0.0)


@pytest.mark.parametrize("seed", range(3))
def test_flows_balance_and_tank_never_overfills(seed: int) -> None:
    rng = np.random.default_rng(seed)
    for _ in range(200):
        m0, c0 = float(rng.uniform(1e5, 1e6)), float(rng.uniform(0.15, 0.39))
        d = BrineDesign(props=KAC, c_max=0.4, v_max_m3=m0 / rho_brine(c0, KAC) * 1.01)
        s = BrineState(m0, c0)
        q, c_in = float(rng.uniform(0, 5e4)), float(rng.uniform(0.05, 0.35))
        b_in, b_out = float(rng.uniform(0, 200)), float(rng.uniform(0, 200))
        h = brine_sep_step(s, q, 50.0, 10.0, d, b_in, c_in, b_out)
        dm = (h.m_brine_in_kg_s - h.m_brine_out_kg_s) * 3600 - h.water_out_kg
        assert h.end.m_brine_kg == pytest.approx(m0 + dm)
        salt = m0 * c0 + (h.m_brine_in_kg_s * c_in - h.m_brine_out_kg_s * c0) * 3600
        assert h.end.m_brine_kg * h.end.c_brine == pytest.approx(salt)
        assert h.end.m_brine_kg / rho_brine(h.end.c_brine, KAC) <= d.v_max_m3 * (1 + 1e-9)
        assert h.m_brine_in_kg_s <= b_in and h.m_brine_out_kg_s <= b_out


def test_sizing_salt_balance_and_footprint() -> None:
    p = BrineSeparationParams(enabled=True).resolved(ModuleContext(it_peak_mw=10))
    water = 10_000 * 1.1 * 24 * 3600 / 2382  # IT + 10 % parasitics, 24 h
    assert p.mass_kg == pytest.approx(water * 0.4 / (0.4 - 0.2))
    assert p.tank_volume_m3 == pytest.approx(p.mass_kg / rho_brine(0.2, KAC))
    d = math.sqrt(4 * p.tank_volume_m3 / (math.pi * 12))
    side = d + 2 * 20 * M_PER_FT
    assert p.default_dims_m() == pytest.approx((side, side))
    assert p.block_area_m2 == pytest.approx(side**2)
    assert "brine_mass_kg" not in p.model_dump()


def test_params_validate_range() -> None:
    with pytest.raises(ValueError):
        BrineSeparationParams(conc_low_wt_pct=30, conc_high_wt_pct=30)
    with pytest.raises(ValueError):
        BrineSeparationParams(conc_low_wt_pct=0)


def test_adapter_concentrates_low_to_high_in_design_hours() -> None:
    p = BrineSeparationParams(enabled=True, concentrate_hours=6).resolved(
        ModuleContext(it_peak_mw=1)
    )
    df = pd.DataFrame({col.IT_LOAD_KW: [1000.0] * 10, col.T_COOLANT_C: [15.0] * 10})
    it = ColumnStream(col.IT_LOAD_KW, st.IT_LOAD_KW)
    node = BrineSeparation(p, t_heat_in_c=50.0, it_parasitic_frac=0.1)
    take_all = in_default(
        Action(target="brine_separation", setting="heat_in", value=100, to=DATA_CENTER)
    )
    out = HourlySolver((it, node), take_all).run(df)
    q = out[col.BRINE_HEAT_KWTH].to_numpy()
    np.testing.assert_allclose(q[:6], 1100.0)  # full DC heat for the design hours
    assert q[6:].sum() == pytest.approx(0.0, abs=1e-6)
    assert out[col.BRINE_CONC_WT_PCT].iloc[-1] == pytest.approx(40.0)
    assert out[col.BRINE_WATER_OUT_KG_H].sum() == pytest.approx(1100 * 6 * 3600 / 2382)
    assert (out[col.BRINE_IN_KG_S] == 0).all() and (out[col.BRINE_OUT_KG_S] == 0).all()


def test_adapter_off_or_unlinked_takes_nothing() -> None:
    """D-054: no THEN naming it (Default) or no heat link → no heat, no brine."""
    p = BrineSeparationParams(enabled=True).resolved(ModuleContext(it_peak_mw=1))
    df = pd.DataFrame({col.IT_LOAD_KW: [1000.0] * 3, col.T_COOLANT_C: [15.0] * 3})
    it = ColumnStream(col.IT_LOAD_KW, st.IT_LOAD_KW)
    node = BrineSeparation(p, t_heat_in_c=50.0, it_parasitic_frac=0.1)
    for ctl in (
        in_default(),
        in_default(Action(target="brine_separation", setting="water_out", to="drain")),
    ):
        out = HourlySolver((it, node), ctl).run(df)
        assert (out[col.BRINE_HEAT_KWTH] == 0).all()
        assert (out[col.BRINE_CONC_WT_PCT] == 20.0).all()
