"""On-disk cache for raw API responses (docs/integrations/nsrdb-weather.md)."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR_ENV = "DCS_CACHE_DIR"  # override, e.g. to keep downloads out of OneDrive


def cache_root() -> Path:
    """`$DCS_CACHE_DIR` if set, else `data/cache/` in the project (gitignored)."""
    override = os.environ.get(CACHE_DIR_ENV)
    return Path(override) if override else PROJECT_ROOT / "data" / "cache"


class DiskCache:
    """Text files keyed by name under one directory. Writes are atomic."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, key: str) -> Path:
        return self.directory / key

    def read(self, key: str) -> str | None:
        p = self.path(key)
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def write(self, key: str, text: str) -> Path:
        p = self.path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
        return p
