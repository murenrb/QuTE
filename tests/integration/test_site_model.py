"""Full pipeline + invariants from docs/models/datacenter-hourly.md."""

import numpy as np
import pandas as pd
import pytest

from core.config.defaults import ASSUMPTIONS, CoolingType
from core.control.catalog import ALL_ON
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.domain.modules import ModuleSettings
from core.models.site_model import run_site_model
from core.timeseries import columns as col


@pytest.fixture(params=[CoolingType.DRY, CoolingType.EVAPORATIVE])
def result(request: pytest.FixtureRequest, synthetic_weather: pd.DataFrame) -> pd.DataFrame:
    t = DataCenterType(cooling_type=request.param)
    return run_site_model(DataCenter(dc_type=t, it_load_peak_mw=10), synthetic_weather, ASSUMPTIONS)


def test_shape_and_no_nan(result: pd.DataFrame) -> None:
    assert len(result) == 8760
    # Every registered column except optional module outputs (no modules enabled here).
    module_columns = {
        col.PV_KW,
        col.ICE_INSTANT_KWTH,
        col.ICE_DISCHARGE_KWTH,
        col.ICE_CHARGE_KWTH,
        col.ICE_SOC_FRAC,
        col.ICE_WATER_SOC_FRAC,
        col.ICE_SUPPLIED_KG_S,
        col.ICE_WATER_IN_KG_S,
        col.ICE_MAKER_ELEC_KW,
        col.ICE_MIX_Q_KWTH,
        col.ICE_MIX_T_C,
        col.ICE_MIX_ICE_KG_S,
        col.ICE_MIX_BRINE_KG_S,
        col.ICE_MIX_BRINE_OUT_KG_S,
        col.ICE_MIX_BRINE_OUT_WT_PCT,
        col.ICE_MIX_WATER_OUT_KG_S,
        col.POWER_GEN_EFF,
        col.POWER_GEN_HEAT_IN_KWTH,
        col.POWER_GEN_REJECT_KWTH,
        col.POWER_GEN_KW,
        col.HWS_CHARGE_KWTH,
        col.HWS_SOC_FRAC,
        col.HWS_T_HOT_C,
        col.HWS_T_COLD_C,
        col.HWS_T_SYS_C,
        col.HWS_DISCHARGE_KWTH,
        col.HWS_NET_KWTH,
        col.HWS_STACK_KWTH,
        col.POWER_GEN_POWER_KWTH,
        col.PV_AVAILABLE_KW,
        col.BRINE_WATER_TO_ICE_KG_S,
        col.BRINE_HEAT_KWTH,
        col.BRINE_MASS_KG,
        col.BRINE_CONC_WT_PCT,
        col.BRINE_SOC_FRAC,
        col.BRINE_WATER_OUT_KG_H,
        col.BRINE_OUT_KG_S,
        col.BRINE_IN_KG_S,
        col.GREENHOUSE_LOSS_KWTH,
        col.GREENHOUSE_SOLAR_KWTH,
        col.GREENHOUSE_DEMAND_KWTH,
        col.GREENHOUSE_VENTED_KWTH,
        col.GREENHOUSE_HEAT_KWTH,
        col.GREENHOUSE_HEAT_HWS_KWTH,
        col.GREENHOUSE_UNMET_KWTH,
    }
    registered = {c.name for c in col.all_columns()} - module_columns
    assert registered <= set(result.columns)
    assert not module_columns & set(result.columns)
    assert np.isfinite(result.to_numpy(dtype=float)).all()


def test_thermal_balance(result: pd.DataFrame) -> None:
    stack = result[col.COOLING_MECH_KWTH] + result[col.COOLING_FREE_KWTH]
    np.testing.assert_allclose(stack, result[col.COOLING_TOTAL_KWTH], rtol=1e-12)
    np.testing.assert_allclose(stack, 1.1 * result[col.IT_LOAD_KW], rtol=1e-12)


def test_exactly_one_cooling_mode_per_hour(result: pd.DataFrame) -> None:
    mech = result[col.COOLING_MECH_KWTH] > 0
    free = result[col.COOLING_FREE_KWTH] > 0
    assert (mech ^ free).all()
    assert mech.any() and free.any()  # synthetic weather crosses the threshold


def test_cop_bounds(result: pd.DataFrame) -> None:
    assert result[col.COP_MECH].between(0, ASSUMPTIONS.cop_max).all()


def test_grid_is_sum_of_electrical_stack(result: pd.DataFrame) -> None:
    expected = result[col.IT_LOAD_KW] + result[col.IT_PARASITIC_KW] + result[col.COOLING_ELEC_KW]
    np.testing.assert_allclose(result[col.GRID_NET_KW], expected, rtol=1e-12)


def test_rejection_ambient_matches_cooling_type(synthetic_weather: pd.DataFrame) -> None:
    for cooling, source in [(CoolingType.DRY, col.TDB_C), (CoolingType.EVAPORATIVE, col.TWB_C)]:
        t = DataCenterType(cooling_type=cooling)
        df = run_site_model(
            DataCenter(dc_type=t, it_load_peak_mw=1), synthetic_weather, ASSUMPTIONS
        )
        np.testing.assert_array_equal(df[col.T_AMBIENT_REJ_C], synthetic_weather[source])


def test_free_cooling_electrical_uses_free_cop(synthetic_weather: pd.DataFrame) -> None:
    t = DataCenterType()
    df = run_site_model(DataCenter(dc_type=t, it_load_peak_mw=10), synthetic_weather, ASSUMPTIONS)
    free = df[df[col.COOLING_FREE_KWTH] > 0]
    np.testing.assert_allclose(free[col.COOLING_ELEC_KW], 11_000 / 50)


def test_return_temp_does_not_change_step1_results(synthetic_weather: pd.DataFrame) -> None:
    run = lambda r: run_site_model(  # noqa: E731
        DataCenter(dc_type=DataCenterType(t_return_c=r), it_load_peak_mw=10),
        synthetic_weather,
        ASSUMPTIONS,
    )
    pd.testing.assert_frame_equal(run(50), run(70))


def test_without_storage_chillers_carry_all_mechanical_demand(result: pd.DataFrame) -> None:
    np.testing.assert_array_equal(result[col.COOLING_CHILLER_KWTH], result[col.COOLING_MECH_KWTH])


@pytest.mark.parametrize("cooling", [CoolingType.DRY, CoolingType.EVAPORATIVE])
def test_ice_storage_full_pipeline(synthetic_weather: pd.DataFrame, cooling: CoolingType) -> None:
    """D-049: nothing requests ice yet, so the ice tank fills from the water tank
    and waits; the chillers carry the whole mechanical demand."""
    from core.domain.modules import IceStorageParams, ModuleContext, ModuleSettings

    dc = DataCenter(dc_type=DataCenterType(cooling_type=cooling), it_load_peak_mw=10)
    base = run_site_model(dc, synthetic_weather, ASSUMPTIONS)
    modules = ModuleSettings(ice_storage=IceStorageParams(enabled=True))
    df = run_site_model(dc, synthetic_weather, ASSUMPTIONS, modules, control=ALL_ON)
    assert np.isfinite(df.to_numpy(dtype=float)).all()
    # the data center is untouched
    for c in (col.COOLING_CHILLER_KWTH, col.COOLING_ELEC_KW):
        np.testing.assert_allclose(df[c], base[c])
    # grid includes the ice maker
    np.testing.assert_allclose(
        df[col.GRID_NET_KW], base[col.GRID_NET_KW] + df[col.ICE_MAKER_ELEC_KW]
    )
    # no ice used, no water in
    assert (df[col.ICE_SUPPLIED_KG_S] == 0).all() and (df[col.ICE_WATER_IN_KG_S] == 0).all()
    assert (df[col.ICE_INSTANT_KWTH] == 0).all() and (df[col.ICE_DISCHARGE_KWTH] == 0).all()
    # defaults (D-058): ice 0, water 1.0 → all the water becomes ice
    assert df[col.ICE_SOC_FRAC].iloc[-1] == pytest.approx(1.0)
    assert df[col.ICE_WATER_SOC_FRAC].iloc[-1] == pytest.approx(0.0)
    assert df[col.ICE_SOC_FRAC].is_monotonic_increasing
    # water frozen = ice made (both tanks hold the same kWh_th): one full tank in all
    np.testing.assert_allclose(df[col.ICE_SOC_FRAC] + df[col.ICE_WATER_SOC_FRAC], 1.0, rtol=1e-9)
    made = df[col.ICE_CHARGE_KWTH].sum()
    p = IceStorageParams(enabled=True).resolved(ModuleContext(it_peak_mw=10))
    assert made == pytest.approx(p.tank_capacity_kwh)
    # then it idles
    assert df[col.ICE_MAKER_ELEC_KW].iloc[-1] == 0 and df[col.ICE_MAKER_ELEC_KW].sum() > 0


def assert_heat_balance(df: pd.DataFrame) -> None:
    """D-054: every kW of data center heat ends up free-cooled, on the chillers,
    in the ice mixer, converted to power, or stored (the stack's storage band)."""
    stack = df[col.COOLING_FREE_KWTH] + df[col.COOLING_CHILLER_KWTH]
    for c in (col.ICE_MIX_Q_KWTH, col.POWER_GEN_POWER_KWTH, col.HWS_STACK_KWTH):
        if c in df.columns:
            stack = stack + df[c]
    np.testing.assert_allclose(stack, df[col.COOLING_TOTAL_KWTH], rtol=1e-6, atol=1e-3)
    np.testing.assert_allclose(df[col.COOLING_TOTAL_KWTH], 1.1 * df[col.IT_LOAD_KW], rtol=1e-12)
    expected = df[col.COOLING_CHILLER_KWTH] / df[col.COP_MECH] + df[col.COOLING_FREE_KWTH] / 50
    np.testing.assert_allclose(df[col.COOLING_ELEC_KW], expected, rtol=1e-9)


def all_modules(fluid: str = "water", **on: bool) -> ModuleSettings:
    from core.config.defaults import IceMixerFluid
    from core.domain.modules import (
        BrineSeparationParams,
        HotWaterStorageParams,
        IceMixerParams,
        IceStorageParams,
        PowerGenerationParams,
    )

    return ModuleSettings(
        ice_storage=IceStorageParams(enabled=on.get("ice_storage", True)),
        ice_mixer=IceMixerParams(enabled=on.get("ice_mixer", True), fluid=IceMixerFluid(fluid)),
        brine_separation=BrineSeparationParams(enabled=on.get("brine_separation", True)),
        hot_water_storage=HotWaterStorageParams(enabled=on.get("hot_water_storage", True)),
        power_generation=PowerGenerationParams(enabled=on.get("power_generation", True)),
    )


@pytest.mark.parametrize("fluid", ["water", "brine"])
def test_ice_mixer_solved_with_ice_storage(synthetic_weather: pd.DataFrame, fluid: str) -> None:
    """D-052, D-054: the solver settles every hour; flows between modules match,
    tanks stay within limits and the mixer's cooling comes off the chillers."""
    from core.domain.brine import rho_brine
    from core.domain.modules import ModuleContext

    dc = DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)
    brine = fluid == "brine"
    modules = all_modules(fluid, brine_separation=brine, power_generation=False)
    df = run_site_model(dc, synthetic_weather, ASSUMPTIONS, modules, control=ALL_ON)
    assert np.isfinite(df.to_numpy(dtype=float)).all()
    # what one module sent is what the other received (to the solver's tolerance)
    np.testing.assert_allclose(df[col.ICE_SUPPLIED_KG_S], df[col.ICE_MIX_ICE_KG_S], atol=1e-5)
    melt_and_recovered = df[col.ICE_MIX_WATER_OUT_KG_S] + (
        df[col.BRINE_WATER_TO_ICE_KG_S] if brine else 0.0
    )
    np.testing.assert_allclose(df[col.ICE_WATER_IN_KG_S], melt_and_recovered, atol=1e-5)
    # the mixer cools the data center's mechanical load; the chillers carry the rest
    np.testing.assert_allclose(
        df[col.COOLING_CHILLER_KWTH] + df[col.ICE_MIX_Q_KWTH], df[col.COOLING_MECH_KWTH], atol=1e-3
    )
    assert_heat_balance(df)
    assert df[col.ICE_MIX_Q_KWTH].sum() > 0
    for c in (col.ICE_SOC_FRAC, col.ICE_WATER_SOC_FRAC):
        assert df[c].between(-1e-6, 1 + 1e-6).all()
    if brine:
        assert (df[col.ICE_MIX_WATER_OUT_KG_S] == 0).all()  # melt water stays in the brine
        np.testing.assert_allclose(df[col.BRINE_OUT_KG_S], df[col.ICE_MIX_BRINE_KG_S], atol=1e-5)
        np.testing.assert_allclose(df[col.BRINE_IN_KG_S], df[col.ICE_MIX_BRINE_OUT_KG_S], atol=1e-5)
        # salt balance across the mixer, every hour (brine leaves the tank at its
        # start-of-hour concentration = the previous hour's end)
        c_start = np.r_[20.0, df[col.BRINE_CONC_WT_PCT].to_numpy()[:-1]]
        salt_in = df[col.ICE_MIX_BRINE_KG_S] * c_start
        salt_out = df[col.ICE_MIX_BRINE_OUT_KG_S] * df[col.ICE_MIX_BRINE_OUT_WT_PCT]
        np.testing.assert_allclose(salt_in, salt_out, rtol=1e-9, atol=1e-6)
        # the brine tank never overfills
        p = modules.brine_separation.resolved(ModuleContext(it_peak_mw=10))
        c = df[col.BRINE_CONC_WT_PCT].to_numpy() / 100
        vol = df[col.BRINE_MASS_KG] / rho_brine(c, p.props)
        assert (vol <= p.tank_volume_m3 * (1 + 1e-9)).all()
        assert df[col.BRINE_OUT_KG_S].sum() > 0
        # the recovered water now refills ice storage's water tank (owner)
        assert df[col.BRINE_WATER_TO_ICE_KG_S].sum() > 0
    else:
        np.testing.assert_allclose(df[col.ICE_MIX_WATER_OUT_KG_S], df[col.ICE_MIX_ICE_KG_S])


def test_ice_mixer_needs_its_suppliers(synthetic_weather: pd.DataFrame) -> None:
    from core.config.defaults import IceMixerFluid
    from core.domain.modules import IceMixerParams, IceStorageParams, ModuleSettings

    dc = DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)
    no_ice = ModuleSettings(ice_mixer=IceMixerParams(enabled=True))
    with pytest.raises(ValueError, match="ice storage"):
        run_site_model(dc, synthetic_weather, ASSUMPTIONS, no_ice)
    no_brine = ModuleSettings(
        ice_storage=IceStorageParams(enabled=True),
        ice_mixer=IceMixerParams(enabled=True, fluid=IceMixerFluid.BRINE),
    )
    with pytest.raises(ValueError, match="brine separation"):
        run_site_model(dc, synthetic_weather, ASSUMPTIONS, no_brine)


@pytest.mark.parametrize("cooling", [CoolingType.DRY, CoolingType.EVAPORATIVE])
def test_power_generation_full_pipeline(
    synthetic_weather: pd.DataFrame, cooling: CoolingType
) -> None:
    """D-045, D-054: on the data center's heat with the supply coolant as its
    cold side; heat taken off the stack reappears 1:1 as generation."""
    from core.domain.modules import ModuleSettings, PowerGenerationParams

    dc = DataCenter(dc_type=DataCenterType(cooling_type=cooling), it_load_peak_mw=10)
    modules = ModuleSettings(power_generation=PowerGenerationParams(enabled=True))
    df = run_site_model(dc, synthetic_weather, ASSUMPTIONS, modules, control=ALL_ON)
    assert np.isfinite(df.to_numpy(dtype=float)).all()
    gen = -df[col.POWER_GEN_KW]
    assert gen.sum() > 0 and (gen >= 0).all()
    assert gen.max() <= 200 + 1e-6  # default rating: 2 % of 10 MW IT
    np.testing.assert_allclose(df[col.POWER_GEN_POWER_KWTH], gen)
    np.testing.assert_allclose(df[col.HEAT_OFFTAKE_KWTH], df[col.POWER_GEN_HEAT_IN_KWTH])
    np.testing.assert_allclose(
        df[col.POWER_GEN_HEAT_IN_KWTH], gen + df[col.POWER_GEN_REJECT_KWTH], rtol=1e-12
    )
    if cooling is CoolingType.DRY:
        assert_heat_balance(df)
    loads = df[col.IT_LOAD_KW] + df[col.IT_PARASITIC_KW] + df[col.COOLING_ELEC_KW]
    np.testing.assert_allclose(df[col.GRID_NET_KW], loads + df[col.POWER_GEN_KW])


def test_power_generation_needs_a_cold_side_and_a_heat_source(
    synthetic_weather: pd.DataFrame,
) -> None:
    from core.domain.control import DATA_CENTER, Action, ControlSettings, ControlState
    from core.domain.modules import ModuleSettings, PowerGenerationParams

    dc = DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)
    modules = ModuleSettings(power_generation=PowerGenerationParams(enabled=True))
    heat_only = ControlSettings(
        default=ControlState(
            id="default",
            name="Default",
            actions=(Action(target="power_generation", setting="heat_in", to=DATA_CENTER),),
        )
    )
    df = run_site_model(dc, synthetic_weather, ASSUMPTIONS, modules, control=heat_only)
    assert (df[col.POWER_GEN_KW] == 0).all()


@pytest.mark.parametrize("with_ice", [False, True])
def test_hot_water_storage_full_pipeline(synthetic_weather: pd.DataFrame, with_ice: bool) -> None:
    """D-046, D-054: receives hot water from the data center (in THEN order) until
    the tanks are full."""
    from core.domain.modules import HotWaterStorageParams, IceStorageParams, ModuleSettings

    dc = DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)
    modules = ModuleSettings(
        hot_water_storage=HotWaterStorageParams(enabled=True),
        ice_storage=IceStorageParams(enabled=with_ice),
    )
    df = run_site_model(dc, synthetic_weather, ASSUMPTIONS, modules, control=ALL_ON)
    assert np.isfinite(df.to_numpy(dtype=float)).all()
    hws = df[col.HWS_CHARGE_KWTH]
    assert (hws >= 0).all() and (hws <= df[col.COOLING_TOTAL_KWTH] + 1e-9).all()
    assert (df[col.HWS_DISCHARGE_KWTH] == 0).all()  # nothing linked to take it
    np.testing.assert_allclose(df[col.HEAT_OFFTAKE_KWTH], hws)
    assert_heat_balance(df)
    # 12 h of IT + 10 % parasitics = 132 MWh sized; indirect uses 8 K of the 10 K
    stored_mwh = hws.sum() / 1000
    assert stored_mwh == pytest.approx(10 * 1.1 * 12 * 0.8, rel=1e-6)
    assert df[col.HWS_SOC_FRAC].iloc[-1] == pytest.approx(1.0)


def test_brine_separation_full_pipeline(synthetic_weather: pd.DataFrame) -> None:
    """D-048, D-054: takes the data center's heat (100 %); its condenser rejects
    the same heat into the supply coolant."""
    from core.domain.modules import BrineSeparationParams, ModuleSettings

    dc = DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)
    base = run_site_model(dc, synthetic_weather, ASSUMPTIONS)
    df = run_site_model(
        dc,
        synthetic_weather,
        ASSUMPTIONS,
        ModuleSettings(brine_separation=BrineSeparationParams(enabled=True)),
        control=ALL_ON,
    )
    assert np.isfinite(df.to_numpy(dtype=float)).all()
    brine = df[col.BRINE_HEAT_KWTH]
    assert brine.sum() > 0
    np.testing.assert_allclose(df[col.HEAT_OFFTAKE_KWTH], brine, atol=1e-6)
    assert_heat_balance(df)
    # 24 h of full heat takes it from 20 to 40 wt%, then it stops
    assert brine.sum() / 1000 == pytest.approx(10 * 1.1 * 24, rel=1e-6)
    assert df[col.BRINE_CONC_WT_PCT].iloc[-1] == pytest.approx(40.0)
    # the condenser heat goes back into the same coolant: cooling is unchanged
    np.testing.assert_allclose(df[col.COOLING_ELEC_KW], base[col.COOLING_ELEC_KW], rtol=1e-9)


@pytest.mark.parametrize("fluid", ["water", "brine"])
def test_routed_states_balance(synthetic_weather: pd.DataFrame, fluid: str) -> None:
    """D-054: a night state charges hot water storage and makes ice; a day state
    runs power generation on stored hot water and condenser steam, cooled by
    the ice mixer, which also cools brine separation's condenser and the data
    center. Every hour settles and every balance closes."""
    from core.domain.control import (
        DATA_CENTER,
        Action,
        Condition,
        ControlSettings,
        ControlState,
        Operator,
    )

    def hour(op: Operator, value: float) -> Condition:
        return Condition(source="time", variable="hour", op=op, value=value)

    night = ControlState(
        id="s1",
        name="Night",
        conditions=(hour(Operator.LT, 6),),
        actions=(
            Action(target="hot_water_storage", setting="heat_in", to=DATA_CENTER),
            Action(target="ice_storage", setting="cleared"),
            Action(target="brine_separation", setting="heat_in", value=50, to=DATA_CENTER),
            Action(target="brine_separation", setting="water_out", to="ice_storage"),
        ),
    )
    day = ControlState(
        id="s2",
        name="Day",
        conditions=(hour(Operator.GE, 10), hour(Operator.LT, 20)),
        actions=(
            Action(target="power_generation", setting="heat_in", to="hot_water_storage"),
            Action(target="power_generation", setting="heat_in", to="brine_separation"),
            Action(target="power_generation", setting="cooling_in", to="ice_mixer"),
            Action(target="power_generation", setting="run_pct", value=80),
            Action(target="brine_separation", setting="heat_in", value=100, to=DATA_CENTER),
            Action(target="brine_separation", setting="brine_out", to="ice_mixer"),
            Action(target="ice_mixer", setting="cooling_out", to="brine_separation"),
            Action(target="ice_mixer", setting="cooling_out", to=DATA_CENTER),
            Action(target="ice_storage", setting="ice_out", to="ice_mixer"),
            Action(target="ice_storage", setting="cleared"),
            Action(target="hot_water_storage", setting="heat_in", to=DATA_CENTER),
            Action(target=DATA_CENTER, setting="it_load_pct", value=90),
        ),
    )
    dc = DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)
    df = run_site_model(
        dc,
        synthetic_weather,
        ASSUMPTIONS,
        all_modules(fluid),
        control=ControlSettings(states=(night, day)),
    )
    assert np.isfinite(df.to_numpy(dtype=float)).all()
    assert_heat_balance(df)
    h = df.index.hour
    assert (df[col.CONTROL_STATE][h < 6] == 1).all()
    assert (df[col.CONTROL_STATE][(h >= 10) & (h < 20)] == 2).all()
    np.testing.assert_allclose(df[col.ICE_SUPPLIED_KG_S], df[col.ICE_MIX_ICE_KG_S], atol=1e-5)
    # stored heat comes back out only in the day state, into power generation
    assert df[col.HWS_DISCHARGE_KWTH].sum() > 0
    assert (df[col.HWS_DISCHARGE_KWTH][(h < 10) | (h >= 20)] == 0).all()
    assert (df[col.HWS_DISCHARGE_KWTH] <= df[col.POWER_GEN_HEAT_IN_KWTH] + 1e-6).all()
    assert (df[col.POWER_GEN_KW][(h < 10) | (h >= 20)] == 0).all()
    assert df[col.POWER_GEN_KW].sum() < 0
    # the ice maker runs only when cleared (night and day states)
    assert (df[col.ICE_MAKER_ELEC_KW][(h >= 6) & (h < 10)] == 0).all()
    for c in (col.ICE_SOC_FRAC, col.ICE_WATER_SOC_FRAC, col.HWS_SOC_FRAC):
        assert df[c].between(-1e-6, 1 + 1e-6).all()


def test_grid_draw_if_reads_the_previous_hour(synthetic_weather: pd.DataFrame) -> None:
    """D-054: "Grid draw (previous hour)" is the net grid load one hour back."""
    from core.domain.control import Condition, ControlSettings, ControlState, Operator

    dc = DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)
    base = run_site_model(dc, synthetic_weather, ASSUMPTIONS)
    threshold = float(base[col.GRID_NET_KW].median())
    high = ControlState(
        id="s1",
        name="High draw",
        conditions=(
            Condition(source="utility", variable="grid_draw_kw", op=Operator.GT, value=threshold),
        ),
    )
    df = run_site_model(dc, synthetic_weather, ASSUMPTIONS, control=ControlSettings(states=(high,)))
    expected = np.r_[False, (df[col.GRID_NET_KW].to_numpy() > threshold)[:-1]]
    np.testing.assert_array_equal(df[col.CONTROL_STATE].to_numpy() == 1, expected)


def test_coolant_column_floats(synthetic_weather: pd.DataFrame) -> None:
    dc = DataCenter(dc_type=DataCenterType(t_supply_min_c=15), it_load_peak_mw=10)
    df = run_site_model(dc, synthetic_weather, ASSUMPTIONS)
    free = df[col.COOLING_FREE_KWTH] > 0
    assert (df.loc[~free, col.T_COOLANT_C] == 40).all()
    assert df.loc[free, col.T_COOLANT_C].between(15, 40).all()
