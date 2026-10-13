"""Output metrics (docs/workflow/02-results.md → Output metrics).

Step 1 set plus one line per enabled module (e.g. annual PV generation);
PUE and parcel utilization wait on open-questions.md Q1.
"""

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from core.config.defaults import GAL_PER_KG_WATER, HOURS_PER_YEAR, KW_PER_MW
from core.timeseries import columns as col
from core.weather.tmy import WeatherMeta


@dataclass(frozen=True)
class Metric:
    label: str
    value: str


def output_metrics(df: pd.DataFrame, weather: WeatherMeta) -> list[Metric]:
    def mwh(c: str) -> str:
        return f"{float(df[c].sum()) / KW_PER_MW:,.0f} MWh/yr"

    free_h = int((df[col.COOLING_FREE_KWTH] > 0).sum())
    module_metrics = []
    if col.UTILITY_COST_USD in df.columns:
        energy = float(df[col.ENERGY_COST_USD].sum())
        demand = float(df[col.DEMAND_COST_USD].sum())
        imported_mwh = float(df[col.GRID_NET_KW].clip(lower=0).sum()) / KW_PER_MW
        module_metrics += [
            Metric("Annual utility cost", f"${energy + demand:,.0f}/yr"),
            # One "$" per value: Streamlit renders text between two "$" as maths.
            Metric("Annual energy cost", f"${energy:,.0f}/yr"),
            Metric("Annual demand charges", f"${demand:,.0f}/yr"),
            Metric(
                "Average utility cost",
                f"${(energy + demand) / imported_mwh:,.2f}/MWh" if imported_mwh > 0 else "—",
            ),
        ]
    if col.PV_KW in df.columns:  # generation is stored negative
        pv_mwh = -float(df[col.PV_KW].sum()) / KW_PER_MW
        module_metrics.append(Metric("Annual PV generation", f"{pv_mwh:,.0f} MWh/yr"))
    if col.ICE_MAKER_ELEC_KW in df.columns:
        ice_mwh = float((df[col.ICE_INSTANT_KWTH] + df[col.ICE_DISCHARGE_KWTH]).sum()) / KW_PER_MW
        module_metrics.append(Metric("Annual cooling from ice", f"{ice_mwh:,.0f} MWh_th/yr"))
        maker_mwh = float(df[col.ICE_MAKER_ELEC_KW].sum()) / KW_PER_MW
        module_metrics.append(Metric("Annual ice maker electricity", f"{maker_mwh:,.0f} MWh/yr"))
    if col.HWS_CHARGE_KWTH in df.columns:
        stored = float(df[col.HWS_CHARGE_KWTH].sum()) / KW_PER_MW
        module_metrics.append(Metric("Heat into hot water storage", f"{stored:,.0f} MWh_th/yr"))
    if col.BRINE_HEAT_KWTH in df.columns:
        heat = float(df[col.BRINE_HEAT_KWTH].sum()) / KW_PER_MW
        water_gal = float(df[col.BRINE_WATER_OUT_KG_H].sum()) * GAL_PER_KG_WATER
        module_metrics += [
            Metric("Heat into brine separation", f"{heat:,.0f} MWh_th/yr"),
            Metric("Water recovered from brine", f"{water_gal:,.0f} gal/yr"),
            Metric(
                "Final brine concentration", f"{float(df[col.BRINE_CONC_WT_PCT].iloc[-1]):.1f} wt%"
            ),
        ]
    if col.POWER_GEN_KW in df.columns:  # generation is stored negative
        gen = -df[col.POWER_GEN_KW]
        module_metrics.append(
            Metric("Annual power generation", f"{float(gen.sum()) / KW_PER_MW:,.0f} MWh/yr")
        )
        run_h = int((gen > 0).sum())
        module_metrics.append(Metric("Power generation hours", f"{run_h:,} h"))
    return [
        Metric("Annual IT energy", mwh(col.IT_LOAD_KW)),
        Metric("Annual cooling electricity", mwh(col.COOLING_ELEC_KW)),
        Metric("Annual grid energy", mwh(col.GRID_NET_KW)),
        Metric("Peak grid load", f"{float(df[col.GRID_NET_KW].max()) / KW_PER_MW:,.2f} MW"),
        Metric("Free-cooling hours", f"{free_h:,} h ({free_h / HOURS_PER_YEAR:.0%})"),
        *module_metrics,
        Metric(
            "Weather",
            f"{weather.source} · {weather.lat:.2f}, {weather.lon:.2f} · "
            f"UTC{weather.utc_offset_h:+g}",
        ),
    ]


def render_metrics(metrics: list[Metric], per_row: int = 3) -> None:
    for row in range(0, len(metrics), per_row):
        cols = st.columns(per_row)
        for c, m in zip(cols, metrics[row : row + per_row], strict=False):
            with c, st.container(border=True):
                st.metric(m.label, m.value)
