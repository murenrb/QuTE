"""State machine (docs/control.md, D-053, D-054): IFs, choosing a state, THENs
as a plan, and the model running under it."""

import numpy as np
import pandas as pd
import pytest

from core.config.defaults import ASSUMPTIONS
from core.control.catalog import ALL_ON, SPECS, controller
from core.control.engine import ControlData, compare, resolve, statistic, warnings
from core.domain.control import (
    COOLANT,
    DATA_CENTER,
    DEFAULT_STATE_ID,
    Action,
    Commodity,
    Condition,
    ControlSettings,
    ControlState,
    Link,
    Operator,
    Reference,
    date_text,
    date_value,
)
from core.domain.datacenter import DataCenter
from core.domain.datacenter_type import DataCenterType
from core.domain.modules import IceStorageParams, ModuleSettings
from core.models.datacenter import IT_LOAD_PCT
from core.models.site_model import run_site_model
from core.timeseries import columns as col
from core.timeseries.frame import year_index


def hour_is(op: Operator, value: float) -> Condition:
    return Condition(source="time", variable="hour", op=op, value=value)


def settings(*states: ControlState) -> ControlSettings:
    return ControlSettings(states=states)


def frame() -> pd.DataFrame:
    """One year of index plus a price that is 0.1 before noon, 0.3 after."""
    idx = year_index()
    price = np.where(idx.hour < 12, 0.1, 0.3)
    return pd.DataFrame({col.ENERGY_PRICE_USD_KWH: price}, index=idx)


def run_states(s: ControlSettings, hours: int = 48, modules: dict | None = None) -> list[str]:
    ctl = controller(s)
    data = ctl.prepare(frame())
    current, out = ctl.initial, []
    for h in range(hours):
        current = ctl.choose(current, data, h, modules or {})
        out.append(current)
    return out


def test_compare_and_statistic() -> None:
    assert compare(1, Operator.LT, 2) and compare(2, Operator.LE, 2)
    assert compare(3, Operator.GT, 2) and compare(2, Operator.GE, 2)
    assert compare(2, Operator.EQ, 2) and compare(1, Operator.NE, 2)
    idx = year_index()
    v = np.where(idx.hour < 12, 0.1, 0.3)
    assert statistic(v, idx, Reference.DAY_MEAN)[0] == pytest.approx(0.2)
    assert statistic(v, idx, Reference.MONTH_MEDIAN)[0] == pytest.approx(0.2)
    assert statistic(v, idx, Reference.YEAR_MEAN)[-1] == pytest.approx(0.2)
    ramp = np.tile(np.arange(24.0), 365)  # 0..23 every day
    assert statistic(ramp, idx, Reference.DAY_Q1)[0] == pytest.approx(5.75)
    assert statistic(ramp, idx, Reference.DAY_Q3)[0] == pytest.approx(17.25)


def test_only_default_without_states() -> None:
    assert set(run_states(ControlSettings())) == {DEFAULT_STATE_ID}


def test_ifs_and_priority() -> None:
    morning = ControlState(id="s1", name="Morning", conditions=(hour_is(Operator.LT, 12),))
    always = ControlState(id="s2", name="Any time", conditions=(hour_is(Operator.GE, 0),))
    states = run_states(settings(morning, always))
    assert states[:12] == ["s1"] * 12 and states[12:24] == ["s2"] * 12
    # reversed priority: the always-true state wins every hour
    assert set(run_states(settings(always, morning))) == {"s2"}


def test_all_ifs_must_hold() -> None:
    window = ControlState(
        id="s1",
        name="10 to 14",
        conditions=(hour_is(Operator.GE, 10), hour_is(Operator.LT, 14)),
    )
    states = run_states(settings(window), hours=24)
    assert [h for h, s in enumerate(states) if s == "s1"] == [10, 11, 12, 13]


def test_price_against_the_days_mean() -> None:
    cheap = ControlState(
        id="s1",
        name="Cheap",
        conditions=(
            Condition(
                source="utility",
                variable="energy_price",
                op=Operator.LT,
                reference=Reference.DAY_MEAN,
            ),
        ),
    )
    states = run_states(settings(cheap), hours=24)
    assert states[:12] == ["s1"] * 12 and states[12:] == [DEFAULT_STATE_ID] * 12


def test_allowed_moves_and_fall_back_to_default() -> None:
    """s1 (morning) may not move to s2 (afternoon): at noon s1 ends, it falls back
    to Default (always allowed), and Default moves on to s2 an hour later."""
    s1 = ControlState(
        id="s1", name="Morning", conditions=(hour_is(Operator.LT, 12),), next_states=()
    )
    s2 = ControlState(id="s2", name="Afternoon", conditions=(hour_is(Operator.GE, 12),))
    states = run_states(settings(s1, s2), hours=24)
    assert states[11] == "s1" and states[12] == DEFAULT_STATE_ID and states[13] == "s2"
    # allowed → it moves straight over
    free = settings(s1.model_copy(update={"next_states": None}), s2)
    assert run_states(free, hours=24)[12] == "s2"


def test_module_ifs_read_start_of_hour_values_and_missing_ones_never_hold() -> None:
    full = Condition(source="ice_storage", variable="ice_level_pct", op=Operator.GE, value=90)
    s = settings(ControlState(id="s1", name="Full", conditions=(full,)))
    ctl = controller(s)
    data: ControlData = ctl.prepare(frame())
    key = ("ice_storage", "ice_level_pct")
    assert ctl.choose(DEFAULT_STATE_ID, data, 0, {key: 95.0}) == "s1"
    assert ctl.choose(DEFAULT_STATE_ID, data, 0, {key: 50.0}) == "default"
    assert ctl.choose(DEFAULT_STATE_ID, data, 0, {}) == DEFAULT_STATE_ID  # not available


def test_date_always_and_planned_load_ifs() -> None:
    summer = ControlState(
        id="s1",
        name="Summer",
        conditions=(
            Condition(source="time", variable="date", op=Operator.GE, value=date_value(6, 1)),
            Condition(source="time", variable="date", op=Operator.LT, value=date_value(9, 1)),
        ),
    )
    idx = year_index()
    ctl = controller(settings(summer))
    data = ctl.prepare(frame())
    chosen = [ctl.choose(DEFAULT_STATE_ID, data, h, {}) for h in range(len(idx))]
    in_summer = (idx.month >= 6) & (idx.month < 9)
    assert all((c == "s1") == bool(x) for c, x in zip(chosen, in_summer, strict=True))
    assert date_text(date_value(6, 1)) == "06-01"
    # Always on / off
    always = Condition(source="time", variable="always", op=Operator.EQ, value=1.0)
    never = Condition(source="time", variable="always", op=Operator.EQ, value=0.0)
    on = ControlState(id="s1", name="On", conditions=(always,))
    off = ControlState(id="s2", name="Off", conditions=(never,))
    assert set(run_states(settings(off, on), hours=5)) == {"s1"}
    # IT load as % of full load: planned 6 MW of a 10 MW peak = 60 %
    half = Condition(source=DATA_CENTER, variable="it_load_pct", op=Operator.LE, value=60)
    ctl = controller(settings(ControlState(id="s1", name="Low", conditions=(half,))), 10_000)
    df = frame().assign(it_load_plan_kw=6_000.0)
    assert ctl.choose(DEFAULT_STATE_ID, ctl.prepare(df), 0, {}) == "s1"
    assert ctl.choose(DEFAULT_STATE_ID, ctl.prepare(df.assign(it_load_plan_kw=7_000.0)), 0, {}) == (
        DEFAULT_STATE_ID
    )


def test_a_state_is_a_complete_description() -> None:
    """D-054: nothing listed = IT at 100 %, every module off; a module runs when
    a THEN names it (at either end of a link) unless it is switched off."""
    empty = resolve((), SPECS)
    assert empty.on == {DATA_CENTER} and empty.links == ()
    assert empty.value(DATA_CENTER, IT_LOAD_PCT, 100.0) == 100.0
    acts = (
        Action(target="power_generation", setting="cooling_in", to="ice_mixer"),
        Action(target="power_generation", setting="heat_in", to="hot_water_storage"),
        Action(target="ice_storage", setting="cleared"),
        # the same link entered at the other end counts once (first position)
        Action(target="hot_water_storage", setting="heat_out", to="power_generation"),
        Action(target="brine_separation", setting="heat_in", value=40, to=DATA_CENTER),
        Action(target="solar_pv", setting="off"),
        Action(target="solar_pv", setting="generate"),  # off wins
        Action(target="ice_storage", setting="gone"),  # no longer exists: ignored
    )
    plan = resolve(acts, SPECS)
    assert plan.on == {
        DATA_CENTER,
        "power_generation",
        "ice_mixer",  # named only as the other end of a link
        "hot_water_storage",
        "ice_storage",
        "brine_separation",
    }
    assert plan.links == (
        Link(Commodity.COOLING, "ice_mixer", "power_generation"),
        Link(Commodity.HEAT, "hot_water_storage", "power_generation"),
        Link(Commodity.HEAT, DATA_CENTER, "brine_separation", 40.0),
    )
    assert plan.flag("ice_storage", "cleared") and not plan.runs("solar_pv")
    # a link to a module that is switched off is dropped
    off = resolve((*acts, Action(target="ice_mixer", setting="off")), SPECS)
    assert off.to("power_generation", Commodity.COOLING) == ()
    coolant = resolve((Action(target="power_generation", setting="cooling_in", to=COOLANT),), SPECS)
    assert coolant.links == (Link(Commodity.COOLING, COOLANT, "power_generation"),)
    assert controller(settings(ControlState(id="s1", name="x"))).columns("s1") == {
        col.CONTROL_STATE: 1.0
    }


def test_warnings_flag_what_will_not_run() -> None:
    s = ControlState(
        id="s1",
        name="x",
        actions=(
            Action(target="power_generation", setting="run_pct", value=50),
            Action(target="ice_mixer", setting="cooling_out", to=DATA_CENTER),
        ),
    )
    msgs = " ".join(warnings(s, SPECS, {DATA_CENTER, "power_generation"}))
    assert "Ice mixer is not on the site" in msgs
    assert "no heat source" in msgs and "no cooling" in msgs
    assert "gets no ice" in msgs


def test_warning_when_a_brine_mixer_gets_no_brine() -> None:
    """A test project: ice to the mixer, the mixer cooling power
    generation, but no brine to a brine mixer, so the whole chain stayed off."""
    mixer_on = (
        Action(target="ice_storage", setting="ice_out", to="ice_mixer"),
        Action(target="ice_mixer", setting="cooling_out", to="power_generation"),
    )
    present = {DATA_CENTER, "ice_storage", "ice_mixer", "power_generation", "brine_separation"}
    s = ControlState(id="s1", name="x", actions=mixer_on)
    assert "gets none" in " ".join(warnings(s, SPECS, present, mixer_on_brine=True))
    assert "gets none" not in " ".join(warnings(s, SPECS, present, mixer_on_brine=False))
    brine = Action(target="brine_separation", setting="brine_out", to="ice_mixer")
    fed = ControlState(id="s1", name="x", actions=(*mixer_on, brine))
    assert "gets none" not in " ".join(warnings(fed, SPECS, present, mixer_on_brine=True))


def test_settings_edits() -> None:
    a = ControlState(id="s1", name="A", next_states=("s2",))
    b = ControlState(id="s2", name="B")
    s = settings(a, b)
    assert s.new_state_id() == "s3"
    gone = s.remove("s2")
    assert [x.id for x in gone.states] == ["s1"] and gone.state("s1").next_states == ()
    assert a.allows(DEFAULT_STATE_ID) and a.allows("s1") and not a.allows("s9")
    with pytest.raises(ValueError):
        settings(a, a)  # duplicate ids
    with pytest.raises(ValueError):
        ControlSettings(
            default=ControlState(id="default", name="D", conditions=(hour_is(Operator.LT, 1),))
        )


def test_catalog_has_every_module_and_the_data_center() -> None:
    for key in ("data_center", *ModuleSettings.model_fields):
        assert SPECS[key].thens, key


# --- the model under the state machine ------------------------------------------------


@pytest.fixture
def dc() -> DataCenter:
    return DataCenter(dc_type=DataCenterType(), it_load_peak_mw=10)


def test_it_load_then_scales_the_planned_load(
    dc: DataCenter, synthetic_weather: pd.DataFrame
) -> None:
    half = ControlState(
        id="s1",
        name="Afternoon half load",
        conditions=(hour_is(Operator.GE, 12),),
        actions=(Action(target="data_center", setting=IT_LOAD_PCT, value=50),),
    )
    df = run_site_model(dc, synthetic_weather, ASSUMPTIONS, control=settings(half))
    pm = df.index.hour >= 12
    np.testing.assert_allclose(df[col.IT_LOAD_KW][pm], 0.5 * df[col.IT_LOAD_PLAN_KW][pm])
    np.testing.assert_allclose(df[col.IT_LOAD_KW][~pm], df[col.IT_LOAD_PLAN_KW][~pm])
    assert (df[col.CONTROL_STATE][pm] == 1).all() and (df[col.CONTROL_STATE][~pm] == 0).all()
    # the rest of the model follows the actual IT load
    np.testing.assert_allclose(
        df[col.IT_PARASITIC_KW], ASSUMPTIONS.it_parasitic_frac * df[col.IT_LOAD_KW]
    )


def test_modules_are_off_in_the_default_state(
    dc: DataCenter, synthetic_weather: pd.DataFrame
) -> None:
    modules = ModuleSettings(ice_storage=IceStorageParams(enabled=True))
    off = run_site_model(dc, synthetic_weather, ASSUMPTIONS, modules)
    assert off[col.ICE_MAKER_ELEC_KW].sum() == 0
    assert (off[col.ICE_SOC_FRAC] == IceStorageParams().soc_start_frac).all()  # just waits
    on = run_site_model(dc, synthetic_weather, ASSUMPTIONS, modules, control=ALL_ON)
    assert on[col.ICE_MAKER_ELEC_KW].sum() > 0


def test_a_state_turns_a_module_on(dc: DataCenter, synthetic_weather: pd.DataFrame) -> None:
    night = ControlState(
        id="s1",
        name="Make ice at night",
        conditions=(hour_is(Operator.LT, 6),),
        actions=(Action(target="ice_storage", setting="cleared"),),
    )
    modules = ModuleSettings(ice_storage=IceStorageParams(enabled=True))
    df = run_site_model(dc, synthetic_weather, ASSUMPTIONS, modules, control=settings(night))
    making = df[col.ICE_MAKER_ELEC_KW] > 0
    assert making.any() and (df.index.hour[making] < 6).all()


def test_project_round_trip_and_old_files_get_default_only() -> None:
    import json

    from core.persistence.project import Project, from_json, to_json

    cheap = Condition(
        source="utility", variable="energy_price", op=Operator.LE, reference=Reference.DAY_MEDIAN
    )
    s = ControlState(
        id="s1",
        name="Cheap power",
        conditions=(cheap,),
        actions=(Action(target="ice_storage", setting="cleared"),),
        next_states=(),
    )
    p = Project(control=settings(s))
    assert from_json(to_json(p)).control == p.control
    old = json.loads(to_json(Project()))
    del old["control"]  # saved before D-053
    assert from_json(json.dumps(old)).control == ControlSettings()


def test_utility_if_compared_with_a_rate_category(dc_10mw, synthetic_weather) -> None:  # type: ignore[no-untyped-def]
    """D-059: 'energy price ≥ the Peak rate' holds exactly in the hours painted
    Peak; a rate category deleted from the tariff never holds."""
    from core.domain.utility import UtilityTariff

    tariff = UtilityTariff()
    afternoon = [(m, h) for m in range(12) for h in range(15, 19)]
    tariff = tariff.painted(afternoon, "peak")
    peak = Condition(
        source="utility",
        variable="energy_price",
        op=Operator.GE,
        reference=Reference.RATE,
        category="peak",
    )
    on_peak = ControlState(id="s1", name="On peak", conditions=(peak,))
    df = run_site_model(
        dc_10mw, synthetic_weather, ASSUMPTIONS, tariff=tariff, control=settings(on_peak)
    )
    in_peak = (df.index.hour >= 15) & (df.index.hour < 19)
    assert (df[col.CONTROL_STATE][in_peak] == 1).all()
    assert (df[col.CONTROL_STATE][~in_peak] == 0).all()
    # the category's demand rate for a demand IF
    ctl = controller(settings(on_peak), tariff=tariff)
    demand = peak.model_copy(update={"variable": "demand_charge"})
    assert ctl.rate(demand) == tariff.category("peak").demand_usd_kw
    # deleted from the tariff: never holds
    gone = controller(settings(on_peak), tariff=tariff.without_category("peak"))
    data = gone.prepare(df)
    assert not any(gone.holds(peak, data, h, {}) for h in range(24))
