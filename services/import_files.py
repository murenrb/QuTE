"""Copy projects and types saved as files (before the database, D-069) into
the database (docs/data-model.md → Database).

    python -m services.import_files [data folder]

The folder (default: this project's data/) has the old layout:
    projects/<stem>.json                              autosaves
    projects/history/<stem>/<YYYYmmdd-HHMMSS>.json    automatic snapshots
    projects/versions/<stem>/<YYYYmmdd-HHMMSS>__<label>.json   saved versions
    datacenter_types/*.json

It writes to the database `DATABASE_URL` names (env or .streamlit/secrets.toml;
else the local SQLite file). Projects already in the database are skipped,
so running it twice is harmless. File times were local; they become UTC.
"""

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import insert

from core.persistence.files import data_root
from core.persistence.project import ProjectFileError, from_json, to_json
from services.store import HISTORY, VERSION, Store, default_store, projects, snapshots

STAMP = "%Y%m%d-%H%M%S"
LABEL_SEP = "__"


@dataclass(frozen=True)
class ImportReport:
    projects: int
    snapshots: int
    types: int
    skipped: tuple[str, ...]  # already in the database, or unreadable


def _local_to_utc(t: datetime) -> datetime:
    return t.astimezone(UTC)  # naive = local time


def _snapshot_rows(folder: Path, stem: str, kind: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for f in sorted(folder.glob("*.json")):
        stamp, _, label = f.stem.partition(LABEL_SEP)
        try:
            when = datetime.strptime(stamp, STAMP)
            text = to_json(from_json(f.read_bytes()))
        except (ValueError, OSError):
            continue
        rows.append(
            {
                "stem": stem,
                "kind": kind,
                "label": label.replace("-", " ") or ("autosave" if kind == HISTORY else "version"),
                "saved_at": _local_to_utc(when),
                "data": text,
            }
        )
    return rows


def import_files(folder: Path, store: Store) -> ImportReport:
    known = {e.stem for e in store.list_projects()}
    pdir = folder / "projects"
    n_projects = n_snaps = 0
    skipped = []
    for f in sorted(pdir.glob("*.json")):
        stem = f.stem
        try:
            p = from_json(f.read_bytes())
        except (ProjectFileError, OSError):
            skipped.append(stem)
            continue
        if stem in known:
            skipped.append(stem)
            continue
        rows = _snapshot_rows(pdir / "history" / stem, stem, HISTORY)
        rows += _snapshot_rows(pdir / "versions" / stem, stem, VERSION)
        modified = _local_to_utc(datetime.fromtimestamp(f.stat().st_mtime))
        with store.engine.begin() as c:
            c.execute(
                insert(projects).values(
                    stem=stem, name=p.name, updated_at=modified, data=to_json(p)
                )
            )
            if rows:
                c.execute(insert(snapshots), rows)
        n_projects += 1
        n_snaps += len(rows)
    n_types = store.seed_types(folder / "datacenter_types")
    return ImportReport(n_projects, n_snaps, n_types, tuple(skipped))


def main(argv: list[str]) -> None:
    folder = Path(argv[1]) if len(argv) > 1 else data_root()
    r = import_files(folder, default_store())
    print(
        f"Imported {r.projects} projects ({r.snapshots} snapshots / versions) and "
        f"{r.types} data center types from {folder}."
    )
    if r.skipped:
        print(f"Skipped (already in the database, or unreadable): {', '.join(r.skipped)}")


if __name__ == "__main__":
    main(sys.argv)
