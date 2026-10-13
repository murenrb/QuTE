"""Hourly data center model (docs/models/datacenter-hourly.md).

The weather-only parts (rejection ambient, coolant temperature, chiller COP)
are vectorized over the 8760-hour frame. The rest is the `DataCenter` solver
node (D-054): each hour it runs the IT load the state asks for, hands its heat
to the modules the state links to it (in THEN order), and cools what is left,
plus the heat modules reject into the supply coolant: free cooling when
possible, mechanical when needed (owner), with the ice mixer taking part of
the mechanical load when the state says so.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from core.config.defaults import CONTROL, KELVIN_OFFSET, CoolingType, ModelAssumptions
from core.domain.control import (
    DATA_CENTER,
    Commodity,
    ControlSetting,
    ControlSpec,
    ControlVariable,
    Plan,
    SettingKind,
)
from core.domain.datacenter_type import DataCenterType
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.solver import Flows, NodeStep, StreamSpec

FloatArray = npt.NDArray[np.float64]

# State machine IFs / THENs (docs/control.md, owner's write-up).
IT_LOAD_PCT = "it_load_pct"
_IT = CONTROL.it_load_pct
CONTROL_SPEC = ControlSpec(
    DATA_CENTER,
    "Data center",
    ifs=(ControlVariable("it_load_pct", "Planned IT load", "% of full load"),),
    thens=(
        ControlSetting(
            IT_LOAD_PCT,
            "IT load is set to {value} % of planned load",
            SettingKind.NUMBER,
            _IT.default,
            _IT.min,
            _IT.max,
            _IT.step,
            "%",
        ),
    ),
)
# Modules that can take the data center's heat (a link THEN at their end).
HEAT_TAKERS = ("brine_separation", "power_generation", "hot_water_storage", "greenhouse")
# Modules that can reject heat into the supply coolant.
COOLANT_USERS = ("brine_separation", "power_generation")
ICE_MIXER = "ice_mixer"


def mechanical_cop(
    t_amb_c: FloatArray,
    t_supply_c: float,
    cooling: CoolingType,
    a: ModelAssumptions,
) -> FloatArray:
    """% of Carnot COP between evaporator (supply - pinch) and condenser (ambient + approach).

    Where the condenser is not warmer than the evaporator, Carnot COP is
    unbounded, so the result is cop_max.
    """
    t_cold_k = t_supply_c - a.t_pinch_c + KELVIN_OFFSET
    t_hot_k = t_amb_c + a.t_cond_approach_c(cooling) + KELVIN_OFFSET
    lift_k = t_hot_k - t_cold_k
    safe_lift = np.where(lift_k > 0, lift_k, 1.0)
    cop = np.where(lift_k > 0, a.carnot_fraction * t_cold_k / safe_lift, a.cop_max)
    return np.clip(cop, a.cop_min, a.cop_max)


def free_cooling_available(
    t_amb_c: FloatArray, t_supply_c: float, t_approach_c: float
) -> npt.NDArray[np.bool_]:
    """Free cooling only if ambient + approach < supply (no temperature cross)."""
    return t_amb_c + t_approach_c < t_supply_c


def coolant_temperature(
    t_amb_c: FloatArray,
    t_supply_c: float,
    t_supply_min_c: float,
    t_approach_c: float,
) -> FloatArray:
    """Cold supply water to IT each hour (D-047).

    Free cooling: ambient + approach, clamped to [min, setpoint]. Otherwise the
    chillers hold the setpoint.
    """
    free = free_cooling_available(t_amb_c, t_supply_c, t_approach_c)
    floating = np.clip(t_amb_c + t_approach_c, t_supply_min_c, t_supply_c)
    return np.where(free, floating, t_supply_c)


@dataclass(frozen=True)
class CoolantTemperature:
    """Heat-rejection ambient (dry or wet bulb), the floating coolant (supply)
    temperature and the chiller COP. Needs only weather, so every module in the
    solver can read them."""

    dc_type: DataCenterType
    assumptions: ModelAssumptions
    name: str = "coolant_temperature"
    requires: tuple[str, ...] = (col.TDB_C, col.TWB_C)
    provides: tuple[str, ...] = (col.T_AMBIENT_REJ_C, col.T_COOLANT_C, col.COP_MECH)

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        t, a = self.dc_type, self.assumptions
        dry = t.cooling_type is CoolingType.DRY
        t_amb = df[col.TDB_C if dry else col.TWB_C].to_numpy(dtype=float)
        coolant = coolant_temperature(t_amb, t.t_supply_c, t.t_supply_min_c, a.t_approach_c)
        cop = mechanical_cop(t_amb, t.t_supply_c, t.cooling_type, a)
        return df.assign(
            **{col.T_AMBIENT_REJ_C: t_amb, col.T_COOLANT_C: coolant, col.COP_MECH: cop}
        )


def cooling_electric_kw(
    chiller_kwth: FloatArray | float,
    free_kwth: FloatArray | float,
    cop_mech: FloatArray | float,
    cop_free: float,
) -> FloatArray:
    """P = chiller load / COP_mech + free cooling / COP_free  [kW_e].

    free_kwth: all heat rejected by the dry coolers / towers without a chiller.
    """
    chiller, cop = np.asarray(chiller_kwth, dtype=float), np.asarray(cop_mech, dtype=float)
    if np.any((chiller > 0) & (cop <= 0)):
        raise ValueError("Mechanical cooling required but COP is zero; check cop_max")
    chiller_elec = np.divide(chiller, cop, out=np.zeros_like(chiller), where=cop > 0)
    out: FloatArray = chiller_elec + np.asarray(free_kwth, dtype=float) / cop_free
    return out


@dataclass(frozen=True)
class DataCenterHour:
    """One hour of the data center node (kW, kW_th)."""

    it_kw: float
    parasitic_kw: float
    heat_kwth: float  # IT + parasitics: all of it must go somewhere
    sent_kwth: dict[str, float | None]  # heat handed to each linked module (None = unasked)
    left_kwth: float  # heat the data center cools itself
    coolant_in_kwth: float  # heat modules rejected into the supply coolant
    free_kwth: float  # rejected by the dry coolers / towers without a chiller
    mech_kwth: float  # needing mechanical cooling (before the ice mixer)
    ice_req_kwth: float | None  # asked of the ice mixer (None = no link)
    ice_kwth: float  # cooling the ice mixer gave the data center
    chiller_kwth: float
    cooling_elec_kw: float


def data_center_hour(
    it_plan_kw: float,
    free: bool,
    cop_mech: float,
    plan: Plan,
    flows: Flows,
    a: ModelAssumptions,
    cop_free: float,
) -> DataCenterHour:
    """One hour.

    IT = planned × the state's IT load %; heat = IT × (1 + parasitic frac).
    Heat goes to the modules the state links to the data center, in THEN order:
    each is offered min(what it wants, what the modules before it left, its %
    of the heat if the THEN gives one) and reports what it used. What is left,
    plus the heat modules reject into the supply coolant, is free-cooled when
    free cooling is possible, otherwise it needs mechanical cooling: the ice
    mixer takes the data center's share of that when the state links it, the
    chillers the rest.
    """
    it_kw = it_plan_kw * plan.value(DATA_CENTER, IT_LOAD_PCT, _IT.default) / 100
    parasitic = a.it_parasitic_frac * it_kw
    heat = it_kw + parasitic
    left = heat
    sent: dict[str, float | None] = {k: None for k in HEAT_TAKERS}
    for link in plan.sent_by(DATA_CENTER, Commodity.HEAT):
        req = flows.get(st.heat_req(DATA_CENTER, link.receiver))
        if req is None or link.receiver not in sent:
            continue  # not asked (yet)
        cap = left if link.amount is None else min(left, link.amount / 100 * heat)
        give = min(max(req, 0.0), max(cap, 0.0))
        sent[link.receiver] = give
        used = flows.get(st.heat_used(DATA_CENTER, link.receiver))
        left -= give if used is None else min(used, give)  # not reported yet: all of it
    coolant_in = sum(flows.get(st.coolant_load(k)) or 0.0 for k in COOLANT_USERS)
    free_kwth = left + coolant_in if free else 0.0
    mech = 0.0 if free else left + coolant_in
    ice_req = None
    ice = 0.0
    if plan.link(Commodity.COOLING, ICE_MIXER, DATA_CENTER):
        ice_req = 0.0 if free else left  # only the data center's own mechanical load
        ice = min(flows.get(st.cool_sent(DATA_CENTER)) or 0.0, ice_req)
    chiller = mech - ice
    elec = float(cooling_electric_kw(chiller, free_kwth, cop_mech, cop_free))
    return DataCenterHour(
        it_kw, parasitic, heat, sent, left, coolant_in, free_kwth, mech, ice_req, ice, chiller, elec
    )


@dataclass(frozen=True)
class DataCenterNode:
    """Solver node (docs/solver.md): IT load, heat hand-out and the cooling plant."""

    dc_type: DataCenterType
    assumptions: ModelAssumptions
    name: str = "data_center"
    control_key: str | None = DATA_CENTER
    requires: tuple[str, ...] = (col.IT_LOAD_PLAN_KW, col.T_AMBIENT_REJ_C, col.COP_MECH)
    provides: tuple[str, ...] = (
        col.IT_LOAD_KW,
        col.IT_PARASITIC_KW,
        col.COOLING_TOTAL_KWTH,
        col.HEAT_OFFTAKE_KWTH,
        col.COOLING_MECH_KWTH,
        col.COOLING_FREE_KWTH,
        col.COOLING_CHILLER_KWTH,
        col.COOLING_ELEC_KW,
    )
    reads: tuple[str, ...] = (
        *(st.heat_req(DATA_CENTER, k) for k in HEAT_TAKERS),
        *(st.heat_used(DATA_CENTER, k) for k in HEAT_TAKERS),
        *(st.coolant_load(k) for k in COOLANT_USERS),
        st.cool_sent(DATA_CENTER),
    )
    writes: tuple[StreamSpec, ...] = (
        StreamSpec(st.IT_LOAD_KW),
        *(
            StreamSpec(st.heat_sent(DATA_CENTER, k), answers=st.heat_req(DATA_CENTER, k))
            for k in HEAT_TAKERS
        ),
        StreamSpec(st.cool_req(DATA_CENTER)),
        StreamSpec(st.cool_used(DATA_CENTER)),
        StreamSpec(st.elec("it_load")),
        StreamSpec(st.elec("it_parasitic")),
        StreamSpec(st.elec("cooling")),
    )

    def prepare(self, df: pd.DataFrame) -> tuple[FloatArray, npt.NDArray[np.bool_], FloatArray]:
        t_amb = df[col.T_AMBIENT_REJ_C].to_numpy(dtype=float)
        free = free_cooling_available(t_amb, self.dc_type.t_supply_c, self.assumptions.t_approach_c)
        return (
            df[col.IT_LOAD_PLAN_KW].to_numpy(dtype=float),
            free,
            df[col.COP_MECH].to_numpy(dtype=float),
        )

    def initial_state(self) -> Any:
        return None

    def step(
        self,
        data: tuple[FloatArray, npt.NDArray[np.bool_], FloatArray],
        state: Any,
        h: int,
        flows: Flows,
        plan: Plan,
    ) -> NodeStep:
        plan_kw, free, cop = data
        a = self.assumptions
        d = data_center_hour(
            float(plan_kw[h]),
            bool(free[h]),
            float(cop[h]),
            plan,
            flows,
            a,
            a.cop_free(self.dc_type.cooling_type),
        )
        return NodeStep(
            None,
            {
                st.IT_LOAD_KW: d.it_kw,
                **{st.heat_sent(DATA_CENTER, k): v for k, v in d.sent_kwth.items()},
                st.cool_req(DATA_CENTER): d.ice_req_kwth,
                st.cool_used(DATA_CENTER): None if d.ice_req_kwth is None else d.ice_kwth,
                st.elec("it_load"): d.it_kw,
                st.elec("it_parasitic"): d.parasitic_kw,
                st.elec("cooling"): d.cooling_elec_kw,
            },
            {
                col.IT_LOAD_KW: d.it_kw,
                col.IT_PARASITIC_KW: d.parasitic_kw,
                col.COOLING_TOTAL_KWTH: d.heat_kwth,
                col.HEAT_OFFTAKE_KWTH: d.heat_kwth - d.left_kwth,
                col.COOLING_MECH_KWTH: d.mech_kwth,
                col.COOLING_FREE_KWTH: d.free_kwth,
                col.COOLING_CHILLER_KWTH: d.chiller_kwth,
                col.COOLING_ELEC_KW: d.cooling_elec_kw,
            },
        )
