"""Hot water storage module: two tank or perfect thermocline
(docs/models/hot-water-storage.md, D-046).

Layer 1 is the one-hour physics (`two_tank_step`), the owner's math with the
fixes listed in the doc; layer 2 (`HotWaterStorage`) is its solver node: the
solver threads tank masses and temperatures hour to hour (docs/solver.md).

Sign convention: Q_heat_in > 0 charges (the facility puts heat in: cold-tank
water is heated by the warm return water and moves to the hot tank);
Q_heat_in < 0 discharges (hot-tank water is cooled against the supply water and
moves to the cold tank). A thermocline is modelled as two perfectly separated
zones in one tank, so the physics is the same; only the footprint differs.

What it does each hour is set by the state (D-054): it charges from the data
center's return water when linked to it (in THEN order with the other heat
users) and discharges to power generation and / or the greenhouse when linked
to them (in THEN order), both in the same hour if the state says so (charge
first). Each receiver cools the hot water to its own temperature (D-064):
power generation against the supply water, the greenhouse coil to its setpoint
+ the coil approach; the cooled water goes back to the cold tank, whose
temperature floats with what comes back.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.config.defaults import SECONDS_PER_HOUR, WATER_CP_KJ_KGK
from core.domain.control import (
    DATA_CENTER,
    Commodity,
    ControlSetting,
    ControlSpec,
    ControlVariable,
    Plan,
    SettingKind,
    off_setting,
)
from core.domain.modules import HotWaterStorageParams
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.solver import Flows, NodeStep, StreamSpec

HOURLY_DT_H = 1.0  # the frame is hourly

KEY = "hot_water_storage"
POWER_GEN = "power_generation"
GREENHOUSE = "greenhouse"
RECEIVERS = (POWER_GEN, GREENHOUSE)  # take its hot water, in THEN order (D-064)
# State machine IFs / THENs (docs/control.md, owner's write-up). Levels are % of
# the total water mass (with two tanks, cold = 100 − hot).
CONTROL_SPEC = ControlSpec(
    KEY,
    "Hot water storage",
    ifs=(
        ControlVariable("hot_level_pct", "Hot water tank level", "%"),
        ControlVariable("cold_level_pct", "Cold water tank level", "%"),
    ),
    thens=(
        ControlSetting(
            "heat_out",
            "Sends hot water to {to}",
            SettingKind.LINK,
            commodity=Commodity.HEAT,
            ends=RECEIVERS,
        ),
        ControlSetting(
            "heat_in",
            "Receives hot water from {to}",
            SettingKind.LINK,
            commodity=Commodity.HEAT,
            receives=True,
            ends=(DATA_CENTER,),
        ),
        off_setting("Hot water storage"),
    ),
)


@dataclass(frozen=True)
class TankState:
    """Both tanks (or both thermocline zones) at one instant."""

    t_cold_c: float
    t_hot_c: float
    m_cold_kg: float
    m_hot_kg: float


@dataclass(frozen=True)
class TwoTankHour:
    """Results of one time step (kW_th are averages over the step)."""

    end: TankState
    q_heat_in_kwth: float  # accepted: > 0 charged, < 0 discharged
    soc_end: float  # hot mass / total mass, 0..1
    # Facility water leaving the storage HX (what downstream sees): charging
    # T_cold + pinch, discharging T_hot − pinch; T_in when no heat moved.
    t_sys_c: float


def two_tank_step(
    start: TankState,
    q_heat_in_req_kwth: float,
    t_heat_in_c: float,
    t_pinch_c: float,
    cp_kj_kgk: float = WATER_CP_KJ_KGK,
    dt_h: float = HOURLY_DT_H,
) -> TwoTankHour:
    """One time step of a two tank (or perfect thermocline) hot water store.

    q_heat_in_req_kwth: heat the facility asks the storage to take (> 0) or give (< 0)
    t_heat_in_c: facility water temperature at the heat exchanger — the return
        (warm) water when charging, the supply (cold) water when discharging
    t_pinch_c: heat exchanger pinch; 0 when the tanks are directly connected

    Charging:    cold water → T_in − pinch → hot tank (mixes with what is there)
                 m = min(Q·Δt / (cp·(T_in − pinch − T_cold)), m_cold)
    Discharging: hot water → T_in + pinch → cold tank (mixes)
                 m = min(−Q·Δt / (cp·(T_hot − (T_in + pinch))), m_hot)
    Q_heat_in = what was actually accepted (limited by the water left to move,
    and zero if the temperatures don't allow heat to flow that way).

    The pinch hurts both ways, so the facility side gets back:
    T_sys = T_cold + pinch (charging) or T_hot − pinch (discharging), using the
    tank temperature at the start of the step; T_in if no heat moved.
    """
    dt_s = dt_h * SECONDS_PER_HOUR
    s = start
    m_total = s.m_cold_kg + s.m_hot_kg
    t_cold, t_hot, m_cold, m_hot = s.t_cold_c, s.t_hot_c, s.m_cold_kg, s.m_hot_kg
    q_in = 0.0
    t_sys = t_heat_in_c  # no exchange: the facility water passes unchanged

    if q_heat_in_req_kwth > 0:
        t_to_hot = t_heat_in_c - t_pinch_c  # cold water leaves the HX at this temp
        dt_k = t_to_hot - s.t_cold_c
        if dt_k > 0:
            m_moved = min(q_heat_in_req_kwth * dt_s / (cp_kj_kgk * dt_k), s.m_cold_kg)
            m_hot = s.m_hot_kg + m_moved
            m_cold = s.m_cold_kg - m_moved
            if m_hot > 0:  # mix into the hot tank
                t_hot = (m_moved * t_to_hot + s.m_hot_kg * s.t_hot_c) / m_hot
            q_in = m_moved * cp_kj_kgk * dt_k / dt_s
            if m_moved > 0:
                t_sys = s.t_cold_c + t_pinch_c  # facility water cooled toward the cold tank
    elif q_heat_in_req_kwth < 0:
        t_to_cold = t_heat_in_c + t_pinch_c  # hot water leaves the HX at this temp
        dt_k = s.t_hot_c - t_to_cold
        if dt_k > 0:
            m_moved = min(-q_heat_in_req_kwth * dt_s / (cp_kj_kgk * dt_k), s.m_hot_kg)
            m_cold = s.m_cold_kg + m_moved
            m_hot = s.m_hot_kg - m_moved
            if m_cold > 0:  # mix into the cold tank
                t_cold = (m_moved * t_to_cold + s.m_cold_kg * s.t_cold_c) / m_cold
            q_in = -m_moved * cp_kj_kgk * dt_k / dt_s
            if m_moved > 0:
                t_sys = s.t_hot_c - t_pinch_c  # facility water heated toward the hot tank

    soc = m_hot / m_total if m_total > 0 else 0.0
    return TwoTankHour(TankState(t_cold, t_hot, m_cold, m_hot), q_in, soc, t_sys)


def initial_state(p: HotWaterStorageParams, t_supply_c: float, t_return_c: float) -> TankState:
    """Cold tank full of supply-temperature water, hot tank empty (owner).

    The empty hot tank's temperature is a placeholder; the first water in sets it.
    """
    return TankState(
        t_cold_c=t_supply_c, t_hot_c=t_return_c - p.t_pinch_c, m_cold_kg=p.mass_kg, m_hot_kg=0.0
    )


def charge_capacity_kwth(s: TankState, t_heat_in_c: float, p: HotWaterStorageParams) -> float:
    """The most heat the tanks can take this hour from water at t_heat_in_c."""
    dt_k = t_heat_in_c - p.t_pinch_c - s.t_cold_c
    return max(s.m_cold_kg * WATER_CP_KJ_KGK * dt_k / (HOURLY_DT_H * SECONDS_PER_HOUR), 0.0)


def discharge_capacity_kwth(s: TankState, t_heat_in_c: float, p: HotWaterStorageParams) -> float:
    """The most heat the tanks can give this hour against water at t_heat_in_c."""
    dt_k = s.t_hot_c - (t_heat_in_c + p.t_pinch_c)
    return max(s.m_hot_kg * WATER_CP_KJ_KGK * dt_k / (HOURLY_DT_H * SECONDS_PER_HOUR), 0.0)


@dataclass(frozen=True)
class HotWaterStorage:
    """Solver node (docs/solver.md). Charges from the data center's return water
    and discharges to power generation and the greenhouse, as the state links
    it (charge first, then discharge from the charged tanks, receivers in THEN
    order).

    params: resolved (tank volume set). Discharging cools the hot water against
    each receiver's water (`sink_c`; default the supply water) and returns it
    to the cold tank.
    """

    params: HotWaterStorageParams
    t_supply_c: float
    t_return_c: float
    # Water temperature each receiver cools the hot water against, °C (the
    # greenhouse: setpoint + coil approach); missing = the supply water.
    sink_c: Mapping[str, float] = field(default_factory=dict)
    name: str = KEY
    control_key: str | None = KEY
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = (
        col.HWS_CHARGE_KWTH,
        col.HWS_DISCHARGE_KWTH,
        col.HWS_NET_KWTH,
        col.HWS_STACK_KWTH,
        col.HWS_SOC_FRAC,
        col.HWS_T_HOT_C,
        col.HWS_T_COLD_C,
        col.HWS_T_SYS_C,
    )
    reads: tuple[str, ...] = (
        st.heat_sent(DATA_CENTER, KEY),
        *(st.heat_req(KEY, k) for k in RECEIVERS),
        *(st.heat_used(KEY, k) for k in RECEIVERS),
    )
    writes: tuple[StreamSpec, ...] = (
        StreamSpec(st.heat_req(DATA_CENTER, KEY)),
        StreamSpec(st.heat_used(DATA_CENTER, KEY)),
        *(StreamSpec(st.heat_sent(KEY, k), answers=st.heat_req(KEY, k)) for k in RECEIVERS),
        StreamSpec(st.HWS_T_HOT_C),
    )

    def prepare(self, df: pd.DataFrame) -> Any:
        return None

    def initial_state(self) -> TankState:
        return initial_state(self.params, self.t_supply_c, self.t_return_c)

    def control_values(self, state: TankState) -> dict[str, float]:
        total = state.m_cold_kg + state.m_hot_kg
        hot = state.m_hot_kg / total * 100 if total > 0 else 0.0
        return {"hot_level_pct": hot, "cold_level_pct": 100 - hot}

    def step(self, data: Any, state: TankState, h: int, flows: Flows, plan: Plan) -> NodeStep:
        p = self.params
        on = plan.runs(KEY)
        charge = on and plan.link(Commodity.HEAT, DATA_CENTER, KEY) is not None
        want = charge_capacity_kwth(state, self.t_return_c, p) if charge else 0.0
        sent = flows[st.heat_sent(DATA_CENTER, KEY)] if charge else 0.0
        q_charge = want if sent is None else min(want, sent)  # unanswered: assume it's given
        ch = two_tank_step(state, q_charge, self.t_return_c, p.t_pinch_c)

        # discharge: each linked receiver in THEN order, from what is left
        tanks, moved, q_dis, q_gh = ch.end, ch, 0.0, 0.0
        offered: dict[str, float | None] = {k: None for k in RECEIVERS}
        for link in plan.sent_by(KEY, Commodity.HEAT) if on else ():
            k = link.receiver
            req = flows[st.heat_req(KEY, k)]
            if req is None:
                continue
            sink = self.sink_c.get(k, self.t_supply_c)
            offer = min(req, discharge_capacity_kwth(tanks, sink, p))
            offered[k] = offer
            used = flows[st.heat_used(KEY, k)]
            give = offer if used is None else min(used, offer)
            dis = two_tank_step(tanks, -give, sink, p.t_pinch_c)
            tanks, q_dis = dis.end, q_dis - dis.q_heat_in_kwth
            if k == GREENHOUSE:
                q_gh -= dis.q_heat_in_kwth
            if dis.q_heat_in_kwth < 0:
                moved = dis
        total = tanks.m_cold_kg + tanks.m_hot_kg
        return NodeStep(
            tanks,
            {
                st.heat_req(DATA_CENTER, KEY): want if charge else None,
                st.heat_used(DATA_CENTER, KEY): ch.q_heat_in_kwth if charge else None,
                **{st.heat_sent(KEY, k): v for k, v in offered.items()},
                # delivery temperature for the receivers, fixed for the hour
                st.HWS_T_HOT_C: state.t_hot_c - p.t_pinch_c,
            },
            {
                col.HWS_CHARGE_KWTH: ch.q_heat_in_kwth,
                col.HWS_DISCHARGE_KWTH: q_dis,
                col.HWS_NET_KWTH: ch.q_heat_in_kwth - q_dis,
                # the stack band: the greenhouse's share is its own band on top
                col.HWS_STACK_KWTH: ch.q_heat_in_kwth - (q_dis - q_gh),
                col.HWS_SOC_FRAC: tanks.m_hot_kg / total if total > 0 else 0.0,
                col.HWS_T_HOT_C: tanks.t_hot_c,
                col.HWS_T_COLD_C: tanks.t_cold_c,
                col.HWS_T_SYS_C: moved.t_sys_c,
            },
        )
