"""Module output panel: what each module shows left of the results figure
(docs/workflow/02-results.md → Module output).

Each module declares its `ModuleOutputs` in its own UI file
(app/components/modules/<module>.py) and passes it to its `ModuleUI`, so a new
module adds its plot and text there with no edit to the figure.
"""

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from app.components.metrics import Metric
from core.config.defaults import KW_PER_MW

PCT_PER_FRAC = 100.0
MW_PER_KW = 1 / KW_PER_MW


@dataclass(frozen=True)
class Trace:
    """One line: plotted value = column × scale."""

    column: str
    label: str
    color: str
    scale: float = 1.0


@dataclass(frozen=True)
class Panel:
    """One module subplot (at most two per module, stacked; owner, D-055)."""

    title: str
    unit: str  # y-axis title
    traces: tuple[Trace, ...]


@dataclass(frozen=True)
class ModuleOutputs:
    panels: tuple[Panel, ...]  # one or two
    text: Callable[[pd.DataFrame], list[Metric]]

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(t.column for p in self.panels for t in p.traces)

    def available(self, df: pd.DataFrame) -> bool:
        """The module ran (it is on the site): all its plotted columns exist."""
        return all(c in df.columns for c in self.columns)


def fmt(value: float, unit: str, decimals: int = 0) -> str:
    """'1,234 MWh/yr'; '—' for a missing value (e.g. a module that never ran)."""
    return "—" if pd.isna(value) else f"{value:,.{decimals}f} {unit}"
