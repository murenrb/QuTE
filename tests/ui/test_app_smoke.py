"""Every page loads without exceptions."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ENTRY = str(Path(__file__).resolve().parents[2] / "streamlit_app.py")

PAGES = ["app/pages/start.py", "app/pages/workspace.py"]


def test_entry_point_loads() -> None:
    at = AppTest.from_file(ENTRY).run(timeout=30)
    assert not at.exception


@pytest.mark.parametrize("page", PAGES)
def test_page_loads(page: str) -> None:
    at = AppTest.from_file(ENTRY).run(timeout=30)
    at.switch_page(page).run(timeout=30)
    assert not at.exception
