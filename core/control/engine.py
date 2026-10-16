"""State machine engine (docs/control.md, D-053, D-054).

Each hour, before the hour is solved:
1. Read every IF: ambient, utility, time and the planned IT load from the
   hourly columns; module values (and the grid draw) from their state at the
   start of the hour.
2. Candidates = the current state (if its IFs still hold) and the states it may
   move to whose IFs all hold. The first in priority order wins (the user's
   order); if none, the Default state.
3. The state's THENs become its `Plan` (every state is a complete description).

The state is fixed for the hour, so the solver never iterates on it.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
import pandas as pd

from core.domain.control import (
    COOLANT,
    DATA_CENTER,
    DEFAULT_STATE_ID,
    DRAIN,
    Action,
    Commodity,
    Condition,
    ControlSettings,
    ControlSpec,
    ControlState,
    Link,
    Operator,
    Plan,
    Reference,
    SettingKind,
)
from core.domain.utility import UtilityTariff
from core.models.utility import WEEKEND_DAYS
from core.timeseries import columns as col

FloatArray = npt.NDArray[np.float64]
ModuleValues = Mapping[tuple[str, str], float]  # (source, variable) → value
ALWAYS_ON = {DATA_CENTER, COOLANT, DRAIN}  # link ends that need no THEN to run

_COMPARE = {
    Operator.LT: np.less,
    Operator.LE: np.less_equal,
    Operator.GT: np.greater,
    Operator.GE: np.greater_equal,
    Operator.EQ: np.equal,
    Operator.NE: np.not_equal,
}
_QUANTILE = {"q1": 0.25, "q3": 0.75}


def compare(lhs: float, op: Operator, rhs: float) -> bool:
    return bool(_COMPARE[op](lhs, rhs))


def statistic(values: FloatArray, index: pd.DatetimeIndex, reference: Reference) -> FloatArray:
    """Each hour's day / month / year mean, median or quartile of `values`."""
    if reference is Reference.VALUE:
        raise ValueError("A plain value has no statistic")
    period, how = reference.value.split("_")
    keys = {"day": index.dayofyear, "month": index.month, "year": index.year}[period]
    grouped = pd.Series(values).groupby(np.asarray(keys))
    if how == "mean":
        stat = grouped.transform("mean")
    elif how == "median":
        stat = grouped.transform("median")
    else:
        q = _QUANTILE[how]
        stat = grouped.transform(lambda s: s.quantile(q))
    return np.asarray(stat, dtype=float)


def resolve(actions: tuple[Action, ...], specs: Mapping[str, ControlSpec]) -> Plan:
    """A state's THENs → its Plan.

    A module runs if a THEN names it (as the target, or the other end of a
    link) and no THEN switches it off. Links are kept in THEN order, once each
    (a link may be entered at either end), and only between ends that run.
    THENs for settings that no longer exist are ignored.
    """
    known = [
        (a, specs[a.target].setting(a.setting))
        for a in actions
        if a.target in specs and specs[a.target].has_setting(a.setting)
    ]
    off = {a.target for a, s in known if s.kind is SettingKind.OFF}
    named = {a.target for a, s in known if s.kind is not SettingKind.OFF}
    named |= {a.to for a, s in known if s.kind is SettingKind.LINK and a.to}
    on = (named - off) | ALWAYS_ON
    values: dict[str, dict[str, float]] = {}
    links: list[Link] = []
    for a, s in known:
        if a.target not in on:
            continue
        if s.kind is SettingKind.FLAG:
            values.setdefault(a.target, {})[a.setting] = 1.0
        elif s.kind is SettingKind.NUMBER:
            values.setdefault(a.target, {})[a.setting] = a.value
        elif s.kind is SettingKind.LINK and s.commodity is not None and a.to in on:
            sender, receiver = (a.to, a.target) if s.receives else (a.target, a.to)
            if not any(
                (k.commodity, k.sender, k.receiver) == (s.commodity, sender, receiver)
                for k in links
            ):
                links.append(Link(s.commodity, sender, receiver, a.value if s.amount else None))
    return Plan(frozenset((on - ALWAYS_ON) | {DATA_CENTER}), values, tuple(links))


@dataclass(frozen=True)
class ControlData:
    """Hourly arrays the conditions read (built once per run)."""

    series: dict[tuple[str, str], FloatArray]  # exogenous (source, variable) → hourly values
    rhs: dict[int, FloatArray]  # id(condition) → its hourly statistic (statistic references)


@dataclass(frozen=True)
class Controller:
    """settings: the user's states. specs: every source / target by key.
    exogenous: (source, variable) → the column holding it (ambient, utility, PV);
    time and the planned IT load are read from the frame.
    it_peak_kw: full load, for the data center's "IT load is … % of full load"."""

    settings: ControlSettings
    specs: Mapping[str, ControlSpec]
    exogenous: Mapping[tuple[str, str], str]
    it_peak_kw: float | None = None
    initial: str = DEFAULT_STATE_ID  # the state before the first hour
    tariff: UtilityTariff | None = None  # rate categories, for Reference.RATE (D-059)
    plans: dict[str, Plan] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        plans = {s.id: resolve(s.actions, self.specs) for s in self.settings.all_states}
        object.__setattr__(self, "plans", plans)

    def _conditions(self) -> list[Condition]:
        return [c for s in self.settings.states for c in s.conditions]

    @property
    def requires(self) -> tuple[str, ...]:
        needed = {(c.source, c.variable) for c in self._conditions()}
        cols = [self.exogenous[k] for k in needed if k in self.exogenous]
        if (DATA_CENTER, "it_load_pct") in needed:
            cols.append(col.IT_LOAD_PLAN_KW)
        return tuple(dict.fromkeys(cols))

    @property
    def provides(self) -> tuple[str, ...]:
        return (col.CONTROL_STATE,)

    def prepare(self, df: pd.DataFrame) -> ControlData:
        index = pd.DatetimeIndex(df.index)
        values: dict[tuple[str, str], FloatArray] = {}
        for key, column in self.exogenous.items():
            if column in df.columns:
                values[key] = df[column].to_numpy(dtype=float)
        if self.it_peak_kw and col.IT_LOAD_PLAN_KW in df.columns:
            plan = df[col.IT_LOAD_PLAN_KW].to_numpy(dtype=float)
            values[(DATA_CENTER, "it_load_pct")] = plan / self.it_peak_kw * 100
        values[("time", "hour")] = index.hour.to_numpy().astype(float)
        values[("time", "date")] = (index.month * 100 + index.day).to_numpy().astype(float)
        values[("time", "month")] = index.month.to_numpy().astype(float)
        values[("time", "weekend")] = np.isin(index.dayofweek, WEEKEND_DAYS).astype(float)
        values[("time", "always")] = np.ones(len(index))
        rhs = {
            id(c): statistic(values[(c.source, c.variable)], index, c.reference)
            for c in self._conditions()
            if c.reference not in (Reference.VALUE, Reference.RATE)
            and (c.source, c.variable) in values
        }
        for c in self._conditions():
            if c.reference is Reference.RATE:
                rate = self.rate(c)
                if rate is not None:
                    rhs[id(c)] = np.full(len(index), rate)
        return ControlData(values, rhs)

    def rate(self, c: Condition) -> float | None:
        """The rate category's price an IF is compared with; None if the
        category is no longer in the tariff (the IF then never holds)."""
        spec = self.specs.get(c.source)
        if self.tariff is None or spec is None or c.category is None:
            return None
        field = next((v.rate_field for v in spec.ifs if v.key == c.variable), "")
        cat = next((x for x in self.tariff.categories if x.id == c.category), None)
        return None if cat is None or not field else float(getattr(cat, field))

    def holds(self, c: Condition, data: ControlData, h: int, modules: ModuleValues) -> bool:
        """One IF. A value that isn't available (e.g. its module is off the
        site) never holds."""
        key = (c.source, c.variable)
        if key in data.series:
            lhs = float(data.series[key][h])
        elif key in modules:
            lhs = modules[key]
        else:
            return False
        rhs = c.value if c.reference is Reference.VALUE else data.rhs.get(id(c))
        if rhs is None:
            return False
        return compare(lhs, c.op, float(rhs[h]) if isinstance(rhs, np.ndarray) else rhs)

    def choose(self, current: str, data: ControlData, h: int, modules: ModuleValues) -> str:
        """The state for hour h, given the state the previous hour ended in."""
        here = self.settings.state(current)
        for state in self.settings.states:  # priority order
            if here.allows(state.id) and all(
                self.holds(c, data, h, modules) for c in state.conditions
            ):
                return state.id
        return DEFAULT_STATE_ID

    def plan(self, state_id: str) -> Plan:
        return self.plans[state_id]

    def columns(self, state_id: str) -> dict[str, float]:
        """The hour's control column: the state's number (0 = Default, then
        priority order)."""
        ids = [s.id for s in self.settings.all_states]
        return {col.CONTROL_STATE: float(ids.index(state_id))}


def warnings(
    state: ControlState,
    specs: Mapping[str, ControlSpec],
    present: set[str],
    mixer_on_brine: bool = False,
) -> list[str]:
    """Things in a state that won't do what the user may expect (shown in the
    editor). present: the modules on the site (plus the data center);
    mixer_on_brine: the ice mixer's fluid is brine (it then needs brine too)."""
    out: list[str] = []
    plan = resolve(state.actions, specs)
    for a in state.actions:
        spec = specs.get(a.target)
        if spec is None or not spec.has_setting(a.setting):
            out.append(f"A THEN for '{a.target}' is no longer available and is ignored.")
            continue
        for end in (a.target, a.to):
            if end and end not in present and end not in ALWAYS_ON:
                label = specs[end].label if end in specs else end
                out.append(
                    f"{label} is not on the site, so this is ignored: "
                    f"'{spec.setting(a.setting).label}'."
                )
    switched_off = {
        a.target
        for a in state.actions
        if a.target in specs
        and specs[a.target].has_setting(a.setting)
        and specs[a.target].setting(a.setting).kind is SettingKind.OFF
    }
    for t in switched_off:
        if sum(a.target == t or a.to == t for a in state.actions) > 1:
            out.append(f"{specs[t].label} is switched off, so its other THENs are ignored.")
    return out + module_warnings(plan, mixer_on_brine)


def module_warnings(plan: Plan, mixer_on_brine: bool = False) -> list[str]:
    """Combinations that leave a running module with nothing to do (a module
    that is short of a supply stays off, and so does anything it feeds)."""
    out = []
    if plan.runs("power_generation"):
        if not plan.to("power_generation", Commodity.HEAT):
            out.append("Waste heat to power has no heat source.")
        if not plan.to("power_generation", Commodity.COOLING):
            out.append("Waste heat to power has no cooling (cold side).")
    if plan.runs("ice_mixer"):
        if not plan.to("ice_mixer", Commodity.ICE):
            out.append("The ice mixer gets no ice (ice storage: 'Sends ice to').")
        if mixer_on_brine and not plan.to("ice_mixer", Commodity.BRINE):
            out.append(
                "The ice mixer is set to brine but gets none (brine separation: 'Sends brine "
                "flow to'), so it stays off, and so does whatever it cools."
            )
        if not plan.sent_by("ice_mixer", Commodity.COOLING):
            out.append("The ice mixer cools nothing ('Provides cooling to').")
    return out
