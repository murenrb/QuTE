"""Power generation physics (docs/models/power-generation.md, D-045)."""

import numpy as np
import pandas as pd
import pytest

from core.config.defaults import KELVIN_OFFSET
from core.control.catalog import controller
from core.control.engine import Controller
from core.domain.control import COOLANT, DATA_CENTER, Action, ControlSettings, ControlState
from core.domain.modules import ModuleContext, PowerGenerationParams
from core.models.power_generation import (
    CycleSource,
    PowerGeneration,
    carnot_efficiency,
    cycle_hour,
    design_heat_kwth,
    power_generation,
)
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.solver import ColumnStream, HourlySolver

T_HOT = 50.0


def _params(**kw: float) -> PowerGenerationParams:
    return PowerGenerationParams(enabled=True, rated_kw=200.0, **kw)


def _eff(t_cold: float, pct: float = 30.0) -> float:
    return pct / 100 * (1 - (t_cold + KELVIN_OFFSET) / (T_HOT + KELVIN_OFFSET))


def test_carnot_efficiency_kelvin_and_clipped() -> None:
    e = carnot_efficiency(T_HOT, np.array([10.0, 50.0, 60.0]))
    assert e[0] == pytest.approx(1 - 283.15 / 323.15)
    assert e[1] == 0.0 and e[2] == 0.0


def test_rated_at_design_cold_side() -> None:
    p = _params()
    q_design = 200 / _eff(10.0)
    h = power_generation(np.array([10.0]), np.array([1e9]), T_HOT, p)
    assert h.power_kwe[0] == pytest.approx(200)
    assert h.heat_in_kwth[0] == pytest.approx(q_design)
    assert h.eff[0] == pytest.approx(_eff(10.0))


def test_colder_is_power_limited_less_heat() -> None:
    """More efficient than design: still rated power, from less heat."""
    h = power_generation(np.array([0.0]), np.array([1e9]), T_HOT, _params())
    assert h.power_kwe[0] == pytest.approx(200)
    assert h.heat_in_kwth[0] == pytest.approx(200 / _eff(0.0))
    assert h.heat_in_kwth[0] < 200 / _eff(10.0)


def test_warmer_is_heat_limited_below_rated() -> None:
    """Above the design cold side: heat input capped at design, power drops."""
    q_design = 200 / _eff(10.0)
    h = power_generation(np.array([25.0]), np.array([1e9]), T_HOT, _params())
    assert h.heat_in_kwth[0] == pytest.approx(q_design)
    assert h.power_kwe[0] == pytest.approx(_eff(25.0) * q_design)
    assert h.power_kwe[0] < 200


def test_limited_by_available_heat() -> None:
    h = power_generation(np.array([5.0]), np.array([100.0]), T_HOT, _params())
    assert h.heat_in_kwth[0] == pytest.approx(100)
    assert h.power_kwe[0] == pytest.approx(_eff(5.0) * 100)


def test_energy_balance_and_no_heat() -> None:
    t = np.linspace(-20, 60, 81)
    avail = np.where(t < 30, 5000.0, 0.0)
    h = power_generation(t, avail, T_HOT, _params())
    np.testing.assert_allclose(h.heat_in_kwth, h.power_kwe + h.reject_kwth)
    assert (h.power_kwe <= 200 + 1e-9).all() and (h.reject_kwth >= 0).all()
    assert (h.heat_in_kwth[avail == 0] == 0).all()
    assert (h.power_kwe[t >= T_HOT] == 0).all()


def test_design_cold_side_not_below_hot_water_gives_nothing() -> None:
    h = power_generation(np.array([0.0]), np.array([1e9]), T_HOT, _params(t_cold_max_c=60.0))
    assert h.power_kwe[0] == 0 and h.heat_in_kwth[0] == 0


def test_rating_follows_it_load_and_footprint() -> None:
    p = PowerGenerationParams(enabled=True).resolved(ModuleContext(it_peak_mw=10))
    assert p.rated_kw == pytest.approx(200)  # 2 % of 10 MW
    assert p.footprint_sqft == pytest.approx(400)  # 0.2 MWe × 2000 sqft/MWe
    big = PowerGenerationParams(rated_pct_of_it=150).resolved(ModuleContext(it_peak_mw=10))
    assert big.rated_kw == pytest.approx(15_000)  # up to 150 % of the IT load (D-063)
    with pytest.raises(ValueError):
        _ = PowerGenerationParams().rated_kwe


def in_default(*actions: Action) -> Controller:
    """A state machine whose Default state has these THENs."""
    return controller(
        ControlSettings(default=ControlState(id="default", name="D", actions=actions))
    )


def test_cycle_hour_matches_the_single_source_physics() -> None:
    p = _params()
    q_design = design_heat_kwth(p, T_HOT)
    for t_cold in (0.0, 10.0, 25.0):
        one = power_generation(np.array([t_cold]), np.array([1e9]), T_HOT, p)
        c = cycle_hour([CycleSource("dc", T_HOT, None)], t_cold, 1.0, p, q_design)
        assert c.power_kwe == pytest.approx(one.power_kwe[0])
        assert c.heat_in_kwth == pytest.approx(one.heat_in_kwth[0])


def test_cycle_hour_sources_in_order_run_pct_and_cold_side_limit() -> None:
    p = _params()
    q_design = design_heat_kwth(p, T_HOT)
    first, second = CycleSource("hws", 46.0, 300.0), CycleSource("dc", T_HOT, None)
    c = cycle_hour([first, second], 10.0, 0.5, p, q_design)
    assert c.used_kwth["hws"] == pytest.approx(300.0)  # first in line, all it can give
    assert c.power_kwe <= 100 + 1e-9  # 50 % of rated
    assert c.heat_in_kwth <= 0.5 * q_design + 1e-9
    # a cold side that can only take 100 kW of rejected heat
    lim = cycle_hour([first, second], 10.0, 0.5, p, q_design, reject_max_kwth=100.0)
    assert lim.reject_kwth == pytest.approx(100.0)
    assert lim.want_kwth == c.want_kwth  # the wants don't shrink with the cold side
    assert lim.reject_want_kwth == pytest.approx(c.reject_kwth)


def test_adapter_runs_on_its_links() -> None:
    """D-054: heat from the data center, the supply coolant as its cold side; no
    free-cooling rule behind the user's back — it runs whenever η > 0."""
    df = pd.DataFrame({"offered": [11000.0, 11000.0], col.T_COOLANT_C: [10.0, 40.0]})
    feed = ColumnStream("offered", st.heat_sent(DATA_CENTER, "power_generation"))
    run = in_default(
        Action(target="power_generation", setting="heat_in", to=DATA_CENTER),
        Action(target="power_generation", setting="cooling_in", to=COOLANT),
    )
    out = HourlySolver((feed, PowerGeneration(_params(), t_return_c=T_HOT)), run).run(df)
    assert out[col.POWER_GEN_KW].iloc[0] == pytest.approx(-200)  # coolant 10 °C = design
    q_design = 200 / _eff(10.0)  # warmer: heat-limited at the design heat
    assert out[col.POWER_GEN_KW].iloc[1] == pytest.approx(-_eff(40.0) * q_design)
    np.testing.assert_allclose(
        out[col.POWER_GEN_HEAT_IN_KWTH],
        out[col.POWER_GEN_POWER_KWTH] + out[col.POWER_GEN_REJECT_KWTH],
    )
    # no cold side: nothing runs
    heat_only = in_default(Action(target="power_generation", setting="heat_in", to=DATA_CENTER))
    idle = HourlySolver((feed, PowerGeneration(_params(), t_return_c=T_HOT)), heat_only).run(df)
    assert (idle[col.POWER_GEN_KW] == 0).all()
