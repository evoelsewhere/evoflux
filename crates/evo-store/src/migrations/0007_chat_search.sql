-- 0007: each chat's transcript moves out of this file into its own
-- (`transcripts/<chat id>.db`, ADR 0007). Chat search can no longer join the
-- transcripts, so it keeps their searchable text here. `stamp` fingerprints
-- the transcript file (size and modification time) the text was read from;
-- a search re-reads every transcript whose stamp changed since.
--
-- The `sessions`, `progress_heads` and `progress_frames` tables of 0003 stay.
-- The shell moves their rows out one chat at a time, each only after its file
-- is safely written (evo_store::transcripts::adopt_legacy); a migration that
-- dropped them could lose a transcript.
CREATE TABLE chat_search (
    chat_id TEXT PRIMARY KEY NOT NULL REFERENCES chats (id) ON DELETE CASCADE,
    stamp   TEXT NOT NULL,
    body    TEXT NOT NULL
) STRICT;
