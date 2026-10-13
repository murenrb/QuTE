"""Start screen: open a project or start a new setup.

Spec: docs/workflow/01-setup-tabs.md §0. Every saved project is listed: the
app is public, all projects are visible to everyone (D-069).
"""

import streamlit as st

from app import state
from core.persistence.project import Project, ProjectFileError, from_json
from services.store import ProjectEntry


def _open(p: Project, stem: str | None = None) -> None:
    """Open and go to the workspace; results recompute live there.

    stem: the saved project it came from (keeps saving there); None → a new one.
    """
    state.open_project(p, stem)
    st.switch_page(state.WORKSPACE_PAGE, query_params={state.PROJECT_PARAM: state.autosave_stem()})


def _label(e: ProjectEntry) -> str:
    return f"{e.name}  ·  {state.local_time(e.updated_at):%Y-%m-%d %H:%M}  ·  {e.stem}"


st.markdown("### Data Center System")
st.caption("Systems engineering for co-located data centers")
st.caption(
    "All projects are public: anyone using this app can open and change any project. "
    "To keep work private, run your own copy of the app (fork the GitHub repository)."
)

col_open, col_new = st.columns(2, gap="medium")
with col_open, st.container(border=True):
    st.markdown("**Open project**")
    entries = state.store().list_projects()
    if entries:
        choice = st.selectbox(
            "Saved projects (newest first; type to search)", entries, format_func=_label
        )
        if st.button("Open project"):
            try:
                _open(state.store().load_project(choice.stem), choice.stem)
            except ProjectFileError as e:
                st.error(str(e))
    else:
        st.caption("No saved projects yet.")
    upload = st.file_uploader("Or open a project file (.json)", type=["json"])
    if upload is not None and st.button("Open uploaded file"):
        try:
            _open(from_json(upload.getvalue()))
        except ProjectFileError as e:
            st.error(str(e))

with col_new, st.container(border=True):
    st.markdown("**New setup**")
    if st.button("Start new setup", type="primary"):
        _open(Project())
