"""SQLite job store. One row per ingested audio file, deduplicated by content hash.
Transcripts and summaries are stored inline and indexed in an FTS5 table for search."""

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256      TEXT UNIQUE NOT NULL,
    filename    TEXT NOT NULL,
    source_path TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    language    TEXT,
    duration    REAL,
    output_dir  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

VALID_STATUSES = {"pending", "transcribing", "summarizing", "done", "error"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
        for col in ("transcript", "summary", "summary_zh"):
            if col not in cols:
                conn.execute(f"ALTER TABLE files ADD COLUMN {col} TEXT")
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS files_fts "
            "USING fts5(filename, transcript, summary)"
        )
        # Recover jobs that were mid-flight when the app last stopped.
        conn.execute(
            "UPDATE files SET status = 'pending', updated_at = ? "
            "WHERE status IN ('transcribing', 'summarizing')",
            (_now(),),
        )
        _backfill(conn)


def _backfill(conn):
    """Import transcripts/summaries written before they were stored in the DB,
    and (re)index any rows missing from the FTS table."""
    rows = conn.execute(
        "SELECT id, output_dir FROM files "
        "WHERE transcript IS NULL AND output_dir IS NOT NULL"
    ).fetchall()
    for r in rows:
        out = Path(r["output_dir"])
        t, s = out / "transcript.md", out / "summary.md"
        conn.execute(
            "UPDATE files SET transcript = ?, summary = ? WHERE id = ?",
            (t.read_text() if t.exists() else None,
             s.read_text() if s.exists() else None, r["id"]),
        )
    missing = conn.execute(
        "SELECT id FROM files WHERE id NOT IN (SELECT rowid FROM files_fts)"
    ).fetchall()
    for r in missing:
        _index(conn, r["id"])


def _index(conn, file_id: int):
    row = conn.execute(
        "SELECT filename, transcript, summary FROM files WHERE id = ?", (file_id,)
    ).fetchone()
    conn.execute("DELETE FROM files_fts WHERE rowid = ?", (file_id,))
    if row is not None:
        conn.execute(
            "INSERT INTO files_fts (rowid, filename, transcript, summary) "
            "VALUES (?, ?, ?, ?)",
            (file_id, row["filename"], row["transcript"] or "", row["summary"] or ""),
        )


def add_file(sha256: str, filename: str, source_path: str) -> int | None:
    """Insert a new job; returns its id, or None if the hash is already known."""
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO files (sha256, filename, source_path, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (sha256, filename, source_path, _now(), _now()),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def next_pending() -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM files WHERE status = 'pending' ORDER BY id LIMIT 1"
        ).fetchone()


def set_status(file_id: int, status: str, *, error: str | None = None):
    assert status in VALID_STATUSES, status
    with connect() as conn:
        conn.execute(
            "UPDATE files SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, error, _now(), file_id),
        )


def set_result(file_id: int, *, language: str | None, duration: float | None, output_dir: str):
    with connect() as conn:
        conn.execute(
            "UPDATE files SET language = ?, duration = ?, output_dir = ?, updated_at = ? "
            "WHERE id = ?",
            (language, duration, output_dir, _now(), file_id),
        )


def set_texts(file_id: int, transcript: str | None, summary: str | None):
    with connect() as conn:
        conn.execute(
            "UPDATE files SET transcript = ?, summary = ?, updated_at = ? WHERE id = ?",
            (transcript, summary, _now(), file_id),
        )
        _index(conn, file_id)


def set_summary_zh(file_id: int, text: str):
    with connect() as conn:
        conn.execute("UPDATE files SET summary_zh = ? WHERE id = ?", (text, file_id))


def _fts_query(q: str, any_term: bool = False) -> str:
    """Build a safe FTS5 MATCH expression: quoted prefix terms, AND (or OR) joined."""
    terms = re.findall(r"\w+", q)
    return (" OR " if any_term else " ").join(f'"{t}"*' for t in terms)


def search(q: str, limit: int = 50) -> list[dict]:
    """Full-text search over filenames, transcripts, and summaries."""
    match = _fts_query(q)
    if not match:
        return []
    with connect() as conn:
        rows = conn.execute(
            "SELECT rowid AS id, snippet(files_fts, 1, '<b>', '</b>', ' … ', 16) AS snippet "
            "FROM files_fts WHERE files_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def retrieve(q: str, limit: int = 6) -> list[dict]:
    """Looser OR-matched retrieval with large snippets, for the assistant."""
    match = _fts_query(q, any_term=True)
    if not match:
        return []
    with connect() as conn:
        rows = conn.execute(
            "SELECT fts.rowid AS id, f.filename, f.created_at, "
            "  snippet(files_fts, 1, '', '', ' … ', 64) AS excerpt, f.summary "
            "FROM files_fts fts JOIN files f ON f.id = fts.rowid "
            "WHERE files_fts MATCH ? ORDER BY rank LIMIT ?",
            (match, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_file(file_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
        conn.execute("DELETE FROM files_fts WHERE rowid = ?", (file_id,))


def list_files() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, sha256, filename, source_path, status, error, language, "
            "duration, output_dir, created_at, updated_at "
            "FROM files ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_file(file_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return dict(row) if row else None
