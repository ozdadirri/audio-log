"""On-demand transcoding of browser-unfriendly audio (aiff, wma, amr, ...) to
m4a for in-browser playback. Cached under DATA_DIR/transcode by content hash."""

import logging
import subprocess
from pathlib import Path

from . import config

log = logging.getLogger("audiolog")

CACHE_DIR = config.DATA_DIR / "transcode"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Formats all major browsers decode natively; everything else gets transcoded.
# .webm is excluded on purpose: MediaRecorder output lacks duration/seek cues,
# so recordings are transcoded to m4a to make the player seekable.
BROWSER_SAFE = {".mp3", ".m4a", ".mp4", ".wav", ".flac", ".ogg", ".opus", ".aac"}


def playable_path(sha256: str, source: Path) -> Path | None:
    """Return a browser-playable file for `source`: the file itself if the format
    is safe, else a cached m4a transcode. None if transcoding fails."""
    if source.suffix.lower() in BROWSER_SAFE:
        return source
    dest = CACHE_DIR / f"{sha256}.m4a"
    if dest.exists():
        return dest
    tmp = dest.with_suffix(".tmp.m4a")
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-vn",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)],
            capture_output=True, check=True,
        )
        tmp.replace(dest)
    except subprocess.CalledProcessError as e:
        log.error("transcode failed for %s: %s", source, e.stderr.decode(errors="replace"))
        tmp.unlink(missing_ok=True)
        return None
    return dest
