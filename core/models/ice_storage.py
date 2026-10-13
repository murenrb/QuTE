"""Ice storage module (docs/models/ice-storage.md, D-049).

Layer 1 is the one-hour physics (`ice_step`), written by the owner; layer 2
(`IceStorage`) is its solver node: the solver threads both tanks' states of
charge hour to hour (docs/solver.md).

Two tanks: the ice maker freezes water from the water tank into the ice tank.
Other modules take ice (a mass flow request) and hand water back (a mass flow
offer), so the step's inputs and outputs are mass flows. Inside, the flows are
turned into duties with the latent heat and the accounting is done in kW_th /
kWh_th; the kW_th terms are also returned as an FYI for performance tracking.

Control (D-054): the state clears the ice maker to run, links the ice tank to
the ice mixer, and the water tank to brine separation's recovered water; the
mixer's melt water comes back automatically.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core.config.defaults import ICE_LATENT_HEAT_KJ_KG
from core.domain.control import (
    Commodity,
    ControlSetting,
    ControlSpec,
    ControlVariable,
    Plan,
    SettingKind,
    off_setting,
)
from core.domain.modules import IceStorageParams
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.solver import Flows, NodeStep, StreamSpec

HOURLY_DT_H = 1.0  # the frame is hourly

KEY = "ice_storage"
ICE_MIXER, BRINE_SEP = "ice_mixer", "brine_separation"
CLEARED = "cleared"
# State machine IFs / THENs (docs/control.md, owner's write-up; "ice maker").
CONTROL_SPEC = ControlSpec(
    KEY,
    "Ice storage",
    ifs=(
        ControlVariable("ice_level_pct", "Ice tank level", "%"),
        ControlVariable("water_level_pct", "Ice maker water tank level", "%"),
    ),
    thens=(
        ControlSetting(CLEARED, "Ice maker cleared to run", SettingKind.FLAG),
        ControlSetting(
            "ice_out",
            "Sends ice to {to}",
            SettingKind.LINK,
            commodity=Commodity.ICE,
            ends=(ICE_MIXER,),
        ),
        ControlSetting(
            "water_in",
            "Receives water from {to}",
            SettingKind.LINK,
            commodity=Commodity.WATER,
            receives=True,
            ends=(BRINE_SEP,),
        ),
        off_setting("Ice maker"),
    ),
)


@dataclass(frozen=True)
class IceTankState:
    """Both tanks at one instant (each the same size, in kWh_th of ice)."""

    soc_ice: float  # 1 = the ice tank is full of ice
    soc_water: float  # 1 = the water tank is full of water


@dataclass(frozen=True)
class IceHour:
    """Results of one time step (kW_th and kg/s are averages over the step)."""

    end: IceTankState
    maker_elec_kw: float  # ice maker electrical power
    m_ice_supplied_kg_s: float  # ice handed to the requester
    m_ice_instant_kg_s: float  # of which made this step
    m_water_in_kg_s: float  # water accepted into the water tank
    # FYI (performance tracking): the same flows as duties
    q_instant_kwth: float  # ice grown and taken this step
    q_discharge_kwth: float  # ice taken from storage
    q_charge_kwth: float  # ice put into the ice tank
    q_missed_kwth: float  # requested ice that could not be supplied


def ice_maker_cop(t_amb_c: float, p: IceStorageParams) -> float:
    """COP fit vs ambient, capped at the COP at minimum discharge pressure."""
    fit = p.cop_coeff_a * t_amb_c**2 + p.cop_coeff_b * t_amb_c + p.cop_coeff_c
    return min(p.cop_max, fit)


def ice_maker_capacity_factor(t_amb_c: float, p: IceStorageParams) -> float:
    """Thermal capacity / nameplate vs ambient, capped at its value at minimum
    discharge pressure, and ≥ 0 (the fit goes negative at high ambient)."""
    fit = p.capacity_coeff_a * t_amb_c**2 + p.capacity_coeff_b * t_amb_c + p.capacity_coeff_c
    return max(0.0, min(p.capacity_factor_max, fit))


def ice_step(
    start: IceTankState,
    m_ice_requested_kg_s: float,
    m_water_in_kg_s: float,
    t_amb_c: float,
    cleared_to_run: bool,
    p: IceStorageParams,
    h_f_kj_kg: float = ICE_LATENT_HEAT_KJ_KG,
    dt_h: float = HOURLY_DT_H,
) -> IceHour:
    """One time step of ice making + ice use.

    start: both tanks at the start of the step
    m_ice_requested_kg_s: ice some process asks for
    m_water_in_kg_s: water some process offers back to the water tank
    t_amb_c: heat-rejection ambient (dry bulb if dry cooling, wet bulb if evap) [°C]

    Flows → duties with h_f: Q = m · h_f [kW_th]. Both tanks hold E_tank kWh_th.
    duty    = min(machine, room in ice tank + Q_req, water in tank + Q_water_in)
    Q_water = min(Q_water_in, room in water tank + duty)   (accepted)
    """
    s = start
    e_ice_kwh = p.tank_capacity_kwh
    e_water_kwh = p.tank_capacity_kwh  # same size as the ice tank (owner)
    im_cop = ice_maker_cop(t_amb_c, p)
    im_th_size = ice_maker_capacity_factor(t_amb_c, p)
    q_required_kwth = m_ice_requested_kg_s * h_f_kj_kg
    q_water_offered_kwth = m_water_in_kg_s * h_f_kj_kg

    if cleared_to_run:
        # ice making thermal power in this timestep: limited by the machine, by the
        # room left in the ice tank plus what is taken this step, and by the water
        # in the tank plus what comes in. (Owner's `max` was a typo → min.)
        im_th_duty_kw = min(
            p.ice_maker_kwth * im_th_size,
            (1 - s.soc_ice) * e_ice_kwh / dt_h + q_required_kwth,
            s.soc_water * e_water_kwh / dt_h + q_water_offered_kwth,
        )
        if im_th_duty_kw > 0 and im_cop <= 0:
            raise ValueError("Ice maker COP is zero or negative at this ambient; check the fit")
        im_e_power_kw = im_th_duty_kw / im_cop if im_th_duty_kw > 0 else 0.0
    else:
        im_th_duty_kw = 0.0
        im_e_power_kw = 0.0

    # Water tank: take what fits after the ice maker has drawn its water. If the
    # duty was water-limited the tank ends empty and all offered water is taken,
    # so this closes without iterating.
    q_water_in = min(q_water_offered_kwth, (1 - s.soc_water) * e_water_kwh / dt_h + im_th_duty_kw)
    soc_water_end = (s.soc_water * e_water_kwh + (q_water_in - im_th_duty_kw) * dt_h) / e_water_kwh

    # total ice supplied
    q_ice = min(s.soc_ice * e_ice_kwh / dt_h + im_th_duty_kw, q_required_kwth)
    # kWh in the ice tank at end of timestep
    soc_ice_end = (s.soc_ice * e_ice_kwh + (im_th_duty_kw - q_ice) * dt_h) / e_ice_kwh

    # Ice made this timestep is the first to be used (owner's assumption).
    q_instant = min(im_th_duty_kw, q_ice)  # grown and taken this timestep
    q_discharge = q_ice - q_instant  # taken from storage on top of that
    q_charge = im_th_duty_kw - q_instant  # put into the ice tank
    q_missed = q_required_kwth - q_ice  # not supplied

    return IceHour(
        end=IceTankState(soc_ice=soc_ice_end, soc_water=soc_water_end),
        maker_elec_kw=im_e_power_kw,
        # Unlimited flows come back exactly as given (no kg/s → kW → kg/s round-off).
        m_ice_supplied_kg_s=(
            m_ice_requested_kg_s if q_ice == q_required_kwth else q_ice / h_f_kj_kg
        ),
        m_ice_instant_kg_s=q_instant / h_f_kj_kg,
        m_water_in_kg_s=(
            m_water_in_kg_s if q_water_in == q_water_offered_kwth else q_water_in / h_f_kj_kg
        ),
        q_instant_kwth=q_instant,
        q_discharge_kwth=q_discharge,
        q_charge_kwth=q_charge,
        q_missed_kwth=q_missed,
    )


def initial_state(p: IceStorageParams) -> IceTankState:
    return IceTankState(soc_ice=p.soc_start_frac, soc_water=p.water_soc_start_frac)


@dataclass(frozen=True)
class IceStorage:
    """Solver node (docs/solver.md): ice maker + ice tank + water tank. Answers the
    ice mixer's wants (ice it can give, melt water it has room for) and balances
    on what the mixer used; takes brine separation's recovered water after the
    melt water (the rest drains). With nothing asking, the ice tank fills (when
    cleared to run) and then waits.
    """

    params: IceStorageParams
    name: str = KEY
    control_key: str | None = KEY
    requires: tuple[str, ...] = (col.T_AMBIENT_REJ_C,)
    provides: tuple[str, ...] = (
        col.ICE_INSTANT_KWTH,
        col.ICE_DISCHARGE_KWTH,
        col.ICE_CHARGE_KWTH,
        col.ICE_SOC_FRAC,
        col.ICE_WATER_SOC_FRAC,
        col.ICE_SUPPLIED_KG_S,
        col.ICE_WATER_IN_KG_S,
        col.ICE_MAKER_ELEC_KW,
    )
    reads: tuple[str, ...] = (
        st.ICE_CALL_KG_S,
        st.ICE_USED_KG_S,
        st.MELT_WATER_KG_S,
        st.MELT_WATER_USED_KG_S,
        st.RECOVERED_WATER_KG_S,
    )
    writes: tuple[StreamSpec, ...] = (
        StreamSpec(st.ICE_SUPPLIED_KG_S, answers=st.ICE_CALL_KG_S),
        StreamSpec(st.MELT_WATER_ACCEPTED_KG_S, answers=st.MELT_WATER_KG_S),
        # brine separation doesn't react to it (the rest drains): not sticky
        StreamSpec(st.RECOVERED_WATER_ACCEPTED_KG_S),
        StreamSpec(st.elec("ice_maker")),
    )

    def prepare(self, df: pd.DataFrame) -> np.ndarray:
        return df[col.T_AMBIENT_REJ_C].to_numpy(dtype=float)

    def initial_state(self) -> IceTankState:
        return initial_state(self.params)

    def control_values(self, state: IceTankState) -> dict[str, float]:
        return {"ice_level_pct": state.soc_ice * 100, "water_level_pct": state.soc_water * 100}

    def step(
        self, data: np.ndarray, state: IceTankState, h: int, flows: Flows, plan: Plan
    ) -> NodeStep:
        on = plan.runs(KEY)
        cleared = on and plan.flag(KEY, CLEARED)
        ice = on and plan.link(Commodity.ICE, KEY, ICE_MIXER) is not None
        water = on and plan.link(Commodity.WATER, BRINE_SEP, KEY) is not None
        t_amb = float(data[h])
        call, melt = flows[st.ICE_CALL_KG_S], flows[st.MELT_WATER_KG_S]
        recovered = flows[st.RECOVERED_WATER_KG_S]
        # Answers to the mixer's wants (melt water comes back with the ice).
        p = self.params
        ask = ice_step(state, call or 0.0, melt or 0.0, t_amb, cleared, p) if ice else None
        # The balance: the ice the mixer used, its melt water first, then the
        # recovered water as far as it fits.
        used, melt_used = flows[st.ICE_USED_KG_S], flows[st.MELT_WATER_USED_KG_S]
        if ask is not None:
            can_ice, can_melt = ask.m_ice_supplied_kg_s, ask.m_water_in_kg_s
            ice_kg_s = can_ice if used is None else min(used, can_ice)
            melt_kg_s = can_melt if melt_used is None else min(melt_used, can_melt)
        else:
            ice_kg_s, melt_kg_s = 0.0, 0.0
        rec_kg_s = (recovered or 0.0) if water else 0.0
        hour = ice_step(state, ice_kg_s, melt_kg_s + rec_kg_s, t_amb, cleared, p)
        rec_accepted = max(hour.m_water_in_kg_s - melt_kg_s, 0.0) if rec_kg_s > 0 else 0.0
        if rec_kg_s > 0 and hour.m_water_in_kg_s == melt_kg_s + rec_kg_s:
            rec_accepted = rec_kg_s  # all fits: the offer comes back exactly
        return NodeStep(
            hour.end,
            {  # no answer until asked; off or unlinked: nothing given / taken
                st.ICE_SUPPLIED_KG_S: None
                if call is None
                else (ask.m_ice_supplied_kg_s if ask else 0.0),
                st.MELT_WATER_ACCEPTED_KG_S: None
                if melt is None
                else (ask.m_water_in_kg_s if ask else 0.0),
                st.RECOVERED_WATER_ACCEPTED_KG_S: None if recovered is None else rec_accepted,
                st.elec("ice_maker"): hour.maker_elec_kw,
            },
            {
                col.ICE_SOC_FRAC: hour.end.soc_ice,
                col.ICE_WATER_SOC_FRAC: hour.end.soc_water,
                col.ICE_SUPPLIED_KG_S: hour.m_ice_supplied_kg_s,
                col.ICE_WATER_IN_KG_S: hour.m_water_in_kg_s,
                col.ICE_MAKER_ELEC_KW: hour.maker_elec_kw,
                col.ICE_INSTANT_KWTH: hour.q_instant_kwth,
                col.ICE_DISCHARGE_KWTH: hour.q_discharge_kwth,
                col.ICE_CHARGE_KWTH: hour.q_charge_kwth,
            },
        )
