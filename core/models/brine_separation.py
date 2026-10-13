"""Brine separation module: single-stage evaporator on data center heat
(docs/models/brine-separation.md, D-048).

Layer 1 is the one-hour physics (`brine_sep_step`), the owner's math with the
fixes listed in the doc; layer 2 (`BrineSeparation`) is its solver node: the
solver threads the tank's brine mass and concentration hour to hour, and the
ice mixer draws concentrated brine and returns diluted brine (docs/solver.md).

The data center's hot water boils water out of the brine (brine at T_hot −
boiler pinch); the vapor condenses against the coolant (condensing at the
pure-water saturation temperature of the brine's vapor pressure, which must be
above coolant + condenser pinch). No internal temperature changes are modelled
(owner): the condenser rejects the same heat the boiler takes in.

What it exchanges is set by the hour's state (D-054): heat from the data
center (a share of it, in THEN order with the other heat users), brine with
the ice mixer, recovered water to ice storage (or the drain). Its condenser
rejects into the supply coolant unless the state has the ice mixer cool it,
and power generation can take condenser heat as its hot side.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.config.defaults import BRINE_INPUTS, CONTROL, SECONDS_PER_HOUR, BrineProperties
from core.domain.brine import rho_brine, vapor_sat_temp, water_activity
from core.domain.control import (
    DATA_CENTER,
    DRAIN,
    Commodity,
    ControlSetting,
    ControlSpec,
    ControlVariable,
    Plan,
    SettingKind,
    off_setting,
)
from core.domain.modules import BrineSeparationParams
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.solver import Flows, NodeStep, StreamSpec

HOURLY_DT_H = 1.0  # the frame is hourly

KEY = "brine_separation"
ICE_MIXER, ICE_STORAGE, POWER_GEN = "ice_mixer", "ice_storage", "power_generation"
_PCT = CONTROL.brine_heat_pct
# State machine IFs / THENs (docs/control.md, owner's write-up).
CONTROL_SPEC = ControlSpec(
    KEY,
    "Brine separation",
    ifs=(ControlVariable("conc_wt_pct", "Brine concentration", "wt%"),),
    thens=(
        ControlSetting(
            "brine_out",
            "Sends brine flow to {to}",
            SettingKind.LINK,
            commodity=Commodity.BRINE,
            ends=(ICE_MIXER,),
        ),
        ControlSetting(
            "heat_in",
            "Accepts {value} % of heat from {to}",
            SettingKind.LINK,
            _PCT.default,
            _PCT.min,
            _PCT.max,
            _PCT.step,
            "%",
            commodity=Commodity.HEAT,
            receives=True,
            ends=(DATA_CENTER,),
            amount=True,
        ),
        ControlSetting(
            "water_out",
            "Sends water to {to}",
            SettingKind.LINK,
            commodity=Commodity.WATER,
            ends=(ICE_STORAGE, DRAIN),
        ),
        off_setting("Brine separation"),
    ),
)
BISECT_STEPS = 60  # brine that fits a full tank: halves the interval to ~1e-18 of the offer


@dataclass(frozen=True)
class BrineState:
    """The tank at one instant."""

    m_brine_kg: float
    c_brine: float  # salt mass fraction


@dataclass(frozen=True)
class BrineSepHour:
    """Results of one time step (kW_th are averages over the step)."""

    end: BrineState
    q_heat_in_kwth: float  # accepted from the data center (= condenser rejection)
    water_out_kg: float  # condensed pure water this step
    m_brine_in_kg_s: float  # brine accepted (≤ offered: the tank may be full)
    m_brine_out_kg_s: float  # brine supplied at the start concentration (≤ requested)


@dataclass(frozen=True)
class BrineDesign:
    """Fixed for the run (computed once from the params)."""

    props: BrineProperties
    c_max: float  # stop concentrating here (high end of the range)
    v_max_m3: float  # tank volume
    h_vap_kj_kg: float = BRINE_INPUTS.h_vap_kj_kg
    pinch_boiler_c: float = BRINE_INPUTS.pinch_boiler_c
    pinch_condenser_c: float = BRINE_INPUTS.pinch_condenser_c


def condensing_temp_c(c: float, t_heat_in_c: float, d: BrineDesign) -> float:
    """Pure-water saturation temperature of the brine's vapor (brine at T_in − pinch)."""
    return vapor_sat_temp(t_heat_in_c - d.pinch_boiler_c, water_activity(c, d.props))


def brine_sep_step(
    start: BrineState,
    q_heat_in_req_kwth: float,
    t_heat_in_c: float,
    t_coolant_c: float,
    d: BrineDesign,
    m_brine_in_kg_s: float = 0.0,
    c_brine_in: float = 0.0,
    m_brine_out_kg_s: float = 0.0,
    dt_h: float = HOURLY_DT_H,
) -> BrineSepHour:
    """One time step of the brine separator.

    Runs if coolant + condenser pinch < condensing temperature (at the start
    concentration). Water out = Q / h_vap, but no more than takes the brine
    (after any brine in / out) to c_max. Salt is conserved:
    m_end = m + in − out − water ;  c_end = (m·c + in·c_in − out·c) / m_end.

    Like every receiving module, it reports what it actually took (D-051):
    out = min(out requested, brine in the tank); in = min(in offered, the most
    that fits in the tank), then the step is recalculated with those flows. If
    no min binds, the recalculation reproduces the requested flows.
    """
    dt_s = dt_h * SECONDS_PER_HOUR
    s = start
    runs = q_heat_in_req_kwth > 0 and (
        t_coolant_c + d.pinch_condenser_c < condensing_temp_c(s.c_brine, t_heat_in_c, d)
    )
    water_req_kg = q_heat_in_req_kwth * dt_s / d.h_vap_kj_kg if runs else 0.0

    def settle(m_in_kg: float, m_out_kg: float) -> tuple[float, float, float]:
        """(water out, end mass, end concentration) for these brine flows."""
        salt = s.m_brine_kg * s.c_brine + m_in_kg * c_brine_in - m_out_kg * s.c_brine
        m_flows = s.m_brine_kg + m_in_kg - m_out_kg
        water_cap = max(m_flows - salt / d.c_max, 0.0)  # stop at c_max
        water = min(water_req_kg, water_cap)
        m_end = m_flows - water
        return water, m_end, salt / m_end if m_end > 0 else s.c_brine

    def volume_m3(in_kg_s: float, out_kg_s: float) -> float:
        _, m, c = settle(in_kg_s * dt_s, out_kg_s * dt_s)
        return m / rho_brine(c, d.props)

    # Flows stay in kg/s so an unlimited flow comes back exactly as offered.
    out_kg_s = min(m_brine_out_kg_s, s.m_brine_kg / dt_s)  # can't supply more than is there
    in_kg_s = m_brine_in_kg_s
    if in_kg_s > 0 and volume_m3(in_kg_s, out_kg_s) > d.v_max_m3:
        # The most brine that fits: the end volume rises with brine in, and with
        # none in it can't exceed the start volume, so bisect on [0, offered].
        lo, hi = 0.0, in_kg_s
        for _ in range(BISECT_STEPS):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if volume_m3(mid, out_kg_s) <= d.v_max_m3 else (lo, mid)
        in_kg_s = lo
    water, m_end, c_end = settle(in_kg_s * dt_s, out_kg_s * dt_s)
    q_in = water * d.h_vap_kj_kg / dt_s
    return BrineSepHour(BrineState(m_end, c_end), q_in, water, in_kg_s, out_kg_s)


@dataclass(frozen=True)
class BrineSeparation:
    """Solver node (docs/solver.md). Takes data center heat when the state links
    it (as much as the brine can take before c_max, while the temperature stack
    works), supplies concentrated brine to / takes diluted brine back from the
    ice mixer, and sends its recovered water to ice storage or the drain.

    Condenser: rejects into the supply coolant (free cooling / chillers), or to
    the ice mixer when the state has it cool brine separation (then the
    condenser works against the mixer's temperature and can reject no more than
    the mixer delivers). Power generation may take condenser heat first.

    params: resolved (brine mass set). t_heat_in_c: data center return (warm)
    water. Starts full of brine at the low concentration.
    """

    params: BrineSeparationParams
    t_heat_in_c: float
    it_parasitic_frac: float
    name: str = KEY
    control_key: str | None = KEY
    requires: tuple[str, ...] = (col.T_COOLANT_C,)
    provides: tuple[str, ...] = (
        col.BRINE_HEAT_KWTH,
        col.BRINE_MASS_KG,
        col.BRINE_CONC_WT_PCT,
        col.BRINE_SOC_FRAC,
        col.BRINE_WATER_OUT_KG_H,
        col.BRINE_WATER_TO_ICE_KG_S,
        col.BRINE_OUT_KG_S,
        col.BRINE_IN_KG_S,
    )
    reads: tuple[str, ...] = (
        st.IT_LOAD_KW,
        st.heat_sent(DATA_CENTER, KEY),
        st.heat_req(KEY, POWER_GEN),
        st.heat_used(KEY, POWER_GEN),
        st.ICE_MIX_T_C,
        st.cool_sent(KEY),
        st.BRINE_CALL_KG_S,
        st.BRINE_USED_KG_S,
        st.BRINE_RETURN_KG_S,
        st.BRINE_RETURN_USED_KG_S,
        st.BRINE_RETURN_C,
        st.RECOVERED_WATER_ACCEPTED_KG_S,
    )
    writes: tuple[StreamSpec, ...] = (
        StreamSpec(st.heat_req(DATA_CENTER, KEY)),
        StreamSpec(st.heat_used(DATA_CENTER, KEY)),
        StreamSpec(st.heat_sent(KEY, POWER_GEN), answers=st.heat_req(KEY, POWER_GEN)),
        StreamSpec(st.CONDENSER_T_C),
        StreamSpec(st.cool_req(KEY)),
        StreamSpec(st.cool_used(KEY)),
        StreamSpec(st.coolant_load(KEY)),
        StreamSpec(st.BRINE_C_START),
        StreamSpec(st.BRINE_SUPPLIED_KG_S, answers=st.BRINE_CALL_KG_S),
        StreamSpec(st.BRINE_RETURN_ACCEPTED_KG_S, answers=st.BRINE_RETURN_KG_S),
        StreamSpec(st.RECOVERED_WATER_KG_S),
    )

    def design(self) -> BrineDesign:
        p = self.params
        return BrineDesign(props=p.props, c_max=p.c_high, v_max_m3=p.tank_volume_m3)

    def prepare(self, df: pd.DataFrame) -> tuple[np.ndarray, BrineDesign]:
        return df[col.T_COOLANT_C].to_numpy(dtype=float), self.design()

    def initial_state(self) -> BrineState:
        return BrineState(self.params.mass_kg, self.params.c_low)

    def control_values(self, state: BrineState) -> dict[str, float]:
        return {"conc_wt_pct": state.c_brine * 100}

    def step(
        self,
        data: tuple[np.ndarray, BrineDesign],
        state: BrineState,
        h: int,
        flows: Flows,
        plan: Plan,
    ) -> NodeStep:
        t_coolant, d = data
        on = plan.runs(KEY)
        by_ice = on and plan.link(Commodity.COOLING, ICE_MIXER, KEY) is not None
        t_mix = flows[st.ICE_MIX_T_C]
        t_cool = t_mix if by_ice and t_mix is not None else float(t_coolant[h])
        c_in = flows[st.BRINE_RETURN_C] or 0.0

        def run(q_kwth: float, m_in: float, m_out: float) -> BrineSepHour:
            return brine_sep_step(state, q_kwth, self.t_heat_in_c, t_cool, d, m_in, c_in, m_out)

        # Brine with the ice mixer: answer its wants, balance on what it used.
        brine = on and plan.link(Commodity.BRINE, KEY, ICE_MIXER) is not None
        call, back = flows[st.BRINE_CALL_KG_S], flows[st.BRINE_RETURN_KG_S]
        w_out, w_in = ((call or 0.0), (back or 0.0)) if brine else (0.0, 0.0)
        u_out, u_in = flows[st.BRINE_USED_KG_S], flows[st.BRINE_RETURN_USED_KG_S]
        a_out = (w_out if u_out is None else u_out) if brine else 0.0
        a_in = (w_in if u_in is None else u_in) if brine else 0.0

        # Heat: the most it could take (the want), then the limits: what the data
        # center gave, and with the ice mixer as condenser cooling, what the mixer
        # and power generation together can take from the condenser.
        heat_link = on and plan.link(Commodity.HEAT, DATA_CENTER, KEY) is not None
        dc_heat = (flows[st.IT_LOAD_KW] or 0.0) * (1 + self.it_parasitic_frac)
        cap = run(dc_heat, a_in, a_out).q_heat_in_kwth if heat_link else 0.0
        pg_link = on and plan.link(Commodity.HEAT, KEY, POWER_GEN) is not None
        pg_req = flows[st.heat_req(KEY, POWER_GEN)] if pg_link else None
        pg_used = flows[st.heat_used(KEY, POWER_GEN)] if pg_link else None
        pg_take = min(pg_req or 0.0, cap) if pg_used is None else pg_used
        ice_req = max(cap - min(pg_req or 0.0, cap), 0.0) if by_ice else None
        ice_offer = flows[st.cool_sent(KEY)] if by_ice else None
        dc_sent = flows[st.heat_sent(DATA_CENTER, KEY)] if heat_link else None
        q = cap if dc_sent is None else min(cap, dc_sent)  # unanswered: assume it's given
        if ice_offer is not None:
            q = min(q, pg_take + ice_offer)

        answers = run(q, w_in, w_out)
        a_out = min(a_out, answers.m_brine_out_kg_s)
        a_in = min(a_in, answers.m_brine_in_kg_s)
        hour = run(q, a_in, a_out)
        q_in = hour.q_heat_in_kwth
        pg_sent = None if pg_req is None else min(pg_req, q_in)
        pg_actual = (pg_sent or 0.0) if pg_used is None else min(pg_used, pg_sent or 0.0)
        reject = q_in - pg_actual  # to the ice mixer or the supply coolant
        water_kg_s = hour.water_out_kg / (HOURLY_DT_H * SECONDS_PER_HOUR)
        to_ice = on and plan.link(Commodity.WATER, KEY, ICE_STORAGE) is not None
        accepted = flows[st.RECOVERED_WATER_ACCEPTED_KG_S] if to_ice else None
        end = hour.end
        return NodeStep(
            end,
            {
                st.heat_req(DATA_CENTER, KEY): cap if heat_link else None,
                st.heat_used(DATA_CENTER, KEY): q_in if heat_link else None,
                st.heat_sent(KEY, POWER_GEN): pg_sent,
                st.CONDENSER_T_C: condensing_temp_c(state.c_brine, self.t_heat_in_c, d)
                - d.pinch_condenser_c,
                st.cool_req(KEY): ice_req,
                st.cool_used(KEY): reject if by_ice else None,
                st.coolant_load(KEY): 0.0 if by_ice else reject,
                st.BRINE_C_START: state.c_brine,  # brine out leaves at the start concentration
                # no answer until asked (None tells the mixer it hasn't been answered)
                st.BRINE_SUPPLIED_KG_S: None if call is None else answers.m_brine_out_kg_s,
                st.BRINE_RETURN_ACCEPTED_KG_S: None if back is None else answers.m_brine_in_kg_s,
                st.RECOVERED_WATER_KG_S: water_kg_s if to_ice else None,
            },
            {
                col.BRINE_HEAT_KWTH: q_in,
                col.BRINE_MASS_KG: end.m_brine_kg,
                col.BRINE_CONC_WT_PCT: end.c_brine * 100,
                col.BRINE_SOC_FRAC: end.m_brine_kg / rho_brine(end.c_brine, d.props) / d.v_max_m3,
                col.BRINE_WATER_OUT_KG_H: hour.water_out_kg / HOURLY_DT_H,
                col.BRINE_WATER_TO_ICE_KG_S: accepted or 0.0,
                col.BRINE_OUT_KG_S: hour.m_brine_out_kg_s,
                col.BRINE_IN_KG_S: hour.m_brine_in_kg_s,
            },
        )
