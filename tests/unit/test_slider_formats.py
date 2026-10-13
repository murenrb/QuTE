"""Number formats for sliders / number inputs are applied in the browser by
sprintf-js, which rejects a lone "%" (e.g. "%g wt%") with "SyntaxError:
[sprintf] unexpected placeholder". A literal percent sign must be "%%"."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
UI_FILES = sorted((ROOT / "app").rglob("*.py"))
PRINTF = re.compile(r"%[-+ 0#]*\d*(?:\.\d+)?[bcdieufgosxX]")


def _formats(path: Path) -> list[str]:
    """String constants that start with a printf placeholder (slider formats)."""
    return [
        n.value
        for n in ast.walk(ast.parse(path.read_text()))
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and PRINTF.match(n.value)
    ]


@pytest.mark.parametrize("path", UI_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_lone_percent_in_number_formats(path: Path) -> None:
    for f in _formats(path):
        rest = PRINTF.sub("", f, count=1).replace("%%", "")
        assert "%" not in rest, f"{path.name}: {f!r} — write a literal % as %%"


def test_check_catches_the_brine_bug() -> None:
    rest = PRINTF.sub("", "%g wt%", count=1).replace("%%", "")
    assert "%" in rest
