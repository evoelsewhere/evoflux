# chat-core notes (AR3)

Python source: `app/api/routes/team/chat.py` (`team_chat`, `team_stream`,
`team_history`), `app/services/chat_service.py`, `app/services/memory_stream_store.py`,
`app/agent/agent_loop/{core,streaming,tool_executor}.py`, `app/agent/turn_usage.py`,
`app/agent/usage.py`, `app/agent/hooks/{stream_publisher,title_generation}.py`,
`app/services/title_service.py`, `app/agent/mode/team/{team,member}.py` (turn lifecycle).

## Endpoints

- `POST /api/team/chat` (form, urlencoded or multipart): `ChatForm` validation
  (422 `Value error, ...`), registry check (422), `session_id` (422 `Invalid session id.`),
  folder (`Invalid folder_id.`, 404 `Folder not found.`, 422 mode mismatch), Work
  workspace (422 absolute / cannot create), `permission_mode` (422), interrupt
  (200 `interrupted`), `/loop` (410), then 202 `{"status": "accepted", "session_id"}`.
- `GET /api/team/{session_id}/stream`: `text/event-stream; charset=utf-8`, frames
  `event: <name>\r\ndata: <json.dumps>\r\n\r\n`, replay journal then live events,
  empty body when no turn is in flight, `: ping` every 15 s.
- `GET /api/team/{session_id}/history[?before=ts|id]`: `TeamHistoryResponse`
  (null fields dropped in `lead` and messages), 404 `Lead session not found.`,
  422 `Invalid before cursor: ...`, FastAPI's UUID 422 for a bad path id.

## Tables

Writes `chat_sessions` (insert on first message; mode/workspace/model/thinking and
`updated_at` per turn; title) and `session_messages` (user, assistant, tool rows;
`extra` with `model`, `usage`, `duration_ms`, `turn_usage`). Reads `session_folders`
and `session_goals`. All through `evoflux_core::db` (`write` lane, `rowid::insert`).

## SSE order for one turn

`agent_status working {phase: ingress}` (before 202; cleared from replay when the
turn starts) → `agent_status working {}` → `agent_status working {phase:
model_calling}` → per call: `thinking`/`message` deltas, `tool_call`, per-call
`usage`, turn-total `usage` → `tool_start`/`tool_end` per tool → ... →
`agent_status idle` (or `error` / `agent_not_configured` + `agent_status error`)
→ `desktop_notification` → `turn_changes` → `done`. Title generation adds a
title-phase turn total and `title_update` whenever it finishes.

## Test map

Contract: `contract-tests/chat-core/test_chat_core.py` (text, second turn, reasoning,
tool, unknown tool, unported tool, 400, 401, raw SSE bytes, empty stream, history
errors, cursor, form validation, title, Python reading Rust rows). Unit tests per
module. Mutants: 0 missed in `pyjson`, `usage`, `lib`, `stream_store`, `agent`,
`title`; `store`, `routes` and `turn` are covered by the contract suite, not mutated.
