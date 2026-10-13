"""Where local files live, and small helpers shared by the stores."""

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR_ENV = "DCS_DATA_DIR"  # override (tests, or to keep local data out of OneDrive)


def data_root() -> Path:
    override = os.environ.get(DATA_DIR_ENV)
    return Path(override) if override else PROJECT_ROOT / "data"


def types_dir() -> Path:
    """Data center types shipped with the repo (added to the database on start)."""
    return data_root() / "datacenter_types"


def slugify(name: str) -> str:
    """File-safe name: lowercase, runs of other characters → '-'."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "untitled"
