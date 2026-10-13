"""Hourly module solver (docs/solver.md, D-052, D-054): settling, the sticky rule, errors."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import pytest

from core.config.defaults import SOLVER
from core.domain.control import Plan
from core.timeseries.solver import (
    ColumnStream,
    Flows,
    HourlySolver,
    NodeStep,
    SolverError,
    StreamSpec,
    _cap,
    _closest_to_zero,
)


@dataclass(frozen=True)
class Toy:
    """A node from a function: flows read → flows written (and a column)."""

    name: str
    reads: tuple[str, ...]
    writes: tuple[StreamSpec, ...]
    fn: Callable[[Flows], dict[str, float | None]]
    calls: list[int] = field(default_factory=list, compare=False)
    requires: tuple[str, ...] = ()
    control_key: str | None = None

    @property
    def provides(self) -> tuple[str, ...]:
        return tuple(f"{self.name}_{s.name}" for s in self.writes)

    def prepare(self, df: pd.DataFrame) -> Any:
        return None

    def initial_state(self) -> Any:
        return None

    def step(self, data: Any, state: Any, h: int, flows: Flows, plan: Plan) -> NodeStep:
        self.calls.append(h)
        out = self.fn(flows)
        cols = {f"{self.name}_{k}": (v if v is not None else float("nan")) for k, v in out.items()}
        return NodeStep(None, out, cols)


def consumer(want: float = 10.0) -> Toy:
    """Asks for `want`, then for no more than it was given (min)."""

    def fn(f: Flows) -> dict[str, float | None]:
        got = f["supply"]
        return {"call": want if got is None else min(want, got)}

    return Toy("consumer", ("supply",), (StreamSpec("call"),), fn)


def tank(available: float) -> Toy:
    """Supplies min(call, available); no answer until asked."""

    def fn(f: Flows) -> dict[str, float | None]:
        call = f["call"]
        return {"supply": None if call is None else min(call, available)}

    return Toy("tank", ("call",), (StreamSpec("supply", answers="call"),), fn)


def solve(*nodes: Toy) -> pd.DataFrame:
    return HourlySolver(nodes).run(pd.DataFrame(index=range(1)))


def test_settles_on_what_the_tank_can_give() -> None:
    out = solve(consumer(10), tank(4))
    assert out["consumer_call"].iloc[0] == 4 and out["tank_supply"].iloc[0] == 4


def test_unlimited_settles_on_the_request_and_skips_unchanged_nodes() -> None:
    c, t = consumer(10), tank(50)
    solve(c, t)
    # it1: consumer (pass 1) + tank; it2: consumer re-runs (supply moved), tank's
    # input didn't change so it isn't re-run; it2 changed nothing → settled.
    assert len(c.calls) == 2 and len(t.calls) == 1


def test_oscillation_sticks_low_and_settles() -> None:
    """A consumer that asks for more whenever it was given little (the owner's
    example: less flow → more flow next time → the level drops again)."""

    def greedy(f: Flows) -> dict[str, float | None]:
        got = f["supply"]
        return {"call": 10.0 if got is None or got <= 3 else 3.0, "used": got}

    asker = Toy("consumer", ("supply",), (StreamSpec("call"), StreamSpec("used")), greedy)
    out = solve(asker, tank(8))
    # supply 8 → 3 → 8 …: after `stick_after` iterations the answer sticks at its
    # lowest of the last `stick_window` (3), as the consumer reads it; the want
    # (call) is never capped, and the tank would balance on what was used.
    assert out["consumer_used"].iloc[0] == 3
    assert out["consumer_call"].iloc[0] == 10


def test_non_sticky_oscillation_raises() -> None:
    a = Toy("a", ("y",), (StreamSpec("x"),), lambda f: {"x": 1 - (f["y"] or 0)})
    b = Toy("b", ("x",), (StreamSpec("y"),), lambda f: {"y": f["x"]})
    with pytest.raises(SolverError, match=f"did not settle in {SOLVER.max_iter}"):
        solve(a, b)


def test_caps() -> None:
    assert _closest_to_zero([10.0, 5.0, None, 7.0]) == 5.0
    assert _closest_to_zero([-5.0, 3.0, -1.0]) == -1.0  # signed: closest to zero
    assert _closest_to_zero([None]) is None
    assert _cap(8.0, 5.0, signed=False) == 5.0
    assert _cap(3.0, 5.0, signed=False) == 3.0
    assert _cap(-4.0, -1.0, signed=True) == -1.0  # magnitude capped, sign kept
    assert _cap(4.0, -1.0, signed=True) == 1.0
    assert _cap(None, 5.0, signed=False) is None


def test_one_writer_per_stream() -> None:
    with pytest.raises(ValueError, match="more than one node"):
        HourlySolver((tank(1), tank(2)))


def test_columns_and_column_stream() -> None:
    df = pd.DataFrame({"demand": [3.0, 12.0]})
    feed = ColumnStream("demand", "want")
    c = Toy(
        "consumer",
        ("want", "supply"),
        (StreamSpec("call"),),
        lambda f: {
            "call": (f["want"] or 0) if f["supply"] is None else min(f["want"] or 0, f["supply"])
        },
    )
    solver = HourlySolver((feed, c, tank(10)))
    assert solver.requires == ("demand",)
    assert set(solver.provides) == {"consumer_call", "tank_supply"}
    out = solver.run(df)
    assert out["tank_supply"].tolist() == [3.0, 10.0]


def test_monotone_convergence_needs_no_sticking() -> None:
    """A coupled loop that contracts toward its answer (like brine return ↔
    condenser ↔ ice, ~50× per iteration) settles before the sticky rule acts."""

    def creep(f: Flows) -> dict[str, float | None]:
        got = f["supply"]
        return {"call": 10.0 if got is None else 4 + (got - 4) / 50}

    out = solve(Toy("consumer", ("supply",), (StreamSpec("call"),), creep), tank(100))
    assert out["consumer_call"].iloc[0] == pytest.approx(4, abs=1e-4)
