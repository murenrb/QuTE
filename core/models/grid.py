"""Net grid load: sum of every stacked electrical column in the registry.

Runs last (it requires the electrical columns). `site_subsystems` passes the
stacked electrical columns that the active subsystems produce, so enabled
modules' loads or generation (negative) are included automatically.
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from core.domain.control import Plan
from core.timeseries import columns as col
from core.timeseries.columns import PlotGroup
from core.timeseries.solver import Flows, NodeStep, StreamSpec


def electrical_stack() -> tuple[str, ...]:
    """Every registered stacked electrical column (loads positive, generation negative)."""
    return tuple(c.name for c in col.columns_in_group(PlotGroup.ELECTRICAL) if c.stacked)


@dataclass(frozen=True)
class GridBalance:
    name: str = "grid_balance"
    requires: tuple[str, ...] = field(default_factory=electrical_stack)
    provides: tuple[str, ...] = (col.GRID_NET_KW,)

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(**{col.GRID_NET_KW: df[list(self.requires)].sum(axis=1)})


@dataclass(frozen=True)
class GridDraw:
    """Solver node: the net grid draw each hour (the sum of every electrical
    stream), kept so the state machine can test the previous hour's draw
    ("grid draw" IF under Utility, D-054). The column is written by
    `GridBalance` after the solver, from the same terms."""

    reads: tuple[str, ...]  # every electrical stream (core.timeseries.streams.elec)
    name: str = "grid_draw"
    control_key: str | None = "utility"
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    writes: tuple[StreamSpec, ...] = ()

    def prepare(self, df: pd.DataFrame) -> Any:
        return None

    def initial_state(self) -> float | None:
        return None  # no hour before the first

    def control_values(self, state: float | None) -> dict[str, float]:
        return {} if state is None else {"grid_draw_kw": state}

    def step(self, data: Any, state: Any, h: int, flows: Flows, plan: Plan) -> NodeStep:
        return NodeStep(sum(flows[r] or 0.0 for r in self.reads), {}, {})
