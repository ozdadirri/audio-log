-- Postgres schema for audio-log, translated from the SQLite schema in app/db.py.
--
-- Notable differences from SQLite:
--   * INTEGER PRIMARY KEY AUTOINCREMENT -> BIGSERIAL PRIMARY KEY
--   * BLOB -> BYTEA
--   * TEXT timestamps -> TIMESTAMPTZ
--   * 0/1 flags -> BOOLEAN
--   * FTS5 virtual table -> a generated tsvector column + GIN index on `files`
--     (search queries need rewriting to use `@@ websearch_to_tsquery(...)` /
--     `plainto_tsquery(...)` instead of FTS5 MATCH syntax)

CREATE TABLE IF NOT EXISTS users (
    id         BIGSERIAL PRIMARY KEY,
    username   TEXT UNIQUE NOT NULL,
    api_key    TEXT UNIQUE NOT NULL,
    is_admin   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id          BIGSERIAL PRIMARY KEY,
    sha256      TEXT UNIQUE NOT NULL,
    filename    TEXT NOT NULL,
    source_path TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    language    TEXT,
    duration    DOUBLE PRECISION,
    output_dir  TEXT,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    transcript   TEXT,
    summary      TEXT,
    summary_zh   TEXT,
    title        TEXT,
    tags         TEXT,
    user_id      BIGINT REFERENCES users(id),
    mem_exclude  BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at   TIMESTAMPTZ,
    search_vector tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(filename, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(transcript, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(summary, '')), 'B')
    ) STORED
);

CREATE INDEX IF NOT EXISTS files_search_idx ON files USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS files_user_idx ON files (user_id);
CREATE INDEX IF NOT EXISTS files_status_idx ON files (status) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS embeddings (
    file_id   BIGINT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chunk_idx INTEGER NOT NULL,
    text      TEXT NOT NULL,
    vector    BYTEA NOT NULL,
    PRIMARY KEY (file_id, chunk_idx)
);

CREATE TABLE IF NOT EXISTS memories (
    user_id      BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    content      TEXT NOT NULL,
    content_zh   TEXT,
    last_file_id BIGINT NOT NULL DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL
);

-- Cached translations. kind='summary' -> ref_id is file_id;
-- kind='memory' -> ref_id is user_id.
CREATE TABLE IF NOT EXISTS translations (
    kind    TEXT NOT NULL,
    ref_id  BIGINT NOT NULL,
    lang    TEXT NOT NULL,
    text    TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id, lang)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
