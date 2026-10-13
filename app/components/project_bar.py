"""Project bar above the workspace: name, autosave status, saved versions,
download (docs/gui.md → Project bar, D-040).

Autosave keeps one working copy per project in the database (D-069). "Save
version" writes a named copy that autosave never touches; "Versions" restores a
saved version or an automatic snapshot (the current state is snapshotted
first). "Link" is this project's URL: anyone with it opens the project.
"""

import streamlit as st

from app import state
from core.persistence.files import slugify
from core.persistence.project import ProjectFileError, to_json
from services.store import SavedVersion, utcnow

K_NAME = f"{state.WIDGET_PREFIX}site_name"
K_LABEL = "version_label"
HISTORY_SHOWN = 10


def _rename() -> None:
    name = str(st.session_state[K_NAME]).strip()
    if name:
        p = state.get_project()
        state.set_project(p.model_copy(update={"site": p.site.model_copy(update={"name": name})}))


def _save_version() -> None:
    stem = state.autosave_stem()
    if stem is None:
        return
    label = str(st.session_state.get(K_LABEL, "")).strip()
    state.store().save_version(state.get_project(), stem, label, utcnow())
    st.session_state[K_LABEL] = ""
    state.flash("project", "success", f"Saved version “{label or 'version'}”.")


def _restore(v: SavedVersion) -> None:
    try:
        p = state.store().load_snapshot(v.id)
    except ProjectFileError as e:
        state.flash("project", "error", str(e))
        return
    state.restore_project(p)
    state.flash(
        "project",
        "success",
        f"Restored “{v.label}” ({state.local_time(v.saved_at):%Y-%m-%d %H:%M}). "
        "Your previous state is in the automatic snapshots.",
    )


def _version_rows(versions: list[SavedVersion], kind: str) -> None:
    for i, v in enumerate(versions):
        c1, c2 = st.columns([0.7, 0.3], vertical_alignment="center")
        c1.markdown(
            f"{v.label}  \n<small>{state.local_time(v.saved_at):%Y-%m-%d %H:%M}</small>",
            unsafe_allow_html=True,
        )
        c2.button("Restore", key=f"restore_{kind}_{i}", on_click=_restore, args=(v,))


def project_link(stem: str) -> str:
    """This page's address with ?project=<stem> (D-069)."""
    base = str(st.context.url or "").split("?")[0]
    return f"{base}?{state.PROJECT_PARAM}={stem}"


def render_project_bar() -> None:
    p = state.get_project()
    stem = state.autosave_stem()
    state.seed(K_NAME, p.site.name)
    c_name, c_status, c_save, c_versions, c_link, c_download = st.columns(
        [0.26, 0.22, 0.13, 0.13, 0.13, 0.13], vertical_alignment="bottom"
    )
    with c_name:
        st.text_input("Project", key=K_NAME, on_change=_rename)
    with c_status:
        saved = state.last_autosave_at()
        when = (
            f"Autosaved {state.local_time(saved):%H:%M:%S}"
            if saved
            else "Autosave on (no changes yet)"
        )
        st.caption(when if stem else "Not saved")
    with c_save, st.popover("Save version", width="stretch"):
        st.caption("A named copy that autosave never overwrites.")
        st.text_input("Version name", key=K_LABEL, placeholder="e.g. before solar")
        st.button("Save", type="primary", on_click=_save_version, disabled=stem is None)
    with c_versions, st.popover("Versions", width="stretch"):
        versions = state.store().list_versions(stem) if stem else []
        st.markdown("**Saved versions**")
        if versions:
            _version_rows(versions, "version")
        else:
            st.caption("None yet — use “Save version”.")
        history = state.store().list_history(stem)[:HISTORY_SHOWN] if stem else []
        st.markdown("**Automatic snapshots**")
        if history:
            _version_rows(history, "history")
        else:
            st.caption("Taken automatically (at most every 5 min) as you work.")
    with c_link, st.popover("Link", width="stretch"):
        if state.last_autosave_at() is None and not state.store().updated_at(stem or ""):
            st.caption("The link works once the project is saved (after your first change).")
        st.caption("Anyone with this link opens this project (all projects are public).")
        st.code(project_link(stem or ""), language=None)
    with c_download:
        st.download_button(
            "Download",
            data=to_json(p),
            file_name=f"{slugify(p.name)}.json",
            mime="application/json",
            width="stretch",
            help="Save the project file to your computer (open it later from Start).",
        )
    state.show_flash("project")
