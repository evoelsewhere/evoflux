-- 0008: usage and cost history (docs/features/usage-and-cost/sdd.md).
--
-- One row per model response: the tokens it used and what it cost at the
-- models.dev price the provider computed it with. The chat's engine writes
-- them as responses finish; the desktop reads them for the Usage page.
--
-- `chat_id` is not a foreign key: spend stays in the history after its chat
-- is deleted. `source` says which part of the chat made the call: the chat's
-- own agent, a subagent it ran, a plugin's child run, or a side question.
CREATE TABLE usage_events (
    id               INTEGER PRIMARY KEY,
    at_ms            INTEGER NOT NULL,
    chat_id          TEXT,
    source           TEXT NOT NULL DEFAULT 'chat'
                     CHECK (source IN ('chat', 'subagent', 'plugin', 'side')),
    provider_id      TEXT NOT NULL,
    model_id         TEXT NOT NULL,
    input            INTEGER NOT NULL DEFAULT 0,
    output           INTEGER NOT NULL DEFAULT 0,
    cache_read       INTEGER NOT NULL DEFAULT 0,
    cache_write      INTEGER NOT NULL DEFAULT 0,
    reasoning        INTEGER NOT NULL DEFAULT 0,
    cost_input       REAL NOT NULL DEFAULT 0,
    cost_output      REAL NOT NULL DEFAULT 0,
    cost_cache_read  REAL NOT NULL DEFAULT 0,
    cost_cache_write REAL NOT NULL DEFAULT 0,
    cost_usd         REAL NOT NULL DEFAULT 0,
    stop_reason      TEXT
) STRICT;

CREATE INDEX usage_events_at ON usage_events (at_ms);
CREATE INDEX usage_events_chat ON usage_events (chat_id, at_ms);
