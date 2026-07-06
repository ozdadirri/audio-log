"""Permanent removal of a recording and everything derived from it.
Shared by the delete-forever endpoint and the trash auto-purge."""

import logging
import shutil
from pathlib import Path

from . import db, thumbnail, transcode

log = logging.getLogger("audiolog")


def hard_delete(row: dict):
    src = Path(row["source_path"])
    if src.exists():
        src.unlink()
    if row.get("output_dir"):
        shutil.rmtree(row["output_dir"], ignore_errors=True)
    for p in thumbnail.THUMB_DIR.glob(f"{row['sha256']}*.png"):
        p.unlink(missing_ok=True)
    (transcode.CACHE_DIR / f"{row['sha256']}.m4a").unlink(missing_ok=True)
    db.delete_file(row["id"])
    log.info("hard-deleted %s (id=%s)", row["filename"], row["id"])
