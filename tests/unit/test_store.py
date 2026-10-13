"""The database: autosave, history snapshots, saved versions, the type
library, and importing the old files (D-040, D-069)."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from core.config.defaults import CoolingType, PersistenceSettings
from core.domain.datacenter_type import DataCenterType
from core.domain.site import Site
from core.persistence.project import Project, ProjectFileError, to_json
from services.import_files import import_files
from services.store import Store, database_url, metadata, new_stem

S = PersistenceSettings(history_min_interval_s=300, history_keep=3)
T0 = datetime(2026, 10, 5, 9, 0, 0, tzinfo=UTC)


PG_TEST_URL = os.environ.get("PG_TEST_URL", "")  # optional: also run against a real Postgres


@pytest.fixture(params=["sqlite", "postgres"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Store:
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'unit.sqlite'}")
    elif PG_TEST_URL:
        engine = create_engine(database_url({"DATABASE_URL": PG_TEST_URL}))
        metadata.drop_all(engine)
    else:
        pytest.skip("set PG_TEST_URL to also test against Postgres")
    metadata.create_all(engine)
    return Store(engine, S)


def _p(lat: float, name: str = "Golden") -> Project:
    return Project(site=Site(name=name, lat=lat, lon=-105.2))


# --- where the database is --------------------------------------------------------


def test_database_url_env_then_secrets_then_sqlite(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets.toml"
    assert database_url({}, secrets).startswith("sqlite:///")
    secrets.write_text('DATABASE_URL = "postgresql://u:p@host/db?sslmode=require"\n')
    assert database_url({}, secrets) == "postgresql+psycopg://u:p@host/db?sslmode=require"
    env = {"DATABASE_URL": "postgres://a@b/c"}
    assert database_url(env, secrets) == "postgresql+psycopg://a@b/c"  # env wins


def test_new_stems_are_unique_per_project() -> None:
    a, b = new_stem("Untitled site", S), new_stem("Untitled site", S)
    assert a != b and a.startswith("untitled-site-")


# --- projects ------------------------------------------------------------------------


def test_round_trip_and_list_newest_first(store: Store) -> None:
    store.write_autosave(_p(1, "Old"), "a", T0)
    store.write_autosave(_p(2, "New"), "b", T0 + timedelta(minutes=1))
    assert [(e.stem, e.name) for e in store.list_projects()] == [("b", "New"), ("a", "Old")]
    assert store.list_projects()[0].updated_at == T0 + timedelta(minutes=1)
    assert store.load_project("a") == _p(1, "Old")
    with pytest.raises(ProjectFileError, match="No saved project"):
        store.load_project("nope")


def test_autosave_snapshots_previous_content_throttled(store: Store) -> None:
    store.write_autosave(_p(1), "g", T0)
    assert store.list_history("g") == []  # nothing to snapshot yet
    store.write_autosave(_p(2), "g", T0 + timedelta(seconds=10))
    (snap,) = store.list_history("g")
    assert store.load_snapshot(snap.id).site.lat == 1  # the overwritten state
    store.write_autosave(_p(3), "g", T0 + timedelta(seconds=60))
    assert len(store.list_history("g")) == 1  # within 5 min: no new snapshot
    store.write_autosave(_p(4), "g", T0 + timedelta(seconds=60), force_snapshot=True)
    assert len(store.list_history("g")) == 2  # forced (e.g. before a restore)
    assert store.load_project("g").site.lat == 4


def test_history_pruned_to_keep(store: Store) -> None:
    for i in range(8):
        store.write_autosave(_p(i), "g", T0 + timedelta(minutes=10 * i))
    store.write_autosave(_p(0), "other", T0)
    store.write_autosave(_p(1), "other", T0 + timedelta(hours=1))
    history = store.list_history("g")
    assert len(history) == S.history_keep
    assert [store.load_snapshot(h.id).site.lat for h in history] == [6, 5, 4]  # newest first
    assert len(store.list_history("other")) == 1  # pruning is per project


def test_saved_versions_are_never_overwritten(store: Store) -> None:
    store.write_autosave(_p(1), "g", T0)
    v = store.save_version(_p(1), "g", "Before solar!", T0)
    for i in range(5):
        store.write_autosave(_p(10 + i), "g", T0 + timedelta(minutes=10 * i))
    assert store.load_snapshot(v.id).site.lat == 1
    store.save_version(_p(2), "g", "  ", T0 + timedelta(hours=1))
    versions = store.list_versions("g")
    assert [x.label for x in versions] == ["version", "Before solar!"]  # newest first
    assert versions[1].saved_at == T0
    assert [e.stem for e in store.list_projects()] == ["g"]  # versions aren't projects


def test_another_sessions_save_is_snapshotted_before_it_is_replaced(store: Store) -> None:
    """Two sessions on one public project (D-069): B's save is newer than what A
    saw, so A's next autosave keeps B's state as a snapshot, even within the
    5 min throttle, and says so."""
    a_saw = store.write_autosave(_p(1), "g", T0).updated_at
    store.write_autosave(_p(2), "g", T0 + timedelta(seconds=10))  # B; snapshots 1
    r = store.write_autosave(_p(3), "g", T0 + timedelta(seconds=20), expected=a_saw)  # A
    assert r.overwrote_other
    assert [store.load_snapshot(h.id).site.lat for h in store.list_history("g")] == [2, 1]
    again = store.write_autosave(_p(4), "g", T0 + timedelta(seconds=30), expected=r.updated_at)
    assert not again.overwrote_other


# --- data center types -----------------------------------------------------------


def test_type_save_and_list(store: Store) -> None:
    a = DataCenterType(cooling_type=CoolingType.EVAPORATIVE)
    b = DataCenterType()
    assert store.save_type(a).created
    assert store.save_type(b).created
    assert store.list_types() == [b, a]  # sorted by name: "Dry …" before "Evap …"


def test_identical_design_returns_saved_version(store: Store) -> None:
    first = store.save_type(DataCenterType(rack_density_kw=80))
    again = store.save_type(DataCenterType(rack_density_kw=80.0000000001))
    assert first.created and not again.created
    assert again.type == first.type
    assert len(store.list_types()) == 1


def test_seed_types_from_repo_files(store: Store, tmp_path: Path) -> None:
    folder = tmp_path / "types"
    folder.mkdir()
    legacy = DataCenterType().model_dump(exclude={"name"}) | {"schema_version": 1, "name": "Old"}
    (folder / "old.json").write_text(json.dumps(legacy))
    (folder / "junk.json").write_text("{not json")
    assert store.seed_types(folder) == 1
    assert store.seed_types(folder) == 0  # already there
    (loaded,) = store.list_types()
    assert loaded == DataCenterType()
    assert loaded.name.startswith("Dry ·")


def test_repo_types_seed_the_default_store(isolated_db: Store) -> None:
    """Types shipped in data/datacenter_types/ are in a new database (the
    test data folder has none, so the test database starts empty)."""
    assert isolated_db.list_types() == []


# --- importing the old files ---------------------------------------------------------


def test_import_old_files(store: Store, tmp_path: Path) -> None:
    data = tmp_path / "data"
    pdir = data / "projects"
    (pdir / "history" / "golden-1").mkdir(parents=True)
    (pdir / "versions" / "golden-1").mkdir(parents=True)
    (pdir / "golden-1.json").write_text(to_json(_p(3)))
    (pdir / "history" / "golden-1" / "20261005-090000.json").write_text(to_json(_p(1)))
    (pdir / "versions" / "golden-1" / "20261005-100000__before-solar.json").write_text(
        to_json(_p(2))
    )
    (pdir / "broken.json").write_text("{nope")
    (data / "datacenter_types").mkdir()
    (data / "datacenter_types" / "t.json").write_text(DataCenterType().model_dump_json())

    r = import_files(data, store)
    assert (r.projects, r.snapshots, r.types, r.skipped) == (1, 2, 1, ("broken",))
    assert store.load_project("golden-1").site.lat == 3
    (v,) = store.list_versions("golden-1")
    assert v.label == "before solar" and store.load_snapshot(v.id).site.lat == 2
    (h,) = store.list_history("golden-1")
    assert store.load_snapshot(h.id).site.lat == 1
    assert import_files(data, store).projects == 0  # running it again is harmless
