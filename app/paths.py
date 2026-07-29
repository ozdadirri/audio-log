"""Portable storage of filesystem paths in the database.

Paths inside DATA_DIR are stored relative to it, so the database survives being
copied to another machine or the repo being moved. Paths outside DATA_DIR — the
externally configured input/output folders, e.g. a Google Drive-synced dir — have
no meaningful relative form and are stored absolute, so they stay machine-specific.
"""

from pathlib import Path

from . import config


def to_db(p: str | Path) -> str:
    """Relative to DATA_DIR when inside it, else absolute."""
    resolved = Path(p).resolve()
    try:
        return str(resolved.relative_to(config.DATA_DIR.resolve()))
    except ValueError:
        return str(resolved)


def from_db(stored: str | Path) -> Path:
    """Inverse of to_db: resolve a stored value back to a usable path."""
    p = Path(stored)
    return p if p.is_absolute() else config.DATA_DIR / p
