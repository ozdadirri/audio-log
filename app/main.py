"""FastAPI app: JSON API + bare HTML frontend, with the pipeline running in
background threads."""

import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import assistant, config, db, pipeline, thumbnail, transcode
from . import summarize as summarize_mod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    pipeline.start_background_threads()
    yield
    pipeline.stop_event.set()


app = FastAPI(title="audio-log", lifespan=lifespan)


@app.get("/")
def index():
    # no-cache: browsers must revalidate so stale page code never runs
    return FileResponse(STATIC_DIR / "index.html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/mictest")
def mictest():
    return FileResponse(STATIC_DIR / "mictest.html",
                        headers={"Cache-Control": "no-cache"})


@app.get("/api/files")
def list_files():
    return db.list_files()


@app.get("/api/files/{file_id}")
def get_file(file_id: int):
    row = db.get_file(file_id)
    if row is None:
        raise HTTPException(404)
    # Texts live in the DB; fall back to the markdown files for old rows.
    out = Path(row["output_dir"]) if row["output_dir"] else None
    for key, name in (("transcript", "transcript.md"), ("summary", "summary.md")):
        if row.get(key):
            continue
        f = out / name if out else None
        row[key] = f.read_text() if f and f.exists() else None
    return row


@app.get("/api/files/{file_id}/thumb")
def get_thumb(file_id: int):
    row = db.get_file(file_id)
    if row is None:
        raise HTTPException(404)
    path = thumbnail.get_or_create(row["sha256"], row["source_path"], row["created_at"])
    if path is None:
        raise HTTPException(404, "thumbnail unavailable")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "max-age=31536000, immutable"})


# Explicit types where Python's mimetypes guess is wrong or unplayable in browsers
# (e.g. .m4a -> audio/mp4a-latm, which Chrome refuses).
AUDIO_MEDIA_TYPES = {
    ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".aac": "audio/aac",
    ".opus": 'audio/ogg; codecs="opus"', ".oga": "audio/ogg",
}


@app.get("/api/files/{file_id}/audio")
def get_audio(file_id: int):
    row = db.get_file(file_id)
    if row is None or not Path(row["source_path"]).exists():
        raise HTTPException(404)
    path = transcode.playable_path(row["sha256"], Path(row["source_path"]))
    if path is None:
        raise HTTPException(500, "transcoding failed")
    filename = row["filename"] if path.suffix != ".m4a" else Path(row["filename"]).stem + ".m4a"
    # inline, not attachment: browsers refuse to play <audio> marked as a download
    return FileResponse(path, filename=filename, content_disposition_type="inline",
                        media_type=AUDIO_MEDIA_TYPES.get(path.suffix.lower()))


@app.post("/api/upload")
def upload(file: UploadFile):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.AUDIO_EXTENSIONS:
        raise HTTPException(400, f"unsupported file type: {suffix or '(none)'}")
    dest = config.INPUT_DIR / Path(file.filename).name
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"saved": str(dest)}


@app.post("/api/files/{file_id}/rerun")
def rerun(file_id: int):
    row = db.get_file(file_id)
    if row is None:
        raise HTTPException(404)
    db.set_status(file_id, "pending")
    return {"status": "pending"}


@app.delete("/api/files/{file_id}")
def delete_file(file_id: int):
    row = db.get_file(file_id)
    if row is None:
        raise HTTPException(404)
    src = Path(row["source_path"])
    if src.exists():
        src.unlink()
    if row["output_dir"]:
        shutil.rmtree(row["output_dir"], ignore_errors=True)
    for p in thumbnail.THUMB_DIR.glob(f"{row['sha256']}*.png"):
        p.unlink(missing_ok=True)
    (transcode.CACHE_DIR / f"{row['sha256']}.m4a").unlink(missing_ok=True)
    db.delete_file(file_id)
    return {"deleted": file_id}


@app.post("/api/files/{file_id}/translate")
def translate(file_id: int):
    """Chinese translation of the summary, generated once and cached in the DB."""
    row = get_file(file_id)  # reuses the markdown-file fallback for old rows
    if row.get("summary_zh"):
        return {"summary_zh": row["summary_zh"]}
    if not row.get("summary"):
        raise HTTPException(409, "summary not ready yet")
    zh = summarize_mod.translate_zh(row["summary"])
    db.set_summary_zh(file_id, zh)
    return {"summary_zh": zh}


@app.get("/api/search")
def search(q: str = ""):
    return db.search(q)


class AskBody(BaseModel):
    question: str


@app.post("/api/ask")
def ask(body: AskBody):
    if not body.question.strip():
        raise HTTPException(400, "empty question")
    return assistant.ask(body.question)


@app.get("/api/config")
def get_config():
    return {
        "input_dir": str(config.INPUT_DIR),
        "output_dir": str(config.OUTPUT_DIR),
        "whisper_model": config.WHISPER_MODEL,
        "ollama_model": config.OLLAMA_MODEL,
    }
