"""App entry: page config, style and navigation. Launched via streamlit_app.py."""

from pathlib import Path

import streamlit as st

from app.components.sidebar import render_sidebar
from app.components.style import inject_css

PAGES_DIR = Path(__file__).parent / "pages"


def run() -> None:
    st.set_page_config(
        page_title="Data Center System", layout="wide", initial_sidebar_state="collapsed"
    )
    inject_css()
    nav = st.navigation(
        [
            st.Page(PAGES_DIR / "start.py", title="Start", default=True),
            st.Page(PAGES_DIR / "workspace.py", title="Workspace"),
        ],
        position="top",
    )
    render_sidebar()
    nav.run()
