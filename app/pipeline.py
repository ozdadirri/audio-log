"""Background workers: an ingest loop that scans INPUT_DIR and a processing loop
that runs pending jobs through transcribe -> summarize -> write outputs.

The watched folder itself stays local disk (it has to — that's how files
arrive), but once a file is stable it's uploaded to object storage and its
local copy is removed; everything downstream (processing, outputs, caches)
lives in storage from then on, not on whichever machine happened to run the
worker."""

import hashlib
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import cleanup, config, db, storage, summarize, transcribe

log = logging.getLogger("audiolog")

stop_event = threading.Event()

TRASH_RETENTION_DAYS = 30
_last_purge = 0.0


def _purge_trash():
    """Hard-delete trash older than the retention window; runs ~hourly."""
    global _last_purge
    if time.monotonic() - _last_purge < 3600 and _last_purge:
        return
    _last_purge = time.monotonic()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=TRASH_RETENTION_DAYS)) \
        .isoformat(timespec="seconds")
    for row in db.trash_older_than(cutoff):
        try:
            cleanup.hard_delete(row)
        except Exception:
            log.exception("trash purge failed for id=%s", row["id"])

# path -> size at last scan; a file is ingested once its size is stable across
# two scans, so half-copied files (cloud sync, large uploads) are not picked up early.
_seen_sizes: dict[Path, int] = {}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ingest_loop():
    while not stop_event.is_set():
        try:
            _scan_once()
            _purge_trash()
        except Exception:
            log.exception("ingest scan failed")
        stop_event.wait(config.SCAN_INTERVAL)


def _scan_once():
    for input_dir in [config.INPUT_DIR, *config.EXTRA_INPUT_DIRS]:
        _scan_dir(input_dir)


def _scan_dir(input_dir: Path):
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in config.AUDIO_EXTENSIONS:
            continue
        size = path.stat().st_size
        if size == 0:
            continue
        if _seen_sizes.get(path) != size:
            _seen_sizes[path] = size  # first sighting or still growing; check next scan
            continue
        digest = _sha256(path)
        key = storage.unique_key("input", path.name)
        storage.upload(key, path)
        # Watched-folder files have no uploader; they belong to the admin.
        file_id = db.add_file(digest, path.name, key, user_id=db.admin_user_id())
        if file_id is not None:
            log.info("queued %s (id=%s)", path.name, file_id)
        else:
            storage.delete(key)  # duplicate content — already in storage under another key
        path.unlink()
        _seen_sizes.pop(path, None)


def worker_loop():
    while not stop_event.is_set():
        job = db.next_pending()
        if job is None:
            stop_event.wait(2)
            continue
        try:
            _process(job)
        except Exception as e:
            log.exception("job %s failed", job["id"])
            db.set_status(job["id"], "error", error=f"{type(e).__name__}: {e}")


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)


def _process(job):
    file_id = job["id"]
    source_key = job["source_path"]
    name = Path(source_key).name
    source = storage.download_to_temp(source_key, suffix=Path(source_key).suffix)
    if source is None:
        db.set_status(file_id, "error", error="source file no longer exists")
        return

    try:
        out_prefix = f"output/{_slug(Path(name).stem)}-{job['sha256'][:8]}"

        log.info("transcribing %s", name)
        db.set_status(file_id, "transcribing")
        result = transcribe.transcribe(str(source))
        transcript_md = transcribe.format_transcript_md(result, name)
        storage.upload_text(f"{out_prefix}/transcript.md", transcript_md)

        segments = result.get("segments", [])
        duration = float(segments[-1]["end"]) if segments else None

        log.info("summarizing %s", name)
        db.set_status(file_id, "summarizing")
        summary_md = summarize.summarize(result["text"].strip())
        storage.upload_text(f"{out_prefix}/summary.md", f"# Summary: {name}\n\n{summary_md}\n")

        storage.upload_text(f"{out_prefix}/meta.json", json.dumps({
            "filename": name,
            "source_path": source_key,
            "sha256": job["sha256"],
            "language": result.get("language"),
            "duration_seconds": duration,
            "whisper_model": config.WHISPER_MODEL,
            "summary_model": db.get_setting("ollama_model", config.LLM_MODEL),
        }, indent=2), content_type="application/json")

        try:
            title = summarize.make_title(summary_md)
            if title:
                db.set_title(file_id, title)
            tags = summarize.make_tags(summary_md)
            if tags:
                db.set_tags(file_id, tags)
        except Exception:
            log.exception("title/tag generation failed for %s", name)

        db.set_texts(file_id, transcript_md, summary_md)

        try:
            from . import embeddings
            embeddings.index_file(file_id)
        except Exception:
            log.exception("embedding failed for %s", name)
        db.set_result(file_id, language=result.get("language"), duration=duration,
                      output_dir=out_prefix)
        db.set_status(file_id, "done")
        log.info("done %s -> %s", name, out_prefix)

        if config.PUBLISH_DIR:
            try:
                publish_dir = config.PUBLISH_DIR / Path(out_prefix).name
                publish_dir.mkdir(parents=True, exist_ok=True)
                for fname in ("transcript.md", "summary.md", "meta.json"):
                    text = storage.download_text(f"{out_prefix}/{fname}")
                    if text is not None:
                        (publish_dir / fname).write_text(text)
                log.info("published %s to %s", Path(out_prefix).name, config.PUBLISH_DIR)
            except Exception:
                log.exception("publish failed for %s", Path(out_prefix).name)
    finally:
        source.unlink(missing_ok=True)

    # Auto-maintain the owner's long-term memory — but only once they've built
    # one; the first build stays a deliberate user action.
    try:
        row = db.get_file(file_id)
        owner = db.get_user_by_id(row["user_id"]) if row and row.get("user_id") else None
        if owner and db.get_memory(owner["id"]):
            from . import memory
            memory.build(owner)
    except Exception:
        log.exception("memory auto-update failed for %s", name)


def start_background_threads() -> list[threading.Thread]:
    threads = [
        threading.Thread(target=ingest_loop, name="ingest", daemon=True),
        threading.Thread(target=worker_loop, name="worker", daemon=True),
    ]
    for t in threads:
        t.start()
    return threads
