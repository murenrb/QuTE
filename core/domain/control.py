"""State machine control (docs/control.md, D-053, D-054).

Three kinds of things live here:

- **Specs**: what can be tested (an IF: `ControlVariable`) and what can be set
  (a THEN: `ControlSetting`) for one source / target (`ControlSpec`). Each module
  and the data center declare their own spec in their model file; ambient,
  utility and time are declared in `core/control/catalog.py`.
- **Settings**: the user's states, saved in the project (`ControlSettings`).
- **Plan**: what one state means for the hour (`Plan`): which modules run,
  their numbers, and the links between them in THEN order. The solver hands
  it to every module.

Each state is a complete description (owner, D-054): a module runs only if
the state's THENs name it, and nothing happens behind the user's back. The
Default state has no IFs and is active whenever no other state's IFs hold.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

DEFAULT_STATE_ID = "default"
DATA_CENTER = "data_center"


class SettingKind(StrEnum):
    FLAG = "flag"  # a THEN with no blanks, e.g. "Ice maker cleared to run"
    OFF = "off"  # "<module> is off"
    NUMBER = "number"  # one number, e.g. "IT load is set to [x] % of planned load"
    LINK = "link"  # a connection to another module, e.g. "Sends ice to [module]"


class Commodity(StrEnum):
    """What a link carries."""

    HEAT = "heat"  # kW_th of hot water / vapor
    COOLING = "cooling"  # kW_th of cooling (a cold side)
    ICE = "ice"  # kg/s
    BRINE = "brine"  # kg/s
    WATER = "water"  # kg/s


# Link ends that aren't modules.
COOLANT = "coolant"  # the supply coolant: free cooling when possible, else chillers
DRAIN = "drain"


@dataclass(frozen=True)
class ControlVariable:
    """Something an IF can test, read at the start of each hour."""

    key: str
    label: str
    unit: str = ""
    # Can be compared with its own mean / median / quartiles (utility prices).
    statistics: bool = False
    # Can be compared with a rate category of the tariff (D-059): the
    # `RateCategory` field it is compared with, e.g. "energy_usd_kwh".
    rate_field: str = ""
    kind: str = "number"  # "number", "date" (MM-DD) or "on_off" (Always)


@dataclass(frozen=True)
class ControlSetting:
    """Something a THEN can set for one target.

    label: the sentence, with `{value}` for a number and `{to}` for the other
    end of a link, e.g. "Accepts {value} % of heat from {to}".
    LINK: `commodity`, `receives` (this target is the receiving end, else it
    sends) and `ends` (the other end's options). `amount`: a link that also
    carries a number (min / max / step / unit / default).
    """

    key: str
    label: str
    kind: SettingKind
    default: float = 0.0
    min: float = 0.0
    max: float = 100.0
    step: float = 1.0
    unit: str = ""
    commodity: Commodity | None = None
    receives: bool = False
    ends: tuple[str, ...] = ()
    amount: bool = False

    @property
    def has_value(self) -> bool:
        return self.kind is SettingKind.NUMBER or self.amount


@dataclass(frozen=True)
class ControlSpec:
    """The IFs and THENs of one source / target (a module, the data center,
    ambient, utility, time)."""

    key: str
    label: str
    ifs: tuple[ControlVariable, ...] = ()
    thens: tuple[ControlSetting, ...] = ()

    def variable(self, key: str) -> ControlVariable:
        return next(v for v in self.ifs if v.key == key)

    def setting(self, key: str) -> ControlSetting:
        return next(s for s in self.thens if s.key == key)

    def has_setting(self, key: str) -> bool:
        return any(s.key == key for s in self.thens)


OFF_KEY = "off"


def off_setting(label: str) -> ControlSetting:
    """Every module's explicit "is off" THEN (owner)."""
    return ControlSetting(OFF_KEY, f"{label} is off", SettingKind.OFF)


# --- the user's states (saved in the project) ---------------------------------


class Operator(StrEnum):
    LT = "<"
    LE = "≤"
    GT = ">"
    GE = "≥"
    EQ = "="
    NE = "≠"


class Reference(StrEnum):
    """What a value is compared with: a number, or a statistic of the variable."""

    VALUE = "value"
    DAY_MEAN = "day_mean"
    DAY_MEDIAN = "day_median"
    DAY_Q1 = "day_q1"  # lower quartile
    DAY_Q3 = "day_q3"  # upper quartile
    YEAR_MEAN = "year_mean"
    YEAR_MEDIAN = "year_median"
    RATE = "rate"  # a rate category of the tariff, by id in `Condition.category` (D-059)
    # Kept so files saved with them still load; no longer offered (owner's list).
    MONTH_MEAN = "month_mean"
    MONTH_MEDIAN = "month_median"


OFFERED_REFERENCES = (
    Reference.VALUE,
    Reference.DAY_MEAN,
    Reference.DAY_MEDIAN,
    Reference.DAY_Q1,
    Reference.DAY_Q3,
    Reference.YEAR_MEAN,
    Reference.YEAR_MEDIAN,
)


def date_value(month: int, day: int) -> float:
    """A date IF's value: MM-DD as month·100 + day, so dates compare in order."""
    return float(month * 100 + day)


def date_text(value: float) -> str:
    v = int(round(value))
    return f"{v // 100:02d}-{v % 100:02d}"


class Condition(BaseModel):
    """IF <source>.<variable> <op> <value | statistic | rate category>."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str  # "ambient", "utility", "time", "data_center" or a module key
    variable: str
    op: Operator = Operator.GT
    value: float = 0.0
    reference: Reference = Reference.VALUE
    category: str | None = None  # rate category id, for Reference.RATE


class Action(BaseModel):
    """THEN <target> <setting> [value] [to]. Order matters: links are served
    in the order the state lists them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target: str  # "data_center" or a module key
    setting: str
    value: float = 0.0  # the number, for NUMBER settings and links with an amount
    to: str | None = None  # the other end, for LINK settings


class ControlState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    conditions: tuple[Condition, ...] = ()  # all must hold to enter / stay (AND)
    actions: tuple[Action, ...] = ()  # the complete description of the state
    # States it may move to; None = any (the default for a new state). The
    # Default state is always reachable, so the machine can never get stuck.
    next_states: tuple[str, ...] | None = None

    def allows(self, state_id: str) -> bool:
        return (
            state_id in (self.id, DEFAULT_STATE_ID)
            or self.next_states is None
            or state_id in self.next_states
        )


class ControlSettings(BaseModel):
    """The state machine. `states` are the user's states in priority order (the
    first whose IFs hold wins); `default` is the Default state (no IFs)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default: ControlState = ControlState(id=DEFAULT_STATE_ID, name="Default")
    states: tuple[ControlState, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> "ControlSettings":
        if self.default.id != DEFAULT_STATE_ID or self.default.conditions:
            raise ValueError("The Default state has the id 'default' and no IFs")
        ids = [s.id for s in self.states]
        if DEFAULT_STATE_ID in ids or len(set(ids)) != len(ids):
            raise ValueError("State ids must be unique and not 'default'")
        return self

    @property
    def all_states(self) -> tuple[ControlState, ...]:
        return (self.default, *self.states)

    def state(self, state_id: str) -> ControlState:
        return next(s for s in self.all_states if s.id == state_id)

    def new_state_id(self) -> str:
        used = {s.id for s in self.states}
        return next(f"s{i}" for i in range(1, len(used) + 2) if f"s{i}" not in used)

    def replace(self, state: ControlState) -> "ControlSettings":
        if state.id == DEFAULT_STATE_ID:
            return self.model_copy(update={"default": state})
        states = tuple(state if s.id == state.id else s for s in self.states)
        return self.model_copy(update={"states": states})

    def remove(self, state_id: str) -> "ControlSettings":
        """Drop a state and every connection to it."""
        kept = []
        for s in self.states:
            if s.id == state_id:
                continue
            if s.next_states is not None:
                s = s.model_copy(
                    update={"next_states": tuple(n for n in s.next_states if n != state_id)}
                )
            kept.append(s)
        return self.model_copy(update={"states": tuple(kept)})


# --- what a state means for one hour --------------------------------------------


@dataclass(frozen=True)
class Link:
    """A connection the active state makes: `sender` gives `commodity` to
    `receiver`. amount: the number the THEN carries (e.g. % of heat), if any."""

    commodity: Commodity
    sender: str
    receiver: str
    amount: float | None = None


@dataclass(frozen=True)
class Plan:
    """One state, resolved for the solver (core/control/engine.py builds it).

    on: modules that run (named by a THEN and not switched off).
    values: target → setting → value for FLAG (1) and NUMBER settings.
    links: in THEN order, only between ends that run.
    """

    on: frozenset[str] = frozenset()
    values: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    links: tuple[Link, ...] = ()

    def runs(self, key: str) -> bool:
        return key in self.on

    def value(self, target: str, setting: str, default: float) -> float:
        return self.values.get(target, {}).get(setting, default)

    def flag(self, target: str, setting: str) -> bool:
        return setting in self.values.get(target, {})

    def to(self, receiver: str, commodity: Commodity) -> tuple[Link, ...]:
        """Links into `receiver`, in THEN order."""
        return tuple(k for k in self.links if k.receiver == receiver and k.commodity == commodity)

    def sent_by(self, sender: str, commodity: Commodity) -> tuple[Link, ...]:
        """Links out of `sender`, in THEN order."""
        return tuple(k for k in self.links if k.sender == sender and k.commodity == commodity)

    def link(self, commodity: Commodity, sender: str, receiver: str) -> Link | None:
        return next(
            (
                k
                for k in self.links
                if (k.commodity, k.sender, k.receiver) == (commodity, sender, receiver)
            ),
            None,
        )


NOTHING_RUNS = Plan()
