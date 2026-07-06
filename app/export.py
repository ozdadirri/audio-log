"""Standalone HTML export of a recording: summary + transcript + metadata,
with the spectrogram thumbnail embedded, in one self-contained file."""

import base64
import html
import re
from pathlib import Path

STYLE = """
body { font-family: -apple-system, "Segoe UI", sans-serif; max-width: 720px;
       margin: 40px auto; padding: 0 20px; color: #1A202C; line-height: 1.7; }
img.thumb { width: 180px; border-radius: 12px; float: right; margin: 0 0 16px 16px; }
h1 { font-size: 24px; }
h2 { font-size: 13px; letter-spacing: 1.2px; text-transform: uppercase;
     color: #3563E9; margin-top: 28px; }
.meta { color: #90A3BF; font-size: 13px; margin-bottom: 24px; }
.meta span { margin-right: 14px; }
.seg { margin: 6px 0; }
.seg b { color: #90A3BF; font-size: 12px; margin-right: 8px; }
ul { padding-left: 22px; }
hr { border: 0; border-top: 1px solid #E7EEF6; margin: 32px 0; clear: both; }
"""


def _md_to_html(md: str) -> str:
    """Minimal markdown: #/## headings, bullets, **bold**, `code`. Escaped."""
    out, in_list = [], False
    for line in html.escape(md).splitlines():
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        line = re.sub(r"`([^`]+)`", r"<code>\1</code>", line)
        bullet = re.match(r"\s*[*-]\s+(.*)", line)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{bullet.group(1)}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        heading = re.match(r"(#{1,4})\s+(.*)", line)
        if heading:
            level = min(len(heading.group(1)) + 1, 6)
            out.append(f"<h{level}>{heading.group(2)}</h{level}>")
        elif line.strip():
            out.append(f"<p>{line}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def render(row: dict, thumb: Path | None) -> str:
    title = html.escape(row.get("title") or row["filename"])
    thumb_tag = ""
    if thumb and thumb.exists():
        b64 = base64.b64encode(thumb.read_bytes()).decode()
        thumb_tag = f'<img class="thumb" src="data:image/png;base64,{b64}" alt="">'
    meta = "".join(
        f"<span>{html.escape(str(v))}</span>" for v in [
            row["filename"],
            row.get("created_at", "")[:19].replace("T", " "),
            f"{int(row['duration'] // 60)}:{int(row['duration'] % 60):02d}" if row.get("duration") else None,
            row.get("language"),
            " ".join("#" + t for t in (row.get("tags") or "").split(",") if t),
        ] if v
    )
    summary = _md_to_html(row.get("summary") or "(no summary)")
    transcript = _md_to_html(row.get("transcript") or "(no transcript)")
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{STYLE}</style></head>
<body>
{thumb_tag}
<h1>{title}</h1>
<div class="meta">{meta}</div>
{summary}
<hr>
{transcript}
<hr>
<div class="meta">Exported from audio-log</div>
</body></html>
"""
