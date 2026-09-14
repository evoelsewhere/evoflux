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

1. **One-tap pairing** — scan a QR or open a deep link; no manual token entry
   on the phone.
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

1. User creates a Telegram bot via BotFather and copies the bot token.
2. In Settings → Remote access the user pastes the token and clicks Connect.
3. EvoFlux stores the token in the OS credential vault, verifies it with the
   Telegram API, and creates a `remote_connections` row.
4. The UI shows a pairing link (or QR). The user opens it on the phone.
5. The user taps Start in the bot chat. EvoFlux records the `chat_id` in
   `remote_pairings` and the state becomes `paired`.

### Daily use

1. User sends a message to the bot on Telegram.
2. The remote adapter polls `getUpdates`, matches the `chat_id` to a pairing,
   and forwards the text into the active session as a user message.
3. The adapter immediately sends one HTML-formatted status card and repeats
   Telegram's native typing indicator while the phone-started turn is unresolved.
   The status card contains only the task title and admission status.
4. On completion or error, the adapter edits that card into a bounded final
   summary. It never mirrors token, tool, or file-path deltas into the live
   status text.
5. A completed card can offer **Full diff** and **Tool log**. Each button is a
   short-lived, opaque capability for that exact turn only; tapping it sends
   the already-persisted detail as redacted, escaped, bounded follow-up cards.
   It cannot retrieve a different turn or session, and an expired button asks
   the user to request fresh detail.

### Desktop, Workflow, and Scheduler completion

- The pairing's persisted notification scope defaults to `all`. Under that
  scope, an addressable top-level Work or Coding session started from the
  desktop, Workflow, or Scheduler sends the same final completion/error card
  to the paired phone.
- These cross-origin sessions never create a live status card or typing
  indicator. Side Chat, child, internal, and otherwise non-addressable
  sessions never notify the phone.
- The `remote_only` scope keeps notifications limited to `remote_origin`
  sessions.

### Gate flow

1. The session hits a permission, question, or plan gate.
2. The stream observer emits a gate event; the adapter sends a Telegram message
   with inline buttons (e.g. Allow once / Reject, Accept / Revise / Reject).
3. The user taps a button. The adapter resolves the gate and continues.

### Unpair

- Desktop: Settings → Remote access → Remove.
- Phone: send `/unpair` to the bot.

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
| Connection and pairing services | `app/remote/connection_service.py`, `app/remote/pairing_service.py` |
| Outbound projection | `app/remote/projection.py` |
| Redaction | `app/remote/redaction.py` (wraps `protect_outbound_text`) |
| API routes | `app/api/routes/remote.py`, `app/api/routes/settings_remote.py` |
| Data models | `app/models/remote_connection.py`, `app/models/remote_pairing.py` |
| Migration | `app/migrations/versions/00000064_*.py` |
| Tests | `tests/remote/` |
| Frontend API client | `web/src/api/client/remote.ts` |
| Frontend settings page | `web/src/routes/settings.remote-access.tsx` |
