"""Central configuration. Every value can be overridden with an environment variable."""

import os
from pathlib import Path
from urllib.parse import quote

BASE_DIR = Path(__file__).resolve().parent.parent

# Load KEY=value lines from a git-ignored .env file (real env vars still win).
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _value = _line.partition("=")
            os.environ.setdefault(_key.strip(), _value.strip())

DATA_DIR = Path(os.getenv("AUDIOLOG_DATA_DIR", BASE_DIR / "data"))

# Drop audio files here (point this at a Google Drive-synced folder to ingest from Drive).
INPUT_DIR = Path(os.getenv("AUDIOLOG_INPUT_DIR", DATA_DIR / "input"))
# Results are written here (point at a Drive-synced folder to sync results back).
OUTPUT_DIR = Path(os.getenv("AUDIOLOG_OUTPUT_DIR", DATA_DIR / "output"))

# Extra watched folders, comma-separated (e.g. a Google Drive-synced dir).
EXTRA_INPUT_DIRS = [Path(p.strip()) for p in
                    os.getenv("AUDIOLOG_EXTRA_INPUT_DIRS", "").split(",") if p.strip()]

# If set, each finished job's outputs (transcript.md, summary.md, meta.json)
# are mirrored here — point it at a Drive-synced folder to publish digests.
PUBLISH_DIR = Path(os.getenv("AUDIOLOG_PUBLISH_DIR")) if os.getenv("AUDIOLOG_PUBLISH_DIR") else None

# Built from DATABASE_HOST/USER/PASSWORD/PORT/NAME so the password never has to
# be hand-escaped into a connection URL; set DATABASE_URL directly to override.
_db_host = os.getenv("DATABASE_HOST", "localhost")
_db_user = os.getenv("DATABASE_USER", "dadirri")
_db_password = os.getenv("DATABASE_PASSWORD", "")
_db_port = os.getenv("DATABASE_PORT", "5432")
_db_name = os.getenv("DATABASE_NAME", "audiolog")
_db_auth = f"{quote(_db_user)}:{quote(_db_password)}" if _db_password else quote(_db_user)
DATABASE_URL = os.getenv(
    "DATABASE_URL", f"postgresql://{_db_auth}@{_db_host}:{_db_port}/{_db_name}"
)

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
# Whisper transcription runs as a separate service (see whisper_service/), same
# pattern as LLM_API_URL below — keeps the mac/mlx-only dependency out of the main app.
# Point this at a Tailscale hostname to run it on another Mac.
WHISPER_URL = os.getenv("WHISPER_URL", "http://localhost:8301").rstrip("/")
# If set, sent as X-API-Key to the whisper service. Empty = no auth.
WHISPER_API_KEY = os.getenv("WHISPER_API_KEY", "")

# Chat + embedding models are served by an Ollama-compatible API, same pattern as
# WHISPER_URL above. Point this at a Tailscale hostname to run it on another Mac.
LLM_API_URL = os.getenv("LLM_API_URL", "http://localhost:11434").rstrip("/")
# If set, sent as `Authorization: Bearer ...`. Empty = no auth (plain Ollama).
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.6:27b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# If set, every /api request must carry this key (X-API-Key header, ?key= query
# param, or audiolog_key cookie). Empty = auth disabled.
API_KEY = os.getenv("AUDIOLOG_API_KEY", "")

# How often (seconds) the ingest loop scans INPUT_DIR for new files.
SCAN_INTERVAL = float(os.getenv("AUDIOLOG_SCAN_INTERVAL", "3"))

AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus",
    ".aiff", ".aif", ".wma", ".amr", ".mp4", ".webm", ".mov",
}

for _dir in (DATA_DIR, INPUT_DIR, OUTPUT_DIR, *EXTRA_INPUT_DIRS,
              *([PUBLISH_DIR] if PUBLISH_DIR else [])):
    _dir.mkdir(parents=True, exist_ok=True)
