"""Transcription via mlx-whisper. The model is loaded lazily on first use and cached
by mlx_whisper itself, so repeated calls are cheap."""

import mlx_whisper

from . import config


def transcribe(audio_path: str) -> dict:
    """Returns {"text": str, "segments": [...], "language": str}."""
    return mlx_whisper.transcribe(
        audio_path,
        path_or_hf_repo=config.WHISPER_MODEL,
    )


def format_transcript_md(result: dict, title: str) -> str:
    """Markdown transcript with [mm:ss] timestamps per segment."""
    lines = [f"# Transcript: {title}", ""]
    for seg in result.get("segments", []):
        start = int(seg["start"])
        lines.append(f"**[{start // 60:02d}:{start % 60:02d}]** {seg['text'].strip()}")
        lines.append("")
    return "\n".join(lines)
