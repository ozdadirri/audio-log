"""FastAPI app: JSON API + bare HTML frontend, with the pipeline running in
background threads."""

import logging
import re
import shutil

import httpx
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import assistant, config, db, export, memory, pipeline, thumbnail, transcode
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
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def require_api_key(request, call_next):
    """Every /api request must carry a user's API key (X-API-Key header, ?key=
    query param, or audiolog_key cookie — query/cookie exist because
    <img>/<audio> loads can't set headers). The key identifies the user."""
    if request.url.path.startswith("/api"):
        supplied = (request.headers.get("x-api-key")
                    or request.query_params.get("key")
                    or request.cookies.get("audiolog_key"))
        user = db.get_user_by_key(supplied) if supplied else None
        if user is None:
            return JSONResponse({"detail": "invalid or missing API key"}, status_code=401)
        request.state.user = user
    return await call_next(request)


def _fetch_owned(file_id: int, request: Request) -> dict:
    """The file row, if it exists and the caller owns it (admin owns all).
    404 either way, so users can't probe for other people's file ids."""
    row = db.get_file(file_id)
    user = request.state.user
    if row is None or (not user["is_admin"] and row.get("user_id") != user["id"]):
        raise HTTPException(404)
    return row


def _require_admin(request: Request) -> dict:
    user = request.state.user
    if not user["is_admin"]:
        raise HTTPException(403, "admin only")
    return user


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
def list_files(request: Request):
    user = request.state.user
    return db.list_files(None if user["is_admin"] else user["id"])


@app.get("/api/files/{file_id}")
def get_file(file_id: int, request: Request):
    row = _fetch_owned(file_id, request)
    # Texts live in the DB; fall back to the markdown files for old rows.
    out = Path(row["output_dir"]) if row["output_dir"] else None
    for key, name in (("transcript", "transcript.md"), ("summary", "summary.md")):
        if row.get(key):
            continue
        f = out / name if out else None
        row[key] = f.read_text() if f and f.exists() else None
    return row


@app.get("/api/files/{file_id}/thumb")
def get_thumb(file_id: int, request: Request):
    row = _fetch_owned(file_id, request)
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
def get_audio(file_id: int, request: Request):
    row = _fetch_owned(file_id, request)
    if not Path(row["source_path"]).exists():
        raise HTTPException(404)
    path = transcode.playable_path(row["sha256"], Path(row["source_path"]))
    if path is None:
        raise HTTPException(500, "transcoding failed")
    filename = row["filename"] if path.suffix != ".m4a" else Path(row["filename"]).stem + ".m4a"
    # inline, not attachment: browsers refuse to play <audio> marked as a download
    return FileResponse(path, filename=filename, content_disposition_type="inline",
                        media_type=AUDIO_MEDIA_TYPES.get(path.suffix.lower()))


@app.get("/api/files/{file_id}/export")
def export_file(file_id: int, request: Request):
    """Self-contained HTML with summary, transcript, and embedded thumbnail."""
    row = get_file(file_id, request)  # ownership + markdown fallback
    thumb = thumbnail.get_or_create(row["sha256"], row["source_path"], row["created_at"])
    html_doc = export.render(row, thumb)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", (row.get("title") or Path(row["filename"]).stem))[:60]
    return Response(html_doc, media_type="text/html", headers={
        "Content-Disposition": f'attachment; filename="{stem}.html"'})


@app.post("/api/upload")
def upload(file: UploadFile, request: Request):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in config.AUDIO_EXTENSIONS:
        raise HTTPException(400, f"unsupported file type: {suffix or '(none)'}")
    dest = config.INPUT_DIR / Path(file.filename).name
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    # Register the row now so it belongs to the uploader; the folder scanner
    # would otherwise pick it up later and assign it to the admin.
    file_id = db.add_file(pipeline._sha256(dest), dest.name, str(dest),
                          user_id=request.state.user["id"])
    return {"saved": str(dest), "id": file_id}


@app.get("/api/memory")
def get_memory(request: Request):
    return memory.status(request.state.user)


@app.post("/api/memory/build")
def build_memory(request: Request):
    return memory.build(request.state.user)


@app.post("/api/memory/translate")
def translate_memory(request: Request):
    zh = memory.translate(request.state.user)
    if zh is None:
        raise HTTPException(409, "no memory to translate yet")
    return {"content_zh": zh}


@app.delete("/api/memory")
def reset_memory(request: Request):
    db.delete_memory(request.state.user["id"])
    return {"reset": True}


@app.get("/api/me")
def me(request: Request):
    user = request.state.user
    return {"id": user["id"], "username": user["username"],
            "is_admin": bool(user["is_admin"])}


@app.get("/api/users")
def list_users(request: Request):
    _require_admin(request)
    return db.list_users()


class UserBody(BaseModel):
    username: str


@app.post("/api/users")
def create_user(body: UserBody, request: Request):
    _require_admin(request)
    username = body.username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{2,30}", username):
        raise HTTPException(400, "username: 2-30 chars, letters/digits/_.- only")
    try:
        return db.create_user(username)
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, request: Request):
    admin = _require_admin(request)
    target = next((u for u in db.list_users() if u["id"] == user_id), None)
    if target is None:
        raise HTTPException(404)
    if target["is_admin"]:
        raise HTTPException(400, "cannot delete an admin account")
    db.delete_user(user_id, reassign_to=admin["id"])
    return {"deleted": user_id, "files_reassigned_to": admin["username"]}


@app.post("/api/files/{file_id}/rerun")
def rerun(file_id: int, request: Request):
    _fetch_owned(file_id, request)
    db.set_status(file_id, "pending")
    return {"status": "pending"}


@app.delete("/api/files/{file_id}")
def delete_file(file_id: int, request: Request):
    row = _fetch_owned(file_id, request)
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
def translate(file_id: int, request: Request):
    """Chinese translation of the summary, generated once and cached in the DB."""
    row = get_file(file_id, request)  # reuses the markdown-file fallback for old rows
    if row.get("summary_zh"):
        return {"summary_zh": row["summary_zh"]}
    if not row.get("summary"):
        raise HTTPException(409, "summary not ready yet")
    zh = summarize_mod.translate_zh(row["summary"])
    db.set_summary_zh(file_id, zh)
    return {"summary_zh": zh}


@app.post("/api/backfill-titles")
def backfill_titles(request: Request):
    """Admin: generate missing titles and tags for already-processed files."""
    _require_admin(request)
    titled = tagged = 0
    for row in db.list_files():
        if row["status"] != "done" or (row.get("title") and row.get("tags")):
            continue
        detail = db.get_file(row["id"])
        if not detail.get("summary"):
            continue
        if not row.get("title"):
            title = summarize_mod.make_title(detail["summary"])
            if title:
                db.set_title(row["id"], title)
                titled += 1
        if not row.get("tags"):
            tags = summarize_mod.make_tags(detail["summary"])
            if tags:
                db.set_tags(row["id"], tags)
                tagged += 1
    return {"titled": titled, "tagged": tagged}


@app.get("/api/search")
def search(request: Request, q: str = ""):
    user = request.state.user
    return db.search(q, None if user["is_admin"] else user["id"])


class HistoryTurn(BaseModel):
    question: str
    answer: str


class AskBody(BaseModel):
    question: str
    history: list[HistoryTurn] = []


@app.post("/api/ask")
def ask(body: AskBody, request: Request):
    if not body.question.strip():
        raise HTTPException(400, "empty question")
    return assistant.ask(body.question, request.state.user,
                         [t.model_dump() for t in body.history])


@app.get("/api/models")
def list_models():
    """Installed Ollama models plus the currently selected one."""
    try:
        resp = httpx.get(f"{config.OLLAMA_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
    except Exception as e:
        raise HTTPException(502, f"cannot reach Ollama: {e}")
    return {"models": models,
            "current": db.get_setting("ollama_model", config.OLLAMA_MODEL)}


class ModelBody(BaseModel):
    model: str


@app.post("/api/model")
def set_model(body: ModelBody):
    available = list_models()["models"]
    if body.model not in available:
        raise HTTPException(400, f"model not installed: {body.model}")
    db.set_setting("ollama_model", body.model)
    return {"current": body.model}


@app.get("/api/config")
def get_config():
    return {
        "input_dir": str(config.INPUT_DIR),
        "output_dir": str(config.OUTPUT_DIR),
        "whisper_model": config.WHISPER_MODEL,
        "ollama_model": db.get_setting("ollama_model", config.OLLAMA_MODEL),
    }
