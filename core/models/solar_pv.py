"""Solar PV module: PVWatts V8 run locally through PySAM (docs/models/solar-pv.md).

Layer 1 (`pvwatts_ac_kw`) takes plain arrays and calls NREL's PVWatts V8 — the
same model as the PVWatts web API, but on our own weather, so each output hour
lines up with the rest of the hourly frame (D-035). Layer 2 (`SolarPV`) is the
pipeline adapter. Generation is written negative (it reduces net grid load).
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import PySAM.Pvwattsv8 as pvwatts

from core.config.defaults import PV_INPUTS, SQFT_TO_M2
from core.domain.control import (
    ControlSetting,
    ControlSpec,
    ControlVariable,
    Plan,
    SettingKind,
    off_setting,
)
from core.domain.modules import SolarPVParams
from core.geometry.areas import area_sqft
from core.timeseries import columns as col
from core.timeseries import streams as st
from core.timeseries.frame import REFERENCE_YEAR
from core.timeseries.solver import Flows, NodeStep, StreamSpec
from core.weather.tmy import WeatherMeta

KEY = "solar_pv"
GENERATE = "generate"
# State machine IFs / THENs (docs/control.md, owner's write-up). The PV output
# IF is what the array can make this hour (whether or not it is curtailed).
CONTROL_SPEC = ControlSpec(
    KEY,
    "Solar PV",
    ifs=(ControlVariable("available_kw", "PV output (available)", "kW"),),
    thens=(
        ControlSetting(GENERATE, "Generates power", SettingKind.FLAG),
        off_setting("PV"),
    ),
)

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
W_PER_KW = 1000.0


def effective_tilt_deg(p: SolarPVParams, site_lat: float | None, fallback_deg: float) -> float:
    """Tilt used for the run: the user's tilt, else |site latitude| (from the map)."""
    if p.tilt_deg is not None:
        return p.tilt_deg
    if site_lat is None:
        return fallback_deg
    return min(90.0, abs(site_lat))


def effective_azimuth_deg(
    p: SolarPVParams, site_lat: float | None, north_deg: float, south_deg: float
) -> float:
    """Azimuth used for the run: the user's azimuth, else equator-facing for the
    site's hemisphere (north_deg for lat ≥ 0, south_deg for lat < 0)."""
    if p.azimuth_deg is not None:
        return p.azimuth_deg
    if site_lat is not None and site_lat < 0:
        return south_deg
    return north_deg


def resolve_orientation(p: SolarPVParams, site_lat: float | None) -> SolarPVParams:
    """Params with tilt and azimuth filled in from the site (D-038, D-039)."""
    i = PV_INPUTS
    return p.model_copy(
        update={
            "tilt_deg": effective_tilt_deg(p, site_lat, i.tilt_deg.default),
            "azimuth_deg": effective_azimuth_deg(
                p, site_lat, i.azimuth_deg.default, i.azimuth_southern_hemisphere_deg
            ),
        }
    )


def pv_capacity_kw(p: SolarPVParams, roof_m2: float = 0.0) -> float:
    """DC nameplate [kW] = (snapped area + data center roof if covered) [sqft]
    × power density [W/sqft] / 1000 (D-036, D-073). roof_m2: data center block area."""
    sqft = area_sqft(p.area) + (roof_m2 / SQFT_TO_M2 if p.cover_data_center else 0.0)
    return sqft * p.power_density_w_sqft / W_PER_KW


@dataclass(frozen=True)
class PvSite:
    """Where the weather applies: the NSRDB cell, in local standard time."""

    lat: float
    lon: float
    utc_offset_h: float
    elevation_m: float
    data_minute: int  # minute past the hour each weather value is stamped at

    @classmethod
    def from_weather(cls, meta: WeatherMeta) -> "PvSite":
        return cls(meta.lat, meta.lon, meta.utc_offset_h, meta.elevation_m, meta.data_minute)


def pvwatts_ac_kw(
    month: IntArray,
    day: IntArray,
    hour: IntArray,
    dni_w_m2: FloatArray,
    dhi_w_m2: FloatArray,
    ghi_w_m2: FloatArray,
    tdb_c: FloatArray,
    wind_m_s: FloatArray,
    site: PvSite,
    p: SolarPVParams,
    capacity_kw: float,
) -> FloatArray:
    """Hourly AC output [kW, ≥ 0 by day] from PVWatts V8.

    Row i is the hour starting at hour[i]; the weather values are stamped at
    hour[i]:site.data_minute, which PVWatts uses for the sun position.
    """
    n = len(month)
    model = pvwatts.new()
    model.SolarResource.solar_resource_data = {
        "lat": site.lat,
        "lon": site.lon,
        "tz": site.utc_offset_h,
        "elev": site.elevation_m,
        "year": [REFERENCE_YEAR] * n,
        "month": [int(v) for v in month],
        "day": [int(v) for v in day],
        "hour": [int(v) for v in hour],
        "minute": [site.data_minute] * n,
        "dn": [float(v) for v in dni_w_m2],
        "df": [float(v) for v in dhi_w_m2],
        "gh": [float(v) for v in ghi_w_m2],
        "tdry": [float(v) for v in tdb_c],
        "wspd": [float(v) for v in wind_m_s],
    }
    design = model.SystemDesign
    design.system_capacity = capacity_kw
    design.array_type = int(p.array_type)
    design.module_type = int(p.module_type)
    if p.tilt_deg is None or p.azimuth_deg is None:
        raise ValueError("Resolve tilt/azimuth first (resolve_orientation)")
    design.tilt = p.tilt_deg
    design.azimuth = p.azimuth_deg
    design.losses = p.losses_pct
    design.dc_ac_ratio = p.dc_ac_ratio
    design.gcr = p.gcr
    design.inv_eff = p.inv_eff_pct
    model.execute(0)
    ac_w = np.asarray(model.Outputs.ac, dtype=float)
    if ac_w.shape != (n,):
        raise ValueError(f"PVWatts returned {ac_w.shape[0]} values for {n} hours")
    return ac_w / W_PER_KW


@dataclass(frozen=True)
class SolarPV:
    """What the array can make each hour (`pv_available_kw`, ≥ 0); the
    `PvOutput` node applies the state's THEN."""

    params: SolarPVParams
    site: PvSite
    site_lat: float | None = None  # map location; default tilt/azimuth follow it
    roof_m2: float = 0.0  # data center block area (used when cover_data_center)
    name: str = "solar_pv"
    requires: tuple[str, ...] = (
        col.GHI_W_M2,
        col.DNI_W_M2,
        col.DHI_W_M2,
        col.TDB_C,
        col.WIND_M_S,
    )
    provides: tuple[str, ...] = (col.PV_AVAILABLE_KW,)

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        params = resolve_orientation(self.params, self.site_lat)
        idx = pd.DatetimeIndex(df.index)
        ac_kw = pvwatts_ac_kw(
            idx.month.to_numpy(),
            idx.day.to_numpy(),
            idx.hour.to_numpy(),
            df[col.DNI_W_M2].to_numpy(dtype=float),
            df[col.DHI_W_M2].to_numpy(dtype=float),
            df[col.GHI_W_M2].to_numpy(dtype=float),
            df[col.TDB_C].to_numpy(dtype=float),
            df[col.WIND_M_S].to_numpy(dtype=float),
            self.site,
            params,
            pv_capacity_kw(params, self.roof_m2),
        )
        return df.assign(**{col.PV_AVAILABLE_KW: ac_kw})


@dataclass(frozen=True)
class PvOutput:
    """Solver node: PV generation = what is available when the state says
    "Generates power", else curtailed (0)."""

    name: str = "pv_output"
    control_key: str | None = None  # its IF is the available column
    requires: tuple[str, ...] = (col.PV_AVAILABLE_KW,)
    provides: tuple[str, ...] = (col.PV_KW,)
    reads: tuple[str, ...] = ()
    writes: tuple[StreamSpec, ...] = (StreamSpec(st.elec("pv")),)

    def prepare(self, df: pd.DataFrame) -> npt.NDArray[np.float64]:
        return df[col.PV_AVAILABLE_KW].to_numpy(dtype=float)

    def initial_state(self) -> Any:
        return None

    def step(
        self, data: npt.NDArray[np.float64], state: Any, h: int, flows: Flows, plan: Plan
    ) -> NodeStep:
        on = plan.runs(KEY) and plan.flag(KEY, GENERATE)
        pv = -float(data[h]) if on else 0.0  # generation is negative
        return NodeStep(None, {st.elec("pv"): pv}, {col.PV_KW: pv})
