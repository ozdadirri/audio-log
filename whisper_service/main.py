"""Standalone transcription microservice wrapping mlx-whisper, served over HTTP —
same pattern as running Ollama locally for LLMs. Keeps the mac/mlx-only dependency
isolated from the main app so the two can be deployed/updated independently.

Run from inside this directory: uvicorn main:app --host 0.0.0.0 --port 8301
"""

import os
from pathlib import Path

import mlx_whisper
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

# Load KEY=value lines from the repo-root .env (real env vars still win) — same
# file the main app reads, so WHISPER_* vars only need to be set once.
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _value = _line.partition("=")
            os.environ.setdefault(_key.strip(), _value.strip())

DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
# If set, requests must carry this key (X-API-Key header). Empty = auth disabled.
API_KEY = os.getenv("WHISPER_API_KEY", "")

app = FastAPI(title="whisper-service")


class TranscribeRequest(BaseModel):
    audio_path: str
    model: str | None = None


def _check_key(x_api_key: str | None):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


@app.get("/health")
def health():
    return {"status": "ok", "default_model": DEFAULT_MODEL}


@app.post("/transcribe")
def transcribe(req: TranscribeRequest, x_api_key: str | None = Header(None)) -> dict:
    """Returns {"text": str, "segments": [...], "language": str}."""
    _check_key(x_api_key)
    return mlx_whisper.transcribe(
        req.audio_path,
        path_or_hf_repo=req.model or DEFAULT_MODEL,
    )
