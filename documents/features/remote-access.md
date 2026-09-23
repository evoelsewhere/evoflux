# Remote access

Status: **Optional** — requires a user-owned Telegram bot and network access
from the EvoFlux host.

## Problem and outcome

When the user walks away from the desktop, EvoFlux becomes unreachable. Active
sessions may pause on a gate (permission, question, plan) and idle until the
user returns. Remote access lets the user receive, read, and resolve those gates
from a phone through a personal Telegram bot — one tap to approve, one message
to continue.

## Goals

1. **One-tap pairing** — scan a QR, open a deep link, or enter a short code;
   no manual token entry on the phone.
2. **Current-task text** — the bot shows what the active session is doing so the
   user can decide without opening the desktop.
3. **Automatic gates and completion** — permission requests, questions, and plan
   review arrive as inline-button messages. Phone-started turns get one live
   status card plus a native typing indicator; their final completion or error
   card edits that same message in place.
4. **Safe redaction** — every outbound message passes through
   `protect_outbound_text(channel="remote")` so secrets and PII never leave the
   machine.

## Non-goals

- No shared or multi-tenant bot — each installation owns one bot.
- No inbound listener — the adapter polls outbound; Telegram cannot push into
  EvoFlux.
- No public URL — the sidecar stays loopback; no webhook endpoint is exposed.

## User flows and states

### Setup

1. In Settings → Remote access, the user clicks **Open BotFather & copy
   /newbot**. The button opens @BotFather in Telegram and copies the
   `/newbot` command to the clipboard so the user can paste it immediately.
2. The user creates a bot in BotFather, copies the token, and pastes it into
   the EvoFlux token field.
3. EvoFlux stores the token in the OS credential vault, verifies it with the
   Telegram API, creates a `remote_connections` row, and starts the adapter.
4. Once the adapter reaches `polling` state, EvoFlux automatically issues a
   one-time pairing link and displays a **QR code** on the settings page. The
   QR code encodes a `t.me/<bot>?start=<token>` deep link.
5. The user scans the QR code with their phone camera (or taps the link).
   Telegram opens and sends the `/start <token>` command automatically — no
   typing needed.
6. EvoFlux records the `chat_id` in `remote_pairings` and the state becomes
   `paired`.

Users who prefer to type a code can expand the "Prefer to type a code
instead?" fallback section, which generates an 8-digit code and a `/pair`
command.

The connection status uses adaptive polling: the frontend polls every 2
seconds during transitional states (`starting`, `backoff`) and every 15
seconds once the connection is stable (`polling`, `offline`). This ensures
the UI tracks adapter lifecycle changes in real time without navigating
away from the settings page.

### Daily use

1. User sends a message to the bot on Telegram.
2. The remote adapter polls `getUpdates`, matches the `chat_id` to a pairing,
   and forwards the text into the active session as a user message.
3. The adapter immediately sends one HTML-formatted status card with animated
   spinner and phase labels (Thinking/Planning/Working/Checking). The card
   includes the current model, token usage, and estimated cost in real time.
4. On completion or error, the adapter edits that card into a bounded final
   summary. It never mirrors tool-call details, arguments, or file-path deltas
   into the live status text. The final card shows only user-facing results,
   model info, token/cache/reasoning usage, and estimated cost.
5. A completed card can offer **Full diff** if file changes are available.
   Tool-log buttons are no longer shown on terminal cards.

### Media delivery

**Outbound:** Photos and other media can be sent from EvoFlux to Telegram using
the `sendPhoto` API. HTTPS-only URLs are enforced; non-HTTPS URLs and images
over 10 MiB are rejected with a text fallback.

**Inbound:** Telegram photos and documents sent to the bot are downloaded,
validated (size, MIME type, magic bytes), and passed through the provider-neutral
attachment pipeline to agent context. Files over 10 MiB are rejected with a
text fallback. iMessage attachments follow the same pipeline when the provider
supports materialization.

### Steering chat

Users can send steering instructions to an active task using `/steer`:

```
/steer Focus on authentication before UI changes
/steer Don't modify tests yet, keep them as-is
```

Steering messages are injected into the active task's context as priority
instructions.

### Settings

The `/settings` command displays a rich card with:

- Connection status with emoji indicator
- Current model (with provider icon)
- Lead agent
- Response mode (live/terminal)
- Thinking level (none/low/medium/high)
- Permission mode
- Provider count and total models available

Models are grouped by provider. Tapping a provider button opens a per-provider
card with pricing (input/output cost per 1M tokens) and a checkmark on the
active selection.

### Info commands

- `/status` — Full dashboard: connection, session, providers, models, active task
- `/skills` — Skills catalog grouped by work/coding mode
- `/skill <name>` — Load a specific skill by name with description and modes
- `/agent` — Current agent info with thinking level reference

### Desktop, Workflow, and Scheduler completion

- The pairing's persisted notification scope defaults to `all`. Under that
  scope, an addressable top-level Work or Coding session started from the
  desktop, Workflow, or Scheduler sends the same final completion/error card
  to the paired phone.
- Desktop-origin sessions are lazily admitted for live streaming when the
  active pairing requests `notify_scope=all`. This means desktop prompts now
  get live process cards, streaming deltas, heartbeat updates, and terminal
  notifications — not just the final card.
- Stream callbacks from worker threads are properly forwarded to the
  adapter-owning event loop using `call_soon_threadsafe`, ensuring terminal
  notifications are never silently dropped.
- Side Chat, child, internal, and otherwise non-addressable sessions never
  notify the phone.
- The `remote_only` scope keeps notifications limited to `remote_origin`
  sessions.

### Gate flow

1. The session hits a permission, question, or plan gate.
2. The stream observer emits a gate event; the adapter sends a Telegram message
   with inline buttons (e.g. Allow once / Reject, Accept / Revise / Reject).
3. The user taps a button. The adapter resolves the gate and continues.

### Unpair

- Desktop: Settings → Remote access → Remove.
- Phone: send `/pair <code>` to connect, or `/unpair` to disconnect.

## Requirements and acceptance criteria

Requirements and acceptance criteria are defined in the base implementation
plan as AC-1 through AC-36 and amended by the response-UI specification. The
implemented response-UI additions are AC-38 (bounded phone-turn lifecycle),
AC-39 (on-demand turn detail), AC-42 (notification scope), and AC-43
(cross-origin completion delivery).
The status, done, and error-card paths also implement the response-card portion
of revised AC-24. They cover:

- Connection lifecycle (create, verify, update label, replace token, delete)
- Pairing lifecycle (link, QR, resolve, revoke)
- Outbound projection (current task, gate events, completion summaries)
- Inbound forwarding (text messages to active session)
- Remote permission replies (limited to `once` and `reject`)
- Redaction of outbound text (secrets and PII)
- SQLite concurrency (per-pairing locks, source_key idempotency)
- Connection states (11 values covering setup through error)
- One connection per installation (v1)
- Migration `00000064`
- HTML-safe Telegram cards, native typing, and one status-card lifecycle for
  phone-started turns
- Opaque, ten-minute Full diff and Tool log capabilities scoped to the
  connection, principal, destination, and completed turn
- Addressability-gated final delivery for desktop, Workflow, and Scheduler
  sessions when notification scope is `all`

## API, event, tool, and UI contracts

### Settings endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/settings/remote` | Read remote settings |
| `PUT` | `/api/settings/remote` | Update remote settings |

### Connection endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/remote/connections` | List connections (0 or 1) |
| `POST` | `/api/remote/connections` | Create connection (write-only token) |
| `PATCH` | `/api/remote/connections/{id}` | Update label or enabled flag |
| `PUT` | `/api/remote/connections/{id}/token` | Replace bot token |
| `DELETE` | `/api/remote/connections/{id}` | Remove connection |

### Pairing endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/remote/connections/{id}/pairing-links` | Issue pairing link |
| `POST` | `/api/remote/connections/{id}/pairing-codes` | Issue one-time8-digit pairing code |
| `GET` | `/api/remote/connections/{id}/pairing` | Read pairing state |
| `DELETE` | `/api/remote/connections/{id}/pairing` | Revoke pairing |

### Settings shape

```yaml
outbound_data_policy: block | redact | off   # default: redact
outbound_pii_policy: off | standard | strict  # default: standard
```

### Connection shape

```
id, label, enabled, bot_username, state, created_at, updated_at
```

Token is write-only; read responses never return it.

### Pairing shape

```
id, connection_id, chat_id, principal_id, state, paired_at
```

## Data model

### `remote_connections`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `label` | text | user-facing name |
| `enabled` | boolean | default true |
| `bot_username` | text | resolved from Telegram API |
| `bot_token_vault_key` | text | OS vault reference, never stored in DB |
| `state` | enum(11) | `disconnected` → `connecting` → `connected` → `paired` … `error` |
| `created_at` | timestamp | |
| `updated_at` | timestamp | |

### `remote_pairings`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID | primary key |
| `connection_id` | UUID | FK → `remote_connections` |
| `chat_id` | bigint | Telegram chat ID |
| `principal_id` | text | authorizes the pairing |
| `destination_id` | text | addresses the pairing |
| `state` | enum | `pending` → `paired` → `revoked` |
| `source_key` | text | idempotency key for `getUpdates` offset |
| `notify_scope` | text | `all` (default) or `remote_only`; controls cross-origin final notifications |
| `paired_at` | timestamp | |

### OS vault

Bot tokens are stored in the OS credential vault (keyring) only. The DB stores
a vault key reference, never the raw token.

## Permissions, security, privacy, and trust

- **Token storage**: bot token lives in OS credential vault (keyring) only; never
  in the database, environment variables, or config files.
- **Remote permission replies**: limited to `once` and `reject`. There is no
  `always` option for remote — every remote approval is single-use.
- **Outbound redaction**: all outbound text passes through
  `protect_outbound_text(channel="remote")` before reaching Telegram.
- **Safe HTML response cards**: the status, done, and error-card builders use
  Telegram HTML parse mode only after outbound redaction. Every non-static
  value passed to those builders is escaped by `app/remote/formatting.py`, so
  agent or user content cannot create markup, links, or mentions.
- **Private chats only**: the adapter only processes private (non-group) chats.
- **Authorization model**: `principal_id` authorizes who can reply;
  `destination_id` addresses which pairing receives the message.
- **On-demand detail**: a Full diff or Tool log token carries no content,
  path, or session identifier. It is in-memory only, expires after ten
  minutes, is bound to the connection, principal, and destination, and reads
  only the detail captured for its own completed turn.
- **One connection per installation** (v1): only a single remote connection is
  allowed at a time.

## Concurrency, failure, recovery, and idempotency

- **SQLite deadlock fix**: the adapter avoids holding write locks during I/O
  (Telegram API calls happen outside the transaction).
- **Per-pairing locks**: each pairing has its own lock to prevent concurrent
  `getUpdates` processing from corrupting state.
- **Source key idempotency**: the `source_key` column on `remote_pairings`
  tracks the last processed Telegram update offset so restarts do not re-deliver
  messages.
- **Adapter crash recovery**: on startup the adapter resumes polling from the
  last persisted offset; no messages are lost if the process restarts.
- **Lifecycle ordering**: outbound delivery serializes queued status sends,
  finalization, and edits. A final card falls back to a new message only when
  its original status card could not be delivered.
- **Cross-origin authorization**: the synchronous stream observer queues an
  unregistered completion, then the asynchronous delivery path loads the
  session and applies the shared addressability predicate before sending.

## Completion and error notifications

Final Telegram notifications identify the outcome and the work itself: success
cards start with `Done: <task title>`, and failure cards start with
`Failed: <task title>` followed by a user-readable error. The card may include
the final response, tool count, elapsed time, and safe follow-up buttons, so a
user receiving only the notification can understand what finished or failed
without reopening the laptop.

## Telegram streaming responses

When a remote-origin turn is configured for live delivery, Telegram receives
incremental redacted assistant output in the same correlated status card. The
projection coalesces deltas and uses the existing Telegram edit budget; output
is previewed up to the provider message limit and finalized into the existing
completion or error card. A provider that does not advertise the private draft
capability uses `editMessageText`; draft-specific delivery is not required for
correctness. Partial delivery state is process-local and is abandoned safely on
restart, cancellation, or connection shutdown. Pairing, addressability,
redaction, and HTML escaping are applied to partial and final payloads alike.

## Observability

### Connection states

The `state` column covers 11 values:

`disconnected`, `connecting`, `connected`, `verifying`, `ready`, `paired`,
`polling`, `paused`, `error_token`, `error_network`, `error_api`

### Adapter status

Adapter health is reported through the standard `/api/health` and Diagnostics
routes. The remote section shows connection state, last poll time, and error
count.

## Compatibility, rollout, and rollback

- **One connection per installation** (v1): the API rejects a second connection
  creation with `409`.
- **Migration**: Alembic migration `00000064` adds `remote_connections` and
  `remote_pairings` tables.
- **Rollback**: removing the connection through the API or reverting the
  migration cleanly drops the tables.

## Ownership and source map

| Layer | Files |
|---|---|
| Adapter and polling | `app/remote/adapter.py`, `app/remote/poller.py` |
| Telegram client | `app/remote/telegram_client.py` |
| Connection and pairing services | `app/remote/connection_service.py`, `app/remote/pairing.py` |
| Outbound projection | `app/remote/projection.py` |
| Redaction | `app/remote/redaction.py` (wraps `protect_outbound_text`) |
| API routes | `app/api/routes/remote.py`, `app/api/routes/settings_remote.py` |
| Data models | `app/models/remote_connection.py`, `app/models/remote_pairing.py` |
| Migration | `app/migrations/versions/00000064_*.py` |
| Tests | `tests/remote/` |
| Frontend API client | `web/src/api/client/remote.ts` |
| Frontend settings page | `web/src/routes/settings.remote-access.tsx` |
