"""Central configuration. Every value can be overridden with an environment variable."""

import os
from pathlib import Path

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

DB_PATH = Path(os.getenv("AUDIOLOG_DB", DATA_DIR / "audiolog.db"))

WHISPER_MODEL = os.getenv("AUDIOLOG_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("AUDIOLOG_OLLAMA_MODEL", "qwen3.6:27b")

# If set, every /api request must carry this key (X-API-Key header, ?key= query
# param, or audiolog_key cookie). Empty = auth disabled.
API_KEY = os.getenv("AUDIOLOG_API_KEY", "")

# How often (seconds) the ingest loop scans INPUT_DIR for new files.
SCAN_INTERVAL = float(os.getenv("AUDIOLOG_SCAN_INTERVAL", "3"))

AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus",
    ".aiff", ".aif", ".wma", ".amr", ".mp4", ".webm", ".mov",
}

for _dir in (DATA_DIR, INPUT_DIR, OUTPUT_DIR):
    _dir.mkdir(parents=True, exist_ok=True)
