"""Semantic retrieval: transcript chunks are embedded with a local Ollama
embedding model and matched to queries by cosine similarity, so meaning matches
even when keywords don't. Falls back gracefully when no vectors exist."""

import logging
import re

import httpx
import numpy as np

from . import config, db

log = logging.getLogger("audiolog")

CHUNK_CHARS = 700   # ~2-6 transcript segments per chunk
MAX_PER_FILE = 2    # retrieval diversity: at most this many chunks per recording

_SEGMENT = re.compile(r"^\*\*\[(\d+:\d{2})\]\*\*\s*(.*)$")


def _embed(texts: list[str]) -> np.ndarray:
    resp = httpx.post(
        f"{config.OLLAMA_URL}/api/embed",
        json={"model": config.EMBED_MODEL, "input": texts},
        timeout=120,
    )
    resp.raise_for_status()
    vectors = np.array(resp.json()["embeddings"], dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-9)


def chunk_transcript(transcript_md: str) -> list[str]:
    """Group timestamped segments into ~CHUNK_CHARS chunks, keeping the first
    timestamp of each chunk as a prefix for context."""
    chunks, current, stamp = [], "", ""
    for line in transcript_md.splitlines():
        match = _SEGMENT.match(line)
        if not match:
            continue
        if not current:
            stamp = match.group(1)
        current += (" " if current else "") + match.group(2).strip()
        if len(current) >= CHUNK_CHARS:
            chunks.append(f"[{stamp}] {current}")
            current = ""
    if current.strip():
        chunks.append(f"[{stamp}] {current}")
    return chunks


def index_file(file_id: int):
    """(Re)build the vector index for one recording's transcript."""
    row = db.get_file(file_id)
    if not row or not row.get("transcript"):
        return
    chunks = chunk_transcript(row["transcript"])
    if not chunks:
        return
    vectors = _embed(chunks)
    db.replace_embeddings(file_id, list(zip(chunks, (v.tobytes() for v in vectors))))
    log.info("embedded %s: %d chunks", row["filename"], len(chunks))


def retrieve(query: str, user_id: int | None = None, limit: int = 6) -> list[dict]:
    """Top transcript chunks by cosine similarity, shaped like db.retrieve().
    Empty list when nothing is indexed (caller falls back to FTS)."""
    rows = db.all_embeddings(user_id)
    if not rows:
        return []
    matrix = np.frombuffer(b"".join(r["vector"] for r in rows), dtype=np.float32)
    matrix = matrix.reshape(len(rows), -1)
    q = _embed([query])[0]
    scores = matrix @ q
    hits, per_file = [], {}
    for i in np.argsort(scores)[::-1]:
        r = rows[int(i)]
        if per_file.get(r["file_id"], 0) >= MAX_PER_FILE:
            continue
        per_file[r["file_id"]] = per_file.get(r["file_id"], 0) + 1
        hits.append({
            "id": r["file_id"],
            "filename": r["filename"],
            "created_at": r["created_at"],
            "excerpt": r["text"],
            "score": float(scores[int(i)]),
        })
        if len(hits) >= limit:
            break
    return hits
