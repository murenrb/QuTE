"""Enforce CLAUDE.md rule 1: engineering code never imports streamlit."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PURE_FILES = sorted([*(ROOT / "core").rglob("*.py"), *(ROOT / "services").rglob("*.py")])


@pytest.mark.parametrize("path", PURE_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_streamlit_import(path: Path) -> None:
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        else:
            continue
        assert not any(m.split(".")[0] == "streamlit" for m in mods), path
