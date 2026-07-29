#!/bin/bash
# Starts the whisper transcription service (port 8301). Requires mlx-whisper, so
# this must run on an Apple Silicon Mac — not necessarily the one running the main
# app, which reaches it over the network via WHISPER_URL in .env.
set -euo pipefail
cd "$(dirname "$0")/whisper_service"

launchctl setenv OLLAMA_HOST 0.0.0.0

exec ../.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8301
