"""Ice mixer module: melts ice from ice storage into water or brine to supply
cooling (docs/models/ice-mixer.md, D-050).

Layer 1 is the one-hour physics (`ice_mixer_step`), the owner's math with the
fixes listed in the doc; layer 2 (`IceMixer`) is its solver node (docs/solver.md).

Two passes per hour. Pass 1 (no supplied flows yet): the mixer assumes the
tanks can give it what it wants and returns those flows as *calls* to ice
storage / brine separation. Pass 2 (the flows that were physically supplied,
and what the tanks accepted of its outputs): it recalculates what it can
deliver. The hourly solver repeats this until the flows settle.

Who it cools is set by the state (D-054): the data center, power generation
and / or brine separation's condenser, served in THEN order; it melts only
the ice for the cooling they actually use.

Brine salt balance (ice carries no salt):
    salt:  m_brine·c_in = m_out·c_mix        mass:  m_out = m_brine + m_ice
    →  m_ice = m_brine·(c_in/c_mix − 1),  m_out = m_brine·c_in/c_mix
"""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from core.config.defaults import BRINES, BrineProperties, BrineType, IceMixerFluid
from core.domain.brine import brine_c, brine_fp, brine_h_solv
from core.domain.control import (
    DATA_CENTER,
    Commodity,
    ControlSetting,
    ControlSpec,
    Plan,
    SettingKind,
    off_setting,
)
from core.domain.ice import ice_hf
from core.domain.modules import IceMixerParams
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.solver import Flows, NodeStep, StreamSpec

KEY = "ice_mixer"
ICE_STORAGE, BRINE_SEP = "ice_storage", "brine_separation"
CONSUMERS = (DATA_CENTER, "power_generation", BRINE_SEP)
# State machine IFs / THENs (docs/control.md, owner's write-up). The fluid
# (water / brine) is the module's input, not a THEN (owner).
CONTROL_SPEC = ControlSpec(
    KEY,
    "Ice mixer",
    ifs=(),
    thens=(
        ControlSetting(
            "cooling_out",
            "Provides cooling to {to}",
            SettingKind.LINK,
            commodity=Commodity.COOLING,
            ends=CONSUMERS,
        ),
        off_setting("Ice mixer"),
    ),
)

DEFAULT_BRINE = BRINES[BrineType.POTASSIUM_ACETATE]


@dataclass(frozen=True)
class IceMixHour:
    """Results of one pass (kW_th and kg/s are averages over the step)."""

    m_ice_call_kg_s: float  # pass 1: ice asked of ice storage; pass 2: ice used
    m_brine_call_kg_s: float  # pass 1: brine asked of brine separation; pass 2: used
    q_delivered_kwth: float  # pass 1: assumes the calls are met
    m_brine_out_kg_s: float  # diluted brine back to the brine tank
    c_brine_out: float  # its salt mass fraction (= c_mix)
    m_water_out_kg_s: float  # melt water back to the ice storage water tank
    t_mix_c: float  # temperature the cooling is supplied at


def ice_mixer_step(
    q_request_kwth: float,
    c_brine_in: float,
    p: IceMixerParams,
    props: BrineProperties = DEFAULT_BRINE,
    m_ice_in_kg_s: float | None = None,
    m_brine_in_kg_s: float | None = None,
    m_water_out_max_kg_s: float | None = None,
    m_brine_out_max_kg_s: float | None = None,
) -> IceMixHour:
    """One pass of the ice mixer.

    q_request_kwth: cooling requested from the mixer
    c_brine_in: salt mass fraction of the brine it is sent (ignored for water)
    m_ice_in_kg_s, m_brine_in_kg_s: flows actually supplied; None = not known yet
        (pass 1), so the mixer assumes it gets what it calls for.
    m_water_out_max_kg_s, m_brine_out_max_kg_s: what the receiving tanks accepted
        of its melt water / diluted brine; None = not known yet. The mixer can't
        dump them, so it melts only as much ice as its outputs can go somewhere.

    Water: the ice melts at 0 °C, h = h_f(0); the melt water goes back to ice storage.
    Brine: t_mix = fp(c_in)·mix_eta (a perfect, impossible mixer cools at the
    incoming brine's freeze point); c_mix = c(t_mix);
    h = (h_f(t_mix) + h_solv(c_mix))·recup_eta (h_solv < 0: solvation heat is
    generated, so it reduces the cooling), recup_eta being the catch-all for
    imperfectly recuperated streams until each component tracks its own.
    Water has no recup_eta: ice is made, stored and melted at 0 °C (owner).
    """
    if p.fluid is IceMixerFluid.WATER:
        h_kj_kg = ice_hf(0.0)
        m_ice = q_request_kwth / h_kj_kg
        if m_ice_in_kg_s is not None:
            m_ice = min(m_ice, m_ice_in_kg_s)  # never melts more than it needs
        if m_water_out_max_kg_s is not None:
            m_ice = min(m_ice, m_water_out_max_kg_s)  # melt water must fit in the water tank
        return IceMixHour(
            m_ice_call_kg_s=m_ice,
            m_brine_call_kg_s=0.0,
            q_delivered_kwth=m_ice * h_kj_kg,
            m_brine_out_kg_s=0.0,
            c_brine_out=0.0,
            m_water_out_kg_s=m_ice,
            t_mix_c=0.0,
        )

    t_mix_c = brine_fp(c_brine_in, props) * p.mix_eta
    c_mix = brine_c(t_mix_c, props)
    if not 0 < c_mix < c_brine_in:
        # Too dilute to mix below 0 °C (the two fits don't invert exactly near c = 0):
        # nothing to call, nothing delivered.
        return IceMixHour(0.0, 0.0, 0.0, 0.0, c_brine_in, 0.0, t_mix_c)
    ice_per_brine = c_brine_in / c_mix - 1  # salt balance: kg ice per kg brine
    h_kj_kg = (ice_hf(t_mix_c) + brine_h_solv(c_mix, props)) * p.recup_eta
    if h_kj_kg <= 0:
        raise ValueError(f"Ice mixer cooling per kg of ice is {h_kj_kg:.1f} kJ/kg ≤ 0")

    m_ice = q_request_kwth / h_kj_kg
    if m_ice_in_kg_s is not None:
        m_ice = min(m_ice, m_ice_in_kg_s)  # ice-limited
    m_brine = m_ice / ice_per_brine
    if m_brine_in_kg_s is not None and m_brine > m_brine_in_kg_s:
        m_brine = m_brine_in_kg_s  # brine-limited: only this much ice can be used
        m_ice = m_brine * ice_per_brine
    if m_brine_out_max_kg_s is not None and m_brine * c_brine_in / c_mix > m_brine_out_max_kg_s:
        m_brine = m_brine_out_max_kg_s * c_mix / c_brine_in  # diluted brine must fit the tank
        m_ice = m_brine * ice_per_brine
    return IceMixHour(
        m_ice_call_kg_s=m_ice,
        m_brine_call_kg_s=m_brine,
        q_delivered_kwth=m_ice * h_kj_kg,
        m_brine_out_kg_s=m_brine * c_brine_in / c_mix,  # = m_brine + m_ice
        c_brine_out=c_mix,
        m_water_out_kg_s=0.0,
        t_mix_c=t_mix_c,
    )


@dataclass(frozen=True)
class IceMixer:
    """Solver node (docs/solver.md): cools the modules the state links it to,
    in THEN order, with ice from ice storage (and brine from brine separation).

    Each hour: its wants (pass 1 on the total cooling asked) go out as calls;
    what it can deliver (pass 2 on the supplied flows) is offered to the
    consumers in order, each getting what the ones before it left; it then
    melts only the ice for what they used (pass 2 again), and returns that
    melt water / diluted brine. props: the brine brine separation holds.
    """

    params: IceMixerParams
    props: BrineProperties = DEFAULT_BRINE
    name: str = KEY
    control_key: str | None = KEY
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = (
        col.ICE_MIX_Q_KWTH,
        col.ICE_MIX_T_C,
        col.ICE_MIX_ICE_KG_S,
        col.ICE_MIX_BRINE_KG_S,
        col.ICE_MIX_BRINE_OUT_KG_S,
        col.ICE_MIX_BRINE_OUT_WT_PCT,
        col.ICE_MIX_WATER_OUT_KG_S,
    )
    reads: tuple[str, ...] = (
        *(st.cool_req(k) for k in CONSUMERS),
        *(st.cool_used(k) for k in CONSUMERS),
        st.BRINE_C_START,
        st.ICE_SUPPLIED_KG_S,
        st.MELT_WATER_ACCEPTED_KG_S,
        st.BRINE_SUPPLIED_KG_S,
        st.BRINE_RETURN_ACCEPTED_KG_S,
    )
    writes: tuple[StreamSpec, ...] = (
        *(StreamSpec(st.cool_sent(k), answers=st.cool_req(k)) for k in CONSUMERS),
        StreamSpec(st.ICE_MIX_T_C),
        StreamSpec(st.ICE_CALL_KG_S),
        StreamSpec(st.ICE_USED_KG_S),
        StreamSpec(st.MELT_WATER_KG_S),
        StreamSpec(st.MELT_WATER_USED_KG_S),
        StreamSpec(st.BRINE_CALL_KG_S),
        StreamSpec(st.BRINE_USED_KG_S),
        StreamSpec(st.BRINE_RETURN_KG_S),
        StreamSpec(st.BRINE_RETURN_USED_KG_S),
        StreamSpec(st.BRINE_RETURN_C),
    )

    def prepare(self, df: pd.DataFrame) -> Any:
        return None

    def initial_state(self) -> Any:
        return None

    def _supplied(self, plan: Plan) -> bool:
        """Its suppliers are linked: ice storage, and brine separation on brine."""
        ice = plan.link(Commodity.ICE, ICE_STORAGE, KEY) is not None
        brine = plan.link(Commodity.BRINE, BRINE_SEP, KEY) is not None
        return ice and (brine or self.params.fluid is IceMixerFluid.WATER)

    def step(self, data: Any, state: Any, h: int, flows: Flows, plan: Plan) -> NodeStep:
        on = plan.runs(KEY) and self._supplied(plan)
        consumers = [k.receiver for k in plan.sent_by(KEY, Commodity.COOLING)] if on else []
        reqs = {k: flows[st.cool_req(k)] for k in consumers}
        total = sum(r for r in reqs.values() if r is not None)
        c_in = flows[st.BRINE_C_START] or 0.0

        def mix(q_kwth: float, limited: bool) -> IceMixHour:
            if not limited:
                return ice_mixer_step(q_kwth, c_in, self.params, self.props)
            return ice_mixer_step(
                q_kwth,
                c_in,
                self.params,
                self.props,
                m_ice_in_kg_s=flows[st.ICE_SUPPLIED_KG_S],
                m_brine_in_kg_s=flows[st.BRINE_SUPPLIED_KG_S],
                m_water_out_max_kg_s=flows[st.MELT_WATER_ACCEPTED_KG_S],
                m_brine_out_max_kg_s=flows[st.BRINE_RETURN_ACCEPTED_KG_S],
            )

        want = mix(total, limited=False)  # pass 1: the calls
        can = mix(total, limited=True)  # pass 2: what the supplied flows allow
        left = can.q_delivered_kwth
        sent: dict[str, float | None] = {k: None for k in CONSUMERS}
        used_total = 0.0
        for k in consumers:  # THEN order
            r = reqs[k]
            if r is None:
                continue
            give = min(r, max(left, 0.0))
            u = flows[st.cool_used(k)]
            took = give if u is None else min(u, give)  # not reported yet: all of it
            sent[k] = give
            left -= took
            used_total += took
        actual = mix(used_total, limited=True)  # melts only what was used
        asked = on and bool(consumers)
        return NodeStep(
            None,
            {
                **{st.cool_sent(k): v for k, v in sent.items()},
                st.ICE_MIX_T_C: want.t_mix_c if on else None,
                st.ICE_CALL_KG_S: want.m_ice_call_kg_s if asked else None,
                st.ICE_USED_KG_S: actual.m_ice_call_kg_s if asked else None,
                st.MELT_WATER_KG_S: want.m_water_out_kg_s if asked else None,
                st.MELT_WATER_USED_KG_S: actual.m_water_out_kg_s if asked else None,
                st.BRINE_CALL_KG_S: want.m_brine_call_kg_s if asked else None,
                st.BRINE_USED_KG_S: actual.m_brine_call_kg_s if asked else None,
                st.BRINE_RETURN_KG_S: want.m_brine_out_kg_s if asked else None,
                st.BRINE_RETURN_USED_KG_S: actual.m_brine_out_kg_s if asked else None,
                st.BRINE_RETURN_C: want.c_brine_out,
            },
            {
                col.ICE_MIX_Q_KWTH: actual.q_delivered_kwth if asked else 0.0,
                col.ICE_MIX_T_C: want.t_mix_c,
                col.ICE_MIX_ICE_KG_S: actual.m_ice_call_kg_s if asked else 0.0,
                col.ICE_MIX_BRINE_KG_S: actual.m_brine_call_kg_s if asked else 0.0,
                col.ICE_MIX_BRINE_OUT_KG_S: actual.m_brine_out_kg_s if asked else 0.0,
                col.ICE_MIX_BRINE_OUT_WT_PCT: actual.c_brine_out * 100,
                col.ICE_MIX_WATER_OUT_KG_S: actual.m_water_out_kg_s if asked else 0.0,
            },
        )
