"""Utility cost: hourly energy price and energy cost, monthly demand charge
(docs/models/utility.md, D-043).

Billed load = net grid load `grid_net_kw` (all loads and generation of every
module). Energy cost = price × net load (negative when exporting: credited at
the hour's energy price). Demand charge: every hour has a *potential* demand
cost = max(net load, 0) × that hour's demand charge; only the month's highest
potential is billed, in its hour.
"""

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
import pandas as pd

from core.config.defaults import HOURS_PER_DAY, MONTHS_PER_YEAR
from core.domain.utility import UtilityTariff, WeekendPricing
from core.timeseries import columns as col

FloatArray = npt.NDArray[np.float64]
WEEKEND_DAYS = (5, 6)  # Saturday, Sunday (pandas dayofweek)


def rate_tables(tariff: UtilityTariff) -> tuple[FloatArray, FloatArray]:
    """12 × 24 tables of energy $/kWh and demand $/kW from the painted schedule."""
    energy = np.empty((MONTHS_PER_YEAR, HOURS_PER_DAY))
    demand = np.empty((MONTHS_PER_YEAR, HOURS_PER_DAY))
    for m, row in enumerate(tariff.schedule):
        for h, cid in enumerate(row):
            c = tariff.category(cid)
            energy[m, h], demand[m, h] = c.energy_usd_kwh, c.demand_usd_kw
    return energy, demand


def hourly_rates(tariff: UtilityTariff, index: pd.DatetimeIndex) -> tuple[FloatArray, FloatArray]:
    """Energy price and demand charge for every hour of the frame."""
    energy_tab, demand_tab = rate_tables(tariff)
    months = index.month.to_numpy() - 1
    hours = index.hour.to_numpy()
    energy = energy_tab[months, hours]
    demand = demand_tab[months, hours]
    if tariff.weekend is WeekendPricing.OFF_PEAK:
        weekend = np.isin(index.dayofweek.to_numpy(), WEEKEND_DAYS)
        cheap = tariff.cheapest
        energy = np.where(weekend, cheap.energy_usd_kwh, energy)
        demand = np.where(weekend, cheap.demand_usd_kw, demand)
    return energy.astype(float), demand.astype(float)


def monthly_peak_only(potential: FloatArray, months: npt.NDArray[np.int64]) -> FloatArray:
    """Keep each month's largest value (first hour on ties), zero elsewhere."""
    out = np.zeros_like(potential)
    for m in np.unique(months):
        idx = np.flatnonzero(months == m)
        top = idx[int(np.argmax(potential[idx]))]
        out[top] = max(potential[top], 0.0)
    return out


@dataclass(frozen=True)
class UtilityPrice:
    """The hour's energy price and demand charge — known before the model runs,
    so the state machine can test them (D-053)."""

    tariff: UtilityTariff
    name: str = "utility_price"
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = (col.ENERGY_PRICE_USD_KWH, col.DEMAND_CHARGE_USD_KW)

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        price, charge = hourly_rates(self.tariff, pd.DatetimeIndex(df.index))
        return df.assign(**{col.ENERGY_PRICE_USD_KWH: price, col.DEMAND_CHARGE_USD_KW: charge})


@dataclass(frozen=True)
class UtilityCost:
    """Bills the net grid load at the hour's prices (from `UtilityPrice`)."""

    name: str = "utility_cost"
    requires: tuple[str, ...] = (
        col.GRID_NET_KW,
        col.ENERGY_PRICE_USD_KWH,
        col.DEMAND_CHARGE_USD_KW,
    )
    provides: tuple[str, ...] = field(
        default=(
            col.ENERGY_COST_USD,
            col.DEMAND_COST_POTENTIAL_USD,
            col.DEMAND_COST_USD,
            col.UTILITY_COST_USD,
            col.CUM_ENERGY_COST_USD,
            col.CUM_DEMAND_COST_USD,
            col.CUM_UTILITY_COST_USD,
        )
    )

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        index = pd.DatetimeIndex(df.index)
        net_kw = df[col.GRID_NET_KW].to_numpy(dtype=float)
        price = df[col.ENERGY_PRICE_USD_KWH].to_numpy(dtype=float)
        charge = df[col.DEMAND_CHARGE_USD_KW].to_numpy(dtype=float)
        energy_cost = price * net_kw  # 1 h steps: kW → kWh; negative = export credit
        potential = np.maximum(net_kw, 0.0) * charge
        demand_cost = monthly_peak_only(potential, index.month.to_numpy())
        return df.assign(
            **{
                col.ENERGY_COST_USD: energy_cost,
                col.DEMAND_COST_POTENTIAL_USD: potential,
                col.DEMAND_COST_USD: demand_cost,
                col.UTILITY_COST_USD: energy_cost + demand_cost,
                # Running sums through the year (D-044)
                col.CUM_ENERGY_COST_USD: np.cumsum(energy_cost),
                col.CUM_DEMAND_COST_USD: np.cumsum(demand_cost),
                col.CUM_UTILITY_COST_USD: np.cumsum(energy_cost + demand_cost),
            }
        )
