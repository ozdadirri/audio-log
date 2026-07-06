"""Background workers: an ingest loop that scans INPUT_DIR and a processing loop
that runs pending jobs through transcribe -> summarize -> write outputs."""

import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path

from . import config, db, summarize, transcribe

log = logging.getLogger("audiolog")

stop_event = threading.Event()

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
        except Exception:
            log.exception("ingest scan failed")
        stop_event.wait(config.SCAN_INTERVAL)


def _scan_once():
    for path in sorted(config.INPUT_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in config.AUDIO_EXTENSIONS:
            continue
        size = path.stat().st_size
        if size == 0:
            continue
        if _seen_sizes.get(path) != size:
            _seen_sizes[path] = size  # first sighting or still growing; check next scan
            continue
        digest = _sha256(path)
        # Watched-folder files have no uploader; they belong to the admin.
        file_id = db.add_file(digest, path.name, str(path), user_id=db.admin_user_id())
        if file_id is not None:
            log.info("queued %s (id=%s)", path.name, file_id)


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
    source = Path(job["source_path"])
    if not source.exists():
        db.set_status(file_id, "error", error="source file no longer exists")
        return

    out_dir = config.OUTPUT_DIR / f"{_slug(source.stem)}-{job['sha256'][:8]}"
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("transcribing %s", source.name)
    db.set_status(file_id, "transcribing")
    result = transcribe.transcribe(str(source))
    transcript_md = transcribe.format_transcript_md(result, source.name)
    (out_dir / "transcript.md").write_text(transcript_md)

    segments = result.get("segments", [])
    duration = float(segments[-1]["end"]) if segments else None

    log.info("summarizing %s", source.name)
    db.set_status(file_id, "summarizing")
    summary_md = summarize.summarize(result["text"].strip())
    (out_dir / "summary.md").write_text(f"# Summary: {source.name}\n\n{summary_md}\n")

    (out_dir / "meta.json").write_text(json.dumps({
        "filename": source.name,
        "source_path": str(source),
        "sha256": job["sha256"],
        "language": result.get("language"),
        "duration_seconds": duration,
        "whisper_model": config.WHISPER_MODEL,
        "summary_model": config.OLLAMA_MODEL,
    }, indent=2))

    try:
        title = summarize.make_title(summary_md)
        if title:
            db.set_title(file_id, title)
    except Exception:
        log.exception("title generation failed for %s", source.name)

    db.set_texts(file_id, transcript_md, summary_md)
    db.set_result(file_id, language=result.get("language"), duration=duration,
                  output_dir=str(out_dir))
    db.set_status(file_id, "done")
    log.info("done %s -> %s", source.name, out_dir)


def start_background_threads() -> list[threading.Thread]:
    threads = [
        threading.Thread(target=ingest_loop, name="ingest", daemon=True),
        threading.Thread(target=worker_loop, name="worker", daemon=True),
    ]
    for t in threads:
        t.start()
    return threads
