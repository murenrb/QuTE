"""Hourly module solver (docs/solver.md, D-052, D-054).

Modules that exchange flows within an hour (the data center's heat, the ice
mixer ↔ ice storage ↔ brine separation, power generation's heat and cold
sides) can't run one after the other for the whole year. Each is written as a
*node*: given its state at the start of the hour and the streams it reads, it
returns its end state, the streams it writes and its column values for the
hour, without changing anything. The
solver steps all nodes hour by hour:

1. Run the nodes in order; each reads the latest streams (None = not written
   yet, e.g. a request nobody has answered). A node whose inputs haven't
   changed since its last run is not re-run.
2. Repeat until no stream changes (within tolerance). At that fixed point every
   module computed from the others' final flows, so the balances between them
   close. Each node always applies its own limits (min()s), so no tank can
   overfill or go below empty whatever the iteration.
3. If not settled after `stick_after` iterations, cap each *sticky* stream at
   its value closest to zero over the last `stick_window` iterations (an
   oscillation is a tank feeding off its own return; sticking low breaks it)
   and allow `max_iter − stick_after` more; then raise SolverError.
   Sticky streams are the *answers* (what a module can supply or accept). The
   cap applies to the answer as the other modules read it: they use no more
   than the capped answer and report what they used, and every module balances
   its own state on what was used (D-054), so the balances still close.
   Wants (requests) are never capped: they must be able to rise again.
4. Commit each node's last step (state → next hour, values → columns).

With a state machine (`controller`, D-053) the hour's state is chosen first,
from the hourly columns and each node's start-of-hour `control_values`, and
every node gets the state's `Plan` (which modules run, their settings, and
the links between them, D-054); the state never changes within the hour.

Contract for nodes: an answer never exceeds the request it answers, and a
request nobody has made yet (None) gets no answer (None).

The solver is itself a pipeline Subsystem, so the rest of the model runs as before.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd

from core.config.defaults import SOLVER, SolverSettings
from core.domain.control import NOTHING_RUNS, Plan
from core.timeseries.pipeline import PipelineError

Flows = Mapping[str, float | None]


@dataclass(frozen=True)
class StreamSpec:
    """A stream a node writes.

    answers: the request (want) stream this one answers (what can be supplied /
    accepted of it). Answers are *sticky*: capped if the hour won't settle.
    signed: may flow either way, so it is capped by magnitude (toward zero).
    """

    name: str
    answers: str | None = None
    signed: bool = False

    @property
    def sticky(self) -> bool:
        return self.answers is not None


@dataclass(frozen=True)
class NodeStep:
    """One node's result for one hour (nothing is applied until committed)."""

    end: Any  # state at the end of the hour
    flows: dict[str, float | None]  # streams written (None = no answer yet)
    columns: dict[str, float]  # column values for this hour


class HourlyNode(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def control_key(self) -> str | None: ...  # its state machine source (IFs), if any
    @property
    def requires(self) -> tuple[str, ...]: ...  # DataFrame columns read
    @property
    def provides(self) -> tuple[str, ...]: ...  # DataFrame columns written
    @property
    def reads(self) -> tuple[str, ...]: ...  # streams read
    @property
    def writes(self) -> tuple[StreamSpec, ...]: ...  # streams written

    def prepare(self, df: pd.DataFrame) -> Any:
        """Pull this node's columns out once (arrays), for `step`."""
        ...

    def initial_state(self) -> Any: ...

    def step(self, data: Any, state: Any, h: int, flows: Flows, plan: Plan) -> NodeStep: ...


class StateController(Protocol):
    """The state machine (core/control/engine.py): picks each hour's state before
    the hour is solved, from the hourly columns and the nodes' start-of-hour
    `control_values`, and gives the state's Plan."""

    @property
    def requires(self) -> tuple[str, ...]: ...
    @property
    def provides(self) -> tuple[str, ...]: ...
    @property
    def initial(self) -> str: ...  # the state before the first hour

    def prepare(self, df: pd.DataFrame) -> Any: ...
    def choose(
        self, current: str, data: Any, h: int, modules: Mapping[tuple[str, str], float]
    ) -> str: ...
    def plan(self, state_id: str) -> Plan: ...
    def columns(self, state_id: str) -> Mapping[str, float]: ...


class SolverError(PipelineError):
    pass


def _settled(old: float | None, new: float | None, s: SolverSettings) -> bool:
    if old is None or new is None:
        return old is new
    return abs(new - old) <= s.abs_tol + s.rel_tol * abs(old)


def _cap(value: float | None, cap: float | None, signed: bool) -> float | None:
    if value is None or cap is None:
        return value
    if signed:
        return float(np.sign(value)) * min(abs(value), abs(cap))
    return min(value, cap)


def _closest_to_zero(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return min(known, key=abs) if known else None


_NOT_RUN = object()


@dataclass(frozen=True)
class HourlySolver:
    """Steps `nodes` together, hour by hour, in the order given. With a
    `controller`, the state machine picks each hour's state first (D-053)."""

    nodes: tuple[HourlyNode, ...]
    controller: StateController | None = None
    settings: SolverSettings = SOLVER
    name: str = "hourly_solver"
    specs: dict[str, StreamSpec] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        specs: dict[str, StreamSpec] = {}
        for node in self.nodes:
            for spec in node.writes:
                if spec.name in specs:
                    raise ValueError(f"Stream {spec.name!r} is written by more than one node")
                specs[spec.name] = spec
        object.__setattr__(self, "specs", specs)

    @property
    def requires(self) -> tuple[str, ...]:
        ctl = self.controller.requires if self.controller else ()
        return tuple(dict.fromkeys([*(c for n in self.nodes for c in n.requires), *ctl]))

    @property
    def provides(self) -> tuple[str, ...]:
        ctl = self.controller.provides if self.controller else ()
        return tuple(dict.fromkeys([*(c for n in self.nodes for c in n.provides), *ctl]))

    def solve_hour(
        self,
        h: int,
        data: list[Any],
        states: list[Any],
        plan: Plan = NOTHING_RUNS,
    ) -> list[NodeStep]:
        """Settle one hour under the active state's plan."""
        s = self.settings
        flows: dict[str, float | None] = {name: None for name in self.specs}
        history: dict[str, list[float | None]] = {
            name: [] for name, spec in self.specs.items() if spec.sticky
        }
        caps: dict[str, float | None] = {}  # answer stream → cap
        last_inputs: list[object] = [_NOT_RUN] * len(self.nodes)
        steps: list[NodeStep | None] = [None] * len(self.nodes)
        for iteration in range(1, s.max_iter + 1):
            changed: set[str] = set()
            for i, node in enumerate(self.nodes):
                inputs = tuple(self._read(node, r, flows, caps) for r in node.reads)
                if inputs == last_inputs[i]:
                    continue  # nothing it reads moved: its last step stands
                flows_in = dict(zip(node.reads, inputs, strict=True))
                step = node.step(data[i], states[i], h, flows_in, plan)
                steps[i], last_inputs[i] = step, inputs
                for name, value in step.flows.items():
                    if iteration == 1 or not _settled(flows[name], value, s):
                        changed.add(name)
                    flows[name] = value
            for name in history:
                history[name].append(flows[name])
            if iteration > 1 and not changed:
                return [st for st in steps if st is not None]
            if iteration == s.stick_after:
                caps = {
                    name: _closest_to_zero(values[-s.stick_window :])
                    for name, values in history.items()
                }
        moving = sorted(n for n, v in history.items() if not _settled(v[-2], v[-1], s)) or sorted(
            changed
        )
        raise SolverError(
            f"Hour {h}: modules did not settle in {s.max_iter} iterations "
            f"(still moving: {', '.join(moving)})"
        )

    def _read(
        self,
        node: HourlyNode,
        stream: str,
        flows: Mapping[str, float | None],
        caps: Mapping[str, float | None],
    ) -> float | None:
        """A stream as `node` reads it: a capped answer is read at its cap."""
        value = flows.get(stream)
        if stream in caps:
            return _cap(value, caps[stream], self.specs[stream].signed)
        return value

    def _module_values(self, states: list[Any]) -> dict[tuple[str, str], float]:
        """Start-of-hour values the state machine's module IFs can test."""
        values: dict[tuple[str, str], float] = {}
        for node, state in zip(self.nodes, states, strict=True):
            read = getattr(node, "control_values", None)
            if node.control_key and read is not None:
                values.update({(node.control_key, k): v for k, v in read(state).items()})
        return values

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        n = len(df)
        data = [node.prepare(df) for node in self.nodes]
        states = [node.initial_state() for node in self.nodes]
        out = {c: np.empty(n) for c in self.provides}
        ctl = self.controller
        ctl_data = ctl.prepare(df) if ctl else None
        current = ctl.initial if ctl else ""
        for h in range(n):  # stateful: each hour starts from the previous hour's end
            plan = NOTHING_RUNS
            if ctl:  # the hour's state is fixed before it is solved
                current = ctl.choose(current, ctl_data, h, self._module_values(states))
                plan = ctl.plan(current)
                for c, v in ctl.columns(current).items():
                    out[c][h] = v
            for i, step in enumerate(self.solve_hour(h, data, states, plan)):
                states[i] = step.end
                for c, v in step.columns.items():
                    out[c][h] = v
        return df.assign(**out)


@dataclass(frozen=True)
class ColumnStream:
    """Feeds a DataFrame column into the solver as a (non-sticky) stream."""

    column: str
    stream: str
    control_key: str | None = None
    reads: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return f"column:{self.column}"

    @property
    def requires(self) -> tuple[str, ...]:
        return (self.column,)

    @property
    def writes(self) -> tuple[StreamSpec, ...]:
        return (StreamSpec(self.stream),)

    def prepare(self, df: pd.DataFrame) -> Any:
        return df[self.column].to_numpy(dtype=float)

    def initial_state(self) -> Any:
        return None

    def step(self, data: Any, state: Any, h: int, flows: Flows, plan: Plan) -> NodeStep:
        return NodeStep(None, {self.stream: float(data[h])}, {})
