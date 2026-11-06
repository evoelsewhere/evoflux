# Application database (`evo.db`) and provider settings

| | |
| --- | --- |
| Status | Implemented (planned tables open) |
| Area | crate `evo-store`, engine, desktop shell |
| Format | Legacy — predates [the SDD template](../../templates/sdd.md); move to it on the next substantial edit |
| Updated | 2026-11-06 |
| ADD sections | [7. Data view](../../architecture/README.md#7-data-view) |
| ADRs | [0002](../../architecture/decisions/0002-models-dev-is-the-model-database.md), [0007](../../architecture/decisions/0007-one-transcript-file-per-chat.md) |

Status: schema v9 shipped (provider settings, models.dev cache, chats, logs,
mail, chat search, usage history) with one transcript file per chat. This note records the
design and the planned tables so later features extend it the same way.

Checks run for the transcript-file change (2026-11-06): `cargo test -p
evo-store` (transcript paths, identity, fork, remove, sweep, legacy move incl.
a crash and a disagreeing file, search refresh, migration 6 → 7),
`cargo test -p evo-engine transcript_file_tests` (harness and evo-store write
the same schema; forked and moved files open as sessions; foreign files are
refused; two chats' files never share a lock), and the desktop app run end to
end on a copy of a real `evo.db`.

## Why a database

The desktop engine owns state that outgrows a JSON file: per-provider
settings that several windows (one engine process each) edit at once, model
lists that are replaced wholesale on refresh, a 6 MB model database, and —
soon — usage history and app preferences. SQLite gives atomic multi-row
writes, concurrent readers (WAL) and a schema that migrates forward.

Sessions keep their own storage (`evo-harness::session`); `evo.db` holds only
host-owned application state. Each chat's transcript is a SQLite file of its
own (see [Transcript files](#transcript-files)).

## Location and connection

- File: `~/.evo/agent/evo.db` (`EVO_CODING_AGENT_DIR` relocates the agent dir).
- `PRAGMA application_id = 0x65766F31` ("evo1") marks the file as evo's;
  opening a foreign SQLite file is refused.
- WAL journal, `busy_timeout = 5s`, `foreign_keys = ON`, `synchronous = NORMAL`.
  The engines' transcript connection (`SqliteSessionRepo`) uses the same
  journal, timeout and `synchronous`: with `FULL`, every streamed frame
  fsynced while holding the file's single write lock.
- Connections are short-lived (open, transact, drop). Every write is one
  transaction; a transaction that reads before it writes opens with
  `BEGIN IMMEDIATE` (a deferred one fails at once with "database is locked"
  when it upgrades after another process wrote).
- A transcript write that finds its file busy after the timeout is rerun from
  the start after a growing, jittered pause, for up to 60 s
  (`evo-harness/src/session/sqlite/busy.rs`). With one file per chat nothing
  else writes that file, so this is a safety net only.

## Who opens it

The `evo-store` crate owns the schema, the migrations, the typed queries
(`chats`, `logs`, `mail`, `settings`, `usage`) and the transcript files' rules
(`transcripts`). The engine re-exports it as `evo_engine::app_db`; the desktop
shell links it directly. Both run the same migrations at open, so whichever
starts first brings the file up to date.

- **Desktop shell** (`apps/desktop/src-tauri/src/db.rs`): workspaces, chats
  and their totals and search text, `app_settings`, mail, and the run log (a
  background writer batches entries every 500 ms and prunes at startup and
  hourly).
- **Engines**: one per open chat, started with
  `--session-db <agent dir>/transcripts/<chat id>.db --session-id <chat id>`.
  They read `evo.db` and write provider settings and the models.dev cache
  (rare), and one `usage_events` row per model response from a writer thread
  (`BEGIN IMMEDIATE` each). They never write transcripts into `evo.db`.

## Transcript files

`~/.evo/agent/transcripts/<chat id>.db`, one per chat
([ADR 0007](../../architecture/decisions/0007-one-transcript-file-per-chat.md),
`crates/evo-store/src/transcripts.rs`).

- **One writer.** Only the chat's engine writes its file, through evo-harness's
  `SqliteSessionRepo` (a `sessions` row holding the reducer snapshot, plus
  `progress_heads` / `progress_frames`). The shell opens files only to read
  them and removes them once the engine has stopped.
- **Identity.** `application_id = 0x65766F54` ("evoT"). `transcripts::prepare`
  stamps a new file before the harness creates its tables and refuses any
  other SQLite file; the engine accepts a transcript, a new file, or `evo.db`
  (what older desktops passed), nothing else.
- **Names.** A chat id becomes a file name only when it is 1–128 ASCII
  letters, digits, `-` or `_` (chat ids are UUIDs); anything else is refused.
- **Schema.** `transcripts::SESSION_SCHEMA` repeats the harness's DDL so the
  shell can build a file the harness opens as its own; a test in evo-engine
  (`session/transcript_file_tests.rs`) checks the two match.
- **Fork** (`chats::fork_chat`): a snapshot of the source's session row is
  written to `<id>.db.partial` (rollback journal, `synchronous = FULL`),
  renamed into place, then the chat row is inserted; a failed insert removes
  the file. The source may be running; progress of a streaming turn is not
  copied.
- **Delete** (`chat_delete`, `workspace_remove`): the chat row goes (its
  `chat_search` row cascades), the shell stops the chat's engine, then removes
  the file with its `-wal`, `-shm` and `-journal`. Windows refuses to delete a
  file still open; it stays for the sweep.
- **Startup** (`Db::open`, before any engine runs):
  1. `transcripts::adopt_legacy` moves transcripts older builds kept in
     `evo.db` into their own files, one chat at a time: build the file
     (session row and progress rows), flush, rename into place, then delete
     the rows. A file that already holds the same transcript (a crash between
     the rename and the delete) just loses the rows; a file that disagrees is
     set aside as `<id>.db.conflict-<ms>` (kept for the person) and `evo.db`'s
     transcript adopted. Rows without a chat (drafts) are dropped, as before.
     After a move, `VACUUM` gives the space back once.
  2. `transcripts::sweep` removes files whose chat no longer exists and
     `*.partial` files a crash left; files still in use are reported and
     retried next time.
- **Guard.** `Db::transcript_for_engine` refuses to start a chat's engine
  while `evo.db` still holds that chat's transcript and moving it fails, so an
  engine never starts an empty transcript beside the real one.
- **Search** (`chats::search_chats`): `chat_search` keeps each chat's
  searchable text (every string of the snapshot except ids, type tags, image
  data and signatures) with a stamp of the file it came from (size and
  modification time of the file and its WAL). A search first re-reads the
  transcripts whose stamp changed and drops the text of chats whose file is
  gone, then matches title, preview and text with `LIKE`. The command runs on
  a blocking thread; the command palette shows only the latest query's answer.
- Settings → Data & logs shows the folder, the files' total size and count.

## Migrations (`crates/evo-store/src`)

- Numbered SQL files in `migrations/`, embedded with `include_str!` and listed
  in `MIGRATIONS`. Versions are contiguous from 1.
- Opening the database applies pending migrations, each in its own
  `BEGIN IMMEDIATE` transaction, so two engines starting together apply each
  migration once. When the file is already evo's and every migration is
  applied with a matching checksum, a read settles that and the open takes
  no write lock; anything else goes through the locked path, which reports
  foreign, newer or changed schemas.
- `schema_migrations(version, name, checksum, applied_at)` records each one
  with the SHA-256 of its SQL, line endings normalized to LF;
  `PRAGMA user_version` mirrors the newest.
- **Append only.** An applied migration whose SQL changed is an error
  (`Tampered`). Change the schema with a new migration. Line endings are
  not a change: the SQL is embedded as checked out, and Git on Windows may
  check it out with CRLF. A recorded checksum matches the SQL with LF or with
  CRLF endings (builds before normalization recorded either), and
  `.gitattributes` keeps `*.sql` LF in every checkout.
- **No downgrades.** A database with a version this build does not know is
  refused (`TooNew`) rather than written by older code.
- Tables are `STRICT`; JSON columns carry `CHECK (json_valid(...))`.
- Timestamps are Unix seconds (`INTEGER`).

### Writing a migration

1. Add `migrations/000N_name.sql`; append `Migration { version: N, ... }`.
2. Prefer additive changes (new tables, `ALTER TABLE ... ADD COLUMN` with a
   default). For a destructive change, create the new table, copy, drop, rename
   — inside the one migration.
3. Add a test in `evo_store::tests` that opens a database at version N-1, applies
   N, and checks the data that must survive.

## Schema today

| Table | Purpose |
| --- | --- |
| `provider_settings` | One row per provider the user touched: `enabled`, `base_url` override, `options_json` (non-secret options: `headers` such as Codex's `ChatGPT-Account-Id`, `account` for display, `region`). |
| `provider_models` | Models a provider reported (`source = 'discovered'`, replaced on every refresh) and models the user added (`'custom'`, e.g. Foundry deployments). `metadata_json` keeps what the provider stated (API route, limits); `hidden` and `position` are reserved for picker curation. Cascades with its provider. |
| `provider_discovery` | Last discovery attempt per provider (`ok`/`error`, message, model count, timestamps) for the settings page. |
| `models_dev_cache` | The last downloaded `https://models.dev/api.json`, its ETag, `fetched_at` / `checked_at`. Singleton row. |
| `workspaces` (v3) | Folders chats run in: `path` (unique, case-insensitive), `name`, `collapsed` in the sidebar, `opened_at`. |
| `chats` (v3) | One sidebar chat; `id` = engine session id = transcript file name. `title` + `title_source` (`auto` from the first prompt, `user` once renamed), `preview`, `provider`/`model`, `pinned`, `unread`, `archived_at`, `turn_count`, `cost_usd`, `tokens`. Times in ms. Deleting a chat removes its transcript file (the shell, after stopping its engine). |
| `sessions`, `progress_heads`, `progress_frames` (v3) | Where older builds kept transcripts (evo-harness's `SqliteSessionRepo` tables). Empty once the shell has moved them into transcript files; kept, since dropping them in a migration could lose a transcript the move had not reached. In a transcript file the same tables hold that chat's session: `state_json` is the whole reducer snapshot, rewritten per write — fine for chat-sized sessions; an append-only entries table is the follow-up for very long ones. |
| `chat_search` (v7) | One row per chat with a transcript: `body` (its searchable text) and `stamp` (the file's size and modification times when it was read). Cascades with its chat. |
| `usage_events` (v8, `duration_ms` v9) | One row per model response: chat, `source` (chat, subagent, plugin, side), provider, model, tokens, cost split and total at its models.dev price, stop reason, duration, `at_ms`. Written by the chat's engine; read by the Usage page. See [usage and cost SDD](../usage-and-cost/sdd.md). |
| `app_settings` (v3) | Key → JSON for preferences shared across windows (`ui.lastChat`, `sidebar.localCollapsed`). |
| `app_logs` (v3) | The run log: `at_ms`, `level` (debug/info/warn/error), `source` (`shell`, `engine`, `provider`, `ui`, `db`), `chat_id`, `message`, `data_json`. Kept 14 days / 50k rows. Shown in Settings → Data & logs, exportable to `~/.evo/agent/logs/`. |

### Secrets stay out

API keys, OAuth tokens and Bedrock IAM keys live in `auth.json` (owner-only
file, written atomically). `evo.db` never holds a secret, so it can be
inspected, backed up or attached to a bug report safely.

## Models: models.dev is the database

No model is written in code or in the provider catalog.

- `evo-runtime/data/provider_catalog.json` holds connection facts only (wire
  API, endpoint, credential variable, headers, routes, `modelsDevId`).
- `evo-runtime::models_dev` parses `api.json`: model list per provider,
  context/output limits, pricing and long-context tiers, vision input,
  `reasoning_options` → evo's thinking-level map (efforts, off toggle, token
  budget), `interleaved` → reasoning replay, per-model `provider.npm/api` →
  wire protocol and endpoint.
- The engine revalidates the document in the background (ETag, every 6 h,
  or on demand from Settings → Providers → Refresh) and hot-swaps provider
  runtimes when it changes.
- `evo-runtime/data/models_dev_snapshot.json` (trimmed) seeds a machine that
  has never been online; regenerate with `scripts/gen_models_dev_snapshot.py`.
- A provider's live `/models` list (discovery) decides *which* models it
  serves when available; models.dev still supplies their metadata.

## Planned tables (not built yet)

Listed so new features land in the same shape. Each arrives as its own
migration.

| Feature | Table(s) | Notes |
| --- | --- | --- |
| Model picker curation | use `provider_models.hidden/position` | Hide models, pin order per provider; UI in the model menu. |
| Model metadata overrides | `model_overrides(provider_id, model_id, metadata_json)` | User-set context window, price, reasoning levels when models.dev is wrong. Merged after models.dev. |
| Spend limits | `spend_limits(scope, provider_id, period, limit_usd)` | Checked before a run against `usage_events`; scope = global/provider. |
| Append-only transcripts | `session_entries(session_id, seq, entry_json)` in each transcript file | Replace the whole-snapshot `state_json` rewrite for long chats. |
| Full-text search | FTS5 over chat titles and `chat_search.body` | Today search is `LIKE` over `chat_search.body` (substring match); FTS5 would rank results but match whole tokens. |
| Provider health | `provider_health(provider_id, at, status, latency_ms, error)` | Recent failures per provider for status dots and automatic fallback. |
| OAuth metadata | extend `provider_settings.options_json` | Plan/tier, token scope, last refresh — still no tokens. |
| Keychain secrets | none in `evo.db` | Move `auth.json` secrets to the OS keychain (Windows Credential Manager, macOS Keychain, Secret Service); `auth.json` remains the fallback. |

## Provider support matrix (this change)

| Provider | Auth | Transport |
| --- | --- | --- |
| Anthropic | API key | Anthropic Messages |
| Xiaomi MiMo | API key, or "Sign in with Xiaomi" (the platform mints a key and returns it X25519/AES-GCM-sealed to a loopback port; token plans also return their host) | Chat Completions (`thinking` with `budget_tokens` + `reasoning_content` replay) |
| Google Gemini | API key (`x-goog-api-key`) | Gemini API `streamGenerateContent` (thought signatures replayed, `thinkingConfig` level or budget) |
| Google Vertex AI | Cloud API key; express mode or project + location | The same Gemini provider under `…/publishers/google` (Gemini models only) |
| DeepSeek, Z.ai, Kimi/Moonshot, Qwen | API key | Chat Completions with each vendor's thinking dialect (`thinkingFormat`: deepseek, glm, kimi, qwen), plan rows included |
| OpenCode Zen / Go | API key | Chat Completions, Responses or Anthropic Messages per model (models.dev routes) |
| OpenAI Codex | ChatGPT sign-in (PKCE on `localhost:1455`), refresh tokens | Responses at `chatgpt.com/backend-api/codex/responses` |
| GitHub Copilot | GitHub device flow; per-account API host (`api.business.githubcopilot.com` for Business seats) | Chat Completions or Responses per model (`supported_endpoints`); `x-initiator` and vision header per request |
| Amazon Bedrock | Bedrock API key (Bearer), IAM keys, or an AWS profile (`~/.aws`: keys, `credential_process`, SSO) / env keys (SigV4) | Converse stream (AWS event-stream) |
| Microsoft Foundry | Resource + API key, deployments listed by the user | OpenAI v1; Claude deployments via `/anthropic` |

Thinking: models.dev says *what* a model supports (levels, budgets, whether
it can stop thinking); the provider's `thinkingFormat` says *how* its endpoint
takes it. FPT (FCI) is deliberately not offered.

Plan usage (`get_provider_usage`, Settings → Providers): Codex
(`chatgpt.com/backend-api/wham/usage`, rate-limit windows), Copilot
(`copilot_internal/user`, premium requests) and OpenCode Go (`{base}/usage`).

Discovery reads what a provider's `/models` states — context and output
limits, reasoning and its efforts (`DiscoveredModel.efforts`, which override
models.dev's levels for that account), vision — and drops models without text
output or tool calls. Ollama is read through `/api/tags` + `/api/show`.
