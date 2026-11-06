-- 0006: mail between sessions (docs/design/session-mesh-protocol.md). The
-- desktop shell's mesh hub stores each message before sending it to the
-- receiving session's engine and marks it delivered when that engine answers;
-- undelivered mail goes out when the receiver's engine next starts.

CREATE TABLE mail (
    id           TEXT PRIMARY KEY,
    from_chat    TEXT NOT NULL,
    to_chat      TEXT NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    body         TEXT NOT NULL,          -- the envelope body (JSON)
    created_at   INTEGER NOT NULL,
    delivered_at INTEGER
);
CREATE INDEX mail_pending ON mail (to_chat, created_at) WHERE delivered_at IS NULL;
