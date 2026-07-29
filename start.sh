#!/bin/bash
# Starts both audio-log services: the whisper transcription service (port 8301)
# and the main app (port 8300). Each runs as its own background process so they
# can be stopped/restarted independently; Ctrl+C here stops both.
set -euo pipefail
cd "$(dirname "$0")"

launchctl setenv OLLAMA_HOST 0.0.0.0

(cd whisper_service && exec ../.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8301) &
WHISPER_PID=$!

.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8300 --reload &
AUDIOLOG_PID=$!

trap 'kill "$AUDIOLOG_PID" "$WHISPER_PID" 2>/dev/null' EXIT INT TERM

wait "$AUDIOLOG_PID" "$WHISPER_PID"
