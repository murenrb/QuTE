from dataclasses import dataclass

import pandas as pd
import pytest

from core.timeseries.pipeline import PipelineError, Subsystem, run_pipeline


@dataclass
class AddColumn:
    name: str
    requires: tuple[str, ...]
    provides: tuple[str, ...]
    produce: bool = True

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        if self.produce:
            df = df.copy()
            df[self.provides[0]] = df[self.requires[0]] + 1
        return df


def test_runs_in_dependency_order_regardless_of_list_order() -> None:
    df = pd.DataFrame({"a": [0, 1]})
    subs: list[Subsystem] = [AddColumn("c", ("b",), ("c",)), AddColumn("b", ("a",), ("b",))]
    out = run_pipeline(df, subs)
    assert out["c"].tolist() == [2, 3]


def test_unsatisfiable_requirement_raises() -> None:
    with pytest.raises(PipelineError, match="Unsatisfiable"):
        run_pipeline(pd.DataFrame({"a": [0]}), [AddColumn("x", ("missing",), ("x",))])


def test_missing_provided_column_raises() -> None:
    with pytest.raises(PipelineError, match="did not provide"):
        run_pipeline(pd.DataFrame({"a": [0]}), [AddColumn("b", ("a",), ("b",), produce=False)])
