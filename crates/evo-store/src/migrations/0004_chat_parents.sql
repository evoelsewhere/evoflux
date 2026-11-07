-- 0004: nested sessions. A chat started by another chat (its `start_session`
-- tool) keeps a link to it, so the sidebar can show it under its parent and
-- the parent can hear back when it finishes a turn. Deleting the parent keeps
-- the child (it moves to the top level).

ALTER TABLE chats ADD COLUMN parent_chat_id TEXT REFERENCES chats (id) ON DELETE SET NULL;

-- Who started the chat: the person, or an agent in another chat.
ALTER TABLE chats ADD COLUMN origin TEXT NOT NULL DEFAULT 'user' CHECK (origin IN ('user', 'agent'));

CREATE INDEX chats_by_parent ON chats (parent_chat_id, updated_at DESC);
