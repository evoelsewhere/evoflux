-- 0003: chats and the folders they run in, their transcripts, app settings
-- and the run log. Everything the desktop keeps lives in this one file.

-- A folder the agent works in. Chats without one run in the home folder
-- ("This computer").
CREATE TABLE workspaces (
    id         TEXT PRIMARY KEY NOT NULL,
    path       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name       TEXT NOT NULL,
    collapsed  INTEGER NOT NULL DEFAULT 0 CHECK (collapsed IN (0, 1)),
    position   INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    opened_at  INTEGER NOT NULL
) STRICT;

-- One chat in the sidebar. `id` is the engine session id, so the transcript
-- is the `sessions` row with the same id.
CREATE TABLE chats (
    id            TEXT PRIMARY KEY NOT NULL,
    workspace_id  TEXT REFERENCES workspaces (id) ON DELETE SET NULL,
    title         TEXT NOT NULL,
    -- `auto` titles follow the first prompt; `user` titles were renamed.
    title_source  TEXT NOT NULL DEFAULT 'auto' CHECK (title_source IN ('auto', 'user')),
    preview       TEXT,
    provider      TEXT,
    model         TEXT,
    pinned        INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    unread        INTEGER NOT NULL DEFAULT 0 CHECK (unread IN (0, 1)),
    archived_at   INTEGER,
    turn_count    INTEGER NOT NULL DEFAULT 0,
    -- Spend and tokens so far, for the sidebar and usage views.
    cost_usd      REAL NOT NULL DEFAULT 0,
    tokens        INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
) STRICT;

CREATE INDEX chats_by_activity ON chats (archived_at, pinned DESC, updated_at DESC);
CREATE INDEX chats_by_workspace ON chats (workspace_id, updated_at DESC);

-- Transcripts: evo-harness's SQLite session repository
-- (evo_harness::session::sqlite::SqliteSessionRepo). Same DDL, so the
-- harness's `CREATE TABLE IF NOT EXISTS` finds these and leaves them alone.
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    parent_session_id TEXT,
    state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS progress_heads (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS progress_frames (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL, id TEXT NOT NULL, lane TEXT NOT NULL,
    run_id TEXT NOT NULL, stream_index INTEGER NOT NULL, frame_json TEXT NOT NULL,
    PRIMARY KEY(session_id, sequence), UNIQUE(session_id,id)
);
CREATE INDEX IF NOT EXISTS progress_run ON progress_frames(session_id,run_id,sequence);

-- Preferences several windows share (key → JSON value).
CREATE TABLE app_settings (
    key        TEXT PRIMARY KEY NOT NULL,
    value_json TEXT NOT NULL CHECK (json_valid(value_json)),
    updated_at INTEGER NOT NULL
) STRICT;

-- The run log kept on this machine for debugging: engine output, shell
-- lifecycle, UI errors. Pruned by age and size (see evo_store::logs).
CREATE TABLE app_logs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at_ms   INTEGER NOT NULL,
    level   TEXT NOT NULL CHECK (level IN ('debug', 'info', 'warn', 'error')),
    source  TEXT NOT NULL,
    chat_id TEXT,
    message TEXT NOT NULL,
    data_json TEXT CHECK (data_json IS NULL OR json_valid(data_json))
) STRICT;

CREATE INDEX app_logs_by_time ON app_logs (at_ms);
CREATE INDEX app_logs_by_chat ON app_logs (chat_id, at_ms);
