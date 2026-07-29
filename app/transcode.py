"""On-demand transcoding of browser-unfriendly audio (aiff, wma, amr, ...) to
m4a for in-browser playback. Cached in object storage under
transcode/<sha256>.m4a (see app/storage.py)."""

import logging
import subprocess
import tempfile
from pathlib import Path

from . import storage

log = logging.getLogger("audiolog")

# Formats all major browsers decode natively; everything else gets transcoded.
# .webm is excluded on purpose: MediaRecorder output lacks duration/seek cues,
# so recordings are transcoded to m4a to make the player seekable.
BROWSER_SAFE = {".mp3", ".m4a", ".mp4", ".wav", ".flac", ".ogg", ".opus", ".aac"}


def playable_key(sha256: str, source_key: str) -> str | None:
    """Return a browser-playable object key for `source_key`: the key itself if
    the format is safe, else a cached m4a transcode's key. None if transcoding
    fails or the source is missing."""
    ext = Path(source_key).suffix.lower()
    if ext in BROWSER_SAFE:
        return source_key
    dest_key = f"transcode/{sha256}.m4a"
    if storage.exists(dest_key):
        return dest_key
    source = storage.download_to_temp(source_key, suffix=ext)
    if source is None:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".m4a") as tmp:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-vn",
                 "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", tmp.name],
                capture_output=True, check=True,
            )
            storage.upload(dest_key, Path(tmp.name), content_type="audio/mp4")
    except subprocess.CalledProcessError as e:
        log.error("transcode failed for %s: %s", source_key, e.stderr.decode(errors="replace"))
        return None
    finally:
        source.unlink(missing_ok=True)
    return dest_key
