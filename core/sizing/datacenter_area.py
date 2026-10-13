"""Facility area from peak IT load (docs/models/sizing.md)."""

import math
from dataclasses import dataclass

from core.config.defaults import SQFT_TO_M2, SizingConstants
from core.domain.datacenter import DataCenter


@dataclass(frozen=True)
class AreaBreakdown:
    data_hall_sqft: float
    backup_power_sqft: float
    chiller_sqft: float

    @property
    def total_sqft(self) -> float:
        return self.data_hall_sqft + self.backup_power_sqft + self.chiller_sqft

    @property
    def total_m2(self) -> float:
        return self.total_sqft * SQFT_TO_M2

    @property
    def square_side_ft(self) -> float:
        return math.sqrt(self.total_sqft)


def data_hall_area_sqft(
    it_peak_kw: float, rack_density_kw: float, white_space_ratio: float, c: SizingConstants
) -> float:
    """A_hall = P / ((slope * rack_density + intercept) * white_space_ratio)."""
    if white_space_ratio < 0.10:
        raise ValueError(f"White space ratio must be at least 10 %, got {white_space_ratio:.0%}")
    ws_density_kw_per_sqft = c.ws_density_slope * rack_density_kw + c.ws_density_intercept
    return it_peak_kw / (ws_density_kw_per_sqft * white_space_ratio)


def backup_power_area_sqft(
    it_peak_kw: float,
    area_factor_sqft_per_kw: float,
    redundancy_x: int,
    redundancy_y: int,
    c: SizingConstants,
) -> float:
    """A_backup = (UPS + gen + switchgear) * P * X * (1 + 0.1 * Y)."""
    return (
        area_factor_sqft_per_kw
        * it_peak_kw
        * redundancy_x
        * (1 + c.redundancy_adder_per_y * redundancy_y)
    )


def size_datacenter(dc: DataCenter, c: SizingConstants) -> AreaBreakdown:
    t = dc.dc_type
    p = dc.it_load_peak_kw
    return AreaBreakdown(
        data_hall_sqft=data_hall_area_sqft(p, t.rack_density_kw, t.white_space_ratio, c),
        backup_power_sqft=backup_power_area_sqft(
            p, t.backup_area_sqft_per_kw, t.redundancy_x, t.redundancy_y, c
        ),
        chiller_sqft=p * c.chiller_area_sqft_per_kw(t.cooling_type),
    )
