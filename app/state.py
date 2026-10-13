"""Typed access to st.session_state. Never use raw session_state keys elsewhere.

The whole configuration lives in one `Project`; every change goes through
`set_project`, which autosaves when the project actually changed (D-010).
Widget keys start with `WIDGET_PREFIX` so opening a project can reset them.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import streamlit as st

from core.config.defaults import PERSISTENCE
from core.persistence.project import Project, to_json
from core.site_layout import normalize_layout
from core.weather.tmy import WeatherMeta
from services.store import Store, default_store, new_stem, utcnow


class Tab(StrEnum):
    """Workspace input tabs, in workflow order (docs/workflow/01-setup-tabs.md)."""

    LOCATION = "location"
    PROPERTY = "property"
    DATA_CENTER = "data_center"
    UTILITY = "utility"
    MODULES = "modules"
    CONTROL = "control"

    @property
    def label(self) -> str:
        return TAB_LABELS[self]


TAB_LABELS = {
    Tab.LOCATION: "Location",
    Tab.PROPERTY: "Property",
    Tab.DATA_CENTER: "Data center",
    Tab.UTILITY: "Utility",
    Tab.MODULES: "Modules",
    Tab.CONTROL: "Control",
}
START_PAGE = "app/pages/start.py"
WORKSPACE_PAGE = "app/pages/workspace.py"

WIDGET_PREFIX = "w_"
_PROJECT = "project"
_LAST_SAVED_JSON = "project_last_saved_json"
_STEM = "project_autosave_stem"  # set only by open_project: no stem → no autosave
_LAST_SAVED_AT = "project_last_saved_at"  # this session's last autosave (UTC)
_DB_SEEN_AT = "project_db_seen_at"  # the saved row's time when this session last saw it
PROJECT_PARAM = "project"  # URL query parameter: ?project=<stem> (D-069)
_RESULTS = "results"
_MAP_VERSION = "map_version"
_MOUNT_VIEW = "map_mount_view"
_SEEN_EDIT = "map_seen_edit"


@dataclass(frozen=True)
class SiteResults:
    frame: pd.DataFrame
    weather: WeatherMeta
    inputs_hash: str  # inputs_hash + weather key the results were computed from


# --- project -----------------------------------------------------------------


def get_project() -> Project:
    p = st.session_state.get(_PROJECT)
    if not isinstance(p, Project):
        p = Project()
        st.session_state[_PROJECT] = p
    return p


def has_open_project() -> bool:
    """True once this session opened or created a project (D-040).

    A session that lost its state (e.g. reconnect after the session TTL) has no
    open project and must never autosave — it would overwrite real work.
    """
    return isinstance(st.session_state.get(_STEM), str)


def autosave_stem() -> str | None:
    stem = st.session_state.get(_STEM)
    return stem if isinstance(stem, str) else None


def last_autosave_at() -> datetime | None:
    t = st.session_state.get(_LAST_SAVED_AT)
    return t if isinstance(t, datetime) else None


def store() -> Store:
    """The database (services/store.py, D-069)."""
    return default_store()


def local_time(t: datetime) -> datetime:
    """A saved (UTC) time in the viewer's browser time zone."""
    try:
        return t.astimezone(ZoneInfo(st.context.timezone or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        return t


def set_project(p: Project, autosave: bool = True, force_snapshot: bool = False) -> None:
    """Store (and autosave) the project, after applying the site layout rules:
    blocks placed/resized, drawn areas cut back where blocks cover them (D-041).

    Projects are public (D-069): if another session saved this project since
    this one last did, its state is kept as a snapshot and a notice is shown."""
    p = normalize_layout(p)
    st.session_state[_PROJECT] = p
    text = to_json(p)
    stem = autosave_stem()
    if autosave and stem is not None and text != st.session_state.get(_LAST_SAVED_JSON):
        seen = st.session_state.get(_DB_SEEN_AT)
        r = store().write_autosave(
            p, stem, utcnow(), seen if isinstance(seen, datetime) else None, force_snapshot
        )
        st.session_state[_LAST_SAVED_JSON] = text
        st.session_state[_LAST_SAVED_AT] = r.updated_at
        st.session_state[_DB_SEEN_AT] = r.updated_at
        if r.overwrote_other:
            flash(
                "project",
                "warning",
                "Someone else changed this project while you had it open; your change "
                "replaced theirs. Their state is in Versions → Automatic snapshots.",
            )


def _reset_session_views() -> None:
    for key in [k for k in st.session_state if str(k).startswith(WIDGET_PREFIX)]:
        del st.session_state[key]
    st.session_state.pop(_RESULTS, None)
    bump_map_version()


def open_project(p: Project, stem: str | None = None) -> None:
    """Make `p` this session's project. `stem`: the saved project it came from
    (keeps saving there); None → a new, unique project (saved on its first change)."""
    _reset_session_views()
    st.session_state[_STEM] = stem or new_stem(p.name, PERSISTENCE)
    st.session_state[_LAST_SAVED_JSON] = to_json(p) if stem else None
    st.session_state[_LAST_SAVED_AT] = None
    st.session_state[_DB_SEEN_AT] = store().updated_at(stem) if stem else None
    st.session_state[_PROJECT] = p


def restore_project(p: Project) -> None:
    """Replace the working project with a saved version or snapshot (same autosave
    file). The current state is snapshotted to history first."""
    _reset_session_views()
    set_project(p, force_snapshot=True)


def seed(key: str, value: Any) -> None:
    """Give a widget its initial value from the project (only if unset)."""
    if key not in st.session_state:
        st.session_state[key] = value


# --- results -----------------------------------------------------------------


def get_results() -> SiteResults | None:
    r = st.session_state.get(_RESULTS)
    return r if isinstance(r, SiteResults) else None


def set_results(r: SiteResults) -> None:
    st.session_state[_RESULTS] = r


# --- messages from callbacks -------------------------------------------------

_FLASH = "flash_messages"


def flash(where: str, level: str, message: str) -> None:
    """Queue a message (level: error/warning/info/success) to show at `where` next render."""
    st.session_state.setdefault(_FLASH, []).append((where, level, message))


def show_flash(where: str) -> None:
    queued: list[tuple[str, str, str]] = st.session_state.get(_FLASH, [])
    keep = []
    for w, level, message in queued:
        if w != where:
            keep.append((w, level, message))
        elif level == "error":
            st.error(message)
        elif level == "warning":
            st.warning(message)
        elif level == "info":
            st.info(message)
        else:
            st.success(message)
    st.session_state[_FLASH] = keep


# --- map ---------------------------------------------------------------------


def map_version() -> int:
    return int(st.session_state.get(_MAP_VERSION, 0))


def bump_map_version() -> None:
    """Remount the map: recentres it and clears finished drawings."""
    st.session_state[_MAP_VERSION] = map_version() + 1


_PENDING_SELECT = "pending_selection"


def request_selection(tab: "Tab", module: str | None = None) -> None:
    """Ask the next run to open `tab` (and select `module` on the Modules tab).

    The tabs widget is already drawn when the map is clicked, so the change is
    applied at the start of the next run (pop_selection).
    """
    st.session_state[_PENDING_SELECT] = (tab, module)


def pop_selection() -> "tuple[Tab, str | None] | None":
    value = st.session_state.pop(_PENDING_SELECT, None)
    return value if isinstance(value, tuple) else None


def mount_view(version: int, current: Any) -> Any:
    """The view a map mount opens on, frozen per map version.

    Panning on the Location tab updates the saved view; keeping the mount view
    fixed stops the map re-rendering (and re-fitting) on every pan.
    """
    stored = st.session_state.get(_MOUNT_VIEW)
    if not stored or stored[0] != version:
        stored = (version, current)
        st.session_state[_MOUNT_VIEW] = stored
    return stored[1]


def tab_for(step: str) -> Tab:
    """Tab stored in a project; older values (site_setup, …) open on Location."""
    return Tab(step) if step in {t.value for t in Tab} else Tab.LOCATION


def edit_is_new(event_id: str | None) -> bool:
    """True once per footprint-editor event (the component re-sends its last value)."""
    if event_id is None or event_id == st.session_state.get(_SEEN_EDIT):
        return False
    st.session_state[_SEEN_EDIT] = event_id
    return True
