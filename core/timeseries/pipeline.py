"""Runs hourly subsystem models in dependency order (docs/architecture.md).

Each subsystem declares the columns it reads (`requires`) and adds
(`provides`). The pipeline orders them so every requirement is produced first,
and checks that each subsystem actually adds what it promised.
"""

from typing import Protocol

import pandas as pd


class Subsystem(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def requires(self) -> tuple[str, ...]: ...
    @property
    def provides(self) -> tuple[str, ...]: ...

    def run(self, df: pd.DataFrame) -> pd.DataFrame: ...


class PipelineError(RuntimeError):
    pass


def order_subsystems(subsystems: list[Subsystem], initial: set[str]) -> list[Subsystem]:
    """Topologically sort subsystems so requirements are met before use."""
    available = set(initial)
    remaining = list(subsystems)
    ordered: list[Subsystem] = []
    while remaining:
        ready = [s for s in remaining if set(s.requires) <= available]
        if not ready:
            missing = {s.name: sorted(set(s.requires) - available) for s in remaining}
            raise PipelineError(f"Unsatisfiable column requirements: {missing}")
        for s in ready:
            ordered.append(s)
            available |= set(s.provides)
            remaining.remove(s)
    return ordered


def run_pipeline(df: pd.DataFrame, subsystems: list[Subsystem]) -> pd.DataFrame:
    for s in order_subsystems(subsystems, set(df.columns)):
        df = s.run(df)
        missing = set(s.provides) - set(df.columns)
        if missing:
            raise PipelineError(f"{s.name} did not provide columns {sorted(missing)}")
    return df
