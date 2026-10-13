"""Greenhouse module: heating demand from the covering's U-value
(docs/models/greenhouse.md, D-061, D-062).

Steady state each hour (no thermal mass, owner). The covering's overall U
(an input, from an extension guide's table) carries the heat from the inside
air at the setpoint to the outside air; the sun comes in through the glass:

    Q_loss  = U · A_cover · (T_set − T_amb)       heat lost through the covering
    Q_solar = τ · GHI · A_floor                   sun through the glass
    Q_net   = Q_loss − Q_solar
    demand  = max(Q_net, 0)                       heat it needs
    vented  = max(−Q_net, 0)                      surplus, vented (goes nowhere)

    A_cover = A_floor · cover/floor (1.3: roof + walls)

Layer 1 is plain numpy (works on one hour or all 8760). Layer 2 is in two
parts, like solar PV: `GreenhouseLoad` (before the solver; weather only)
writes the demand, so the state machine can test it, and the
`GreenhouseHeating` solver node takes heat from the data center's return
water and / or hot water storage when the state links them (sources in THEN
order; D-064). The heat goes through a water → air coil: a source gives heat
only if its water is warmer than setpoint + coil approach (10 K), and hot water
storage cools its water to that temperature before taking it back. What the
sources don't cover is `greenhouse_unmet_kwth` (a boiler's job).
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from core.config.defaults import GREENHOUSE_INPUTS, GreenhouseInputs
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
from core.domain.modules import GreenhouseParams
from core.geometry.areas import area_m2
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.solver import Flows, NodeStep, StreamSpec

FloatArray = npt.NDArray[np.float64]
W_PER_KW = 1000.0

KEY = "greenhouse"
HEAT_IN = "heat_in"
HWS = "hot_water_storage"
SOURCES = (DATA_CENTER, HWS)  # "Takes heat from", served in THEN order
# State machine IFs / THENs (docs/control.md). The demand IF is the hour's
# heating demand from the weather (before any heat is given).
CONTROL_SPEC = ControlSpec(
    KEY,
    "Greenhouse",
    ifs=(ControlVariable("demand_kw", "Heating demand", "kW_th"),),
    thens=(
        ControlSetting(
            HEAT_IN,
            "Takes heat from {to}",
            SettingKind.LINK,
            commodity=Commodity.HEAT,
            receives=True,
            ends=SOURCES,
        ),
        off_setting("Greenhouse heating"),
    ),
)


# --- layer 1: physics -------------------------------------------------------


def heat_loss_kwth(
    u_w_m2k: float, cover_m2: float, t_set_c: float, t_amb_c: FloatArray
) -> FloatArray:
    """Q_loss = U·A_cover·(T_set − T_amb) / 1000; negative when it is warmer outside."""
    return u_w_m2k * cover_m2 * (t_set_c - t_amb_c) / W_PER_KW


def solar_gain_kwth(ghi_w_m2: FloatArray, transmissivity: float, floor_m2: float) -> FloatArray:
    """Q_solar = τ·GHI·A_floor / 1000 (the sun on the house's horizontal footprint)."""
    return transmissivity * ghi_w_m2 * floor_m2 / W_PER_KW


@dataclass(frozen=True)
class GreenhouseLoadResult:
    """Hourly results (arrays, kW_th ≥ 0 unless noted)."""

    loss_kwth: FloatArray  # through the covering; < 0 when warmer outside than the setpoint
    solar_kwth: FloatArray
    demand_kwth: FloatArray  # heat needed to hold the setpoint
    vented_kwth: FloatArray  # surplus, vented


def greenhouse_load(
    t_amb_c: FloatArray,
    ghi_w_m2: FloatArray,
    floor_m2: float,
    p: GreenhouseParams,
    c: GreenhouseInputs = GREENHOUSE_INPUTS,
) -> GreenhouseLoadResult:
    """Heat balance of the greenhouse air at the setpoint, every hour.

    A_cover = A_floor · cover/floor.
    Q_net = Q_loss − Q_solar → demand = max(Q_net, 0), vented = max(−Q_net, 0).
    """
    cover_m2 = floor_m2 * c.cover_to_floor_ratio
    loss = heat_loss_kwth(p.u_w_m2k, cover_m2, p.t_set_c, t_amb_c)
    solar = solar_gain_kwth(ghi_w_m2, p.transmissivity, floor_m2)
    net = loss - solar
    return GreenhouseLoadResult(
        loss_kwth=loss,
        solar_kwth=solar,
        demand_kwth=np.maximum(net, 0.0),
        vented_kwth=np.maximum(-net, 0.0),
    )


# --- layer 2: pipeline / solver ------------------------------------------------


@dataclass(frozen=True)
class GreenhouseLoad:
    """Heating demand from the weather (before the solver; no state)."""

    params: GreenhouseParams
    name: str = "greenhouse_load"
    requires: tuple[str, ...] = (col.TDB_C, col.GHI_W_M2)
    provides: tuple[str, ...] = (
        col.GREENHOUSE_LOSS_KWTH,
        col.GREENHOUSE_SOLAR_KWTH,
        col.GREENHOUSE_DEMAND_KWTH,
        col.GREENHOUSE_VENTED_KWTH,
    )

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        r = greenhouse_load(
            df[col.TDB_C].to_numpy(dtype=float),
            df[col.GHI_W_M2].to_numpy(dtype=float),
            area_m2(self.params.area),
            self.params,
        )
        return df.assign(
            **{
                col.GREENHOUSE_LOSS_KWTH: r.loss_kwth,
                col.GREENHOUSE_SOLAR_KWTH: r.solar_kwth,
                col.GREENHOUSE_DEMAND_KWTH: r.demand_kwth,
                col.GREENHOUSE_VENTED_KWTH: r.vented_kwth,
            }
        )


def coil_water_c(t_set_c: float, c: GreenhouseInputs = GREENHOUSE_INPUTS) -> float:
    """Coldest the heating water can leave the coil: setpoint + coil approach."""
    return t_set_c + c.coil_approach_c


def can_heat(t_water_c: float, t_set_c: float, c: GreenhouseInputs = GREENHOUSE_INPUTS) -> bool:
    """Water heats the air through the coil only if it is warmer than
    setpoint + coil approach."""
    return t_water_c > coil_water_c(t_set_c, c)


@dataclass(frozen=True)
class GreenhouseHeating:
    """Solver node: asks its linked sources ("Takes heat from …"), in THEN
    order, for what of the hour's demand is still open, each only if its water
    is warm enough for the coil; the rest of the demand is unmet."""

    t_set_c: float
    t_return_c: float  # data center return (warm) water
    name: str = KEY
    control_key: str | None = None  # its IF is the demand column
    requires: tuple[str, ...] = (col.GREENHOUSE_DEMAND_KWTH,)
    provides: tuple[str, ...] = (
        col.GREENHOUSE_HEAT_KWTH,
        col.GREENHOUSE_HEAT_HWS_KWTH,
        col.GREENHOUSE_UNMET_KWTH,
    )
    reads: tuple[str, ...] = (*(st.heat_sent(k, KEY) for k in SOURCES), st.HWS_T_HOT_C)
    writes: tuple[StreamSpec, ...] = (
        *(StreamSpec(st.heat_req(k, KEY)) for k in SOURCES),
        *(StreamSpec(st.heat_used(k, KEY)) for k in SOURCES),
    )

    def _t_water(self, source: str, flows: Flows) -> float | None:
        """Water temperature the source delivers (None = not known yet)."""
        return self.t_return_c if source == DATA_CENTER else flows[st.HWS_T_HOT_C]

    def prepare(self, df: pd.DataFrame) -> FloatArray:
        return df[col.GREENHOUSE_DEMAND_KWTH].to_numpy(dtype=float)

    def initial_state(self) -> Any:
        return None

    def step(self, data: FloatArray, state: Any, h: int, flows: Flows, plan: Plan) -> NodeStep:
        demand = float(data[h])
        left = demand
        flows_out: dict[str, float | None] = {}
        got: dict[str, float] = {}
        for link in plan.to(KEY, Commodity.HEAT) if plan.runs(KEY) else ():
            k = link.sender
            t = self._t_water(k, flows)
            want = left if t is None or can_heat(t, self.t_set_c) else 0.0  # unknown: ask
            sent = flows[st.heat_sent(k, KEY)]
            got[k] = want if sent is None else min(want, sent)  # unanswered: assume given
            flows_out[st.heat_req(k, KEY)] = want
            flows_out[st.heat_used(k, KEY)] = got[k]
            left -= got[k]
        for k in SOURCES:  # not linked: no answer
            flows_out.setdefault(st.heat_req(k, KEY), None)
            flows_out.setdefault(st.heat_used(k, KEY), None)
        return NodeStep(
            None,
            flows_out,
            {
                col.GREENHOUSE_HEAT_KWTH: got.get(DATA_CENTER, 0.0),
                col.GREENHOUSE_HEAT_HWS_KWTH: got.get(HWS, 0.0),
                col.GREENHOUSE_UNMET_KWTH: left,
            },
        )
