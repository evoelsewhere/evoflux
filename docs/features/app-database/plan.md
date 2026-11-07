# Application database (`evo.db`) and provider settings — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [7. Data view](../../architecture/README.md#7-data-view) |
| ADRs | [0002 models.dev is the model database](../../architecture/decisions/0002-models-dev-is-the-model-database.md), [0007 One transcript file per chat](../../architecture/decisions/0007-one-transcript-file-per-chat.md) |

## 1. Context and constraints

The desktop engine owns state that outgrows a JSON file: per-provider
settings that several windows (one engine process each) edit at once, model
lists that are replaced wholesale on refresh, a 6 MB model database, usage
history and app preferences. SQLite gives atomic multi-row writes,
concurrent readers (WAL) and a schema that migrates forward.

Sessions keep their own storage (`evo-harness::session`); `evo.db` holds
only host-owned application state. Each chat's transcript is a SQLite file
of its own (3.4, [ADR 0007](../../architecture/decisions/0007-one-transcript-file-per-chat.md)).

Schema v9 is shipped (provider settings, models.dev cache, chats, logs,
mail, chat search, usage history) with one transcript file per chat.

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | The shell owns workspaces, chats, preferences, mail and the run log; engines write provider settings, the model cache, usage rows and their own transcript. No agent decisions in the store. |
| Layers point down; library crates stay free of engine/desktop concerns | ok | `evo-store` owns schema and typed queries only; the engine re-exports it, the shell links it directly. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | n/a | No protocol change; the engine takes its transcript path on the command line. |
| Models come from models.dev; no hardcoded model facts | ok | `models_dev_cache` holds the document; the provider catalog holds connection facts only ([ADR 0002](../../architecture/decisions/0002-models-dev-is-the-model-database.md)). |
| Real engine in the app; settings and credentials reload live | ok | Provider runtimes are hot-swapped when models.dev or provider settings change. |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | No secrets in `evo.db`; foreign SQLite files and unsafe chat ids are refused. |
| Desktop UI structure and `DESIGN.md` | n/a | Storage only; **Settings → Data & logs** and **Settings → Providers** belong to their features. |

## 3. Design

### 3.1 Overview

```text
 desktop shell (db.rs) ───────────┐            ┌──── engine (chat A) ── writes ──► transcripts/A.db
   workspaces, chats, search,     │            │       provider settings, models.dev cache,
   app_settings, mail, run log    ▼            ▼       usage_events
                         ~/.evo/agent/evo.db  (WAL, migrations at open)
                                  ▲            ▲
   reads transcript files ────────┘            └──── engine (chat B) ── writes ──► transcripts/B.db
```

`evo-store` owns the schema, the migrations and the typed queries. Both the
shell and every engine run the same migrations at open, so whichever starts
first brings the file up to date. Each engine writes only its own transcript
file.

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| crate | `crates/evo-store/src/lib.rs` | Open, identity check, connection pragmas, migrations (`MIGRATIONS`, `schema_migrations`), `Db::open` startup work, `Db::transcript_for_engine` | FR-1–FR-4, FR-9, FR-10, NFR-3, NFR-4 |
| crate | `crates/evo-store/src/migrations/` | Numbered SQL migrations `0001`–`0009` | FR-3, FR-12, FR-14 |
| crate | `crates/evo-store/src/transcripts.rs` | Transcript file rules: names, `prepare`, `SESSION_SCHEMA`, fork copy, remove, `adopt_legacy`, `sweep`, stamps, searchable text | FR-6–FR-9, FR-11, NFR-2 |
| crate | `crates/evo-store/src/chats.rs` | Workspaces and chats, `fork_chat`, `search_chats` | FR-7, FR-11, FR-14 |
| crate | `crates/evo-store/src/settings.rs` | Provider settings and models, `app_settings` | FR-12, FR-14 |
| crate | `crates/evo-store/src/logs.rs` | Run log: append, query, prune | FR-15 |
| crate | `crates/evo-store/src/mail.rs`, `usage.rs` | Mail between sessions; usage rows | FR-14 |
| crate | `crates/evo-harness/src/session/sqlite/busy.rs` | Transcript write retry when the file is busy | NFR-1 |
| engine | `crates/evo-engine` (`evo_engine::app_db`), `crates/evo-engine/src/session/transcript_file_tests.rs` | Re-exports `evo-store`; opens its transcript file; checks the harness and `evo-store` schemas match | FR-1, FR-6 |
| engine | `crates/evo-engine/src/provider_settings.rs`, `models_dev.rs`, `provider_usage.rs` | Provider settings, models.dev revalidation and hot-swap, plan usage | FR-12, FR-13, FR-16 |
| crate | `crates/evo-runtime/src/models_dev.rs`, `crates/evo-runtime/data/provider_catalog.json`, `crates/evo-runtime/data/models_dev_snapshot.json`, `crates/evo-runtime/scripts/gen_models_dev_snapshot.py` | models.dev parsing, connection facts, the offline snapshot and its generator | FR-13 |
| desktop shell | `apps/desktop/src-tauri/src/db.rs` | Workspaces, chats and their totals and search text, `app_settings`, mail, the run log writer, chat delete and workspace remove | FR-8, FR-11, FR-14, FR-15 |

### 3.3 Interfaces

**Engine start.** One engine per open chat, started with
`--session-db <agent dir>/transcripts/<chat id>.db --session-id <chat id>`.
The engine accepts a transcript file, a new file, or `evo.db` (what older
desktops passed), nothing else.

**`evo-store` entry points:** `Db::open` (migrations, then the startup steps
of 3.5), `Db::transcript_for_engine` (the guard), `transcripts::prepare`,
`transcripts::adopt_legacy`, `transcripts::sweep`,
`transcripts::SESSION_SCHEMA`, `chats::fork_chat`, `chats::search_chats`.
Shell commands: `chat_delete`, `workspace_remove`. Engine RPC: `get_provider_usage`.

**Provider support matrix:**

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
| Microsoft Foundry | Resource + API key, deployments listed by the user | OpenAI v1; Anthropic model deployments via `/anthropic` |

**Thinking:** models.dev says *what* a model supports (levels, budgets,
whether it can stop thinking); the provider's `thinkingFormat` says *how* its
endpoint takes it.

**Plan usage** (`get_provider_usage`, **Settings → Providers**): Codex
(`chatgpt.com/backend-api/wham/usage`, rate-limit windows), Copilot
(`copilot_internal/user`, premium requests) and OpenCode Go
(`{base}/usage`).

**Discovery** reads what a provider's `/models` states — context and output
limits, reasoning and its efforts (`DiscoveredModel.efforts`, which override
models.dev's levels for that account), vision — and drops models without text
output or tool calls. Ollama is read through `/api/tags` + `/api/show`.

**models.dev mapping** (`evo-runtime::models_dev` parses `api.json`): model
list per provider, context/output limits, pricing and long-context tiers,
vision input, `reasoning_options` → evo's thinking-level map (efforts, off
toggle, token budget), `interleaved` → reasoning replay, per-model
`provider.npm/api` → wire protocol and endpoint. The provider catalog
(`evo-runtime/data/provider_catalog.json`) holds connection facts only (wire
API, endpoint, credential variable, headers, routes, `modelsDevId`).

### 3.4 Data and storage

**Location and connection.**

- File: `~/.evo/agent/evo.db` (`EVO_CODING_AGENT_DIR` relocates the agent
  dir).
- `PRAGMA application_id = 0x65766F31` ("evo1") marks the file as evo's;
  opening a foreign SQLite file is refused.
- WAL journal, `busy_timeout = 5s`, `foreign_keys = ON`,
  `synchronous = NORMAL`. The engines' transcript connection
  (`SqliteSessionRepo`) uses the same journal, timeout and `synchronous`:
  with `FULL`, every streamed frame fsynced while holding the file's single
  write lock.
- Connections are short-lived (open, transact, drop). Every write is one
  transaction; a transaction that reads before it writes opens with
  `BEGIN IMMEDIATE` (a deferred one fails at once with "database is locked"
  when it upgrades after another process wrote).

**Migrations** (`crates/evo-store/src`).

- Numbered SQL files in `migrations/`, embedded with `include_str!` and
  listed in `MIGRATIONS`. Versions are contiguous from 1.
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
  (`Tampered`). Change the schema with a new migration. Line endings are not
  a change: the SQL is embedded as checked out, and Git on Windows may check
  it out with CRLF. A recorded checksum matches the SQL with LF or with CRLF
  endings (builds before normalization recorded either), and
  `.gitattributes` keeps `*.sql` LF in every checkout.
- **No downgrades.** A database with a version this build does not know is
  refused (`TooNew`) rather than written by older code.
- Tables are `STRICT`; JSON columns carry `CHECK (json_valid(...))`.
- Timestamps are Unix seconds (`INTEGER`).

**Writing a migration.**

1. Add `migrations/000N_name.sql`; append `Migration { version: N, ... }`.
2. Prefer additive changes (new tables, `ALTER TABLE ... ADD COLUMN` with a
   default). For a destructive change, create the new table, copy, drop,
   rename — inside the one migration.
3. Add a test in `evo_store::tests` that opens a database at version N-1,
   applies N, and checks the data that must survive.

**Schema today.**

| Table | Purpose |
| --- | --- |
| `provider_settings` | One row per provider the user touched: `enabled`, `base_url` override, `options_json` (non-secret options: `headers` such as Codex's `ChatGPT-Account-Id`, `account` for display, `region`). |
| `provider_models` | Models a provider reported (`source = 'discovered'`, replaced on every refresh) and models the user added (`'custom'`, e.g. Foundry deployments). `metadata_json` keeps what the provider stated (API route, limits); `hidden` and `position` are reserved for picker curation. Cascades with its provider. |
| `provider_discovery` | Last discovery attempt per provider (`ok`/`error`, message, model count, timestamps) for the settings page. |
| `models_dev_cache` | The last downloaded `https://models.dev/api.json`, its ETag, `fetched_at` / `checked_at`. Singleton row. |
| `workspaces` (v3) | Folders chats run in: `path` (unique, case-insensitive), `name`, `collapsed` in the sidebar, `opened_at`. |
| `chats` (v3) | One sidebar chat; `id` = engine session id = transcript file name. `title` + `title_source` (`auto` from the first prompt, `user` once renamed), `preview`, `provider`/`model`, `pinned`, `unread`, `archived_at`, `turn_count`, `cost_usd`, `tokens`. Times in ms. Deleting a chat removes its transcript file (the shell, after stopping its engine). Parent link and origin (v4) and worktree path (v5): see [subagents and nested sessions](../subagents-and-nested-sessions/plan.md). |
| `sessions`, `progress_heads`, `progress_frames` (v3) | Where older builds kept transcripts (evo-harness's `SqliteSessionRepo` tables). Empty once the shell has moved them into transcript files; kept, since dropping them in a migration could lose a transcript the move had not reached. In a transcript file the same tables hold that chat's session: `state_json` is the whole reducer snapshot, rewritten per write — fine for chat-sized sessions; an append-only entries table is the follow-up for very long ones. |
| `mail` (v6) | Mail between sessions; see [session mesh](../session-mesh-protocol/plan.md). |
| `chat_search` (v7) | One row per chat with a transcript: `body` (its searchable text) and `stamp` (the file's size and modification times when it was read). Cascades with its chat. |
| `usage_events` (v8, `duration_ms` v9) | One row per model response: chat, `source` (chat, subagent, plugin, side), provider, model, tokens, cost split and total at its models.dev price, stop reason, duration, `at_ms`. Written by the chat's engine; read by the Usage page. See [usage and cost](../usage-and-cost/spec.md). |
| `app_settings` (v3) | Key → JSON for preferences shared across windows (`ui.lastChat`, `sidebar.localCollapsed`). |
| `app_logs` (v3) | The run log: `at_ms`, `level` (debug/info/warn/error), `source` (`shell`, `engine`, `provider`, `ui`, `db`), `chat_id`, `message`, `data_json`. Kept 14 days / 50k rows. Shown in **Settings → Data & logs**, exportable to `~/.evo/agent/logs/`. |

**Transcript files** — `~/.evo/agent/transcripts/<chat id>.db`, one per
chat (`crates/evo-store/src/transcripts.rs`).

- **One writer.** Only the chat's engine writes its file, through
  evo-harness's `SqliteSessionRepo` (a `sessions` row holding the reducer
  snapshot, plus `progress_heads` / `progress_frames`). The shell opens files
  only to read them and removes them once the engine has stopped.
- **Identity.** `application_id = 0x65766F54` ("evoT").
  `transcripts::prepare` stamps a new file before the harness creates its
  tables and refuses any other SQLite file.
- **Names.** A chat id becomes a file name only when it is 1–128 ASCII
  letters, digits, `-` or `_` (chat ids are UUIDs); anything else is refused.
- **Schema.** `transcripts::SESSION_SCHEMA` repeats the harness's DDL so the
  shell can build a file the harness opens as its own; a test in evo-engine
  (`session/transcript_file_tests.rs`) checks the two match.

**Secrets stay out.** API keys, OAuth tokens and Bedrock IAM keys live in
`auth.json` (owner-only file, written atomically). `evo.db` never holds a
secret, so it can be inspected, backed up or attached to a bug report
safely.

**models.dev snapshot.** `evo-runtime/data/models_dev_snapshot.json`
(trimmed) seeds a machine that has never been online; regenerate it with
`crates/evo-runtime/scripts/gen_models_dev_snapshot.py`.

#### Planned tables

Listed so new features land in the same shape. None is built; each arrives
as its own migration, with its own feature spec (tasks.md, Phase 6).

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

### 3.5 Behaviour

**Who opens it.** The engine re-exports `evo-store` as `evo_engine::app_db`;
the desktop shell links it directly.

- **Desktop shell** (`apps/desktop/src-tauri/src/db.rs`): workspaces, chats
  and their totals and search text, `app_settings`, mail, and the run log (a
  background writer batches entries every 500 ms and prunes at startup and
  hourly).
- **Engines**: one per open chat. They read `evo.db` and write provider
  settings and the models.dev cache (rare), and one `usage_events` row per
  model response from a writer thread (`BEGIN IMMEDIATE` each). They never
  write transcripts into `evo.db`.

**Fork** (`chats::fork_chat`): a snapshot of the source's session row is
written to `<id>.db.partial` (rollback journal, `synchronous = FULL`),
renamed into place, then the chat row is inserted; a failed insert removes
the file. The source may be running; progress of a streaming turn is not
copied.

**Delete** (`chat_delete`, `workspace_remove`): the chat row goes (its
`chat_search` row cascades), the shell stops the chat's engine, then removes
the file with its `-wal`, `-shm` and `-journal`. Windows refuses to delete a
file still open; it stays for the sweep.

**Startup** (`Db::open`, before any engine runs):

1. `transcripts::adopt_legacy` moves transcripts older builds kept in
   `evo.db` into their own files, one chat at a time: build the file (session
   row and progress rows), flush, rename into place, then delete the rows. A
   file that already holds the same transcript (a crash between the rename
   and the delete) just loses the rows; a file that disagrees is set aside as
   `<id>.db.conflict-<ms>` (kept for the person) and `evo.db`'s transcript
   adopted. Rows without a chat (drafts) are dropped, as before. After a move,
   `VACUUM` gives the space back once.
2. `transcripts::sweep` removes files whose chat no longer exists and
   `*.partial` files a crash left; files still in use are reported and
   retried next time.

**Guard.** `Db::transcript_for_engine` refuses to start a chat's engine while
`evo.db` still holds that chat's transcript and moving it fails, so an engine
never starts an empty transcript beside the real one.

**Search** (`chats::search_chats`): `chat_search` keeps each chat's
searchable text (every string of the snapshot except ids, type tags, image
data and signatures) with a stamp of the file it came from (size and
modification time of the file and its WAL). A search first re-reads the
transcripts whose stamp changed and drops the text of chats whose file is
gone, then matches title, preview and text with `LIKE`. The command runs on a
blocking thread; the command palette shows only the latest query's answer.

**Busy transcript.** A transcript write that finds its file busy after the
timeout is rerun from the start after a growing, jittered pause, for up to
60 s (`crates/evo-harness/src/session/sqlite/busy.rs`). With one file per
chat nothing else writes that file, so this is a safety net only.

**models.dev.** The engine revalidates the document in the background (ETag,
every 6 h, or on demand from **Settings → Providers → Refresh**) and
hot-swaps provider runtimes when it changes. A provider's live `/models`
list (discovery) decides *which* models it serves when available; models.dev
still supplies their metadata.

### 3.6 Errors and edge cases

- Foreign SQLite file → refused at open (`application_id`).
- Edited applied migration → `Tampered`; unknown newer version → `TooNew`.
- "database is locked" → avoided by `BEGIN IMMEDIATE` for read-then-write
  transactions and a 5 s busy timeout; transcript writes retry for up to
  60 s.
- File still open on Windows at delete → left for the next sweep.
- Crash during adopt → finished on the next start; disagreeing file → kept
  as `<id>.db.conflict-<ms>`.
- Crash during fork → `*.partial` removed by the sweep.
- Unsafe chat id → no file; failed legacy move → the engine does not start.

### 3.7 Security and trust

- No secret in `evo.db` (3.4); `auth.json` is owner-only and written
  atomically.
- `application_id` stamps (`evo1`, `evoT`) keep evo from writing into a
  foreign SQLite file, and keep an engine from opening anything but a
  transcript, a new file or `evo.db`.
- Chat ids are checked before they become file names (no path traversal).
- Provider options hold non-secret values only; OAuth metadata (planned)
  still holds no tokens.

### 3.8 Configuration

| Setting | Type, default | Where | Applies |
| --- | --- | --- | --- |
| `EVO_CODING_AGENT_DIR` | path, `~/.evo/agent` | environment | at start |
| models.dev revalidation | every 6 h; **Settings → Providers → Refresh** on demand | engine | live (hot-swap) |
| Run log retention | 14 days / 50k rows | shell | at startup and hourly |
| Provider settings | per provider | `provider_settings` | live |
| `.gitattributes` `*.sql` | LF | repository | every checkout |

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| A JSON settings file | Several engines edit settings at once; model lists are replaced wholesale; the model database is 6 MB. |
| Transcripts inside `evo.db` | Every chat shared one write lock ([ADR 0007](../../architecture/decisions/0007-one-transcript-file-per-chat.md)). |
| `synchronous = FULL` for transcripts | Every streamed frame fsynced while holding the file's single write lock. |
| Deferred transactions for read-then-write | Fail at once with "database is locked" when they upgrade after another process wrote. |
| Dropping the legacy `sessions` tables in a migration | Could lose a transcript the move had not reached. |
| FTS5 for chat search | Ranks results but matches whole tokens; substring `LIKE` is used today, FTS5 is a planned table. |
| Secrets in `evo.db` | The file must be safe to inspect, back up and attach to a bug report. |

## 5. As-built notes

- Transcript files keep the whole reducer snapshot in `state_json`,
  rewritten per write — fine for chat-sized sessions; append-only entries are
  a planned table.
- The engine also accepts `evo.db` as its session database, for older
  desktops that passed it.
- A recorded migration checksum matches LF or CRLF SQL because builds before
  line-ending normalization recorded either.
- The desktop app was run end to end on a copy of a real `evo.db` for the
  transcript-file change (2026-11-06).
