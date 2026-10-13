"""The database: projects (autosave, snapshots, saved versions) and the
DataCenterType library (docs/data-model.md → Database, D-069).

Everything is public: every project and type is visible to everyone using the
app (owner). Documents are stored as their JSON text, so the schema of the
tables never changes when a project's does; `from_json` migrates on load.

The database is a SQLAlchemy URL: `DATABASE_URL` from the environment
(Streamlit Cloud exposes root secrets this way), else `.streamlit/secrets.toml`,
else a SQLite file in the data folder (local use and tests).

Tables:
    projects            stem → the working autosave (overwritten on change)
    project_snapshots   automatic snapshots (kind "history", newest
                        `history_keep` kept) and saved versions (kind
                        "version", never overwritten or pruned)
    datacenter_types    one row per design; identical designs are not saved
                        twice (D-023)
"""

import os
import secrets
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import (
    Column,
    Connection,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    insert,
    select,
    update,
)

from core.config.defaults import PERSISTENCE, PersistenceSettings
from core.domain.datacenter_type import DataCenterType, type_file_stem
from core.persistence.files import PROJECT_ROOT, data_root, slugify, types_dir
from core.persistence.project import Project, ProjectFileError, from_json, to_json

URL_NAME = "DATABASE_URL"
SECRETS_FILE = PROJECT_ROOT / ".streamlit" / "secrets.toml"
HISTORY = "history"
VERSION = "version"

metadata = MetaData()
projects = Table(
    "projects",
    metadata,
    Column("stem", String(200), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("data", Text, nullable=False),
)
snapshots = Table(
    "project_snapshots",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("stem", String(200), nullable=False, index=True),
    Column("kind", String(20), nullable=False),  # HISTORY or VERSION
    Column("label", String(200), nullable=False),
    Column("saved_at", DateTime(timezone=True), nullable=False),
    Column("data", Text, nullable=False),
)
types = Table(
    "datacenter_types",
    metadata,
    Column("stem", String(200), primary_key=True),
    Column("name", String(300), nullable=False),
    Column("data", Text, nullable=False),
)


def database_url(env: Mapping[str, str] | None = None, secrets_file: Path = SECRETS_FILE) -> str:
    """`DATABASE_URL` from env, else secrets.toml, else SQLite in the data folder.
    Postgres URLs are pointed at the psycopg (v3) driver."""
    url = (os.environ if env is None else env).get(URL_NAME, "")
    if not url and secrets_file.is_file():
        with secrets_file.open("rb") as f:
            url = str(tomllib.load(f).get(URL_NAME, ""))
    if not url:
        return f"sqlite:///{data_root() / PERSISTENCE.sqlite_file}"
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url.removeprefix(prefix)
    return url


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_stem(name: str, s: PersistenceSettings = PERSISTENCE) -> str:
    """Unique id for a new project: `<name-slug>-<random>`, so two "Untitled
    site" projects never overwrite each other."""
    return f"{slugify(name)}-{secrets.token_hex(s.stem_suffix_hex // 2)}"


@dataclass(frozen=True)
class ProjectEntry:
    stem: str
    name: str
    updated_at: datetime  # UTC


@dataclass(frozen=True)
class SavedVersion:
    id: int
    label: str
    saved_at: datetime  # UTC


@dataclass(frozen=True)
class SaveOutcome:
    type: DataCenterType  # the saved version (existing one if it was a duplicate)
    created: bool


@dataclass(frozen=True)
class AutosaveResult:
    updated_at: datetime
    # Someone else saved this project after `expected` (two sessions on one
    # project): their state was snapshotted, then replaced.
    overwrote_other: bool


def _aware(t: datetime) -> datetime:
    """SQLite hands datetimes back naive; they were stored as UTC."""
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


class Store:
    """All reads and writes of saved projects and types."""

    def __init__(self, engine: Engine, s: PersistenceSettings = PERSISTENCE) -> None:
        self.engine = engine
        self.s = s

    # --- projects --------------------------------------------------------------

    def list_projects(self) -> list[ProjectEntry]:
        """Every saved project, most recently changed first."""
        q = select(projects.c.stem, projects.c.name, projects.c.updated_at).order_by(
            projects.c.updated_at.desc()
        )
        with self.engine.connect() as c:
            return [ProjectEntry(r.stem, r.name, _aware(r.updated_at)) for r in c.execute(q)]

    def load_project(self, stem: str) -> Project:
        with self.engine.connect() as c:
            text = c.execute(select(projects.c.data).where(projects.c.stem == stem)).scalar()
        if text is None:
            raise ProjectFileError(f"No saved project “{stem}”.")
        return from_json(text)

    def updated_at(self, stem: str) -> datetime | None:
        with self.engine.connect() as c:
            t = c.execute(select(projects.c.updated_at).where(projects.c.stem == stem)).scalar()
        return None if t is None else _aware(t)

    def write_autosave(
        self,
        p: Project,
        stem: str,
        now: datetime,
        expected: datetime | None = None,
        force_snapshot: bool = False,
    ) -> AutosaveResult:
        """Overwrite the working autosave, first snapshotting the previous
        content into history (at most every `history_min_interval_s` unless
        forced, e.g. before a restore; keeps the newest `history_keep`).

        expected: when this session last saved / opened the project. A newer
        save means another session changed it: its state is always snapshotted
        before it is replaced."""
        text = to_json(p)
        with self.engine.begin() as c:
            row = c.execute(
                select(projects.c.data, projects.c.updated_at).where(projects.c.stem == stem)
            ).first()
            other = row is not None and expected is not None and _aware(row.updated_at) > expected
            if row is not None and row.data != text:
                self._snapshot(c, stem, row.data, now, force_snapshot or other)
            values = {"name": p.name, "updated_at": now, "data": text}
            if row is None:
                c.execute(insert(projects).values(stem=stem, **values))
            else:
                c.execute(update(projects).where(projects.c.stem == stem).values(**values))
        return AutosaveResult(now, other)

    def _snapshot(self, c: Connection, stem: str, text: str, now: datetime, force: bool) -> None:
        is_history = (snapshots.c.stem == stem) & (snapshots.c.kind == HISTORY)
        last = c.execute(
            select(snapshots.c.saved_at).where(is_history).order_by(snapshots.c.saved_at.desc())
        ).scalar()
        recent = last is not None and (
            (now - _aware(last)).total_seconds() < self.s.history_min_interval_s
        )
        if recent and not force:
            return
        c.execute(
            insert(snapshots).values(
                stem=stem, kind=HISTORY, label="autosave", saved_at=now, data=text
            )
        )
        keep = (
            select(snapshots.c.id)
            .where(is_history)
            .order_by(snapshots.c.saved_at.desc(), snapshots.c.id.desc())
            .limit(self.s.history_keep)
        )
        c.execute(delete(snapshots).where(is_history & snapshots.c.id.not_in(keep)))

    def save_version(self, p: Project, stem: str, label: str, now: datetime) -> SavedVersion:
        """A named copy that autosave never touches."""
        label = label.strip() or "version"
        with self.engine.begin() as c:
            new_id = c.execute(
                insert(snapshots).values(
                    stem=stem, kind=VERSION, label=label, saved_at=now, data=to_json(p)
                )
            ).inserted_primary_key
        assert new_id is not None
        return SavedVersion(int(new_id[0]), label, now)

    def list_versions(self, stem: str) -> list[SavedVersion]:
        return self._list(stem, VERSION)

    def list_history(self, stem: str) -> list[SavedVersion]:
        return self._list(stem, HISTORY)

    def _list(self, stem: str, kind: str) -> list[SavedVersion]:
        """Newest first."""
        q = (
            select(snapshots.c.id, snapshots.c.label, snapshots.c.saved_at)
            .where((snapshots.c.stem == stem) & (snapshots.c.kind == kind))
            .order_by(snapshots.c.saved_at.desc(), snapshots.c.id.desc())
        )
        with self.engine.connect() as c:
            return [SavedVersion(r.id, r.label, _aware(r.saved_at)) for r in c.execute(q)]

    def load_snapshot(self, snapshot_id: int) -> Project:
        with self.engine.connect() as c:
            text = c.execute(select(snapshots.c.data).where(snapshots.c.id == snapshot_id)).scalar()
        if text is None:
            raise ProjectFileError("That saved version no longer exists.")
        return from_json(text)

    # --- data center types -----------------------------------------------------

    def list_types(self) -> list[DataCenterType]:
        """All readable saved types, sorted by name. Unreadable rows are skipped."""
        with self.engine.connect() as c:
            rows: list[str] = list(c.execute(select(types.c.data)).scalars())
        out = []
        for text in rows:
            try:
                out.append(DataCenterType.model_validate_json(text))
            except ValidationError:
                continue
        return sorted(out, key=lambda t: t.name.lower())

    def save_type(self, t: DataCenterType) -> SaveOutcome:
        """Save a new design, or return the already-saved identical design unchanged."""
        existing = next((s for s in self.list_types() if s.same_design(t)), None)
        if existing is not None:
            return SaveOutcome(existing, created=False)
        with self.engine.begin() as c:
            c.execute(
                insert(types).values(
                    stem=type_file_stem(t), name=t.name, data=t.model_dump_json(indent=2)
                )
            )
        return SaveOutcome(t, created=True)

    def seed_types(self, directory: Path) -> int:
        """Add the type files shipped in the repo (data/datacenter_types/) that
        the database doesn't have yet. Returns how many were added."""
        added = 0
        for f in sorted(directory.glob("*.json")):
            try:
                t = DataCenterType.model_validate_json(f.read_text(encoding="utf-8"))
            except (ValidationError, OSError):
                continue
            added += self.save_type(t).created
        return added


@cache
def _store(url: str) -> Store:
    """One engine per database (a pool of connections, checked before use:
    hosted Postgres closes idle ones). Creates missing tables and adds the
    repo's types, once per process."""
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, pool_pre_ping=True)
    metadata.create_all(engine)
    store = Store(engine)
    store.seed_types(types_dir())
    return store


def default_store() -> Store:
    return _store(database_url())


def open_store(url: str) -> Store:
    return _store(url)
