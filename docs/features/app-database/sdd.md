# Application database (`evo.db`) and provider settings

Status: v2 schema shipped (provider settings, models.dev cache). This note
records the design and the planned tables so later features extend it the
same way.

## Why a database

The desktop engine owns state that outgrows a JSON file: per-provider
settings that several windows (one engine process each) edit at once, model
lists that are replaced wholesale on refresh, a 6 MB model database, and —
soon — usage history and app preferences. SQLite gives atomic multi-row
writes, concurrent readers (WAL) and a schema that migrates forward.

Sessions keep their own storage (`evo-harness::session`); `evo.db` holds only
host-owned application state.

## Location and connection

- File: `~/.evo/agent/evo.db` (`EVO_CODING_AGENT_DIR` relocates the agent dir).
- `PRAGMA application_id = 0x65766F31` ("evo1") marks the file as evo's;
  opening a foreign SQLite file is refused.
- WAL journal, `busy_timeout = 5s`, `foreign_keys = ON`, `synchronous = NORMAL`.
- Connections are short-lived (open, transact, drop). Every write is one
  transaction.

## Who opens it

The `evo-store` crate owns the schema, the migrations and the typed queries
(`chats`, `logs`, `settings`). The engine re-exports it as `evo_engine::app_db`;
the desktop shell links it directly. Both run the same migrations at open, so
whichever starts first brings the file up to date.

- **Desktop shell** (`apps/desktop/src-tauri/src/db.rs`): workspaces, chats
  and their totals, `app_settings`, and the run log (a background writer
  batches entries every 500 ms and prunes at startup and hourly).
- **Engines**: one per open chat, started with
  `--session-db <evo.db> --session-id <chat id>`. The transcript is the
  evo-harness `SqliteSessionRepo` row with the chat's id (opened, or created on
  first start). Provider settings and the models.dev cache as before.
- On startup the shell deletes `sessions` rows with no `chats` row (drafts that
  never got a prompt), before any engine runs.

## Migrations (`crates/evo-store/src`)

- Numbered SQL files in `migrations/`, embedded with `include_str!` and listed
  in `MIGRATIONS`. Versions are contiguous from 1.
- Opening the database applies pending migrations, each in its own
  `BEGIN IMMEDIATE` transaction, so two engines starting together apply each
  migration once.
- `schema_migrations(version, name, checksum, applied_at)` records each one
  with the SHA-256 of its SQL; `PRAGMA user_version` mirrors the newest.
- **Append only.** An applied migration whose SQL changed is an error
  (`Tampered`). Change the schema with a new migration.
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
| `chats` (v3) | One sidebar chat; `id` = engine session id. `title` + `title_source` (`auto` from the first prompt, `user` once renamed), `preview`, `provider`/`model`, `pinned`, `unread`, `archived_at`, `turn_count`, `cost_usd`, `tokens`. Times in ms. Deleting a chat deletes its `sessions` row. |
| `sessions`, `progress_heads`, `progress_frames` (v3) | evo-harness's SQLite session repository, same DDL (`IF NOT EXISTS`). `state_json` is the whole reducer snapshot, rewritten per write — fine for chat-sized sessions; an append-only entries table is the follow-up for very long ones. |
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
| Usage and cost history | `usage_events(id, session_id, provider_id, model_id, input, output, cache_read, cache_write, cost_usd, at)` + daily rollup view | Feeds a usage page and spend limits; written from `agent_end` usage. |
| Spend limits | `spend_limits(scope, provider_id, period, limit_usd)` | Checked before a run; scope = global/provider. |
| Append-only transcripts | `session_entries(session_id, seq, entry_json)` | Replace the whole-snapshot `state_json` rewrite for long chats. |
| Full-text search | FTS5 over chat titles and message text | Today search is `LIKE` over `state_json`. |
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
