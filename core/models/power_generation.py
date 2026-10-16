"""Power generation module: transcritical CO2 cycle on data center waste heat
(docs/models/power-generation.md, D-045).

Layer 1 is the cycle physics (`power_generation` on arrays, `cycle_hour` for
one hour with several heat sources); layer 2 (`PowerGeneration`) is its solver
node. What it runs on is set by the state (D-054): heat from the data center's
return water, hot water storage or brine separation's condenser (in THEN
order), and a cold side of the supply coolant or the ice mixer. Heat in =
power out + heat rejected; the rejected heat goes to its cold side.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from core.config.defaults import CONTROL, KELVIN_OFFSET
from core.domain.control import (
    COOLANT,
    DATA_CENTER,
    Commodity,
    ControlSetting,
    ControlSpec,
    Plan,
    SettingKind,
    off_setting,
)
from core.domain.modules import PowerGenerationParams
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.solver import Flows, NodeStep, StreamSpec

KEY = "power_generation"
HWS, BRINE_SEP, ICE_MIXER = "hot_water_storage", "brine_separation", "ice_mixer"
HEAT_SOURCES = (DATA_CENTER, HWS, BRINE_SEP)
RUN_PCT = "run_pct"
_RUN = CONTROL.power_gen_run_pct
# State machine IFs / THENs (docs/control.md, owner's write-up).
CONTROL_SPEC = ControlSpec(
    KEY,
    "Waste heat to power",
    ifs=(),
    thens=(
        ControlSetting(
            RUN_PCT,
            "Runs at {value} % of design",
            SettingKind.NUMBER,
            _RUN.default,
            _RUN.min,
            _RUN.max,
            _RUN.step,
            "%",
        ),
        ControlSetting(
            "heat_in",
            "Accepts heat from {to}",
            SettingKind.LINK,
            commodity=Commodity.HEAT,
            receives=True,
            ends=HEAT_SOURCES,
        ),
        ControlSetting(
            "cooling_in",
            "Accepts cooling from {to}",
            SettingKind.LINK,
            commodity=Commodity.COOLING,
            receives=True,
            ends=(COOLANT, ICE_MIXER),
        ),
        off_setting("Waste heat to power"),
    ),
)

FloatArray = npt.NDArray[np.float64]


def carnot_efficiency(t_hot_c: float, t_cold_c: FloatArray) -> FloatArray:
    """1 − T_cold/T_hot (kelvin); 0 where the cold side is not colder."""
    eff = 1.0 - (np.asarray(t_cold_c, dtype=float) + KELVIN_OFFSET) / (t_hot_c + KELVIN_OFFSET)
    return np.clip(eff, 0.0, None)


@dataclass(frozen=True)
class PowerGenHours:
    eff: FloatArray  # cycle efficiency, power / heat in
    heat_in_kwth: FloatArray  # heat taken from the data center
    power_kwe: FloatArray  # generated (positive here)
    reject_kwth: FloatArray  # heat rejected to ambient = heat in − power


def power_generation(
    t_cold_c: FloatArray,
    heat_available_kwth: FloatArray,
    t_hot_c: float,
    p: PowerGenerationParams,
) -> PowerGenHours:
    """Each hour:

    η        = %Carnot × (1 − T_cold/T_hot)
    η_design = η at the max cold-side temperature (where the generator is rated)
    Q_design = rated / η_design      heat input the plant is sized for
    Q_max    = min(rated / η, Q_design)
               colder than design: power-limited (rated, at less heat);
               warmer than design: heat-limited (Q_design, below rated)
    Q_in     = min(Q_max, heat available);  P = η × Q_in;  rejected = Q_in − P

    Call with resolved params (rated_kw set).
    """
    frac = p.carnot_pct / 100.0
    t_cold = np.asarray(t_cold_c, dtype=float)
    avail = np.clip(np.asarray(heat_available_kwth, dtype=float), 0.0, None)
    eff = frac * carnot_efficiency(t_hot_c, t_cold)
    eff_design = frac * float(carnot_efficiency(t_hot_c, np.array([p.t_cold_max_c]))[0])
    if eff_design <= 0:  # design cold side not below the hot water: no cycle
        zero = np.zeros_like(t_cold)
        return PowerGenHours(zero, zero, zero, zero)
    rated = p.rated_kwe
    q_design = rated / eff_design
    q_power_limit = np.divide(rated, eff, out=np.zeros_like(eff), where=eff > 0)
    q_max = np.where(eff > 0, np.minimum(q_power_limit, q_design), 0.0)
    heat_in = np.minimum(q_max, avail)
    power = eff * heat_in
    return PowerGenHours(eff, heat_in, power, heat_in - power)


def design_heat_kwth(p: PowerGenerationParams, t_hot_c: float) -> float:
    """Q_design = rated / η at the design (max) cold side, with the data center's
    return water as the hot side: the heat input the plant is sized for
    (0 if the design cold side is not below the hot water)."""
    eff = p.carnot_pct / 100 * float(carnot_efficiency(t_hot_c, np.array([p.t_cold_max_c]))[0])
    return p.rated_kwe / eff if eff > 0 else 0.0


@dataclass(frozen=True)
class CycleSource:
    """One heat source for one hour."""

    key: str
    t_hot_c: float
    sent_kwth: float | None  # what the source can give (None = not answered yet)


@dataclass(frozen=True)
class CycleHour:
    want_kwth: dict[str, float]  # asked of each source (never limited by the cold side)
    used_kwth: dict[str, float]  # taken from each source
    reject_want_kwth: float  # cold side asked for (ice mixer)
    heat_in_kwth: float
    power_kwe: float
    reject_kwth: float


def cycle_hour(
    sources: list[CycleSource],
    t_cold_c: float,
    run_frac: float,
    p: PowerGenerationParams,
    q_design_kwth: float,
    reject_max_kwth: float | None = None,
) -> CycleHour:
    """One hour of the cycle on several heat sources, taken in order.

    Each source at its own hot temperature: η = %Carnot × (1 − T_cold/T_hot).
    Caps for the hour: heat in ≤ run × Q_design, power ≤ run × rated, and
    (cold side = ice mixer) heat rejected ≤ what the mixer gives.
    Want from each source = what the heat and power caps leave after the
    sources before it (as far as they can give); the cold side's limit applies
    only to what is used, so the wants can rise again when it frees up.
    """
    frac = p.carnot_pct / 100
    heat_left, power_left = run_frac * q_design_kwth, run_frac * p.rated_kwe
    want, got = {}, {}
    reject_want = 0.0
    effs = {}
    for src in sources:
        eff = frac * float(carnot_efficiency(src.t_hot_c, np.array([t_cold_c]))[0])
        effs[src.key] = eff
        if eff <= 0:
            want[src.key], got[src.key] = 0.0, 0.0
            continue
        w = max(min(heat_left, power_left / eff), 0.0)
        g = w if src.sent_kwth is None else min(w, src.sent_kwth)  # unanswered: assume given
        want[src.key], got[src.key] = w, g
        heat_left -= g
        power_left -= eff * g
        reject_want += (1 - eff) * g
    reject_left = np.inf if reject_max_kwth is None else reject_max_kwth
    used, heat_in, power = {}, 0.0, 0.0
    for src in sources:
        eff, g = effs[src.key], got[src.key]
        u = g if eff >= 1 else min(g, max(reject_left, 0.0) / (1 - eff))
        used[src.key] = u
        reject_left -= (1 - eff) * u
        heat_in += u
        power += eff * u
    return CycleHour(want, used, reject_want, heat_in, power, heat_in - power)


@dataclass(frozen=True)
class PowerGeneration:
    """Solver node (docs/solver.md). Runs when the state names it, on the heat
    sources and cold side the state links to it.

    t_return_c: data center hot (return) water — a heat source, and the hot side
    the plant is designed on. Cold side: the floating coolant `t_coolant_c`
    (D-047), its heat rejected into the supply coolant (free cooling when
    possible, else the chillers), or the ice mixer's temperature, its heat
    rejected to the mixer.
    """

    params: PowerGenerationParams  # resolved
    t_return_c: float
    name: str = KEY
    control_key: str | None = KEY
    requires: tuple[str, ...] = (col.T_COOLANT_C,)
    provides: tuple[str, ...] = (
        col.POWER_GEN_EFF,
        col.POWER_GEN_HEAT_IN_KWTH,
        col.POWER_GEN_REJECT_KWTH,
        col.POWER_GEN_POWER_KWTH,
        col.POWER_GEN_KW,
    )
    reads: tuple[str, ...] = (
        *(st.heat_sent(k, KEY) for k in HEAT_SOURCES),
        st.HWS_T_HOT_C,
        st.CONDENSER_T_C,
        st.ICE_MIX_T_C,
        st.cool_sent(KEY),
    )
    writes: tuple[StreamSpec, ...] = (
        *(StreamSpec(st.heat_req(k, KEY)) for k in HEAT_SOURCES),
        *(StreamSpec(st.heat_used(k, KEY)) for k in HEAT_SOURCES),
        StreamSpec(st.cool_req(KEY)),
        StreamSpec(st.cool_used(KEY)),
        StreamSpec(st.coolant_load(KEY)),
        StreamSpec(st.elec("power_generation")),
    )

    def prepare(self, df: pd.DataFrame) -> tuple[FloatArray, float]:
        return (
            df[col.T_COOLANT_C].to_numpy(dtype=float),
            design_heat_kwth(self.params, self.t_return_c),
        )

    def initial_state(self) -> Any:
        return None

    def _t_hot(self, key: str, flows: Flows) -> float | None:
        temps: Mapping[str, float | None] = {
            DATA_CENTER: self.t_return_c,
            HWS: flows[st.HWS_T_HOT_C],
            BRINE_SEP: flows[st.CONDENSER_T_C],
        }
        return temps[key]

    def step(
        self, data: tuple[FloatArray, float], state: Any, h: int, flows: Flows, plan: Plan
    ) -> NodeStep:
        t_coolant, q_design = data
        cold = plan.to(KEY, Commodity.COOLING) if plan.runs(KEY) else ()
        cold_side = cold[0].sender if cold else None  # the first listed cold side
        t_cold = flows[st.ICE_MIX_T_C] if cold_side == ICE_MIXER else float(t_coolant[h])
        sources = []
        if cold_side is not None and t_cold is not None:
            for link in plan.to(KEY, Commodity.HEAT):
                t_hot = self._t_hot(link.sender, flows)
                if t_hot is not None:
                    sent = flows[st.heat_sent(link.sender, KEY)]
                    sources.append(CycleSource(link.sender, t_hot, sent))
        by_ice = cold_side == ICE_MIXER
        ice = flows[st.cool_sent(KEY)] if by_ice else None
        run = plan.value(KEY, RUN_PCT, _RUN.default) / 100
        c = cycle_hour(sources, t_cold or 0.0, run, self.params, q_design, ice)
        eff = c.power_kwe / c.heat_in_kwth if c.heat_in_kwth > 0 else 0.0
        named = {s.key for s in sources}
        return NodeStep(
            None,
            {
                **{
                    st.heat_req(k, KEY): c.want_kwth[k] if k in named else None
                    for k in HEAT_SOURCES
                },
                **{
                    st.heat_used(k, KEY): c.used_kwth[k] if k in named else None
                    for k in HEAT_SOURCES
                },
                st.cool_req(KEY): c.reject_want_kwth if by_ice else None,
                st.cool_used(KEY): c.reject_kwth if by_ice else None,
                st.coolant_load(KEY): 0.0 if by_ice else c.reject_kwth,
                st.elec("power_generation"): -c.power_kwe,
            },
            {
                col.POWER_GEN_EFF: eff,
                col.POWER_GEN_HEAT_IN_KWTH: c.heat_in_kwth,
                col.POWER_GEN_REJECT_KWTH: c.reject_kwth,
                col.POWER_GEN_POWER_KWTH: c.power_kwe,
                col.POWER_GEN_KW: -c.power_kwe,  # generation is negative
            },
        )
