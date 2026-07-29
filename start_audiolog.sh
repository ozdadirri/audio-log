#!/bin/bash
# Starts the main audio-log app (port 8300). Transcription is handled by the
# whisper service, which runs separately — usually on another machine; see
# start_whisper.sh and WHISPER_URL in .env.
set -euo pipefail
cd "$(dirname "$0")"

exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8300 --reload
