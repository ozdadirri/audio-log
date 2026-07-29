"""One-time data migration: copies every row from the old SQLite audiolog.db
into the new Postgres database (schema from postgres/schema.sql must already
be applied). Preserves ids so foreign keys (files.user_id, embeddings.file_id,
translations.ref_id) stay correct, then resets Postgres's SERIAL sequences to
continue after the highest migrated id.

Usage: .venv/bin/python postgres/migrate_from_sqlite.py [path/to/audiolog.db]
"""

import sqlite3
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

SQLITE_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/audiolog.db")


def migrate():
    src = sqlite3.connect(SQLITE_PATH)
    src.row_factory = sqlite3.Row
    dst = psycopg.connect(config.DATABASE_URL)

    with dst.cursor() as cur:
        cur.execute(
            "TRUNCATE users, files, embeddings, memories, translations, settings "
            "RESTART IDENTITY CASCADE"
        )

        users = src.execute("SELECT * FROM users").fetchall()
        for r in users:
            cur.execute(
                "INSERT INTO users (id, username, api_key, is_admin, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (r["id"], r["username"], r["api_key"], bool(r["is_admin"]), r["created_at"]),
            )
        print(f"users: {len(users)}")

        files = src.execute("SELECT * FROM files").fetchall()
        for r in files:
            cur.execute(
                "INSERT INTO files (id, sha256, filename, source_path, status, error, "
                "language, duration, output_dir, created_at, updated_at, transcript, "
                "summary, summary_zh, title, tags, user_id, mem_exclude, deleted_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
                "%s, %s, %s)",
                (r["id"], r["sha256"], r["filename"], r["source_path"], r["status"],
                 r["error"], r["language"], r["duration"], r["output_dir"], r["created_at"],
                 r["updated_at"], r["transcript"], r["summary"], r["summary_zh"], r["title"],
                 r["tags"], r["user_id"], bool(r["mem_exclude"]), r["deleted_at"]),
            )
        print(f"files: {len(files)}")

        embeddings = src.execute("SELECT * FROM embeddings").fetchall()
        for r in embeddings:
            cur.execute(
                "INSERT INTO embeddings (file_id, chunk_idx, text, vector) "
                "VALUES (%s, %s, %s, %s)",
                (r["file_id"], r["chunk_idx"], r["text"], bytes(r["vector"])),
            )
        print(f"embeddings: {len(embeddings)}")

        memories = src.execute("SELECT * FROM memories").fetchall()
        for r in memories:
            cur.execute(
                "INSERT INTO memories (user_id, content, content_zh, last_file_id, updated_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (r["user_id"], r["content"], r["content_zh"], r["last_file_id"], r["updated_at"]),
            )
        print(f"memories: {len(memories)}")

        translations = src.execute("SELECT * FROM translations").fetchall()
        for r in translations:
            cur.execute(
                "INSERT INTO translations (kind, ref_id, lang, text) VALUES (%s, %s, %s, %s)",
                (r["kind"], r["ref_id"], r["lang"], r["text"]),
            )
        print(f"translations: {len(translations)}")

        settings = src.execute("SELECT * FROM settings").fetchall()
        for r in settings:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s)", (r["key"], r["value"])
            )
        print(f"settings: {len(settings)}")

        # SERIAL sequences still start at 1 after explicit-id inserts; bump them
        # past the highest migrated id so future INSERTs (no explicit id) don't collide.
        for table in ("users", "files"):
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                f"(SELECT MAX(id) FROM {table}) IS NOT NULL)"
            )

    dst.commit()
    dst.close()
    src.close()
    print("done")


if __name__ == "__main__":
    migrate()
