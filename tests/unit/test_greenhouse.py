"""Greenhouse heating load (docs/models/greenhouse.md, D-061, D-062):
hand-checked physics, a spot check against Purdue's worked example, annual
balances and the data center link."""

import numpy as np
import pandas as pd
import pytest

from core.config.defaults import (
    ASSUMPTIONS,
    GREENHOUSE_INPUTS,
    KBTU_PER_KWH,
    SQFT_TO_M2,
    W_M2K_PER_BTU_HFT2F,
)
from core.control.catalog import ALL_ON
from core.domain.control import (
    DATA_CENTER,
    Action,
    Condition,
    ControlSettings,
    ControlState,
    Operator,
)
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.domain.modules import GreenhouseParams, HotWaterStorageParams, ModuleSettings
from core.domain.site import AreaPolygon
from core.geometry.local_frame import LocalFrame
from core.models.greenhouse import (
    HEAT_IN,
    HWS,
    KEY,
    can_heat,
    greenhouse_load,
    heat_loss_kwth,
    solar_gain_kwth,
)
from core.models.site_model import run_site_model
from core.timeseries import columns as col

ACRE_M2 = 4047.0
C = GREENHOUSE_INPUTS


def square(m2: float, center: tuple[float, float] = (33.45, -112.06)) -> AreaPolygon:
    half = m2**0.5 / 2
    corners = [(-half, -half), (half, -half), (half, half), (-half, half)]
    return AreaPolygon(exterior=tuple(LocalFrame(center).to_latlon(corners)))


def greenhouse(m2: float = ACRE_M2, **changes: float) -> GreenhouseParams:
    return GreenhouseParams(enabled=True, area=(square(m2),), **changes)


def heated(*actions: Action) -> ControlSettings:
    """Default state: the greenhouse takes the data center's heat."""
    link = Action(target=KEY, setting=HEAT_IN, to=DATA_CENTER)
    return ControlSettings(
        default=ControlSettings().default.model_copy(update={"actions": (link, *actions)})
    )


# --- layer 1: hand values ------------------------------------------------------


def test_loss_and_solar_gain() -> None:
    # U = 2 W/m²K, 130 m² of glass, 20 K → 5.2 kW; colder inside than out → negative
    loss = heat_loss_kwth(2.0, 130.0, 20.0, np.array([0.0, 30.0]))
    assert loss == pytest.approx([5.2, -2.6])
    # 90 % of 500 W/m² on 100 m² of floor = 45 kW
    assert solar_gain_kwth(np.array([500.0]), 0.9, 100.0) == pytest.approx([45.0])


def test_balance_gives_demand_or_vented_never_both() -> None:
    t = np.array([-10.0, 5.0, 30.0])
    ghi = np.array([0.0, 800.0, 900.0])
    r = greenhouse_load(t, ghi, 1000.0, greenhouse(1000.0))
    net = r.loss_kwth - r.solar_kwth
    np.testing.assert_allclose(r.demand_kwth - r.vented_kwth, net)
    assert (np.minimum(r.demand_kwth, r.vented_kwth) == 0).all()
    assert r.demand_kwth[0] > 0 and r.vented_kwth[2] > 0
    # cold night: all of it is loss through the covering, A_cover = 1.3 · A_floor:
    # 7.5 W/m²K × 1,300 m² × 30 K = 292.5 kW
    assert r.demand_kwth[0] == pytest.approx(292.5)


def test_more_u_more_setpoint_more_demand() -> None:
    t, ghi = np.array([0.0]), np.array([0.0])
    base = greenhouse_load(t, ghi, ACRE_M2, greenhouse())
    double = greenhouse_load(t, ghi, ACRE_M2, greenhouse(u_w_m2k=10.0))
    warm = greenhouse_load(t, ghi, ACRE_M2, greenhouse(t_set_c=30.0))
    assert double.demand_kwth[0] == pytest.approx(base.demand_kwth[0] * 10 / 7.5)
    assert warm.demand_kwth[0] == pytest.approx(base.demand_kwth[0] * 30 / 20)


@pytest.mark.parametrize(("house", "btu_h"), [("A-frame", 135_878.0), ("Quonset", 170_860.0)])
def test_spot_check_purdue(house: str, btu_h: float) -> None:
    """Purdue CEA, "Calculating greenhouse heating requirements" (owner's spot
    check): Q = U·A·ΔT with U = 0.55 Btu/h·ft²·°F (double polycarbonate),
    66.6 °F inside, 30 °F outside → 135,878 (A-frame) and 170,860 (Quonset)
    Btu/h. The surface areas are in the article's Fig. 1 (an image); the ones
    implied by its results are used, so this checks our formula and units."""
    u_btu, t_in_f, t_out_f = 0.55, 66.6, 30.0
    area_ft2 = btu_h / (u_btu * (t_in_f - t_out_f))  # 6,750 / 8,488 ft²
    q_kw = heat_loss_kwth(
        u_btu * W_M2K_PER_BTU_HFT2F,
        area_ft2 * SQFT_TO_M2,
        (t_in_f - 32) / 1.8,
        np.array([(t_out_f - 32) / 1.8]),
    )
    assert float(q_kw[0]) * KBTU_PER_KWH * 1000 == pytest.approx(btu_h, rel=1e-4)


# --- in the site model ---------------------------------------------------------


@pytest.fixture
def dc() -> DataCenter:
    return DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)


def run(dc: DataCenter, weather: pd.DataFrame, gh: GreenhouseParams, control: ControlSettings):  # type: ignore[no-untyped-def]
    return run_site_model(dc, weather, ASSUMPTIONS, ModuleSettings(greenhouse=gh), control=control)


def test_annual_energy_balance(dc: DataCenter, synthetic_weather: pd.DataFrame) -> None:
    df = run(dc, synthetic_weather, greenhouse(), heated())
    # Σ demand − Σ vented = Σ loss − Σ solar
    lhs = df[col.GREENHOUSE_DEMAND_KWTH].sum() - df[col.GREENHOUSE_VENTED_KWTH].sum()
    rhs = df[col.GREENHOUSE_LOSS_KWTH].sum() - df[col.GREENHOUSE_SOLAR_KWTH].sum()
    assert lhs == pytest.approx(rhs, rel=1e-12)
    # loss = U·A_cover·(T_set − T_amb) every hour
    cover = ACRE_M2 * C.cover_to_floor_ratio
    expected = 7.5 * cover * (20.0 - synthetic_weather[col.TDB_C].to_numpy()) / 1000
    np.testing.assert_allclose(df[col.GREENHOUSE_LOSS_KWTH], expected, rtol=1e-6)


def test_data_center_heats_the_greenhouse(dc: DataCenter, synthetic_weather: pd.DataFrame) -> None:
    """Linked: the greenhouse takes its demand from the data center's heat,
    which leaves the data center's own cooling; nothing is left unmet."""
    base = run_site_model(dc, synthetic_weather, ASSUMPTIONS)
    df = run(dc, synthetic_weather, greenhouse(), heated())
    heat = df[col.GREENHOUSE_HEAT_KWTH]
    assert heat.sum() > 0
    np.testing.assert_allclose(heat, df[col.GREENHOUSE_DEMAND_KWTH])  # 11 MW ≫ 1 acre
    assert (df[col.GREENHOUSE_UNMET_KWTH] == 0).all()
    cooled = df[col.COOLING_FREE_KWTH] + df[col.COOLING_CHILLER_KWTH]
    np.testing.assert_allclose(cooled + heat, df[col.COOLING_TOTAL_KWTH], rtol=1e-9)
    np.testing.assert_allclose(df[col.COOLING_TOTAL_KWTH], base[col.COOLING_TOTAL_KWTH])
    assert df[col.COOLING_ELEC_KW].sum() < base[col.COOLING_ELEC_KW].sum()


def test_not_linked_or_too_cold_return_water_leaves_it_unmet(
    dc: DataCenter, synthetic_weather: pd.DataFrame
) -> None:
    gh = greenhouse()
    off = run(dc, synthetic_weather, gh, ControlSettings())  # Default lists nothing
    assert (off[col.GREENHOUSE_HEAT_KWTH] == 0).all()
    np.testing.assert_allclose(off[col.GREENHOUSE_UNMET_KWTH], off[col.GREENHOUSE_DEMAND_KWTH])
    # setpoint above the return water (25 °C): the data center can't heat it
    cool_return = DataCenter(
        dc_type=DataCenterType(t_supply_c=18, t_return_c=25), it_load_peak_mw=10
    )
    df = run(cool_return, synthetic_weather, greenhouse(t_set_c=30.0), heated())
    assert (df[col.GREENHOUSE_HEAT_KWTH] == 0).all()
    assert df[col.GREENHOUSE_UNMET_KWTH].sum() > 0


def test_only_part_of_a_small_data_center(synthetic_weather: pd.DataFrame) -> None:
    """A 20 acre house on a 0.1 MW data center: it gets all the heat there is,
    the rest is unmet."""
    small = DataCenter(dc_type=DataCenterType(), it_load_peak_mw=0.1)
    df = run(small, synthetic_weather, greenhouse(20 * ACRE_M2), heated())
    short = df[col.GREENHOUSE_UNMET_KWTH] > 0
    assert short.any()
    np.testing.assert_allclose(
        df.loc[short, col.GREENHOUSE_HEAT_KWTH], df.loc[short, col.COOLING_TOTAL_KWTH]
    )


def test_heating_demand_if(dc: DataCenter, synthetic_weather: pd.DataFrame) -> None:
    """The demand is an IF (control.md); with no greenhouse on the site the
    same IF never holds instead of stopping the run (D-061)."""
    needs_heat = Condition(source=KEY, variable="demand_kw", op=Operator.GT, value=0)
    s = ControlSettings(states=(ControlState(id="s1", name="Heat", conditions=(needs_heat,)),))
    df = run(dc, synthetic_weather, greenhouse(), s)
    np.testing.assert_array_equal(df[col.CONTROL_STATE] == 1, df[col.GREENHOUSE_DEMAND_KWTH] > 0)
    without = run_site_model(dc, synthetic_weather, ASSUMPTIONS, control=s)
    assert (without[col.CONTROL_STATE] == 0).all()


def test_run_everything_heats_the_greenhouse_first(
    dc: DataCenter, synthetic_weather: pd.DataFrame
) -> None:
    df = run(dc, synthetic_weather, greenhouse(), ALL_ON)
    np.testing.assert_allclose(df[col.GREENHOUSE_HEAT_KWTH], df[col.GREENHOUSE_DEMAND_KWTH])


# --- heat from hot water storage (D-064) ----------------------------------------


def test_coil_needs_water_10k_above_the_setpoint() -> None:
    assert C.coil_approach_c == 10.0  # as the other air coils (owner)
    assert not can_heat(30.0, 20.0) and can_heat(30.5, 20.0)


def test_return_water_within_the_coil_approach_gives_no_heat(
    synthetic_weather: pd.DataFrame,
) -> None:
    warm = DataCenter(dc_type=DataCenterType(t_supply_c=18, t_return_c=28), it_load_peak_mw=10)
    df = run(warm, synthetic_weather, greenhouse(), heated())  # 28 °C < 20 + 10
    assert (df[col.GREENHOUSE_HEAT_KWTH] == 0).all()


def hws_run(dc: DataCenter, weather: pd.DataFrame, *actions: Action) -> pd.DataFrame:
    modules = ModuleSettings(
        greenhouse=greenhouse(), hot_water_storage=HotWaterStorageParams(enabled=True)
    )
    default = ControlSettings().default.model_copy(update={"actions": actions})
    return run_site_model(
        dc, weather, ASSUMPTIONS, modules, control=ControlSettings(default=default)
    )


CHARGE = Action(target=HWS, setting="heat_in", to=DATA_CENTER)
TO_GH = Action(target=HWS, setting="heat_out", to=KEY)
FROM_HWS = Action(target=KEY, setting=HEAT_IN, to=HWS)
FROM_DC = Action(target=KEY, setting=HEAT_IN, to=DATA_CENTER)


def test_hot_water_storage_heats_the_greenhouse(
    dc: DataCenter, synthetic_weather: pd.DataFrame
) -> None:
    """Storage charges from the data center and gives its hot water to the
    greenhouse coil; the water comes back at setpoint + coil approach + pinch,
    so the cold tank floats below the supply water (owner: let it float)."""
    df = hws_run(dc, synthetic_weather, CHARGE, TO_GH, FROM_HWS)
    from_hws = df[col.GREENHOUSE_HEAT_HWS_KWTH]
    assert from_hws.sum() > 0
    assert (df[col.GREENHOUSE_HEAT_KWTH] == 0).all()  # nothing straight from the data center
    np.testing.assert_allclose(df[col.HWS_DISCHARGE_KWTH], from_hws, atol=1e-6)
    t_back = 20.0 + C.coil_approach_c + 2.0  # setpoint + approach + HX pinch (indirect)
    assert df[col.HWS_T_COLD_C].min() < dc.dc_type.t_supply_c
    assert df[col.HWS_T_COLD_C].min() >= t_back - 1e-9
    # D-065: the stack below the hatched band is the data center's heat, with no
    # negative band (storage's band is its charge); the greenhouse's heat from
    # storage sits on top, above the data center's total
    stack = (
        df[col.COOLING_FREE_KWTH]
        + df[col.COOLING_CHILLER_KWTH]
        + df[col.HWS_STACK_KWTH]
        + df[col.GREENHOUSE_HEAT_KWTH]
    )
    np.testing.assert_allclose(stack, df[col.COOLING_TOTAL_KWTH], rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(df[col.HWS_STACK_KWTH], df[col.HWS_CHARGE_KWTH])
    assert (df[col.HWS_STACK_KWTH] >= 0).all()


def test_sources_are_served_in_then_order(dc: DataCenter, synthetic_weather: pd.DataFrame) -> None:
    """The first linked source covers what it can, the next the rest: storage
    first takes it all; the data center first leaves storage nothing to give."""
    first = hws_run(dc, synthetic_weather, CHARGE, TO_GH, FROM_HWS, FROM_DC)
    np.testing.assert_allclose(
        first[col.GREENHOUSE_HEAT_HWS_KWTH], first[col.GREENHOUSE_DEMAND_KWTH], atol=1e-6
    )
    assert (first[col.GREENHOUSE_HEAT_KWTH] < 1e-6).all()
    # (the data center also serves its own takers in THEN order: greenhouse before storage)
    second = hws_run(dc, synthetic_weather, FROM_DC, CHARGE, TO_GH, FROM_HWS)
    np.testing.assert_allclose(second[col.GREENHOUSE_HEAT_KWTH], second[col.GREENHOUSE_DEMAND_KWTH])
    assert (second[col.GREENHOUSE_HEAT_HWS_KWTH] == 0).all()
    assert (second[col.HWS_DISCHARGE_KWTH] == 0).all()
