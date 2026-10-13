"""Sidebar on every page: model assumptions (docs/gui.md). Project name, saving and
versions live in the project bar on the workspace (D-040)."""

from dataclasses import fields

import streamlit as st

from app import state


def render_sidebar() -> None:
    p = state.get_project()
    with st.sidebar, st.expander("Model assumptions"):
        st.caption("Fixed for now; editable in a later version.")
        rows = {f.name: getattr(p.assumptions, f.name) for f in fields(p.assumptions)}
        st.table({"Assumption": list(rows), "Value": [f"{v:g}" for v in rows.values()]})
