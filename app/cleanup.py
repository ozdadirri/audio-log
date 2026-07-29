"""Permanent removal of a recording and everything derived from it.
Shared by the delete-forever endpoint and the trash auto-purge."""

import logging

from . import db, storage

log = logging.getLogger("audiolog")


def hard_delete(row: dict):
    storage.delete(row["source_path"])
    if row.get("output_dir"):
        storage.delete_prefix(row["output_dir"] + "/")
    storage.delete_prefix(f"thumbs/{row['sha256']}")
    storage.delete(f"transcode/{row['sha256']}.m4a")
    db.delete_file(row["id"])
    log.info("hard-deleted %s (id=%s)", row["filename"], row["id"])
