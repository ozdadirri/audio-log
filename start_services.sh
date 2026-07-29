#!/bin/bash
# Starts/ensures the machine-level services audio-log depends on: Postgres,
# Ollama (listening on all interfaces), MinIO, and finally the whisper
# transcription service itself (runs in the foreground; this is the last
# thing the script does). Run this once after a reboot (or add it to Login
# Items). The main app (start_audiolog.sh) can run on this or another machine.
set -euo pipefail

# True if something is already listening on TCP port $1.
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# Postgres: brew services already keeps this running across reboots, but make
# sure it's up. Safe to rerun — brew no-ops if already started.
brew services start postgresql@16

# Ollama listens on localhost only by default; this makes it reachable from
# other machines (e.g. the audio-log app running elsewhere). Only affects
# apps started after this runs, so (re)start Ollama after running this script.
# Safe to rerun — idempotent.
launchctl setenv OLLAMA_HOST 0.0.0.0

# MinIO: run in the background, logging to ~/minio-data/minio.log. Skipped if
# already running (rerunning would just fail to bind the port).
if port_busy 9000; then
    echo "minio: already running on :9000, skipping"
else
    MINIO_ROOT_USER=admin MINIO_ROOT_PASSWORD='MyKey2minio!' \
      minio server ~/minio-data --console-address ":9001" \
      > ~/minio-data/minio.log 2>&1 &
    echo "minio started, pid $!, logging to ~/minio-data/minio.log"
fi

# whisper service: runs in the foreground as the last step. Skipped (instead
# of failing on a bind error) if already running.
if port_busy 8301; then
    echo "whisper: already running on :8301, nothing more to do"
else
    cd "$(dirname "$0")/whisper_service"
    exec ../.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8301
fi