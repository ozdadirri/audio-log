"""Square spectrogram thumbnails: ffmpeg decode -> numpy log-spectrogram ->
colormapped PNG, with the color scheme derived from the recording date so
different days are visually distinct. Cached under DATA_DIR/thumbs by content hash."""

import colorsys
import logging
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

from . import config

log = logging.getLogger("audiolog")

THUMB_DIR = config.DATA_DIR / "thumbs"
THUMB_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_RATE = 16000
SIZE = 512  # thumbnail is SIZE x SIZE pixels

# Golden angle spreads consecutive days far apart on the color wheel, so
# recordings from different days get clearly different hues while same-day
# recordings share a color family.
GOLDEN_ANGLE = 137.508


def date_hue(created_at: str) -> int:
    """Hue in degrees derived from the date part of an ISO timestamp."""
    days = date.fromisoformat(created_at[:10]).toordinal()
    return round(days * GOLDEN_ANGLE) % 360


def _anchors(hue_deg: int) -> list[tuple[float, tuple[float, float, float]]]:
    """Colormap anchors: near-black -> saturated hue -> near-white, with the hue
    drifting slightly upward so the ramp doesn't look flat."""
    h = hue_deg / 360
    hsv = [
        (0.00, (h, 0.90, 0.04)),
        (0.30, (h, 0.95, 0.30)),
        (0.55, (h + 0.04, 0.90, 0.65)),
        (0.80, (h + 0.08, 0.70, 0.92)),
        (1.00, (h + 0.12, 0.15, 1.00)),
    ]
    return [(p, colorsys.hsv_to_rgb(hh % 1.0, s, v)) for p, (hh, s, v) in hsv]


def _colormap(values: np.ndarray, hue_deg: int) -> np.ndarray:
    """Map floats in [0, 1] to an (..., 3) uint8 RGB array."""
    anchors = _anchors(hue_deg)
    xp = np.array([p for p, _ in anchors])
    channels = [
        np.interp(values, xp, np.array([c[i] * 255 for _, c in anchors]))
        for i in range(3)
    ]
    return np.stack(channels, axis=-1).astype(np.uint8)


def _decode(path: Path) -> np.ndarray:
    """Decode any ffmpeg-readable file to mono float32 at SAMPLE_RATE."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"],
        capture_output=True, check=True,
    )
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def _spectrogram(samples: np.ndarray) -> np.ndarray:
    """Log-frequency, log-magnitude spectrogram as a SIZE x SIZE float array in [0, 1]."""
    n_fft = 2048
    if len(samples) < n_fft:
        samples = np.pad(samples, (0, n_fft - len(samples)))
    hop = max((len(samples) - n_fft) // (SIZE - 1), 1)
    starts = np.arange(SIZE) * hop
    starts = np.clip(starts, 0, len(samples) - n_fft)
    window = np.hanning(n_fft)
    frames = np.stack([samples[s:s + n_fft] * window for s in starts])
    mag = np.abs(np.fft.rfft(frames, axis=1))  # (SIZE, n_fft/2+1)

    # Resample frequency axis onto a log scale (~60 Hz .. Nyquist) so voice
    # detail isn't crushed into the bottom rows.
    n_bins = mag.shape[1]
    lo = int(60 / (SAMPLE_RATE / 2) * n_bins)
    log_idx = np.geomspace(max(lo, 1), n_bins - 1, SIZE).astype(int)
    spec = mag[:, log_idx].T[::-1]  # freq on y, low at bottom

    spec = np.log1p(spec * 100)
    lo_v, hi_v = np.percentile(spec, [2, 99.5])
    return np.clip((spec - lo_v) / max(hi_v - lo_v, 1e-9), 0, 1)


def generate(source: Path, dest: Path, hue_deg: int):
    samples = _decode(source)
    if len(samples) == 0:
        samples = np.zeros(SAMPLE_RATE, dtype=np.float32)
    rgb = _colormap(_spectrogram(samples), hue_deg)
    tmp = dest.with_suffix(".tmp.png")
    Image.fromarray(rgb).save(tmp, format="PNG")
    tmp.replace(dest)


def get_or_create(sha256: str, source_path: str, created_at: str) -> Path | None:
    """Return the cached thumbnail path, generating it if needed. None on failure."""
    hue = date_hue(created_at)
    dest = THUMB_DIR / f"{sha256}-h{hue}.png"  # hue in the name invalidates old-style thumbs
    if dest.exists():
        return dest
    source = Path(source_path)
    if not source.exists():
        return None
    try:
        generate(source, dest, hue)
    except Exception:
        log.exception("thumbnail generation failed for %s", source)
        return None
    return dest
