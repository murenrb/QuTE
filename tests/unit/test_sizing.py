"""Worked example and edge cases from docs/models/sizing.md."""

import pytest

from core.config.defaults import SIZING, CoolingType
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.sizing.datacenter_area import data_hall_area_sqft, size_datacenter


def test_worked_example_10mw_dry(dc_10mw: DataCenter) -> None:
    a = size_datacenter(dc_10mw, SIZING)
    assert a.data_hall_sqft == pytest.approx(29_495.04, abs=0.01)
    assert a.backup_power_sqft == pytest.approx(33_000)
    assert a.chiller_sqft == pytest.approx(4_000)
    assert a.total_sqft == pytest.approx(66_495.04, abs=0.01)
    assert a.square_side_ft == pytest.approx(257.87, abs=0.01)
    assert a.total_m2 == pytest.approx(a.total_sqft * 0.09290304, rel=1e-12)


def test_evaporative_chiller_area() -> None:
    t = DataCenterType(cooling_type=CoolingType.EVAPORATIVE)
    a = size_datacenter(DataCenter(dc_type=t, it_load_peak_mw=10), SIZING)
    assert a.chiller_sqft == pytest.approx(2_000)


@pytest.mark.parametrize(
    ("x", "y", "factor"), [(1, 1, 1.1), (1, 2, 1.2), (2, 1, 2.2), (3, 10, 6.0)]
)
def test_redundancy(x: int, y: int, factor: float) -> None:
    t = DataCenterType(redundancy_x=x, redundancy_y=y)
    a = size_datacenter(DataCenter(dc_type=t, it_load_peak_mw=10), SIZING)
    assert a.backup_power_sqft == pytest.approx(3.0 * 10_000 * factor)


def test_white_space_below_minimum_rejected() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        data_hall_area_sqft(10_000, 50, 0.05, SIZING)


def test_area_scales_linearly_with_it_load(dc_type: DataCenterType) -> None:
    a1 = size_datacenter(DataCenter(dc_type=dc_type, it_load_peak_mw=1), SIZING)
    a10 = size_datacenter(DataCenter(dc_type=dc_type, it_load_peak_mw=10), SIZING)
    assert a10.total_sqft == pytest.approx(10 * a1.total_sqft)
