"""Transcription client for the whisper_service HTTP microservice (see
whisper_service/main.py), which wraps mlx-whisper. Kept as a separate service so the
mac/mlx-only dependency can be run and updated independently of the main app."""

import httpx

from . import config


def transcribe(audio_path: str) -> dict:
    """Returns {"text": str, "segments": [...], "language": str}."""
    headers = {"X-API-Key": config.WHISPER_API_KEY} if config.WHISPER_API_KEY else {}
    resp = httpx.post(
        f"{config.WHISPER_URL}/transcribe",
        json={"audio_path": audio_path, "model": config.WHISPER_MODEL},
        headers=headers,
        timeout=None,
    )
    resp.raise_for_status()
    return resp.json()


def format_transcript_md(result: dict, title: str) -> str:
    """Markdown transcript with [mm:ss] timestamps per segment."""
    lines = [f"# Transcript: {title}", ""]
    for seg in result.get("segments", []):
        start = int(seg["start"])
        lines.append(f"**[{start // 60:02d}:{start % 60:02d}]** {seg['text'].strip()}")
        lines.append("")
    return "\n".join(lines)
