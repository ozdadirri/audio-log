"""Postgres job store. One row per ingested audio file, deduplicated by content hash.
Transcripts and summaries are stored inline; full-text search runs against the
generated tsvector column (see postgres/schema.sql) instead of a SQLite FTS5 table."""

import logging
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from . import config, storage

log = logging.getLogger("audiolog")

VALID_STATUSES = {"pending", "transcribing", "summarizing", "done", "error"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_factory(cursor):
    """dict_row, but TIMESTAMPTZ columns come back as ISO strings (not datetime
    objects) — callers throughout the app slice/parse created_at/updated_at/
    deleted_at as strings, matching the old SQLite TEXT-timestamp contract."""
    make_row = dict_row(cursor)

    def row(values):
        r = make_row(values)
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat(timespec="seconds")
        return r

    return row


@contextmanager
def connect():
    conn = psycopg.connect(config.DATABASE_URL, row_factory=_row_factory)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    """Schema lives in postgres/schema.sql (apply with `psql $DATABASE_URL -f
    postgres/schema.sql`). This just recovers mid-flight jobs, backfills
    transcript/summary text written before it was stored in the DB, and bootstraps
    the admin user."""
    with connect() as conn:
        conn.execute(
            "UPDATE files SET status = 'pending', updated_at = %s "
            "WHERE status IN ('transcribing', 'summarizing')",
            (_now(),),
        )
        _backfill(conn)
        _bootstrap_admin(conn)


def _bootstrap_admin(conn):
    """First run with users enabled: the configured API key becomes the admin
    account, and all pre-existing files are assigned to it."""
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()["count"]:
        return
    key = config.API_KEY or secrets.token_hex(16)
    cur = conn.execute(
        "INSERT INTO users (username, api_key, is_admin, created_at) "
        "VALUES ('admin', %s, TRUE, %s) RETURNING id", (key, _now()),
    )
    admin_id = cur.fetchone()["id"]
    conn.execute("UPDATE files SET user_id = %s WHERE user_id IS NULL", (admin_id,))
    if not config.API_KEY:
        log.warning("no AUDIOLOG_API_KEY set — generated admin key: %s", key)


def _backfill(conn):
    """Import transcripts/summaries written before they were stored in the DB."""
    rows = conn.execute(
        "SELECT id, output_dir FROM files "
        "WHERE transcript IS NULL AND output_dir IS NOT NULL"
    ).fetchall()
    for r in rows:
        out = r["output_dir"]
        conn.execute(
            "UPDATE files SET transcript = %s, summary = %s WHERE id = %s",
            (storage.download_text(f"{out}/transcript.md"),
             storage.download_text(f"{out}/summary.md"), r["id"]),
        )


def add_file(sha256: str, filename: str, source_path: str,
             user_id: int | None = None) -> int | None:
    """Insert a new job; returns its id, or None if the hash is already known."""
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO files (sha256, filename, source_path, user_id, "
                "created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (sha256, filename, source_path, user_id, _now(), _now()),
            )
            return cur.fetchone()["id"]
        except psycopg.errors.UniqueViolation:
            return None


def next_pending() -> dict | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM files WHERE status = 'pending' AND deleted_at IS NULL "
            "ORDER BY id LIMIT 1"
        ).fetchone()


def set_status(file_id: int, status: str, *, error: str | None = None):
    assert status in VALID_STATUSES, status
    with connect() as conn:
        conn.execute(
            "UPDATE files SET status = %s, error = %s, updated_at = %s WHERE id = %s",
            (status, error, _now(), file_id),
        )


def set_result(file_id: int, *, language: str | None, duration: float | None, output_dir: str):
    with connect() as conn:
        conn.execute(
            "UPDATE files SET language = %s, duration = %s, output_dir = %s, updated_at = %s "
            "WHERE id = %s",
            (language, duration, output_dir, _now(), file_id),
        )


def set_texts(file_id: int, transcript: str | None, summary: str | None):
    with connect() as conn:
        conn.execute(
            "UPDATE files SET transcript = %s, summary = %s, updated_at = %s WHERE id = %s",
            (transcript, summary, _now(), file_id),
        )


# ── Users ─────────────────────────────────────────────────────────────────

def get_user_by_id(user_id: int) -> dict | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()


def get_user_by_key(api_key: str) -> dict | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE api_key = %s", (api_key,)).fetchone()


def admin_user_id() -> int:
    with connect() as conn:
        return conn.execute(
            "SELECT id FROM users WHERE is_admin = TRUE ORDER BY id LIMIT 1"
        ).fetchone()["id"]


def list_users() -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT u.id, u.username, u.api_key, u.is_admin, u.created_at, "
            "  (SELECT COUNT(*) FROM files f WHERE f.user_id = u.id "
            "   AND f.deleted_at IS NULL) AS file_count "
            "FROM users u ORDER BY u.id"
        ).fetchall()


def create_user(username: str) -> dict:
    """Create a user with a generated API key; raises ValueError if taken."""
    key = secrets.token_hex(16)
    with connect() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, api_key, is_admin, created_at) "
                "VALUES (%s, %s, FALSE, %s) RETURNING id", (username, key, _now()),
            )
        except psycopg.errors.UniqueViolation:
            raise ValueError(f"username already exists: {username}")
        return {"id": cur.fetchone()["id"], "username": username, "api_key": key, "is_admin": False}


def delete_user(user_id: int, reassign_to: int):
    """Delete a user; their files are reassigned (to the admin)."""
    with connect() as conn:
        conn.execute("UPDATE files SET user_id = %s WHERE user_id = %s", (reassign_to, user_id))
        conn.execute("DELETE FROM users WHERE id = %s", (user_id,))


# ── Memory ────────────────────────────────────────────────────────────────

def get_memory(user_id: int) -> dict | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM memories WHERE user_id = %s", (user_id,)).fetchone()


def set_memory(user_id: int, content: str, last_file_id: int):
    with connect() as conn:
        # content changed -> any cached translation is stale
        conn.execute(
            "INSERT INTO memories (user_id, content, content_zh, last_file_id, updated_at) "
            "VALUES (%s, %s, NULL, %s, %s) ON CONFLICT(user_id) DO UPDATE SET "
            "content = excluded.content, content_zh = NULL, "
            "last_file_id = excluded.last_file_id, updated_at = excluded.updated_at",
            (user_id, content, last_file_id, _now()),
        )
        conn.execute("DELETE FROM translations WHERE kind = 'memory' AND ref_id = %s",
                     (user_id,))


def set_memory_zh(user_id: int, content_zh: str):
    with connect() as conn:
        conn.execute("UPDATE memories SET content_zh = %s WHERE user_id = %s",
                     (content_zh, user_id))


def delete_memory(user_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM memories WHERE user_id = %s", (user_id,))


def memory_pending(user: dict, last_file_id: int) -> list[dict]:
    """Summarized files newer than the memory watermark, visible to this user
    and not flagged as excluded from memory."""
    scope = "" if user["is_admin"] else "AND user_id = %s "
    args = (last_file_id, user["id"]) if not user["is_admin"] else (last_file_id,)
    with connect() as conn:
        return conn.execute(
            "SELECT id, filename, title, created_at, summary FROM files "
            "WHERE status = 'done' AND summary IS NOT NULL AND id > %s "
            "AND COALESCE(mem_exclude, FALSE) = FALSE AND deleted_at IS NULL "
            f"{scope}ORDER BY id",
            args,
        ).fetchall()


def set_mem_exclude(file_id: int, exclude: bool):
    with connect() as conn:
        conn.execute("UPDATE files SET mem_exclude = %s WHERE id = %s", (exclude, file_id))


def get_setting(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def set_title(file_id: int, title: str):
    with connect() as conn:
        conn.execute("UPDATE files SET title = %s WHERE id = %s", (title, file_id))


def set_tags(file_id: int, tags: str):
    """tags: comma-separated lowercase labels."""
    with connect() as conn:
        conn.execute("UPDATE files SET tags = %s WHERE id = %s", (tags, file_id))


def set_summary_zh(file_id: int, text: str):
    with connect() as conn:
        conn.execute("UPDATE files SET summary_zh = %s WHERE id = %s", (text, file_id))


def get_translation(kind: str, ref_id: int, lang: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT text FROM translations WHERE kind = %s AND ref_id = %s AND lang = %s",
            (kind, ref_id, lang),
        ).fetchone()
        return row["text"] if row else None


def set_translation(kind: str, ref_id: int, lang: str, text: str):
    with connect() as conn:
        conn.execute(
            "INSERT INTO translations (kind, ref_id, lang, text) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (kind, ref_id, lang) DO UPDATE SET text = excluded.text",
            (kind, ref_id, lang, text),
        )


def clear_translations(kind: str, ref_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM translations WHERE kind = %s AND ref_id = %s", (kind, ref_id))


def _tsquery(q: str, any_term: bool = False) -> str | None:
    """Build a prefix-matching tsquery expression (":*" per term), terms AND'd
    (or OR'd) together — mirrors the old FTS5 MATCH behavior."""
    terms = re.findall(r"\w+", q)
    if not terms:
        return None
    joiner = " | " if any_term else " & "
    return joiner.join(f"{t}:*" for t in terms)


def search(q: str, user_id: int | None = None, limit: int = 50) -> list[dict]:
    """Full-text search over filenames, transcripts, and summaries.
    user_id scopes results to one owner; None = all files (admin)."""
    tsq = _tsquery(q)
    if tsq is None:
        return []
    scope = "AND f.deleted_at IS NULL " + ("AND f.user_id = %s " if user_id is not None else "")
    args = [tsq, tsq]
    if user_id is not None:
        args.append(user_id)
    args += [tsq, limit]
    with connect() as conn:
        return conn.execute(
            "SELECT f.id AS id, ts_headline('english', "
            "  coalesce(f.filename, '') || ' ' || coalesce(f.transcript, '') || ' ' || "
            "  coalesce(f.summary, ''), to_tsquery('english', %s), "
            "  'StartSel=<b>,StopSel=</b>,MaxFragments=1,MaxWords=16,MinWords=6,"
            "FragmentDelimiter= … ') AS snippet "
            "FROM files f "
            f"WHERE f.search_vector @@ to_tsquery('english', %s) {scope}"
            "ORDER BY ts_rank(f.search_vector, to_tsquery('english', %s)) DESC LIMIT %s",
            args,
        ).fetchall()


def retrieve(q: str, user_id: int | None = None, limit: int = 6) -> list[dict]:
    """Looser OR-matched retrieval with large snippets, for the assistant."""
    tsq = _tsquery(q, any_term=True)
    if tsq is None:
        return []
    scope = "AND f.deleted_at IS NULL " + ("AND f.user_id = %s " if user_id is not None else "")
    args = [tsq, tsq]
    if user_id is not None:
        args.append(user_id)
    args += [tsq, limit]
    with connect() as conn:
        return conn.execute(
            "SELECT f.id AS id, f.filename, f.created_at, f.summary, "
            "  ts_headline('english', coalesce(f.transcript, ''), to_tsquery('english', %s), "
            "  'MaxFragments=1,MaxWords=64,MinWords=32,FragmentDelimiter= … ') AS excerpt "
            "FROM files f "
            f"WHERE f.search_vector @@ to_tsquery('english', %s) {scope}"
            "ORDER BY ts_rank(f.search_vector, to_tsquery('english', %s)) DESC LIMIT %s",
            args,
        ).fetchall()


def delete_file(file_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM files WHERE id = %s", (file_id,))
        conn.execute("DELETE FROM embeddings WHERE file_id = %s", (file_id,))


def replace_embeddings(file_id: int, chunks: list[tuple[str, bytes]]):
    with connect() as conn:
        conn.execute("DELETE FROM embeddings WHERE file_id = %s", (file_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO embeddings (file_id, chunk_idx, text, vector) "
                "VALUES (%s, %s, %s, %s)",
                [(file_id, i, text, vector) for i, (text, vector) in enumerate(chunks)],
            )


def all_embeddings(user_id: int | None = None) -> list[dict]:
    """Every indexed chunk visible to the user (trash excluded)."""
    scope = "AND f.user_id = %s " if user_id is not None else ""
    with connect() as conn:
        return conn.execute(
            "SELECT e.file_id, e.text, e.vector, f.filename, f.created_at "
            "FROM embeddings e JOIN files f ON f.id = e.file_id "
            f"WHERE f.deleted_at IS NULL {scope}ORDER BY e.file_id, e.chunk_idx",
            (user_id,) if user_id is not None else (),
        ).fetchall()


def files_missing_embeddings() -> list[int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM files WHERE transcript IS NOT NULL AND deleted_at IS NULL "
            "AND id NOT IN (SELECT DISTINCT file_id FROM embeddings) ORDER BY id"
        ).fetchall()
        return [r["id"] for r in rows]


def soft_delete_file(file_id: int):
    """Move to trash: hidden from every list/search until restored or purged."""
    with connect() as conn:
        conn.execute("UPDATE files SET deleted_at = %s, updated_at = %s WHERE id = %s",
                     (_now(), _now(), file_id))


def restore_file(file_id: int):
    with connect() as conn:
        conn.execute("UPDATE files SET deleted_at = NULL, updated_at = %s WHERE id = %s",
                     (_now(), file_id))


def list_trash(user_id: int | None = None) -> list[dict]:
    scope = "AND f.user_id = %s " if user_id is not None else ""
    with connect() as conn:
        return conn.execute(
            "SELECT f.id, f.filename, f.title, f.duration, f.deleted_at, f.created_at, "
            "u.username AS owner FROM files f LEFT JOIN users u ON u.id = f.user_id "
            f"WHERE f.deleted_at IS NOT NULL {scope}ORDER BY f.deleted_at DESC",
            (user_id,) if user_id is not None else (),
        ).fetchall()


def trash_older_than(cutoff_iso: str) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM files WHERE deleted_at IS NOT NULL AND deleted_at < %s",
            (cutoff_iso,),
        ).fetchall()


def list_files(user_id: int | None = None) -> list[dict]:
    """user_id scopes to one owner; None = all files (admin). Trash excluded."""
    scope = "WHERE f.deleted_at IS NULL " + ("AND f.user_id = %s " if user_id is not None else "")
    with connect() as conn:
        return conn.execute(
            "SELECT f.id, f.sha256, f.filename, f.title, f.tags, f.source_path, "
            "f.status, f.error, f.language, f.duration, f.output_dir, f.user_id, "
            "f.created_at, f.updated_at, u.username AS owner "
            "FROM files f LEFT JOIN users u ON u.id = f.user_id "
            f"{scope}ORDER BY f.id DESC",
            (user_id,) if user_id is not None else (),
        ).fetchall()


def get_file_by_hash(sha256: str) -> dict | None:
    """The existing row for this content, if any. Used to tell an uploader that
    a recording is already in the library rather than silently doing nothing."""
    with connect() as conn:
        return conn.execute(
            "SELECT id, filename, deleted_at FROM files WHERE sha256 = %s", (sha256,)
        ).fetchone()


def get_file(file_id: int) -> dict | None:
    with connect() as conn:
        return conn.execute(
            "SELECT f.*, u.username AS owner FROM files f "
            "LEFT JOIN users u ON u.id = f.user_id WHERE f.id = %s",
            (file_id,),
        ).fetchone()
