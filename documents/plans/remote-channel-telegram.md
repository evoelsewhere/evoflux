# Remote access over Telegram

Status: proposed

## Problem and outcome

EvoFlux is a local-first desktop application. The Tauri shell starts the
FastAPI sidecar on loopback with a per-launch bearer token, so a phone cannot
reach the application directly. When the user leaves a long-running task and
takes only their phone, a permission request, question, or plan review can
block the run until they return. Completion notices also remain on the desktop.

The outcome is a personal remote connection that dials out from a running
EvoFlux installation to Telegram. Each user creates and configures their own
bot on their own computer. After that one-time setup, they select **Connect
phone**, scan a QR code or open a link, and press Telegram's Start button. The
phone is paired without entering server addresses, session identifiers, or a
manual code.

Once paired, the user opens the bot and writes naturally. EvoFlux keeps one
current remote task for that connection, creates a Work task for the first
message when needed, and lets the user start a fresh task with one button.
Blocking gates and completion notices from user-visible desktop tasks arrive
automatically with the task name. Selecting **Continue this task** makes that
desktop task the phone's current conversation.

Telegram is the only adapter in the first release and each installation permits
one configured connection and one paired Telegram account. The core is
connection-aware: stored records, credential keys, service interfaces, source
keys, and callback ownership include a connection identifier. A later release
can permit several connections or add another adapter without changing those
ownership contracts. This is a narrow adapter seam, not a general plugin
framework.

Telegram's `getUpdates` long poll is outbound. The feature adds no listener,
tunnel, public URL, or LAN requirement. Telegram deep links carry a private
`start` parameter of at most 64 base64url characters, which is sufficient for a
single-use pairing token. Protocol constraints are defined by the official
[Bot API](https://core.telegram.org/bots/api) and
[deep-linking contract](https://core.telegram.org/bots/features#deep-linking).

## Goals

- Let a user operate their running EvoFlux installation from a phone without an
  inbound network path.
- Make first connection a scan-or-tap flow after the bot token is configured on
  the desktop.
- Accept natural-language work without requiring the user to understand
  sessions, IDs, modes, or command syntax.
- Deliver and resolve `permission_asked`, `question_asked`, and
  `plan_approval_requested` gates from the phone.
- Deliver one completion report for each user-visible top-level task, including
  tasks started on the desktop.
- Allow the user to continue a desktop task or start a new remote Work task with
  one explicit action.
- Keep approved workflows, Coding projects, Evo Agent Specs runs, and scheduled
  tasks available through a secondary menu without making that menu part of the
  primary flow.
- Preserve all existing permission, sandbox, workspace, workflow-approval, and
  outbound-data policies.
- Keep the feature free at rest: when unconfigured or disabled, it performs no
  imports of adapter code, creates no tasks, and makes no network calls.
- Make every installation responsible for its own bot and credential; EvoFlux
  provides no shared relay or hosted bot.
- Keep the first implementation ready for multiple connection records while
  enforcing a one-connection product limit in v1.

## Non-goals

- No inbound HTTP endpoint, public listener, tunnel, reverse proxy, or
  `evoflux start --lan` requirement.
- No EvoFlux-hosted Telegram bot, shared bot token, account service, cloud
  relay, or cross-installation routing.
- No more than one configured remote connection or one paired Telegram account
  per installation in v1.
- No group chats, channel chats, topics, inline mode, Mini Apps, guest mode, or
  business-bot behavior.
- No attachments, voice, photos, files, location, contacts, reactions, or media
  in either direction.
- No remote entry or modification of provider credentials, bot credentials,
  sandbox policy, outbound-data policy, connection settings, model-provider
  configuration, or `permission_mode: bypass`.
- No durable **Always allow** permission decision from the phone.
- No remote approval of a new or changed Workflow definition. A remotely
  started Workflow must already satisfy the existing definition-hash approval
  contract.
- No execution of Telegram messages accumulated while EvoFlux is stopped.
- No complete session browser or transcript export. The channel sends bounded
  event projections and finalized replies, not historical session content.
- No durable outbound outbox, Telegram update archive, callback table, or
  remote-interaction table in v1.
- No general remote-channel plugin SDK, adapter discovery protocol, or
  third-party adapter loading.

## User flows and states

### Configure the personal connection

The user creates a bot with `@BotFather`, opens **Settings → Remote access**,
and pastes the token. EvoFlux calls `getMe` before storing anything. A valid
response supplies the immutable bot identifier and display username shown for
review. EvoFlux then stores the token in the OS credential vault under the new
connection ID and creates the connection record.

If validation or vault storage fails, no connection record remains and the UI
shows an actionable error. The token is never written to `settings.yaml`, the
application database, logs, diagnostics, or the config-directory `.env` file.

The installation permits one configured connection in v1. The service returns
a stable conflict response if a second connection is requested. This is a
service-level product limit rather than a database uniqueness constraint.

### Connect the phone

The user selects **Connect phone**. EvoFlux creates an in-memory, single-use
pairing token with at least 128 bits of entropy and a ten-minute expiry. The UI
shows both a QR code and an **Open Telegram** action for:

```text
https://t.me/<bot_username>?start=<pairing_token>
```

Opening the link presents Telegram's normal Start action. The resulting
`/start <pairing_token>` update must come from a private chat. EvoFlux binds the
transport-reported principal ID and destination/chat ID to the connection,
deletes the pairing token, sends **Connected to EvoFlux on <device label>**,
and displays the paired Telegram account on the desktop.

The principal ID authorizes actions. The destination ID addresses replies.
They are stored separately and are never assumed to be equal, even when the
first adapter commonly reports matching values for a private chat.

A plain `/start` without a valid token does not pair. An invalid or expired
token receives no installation details. The UI can mint a replacement without
changing the connection or bot token.

### Send the first task

After pairing, the user sends ordinary text. If the pairing has no current
task, EvoFlux creates a top-level Work session using the existing default team,
model, permission mode, and Work workspace behavior. The message is persisted
and dispatched through the same interactive ingress used by the desktop. The
bot replies with a short accepted or queued acknowledgement.

The created session receives channel-neutral provenance tags
`remote_origin` and `remote_connection:<connection-id>`. These tags support
diagnostics and future ownership checks; they do not weaken tool policy and are
not required for desktop sessions to emit remote notices.

Later plain text continues the pairing's current task. If the task is already
running, existing follow-up delivery policy decides whether the message is
spliced into the turn or queued. The phone reports the actual accepted,
pending, or queued result.

### Observe and continue a desktop task

While the connection is enabled and paired, the remote service observes
user-visible top-level Work and Coding sessions. Team-member child sessions,
Side Chat sessions, internal sessions, and raw specialist activity are not
remote-addressable.

Blocking gates and terminal completion notices are projected automatically.
Each message names the task and includes an opaque **Continue this task**
button. Pressing it changes only that pairing's `active_session_id`; it does not
modify the session, cancel work, or resend history. The bot confirms the new
current task. Subsequent plain text follows up in that session through the
normal persisted ingress.

The phone never needs a `/sessions` command for the primary flow. A secondary
**Recent tasks** menu may list a bounded set of top-level sessions if the user
explicitly opens the menu.

### Start a new task

The persistent **New task** action clears the current binding and creates a new
top-level Work session when the user submits their next message. It never
deletes, interrupts, archives, or hides the previous task.

Starting a Coding task requires selecting an existing authorized Coding
project from the secondary menu. Remote input cannot add a repository or widen
the selected project's authorized workspace paths.

### Answer a blocking gate

Permission cards identify the task, tool, and complete policy-relevant patterns
after outbound redaction. Choices are **Allow once** and **Deny**. There is no
remote **Always allow** action.

Question cards render every required question and its allowed choices. Freeform
answers are accepted only when the existing question schema permits them. Plan
cards show a bounded plan summary and offer the same transient approval/reject
decisions as the existing plan-review service.

The callback query is acknowledged immediately, before database access or gate
resolution. The card is then edited to a terminal state. If the gate was
answered on the desktop first, the buttons disappear and the card says that it
was answered elsewhere.

### Receive status and completion

A message admitted from the phone creates one short lifecycle message for that
turn. EvoFlux edits it only when the admission state changes, the turn fails, or
the turn completes. It does not send periodic progress or mirror activity.
Token deltas, model thinking, tool output, specialist mail, usage events, and
raw stream envelopes are never copied to Telegram.

All user-visible top-level tasks may send a terminal completion notice. On
`done`, the service reads the finalized persisted assistant message rather than
reconstructing a result from stream deltas. It sends the task name, bounded
final text, and **Continue this task**. If no finalized assistant message is
available, it sends a completion stub that directs the user to EvoFlux.

Long text is split at safe text boundaries within Telegram's message limit.
Messages are sent without a parse mode so model text cannot manufacture links,
mentions, or formatting through Telegram markup.

### Advanced actions

The bot profile exposes only `/start`, `/help`, `/status`, `/new`, `/stop`, and
`/unpair`. An optional **More actions** menu provides:

- recent top-level tasks;
- existing Coding projects;
- approved Workflows;
- eligible Evo Agent Specs runs and currently available actions;
- existing scheduled tasks that permit manual triggering.

Every list uses opaque, expiring choice tokens. It never embeds repository
paths, database UUIDs, definition hashes, or credentials in `callback_data`.
The menu is secondary: a user can pair, work, answer gates, receive results,
continue a desktop task, and start a new task without opening it.

### Disable, unpair, and remove

- **Disable connection** stops polling and outbound delivery but retains the
  connection record, vault credential, and pairing.
- `/unpair` from the paired private account deletes the pairing and invalidates
  its active callback tokens. It works even when other remote commands are
  restricted.
- **Unpair phone** on the desktop performs the same deletion.
- **Remove connection** stops the adapter, deletes the pairing and connection,
  deletes the vault credential, and invalidates all connection-owned tokens.
  It does not delete or modify chat sessions.

### Stale and refused states

- An unpaired sender receives no response except when presenting a valid live
  pairing token.
- A group, channel, bot-authored, edited, media-only, or unsupported update is
  ignored and counted by reason.
- A callback after restart reports that the action expired.
- A callback after another surface resolved the gate reports that it was
  already answered.
- A callback owned by another connection or principal is refused without
  revealing its target.
- A revoked bot token stops the poller and produces an **Invalid token** state.
- Another consumer polling the same bot produces a **Used elsewhere** state and
  bounded retries; the UI explains that each EvoFlux installation needs its
  own bot.
- If the paired account blocks the bot or the chat becomes unavailable,
  Settings shows **Phone unreachable** while the poller remains diagnosable.
- Messages accumulated while EvoFlux was stopped are discarded before live
  polling starts and never execute later.

## Requirements and acceptance criteria

- **AC-1 — Off and free by default:** With no enabled connection, importing
  `app.api.app` leaves Telegram adapter modules absent from `sys.modules`, no
  remote task is created, and no network request is made.
- **AC-2 — Outbound only:** Enabling remote access opens no listening socket and
  introduces no route authenticated by a Telegram token. Every new HTTP route
  uses normal desktop authentication.
- **AC-3 — Per-installation ownership:** Setup creates a connection owned by the
  local installation. No shared service or default bot exists, and v1 returns a
  defined `409` response when a second connection is requested.
- **AC-4 — Connection-aware contracts:** Every pairing, credential key, inbound
  source key, callback token, queue item, and runtime status carries a
  connection ID. Tests can instantiate two service-level connections and prove
  that messages and callbacks never cross them even though the public v1 API
  prevents configuring the second.
- **AC-5 — Token custody:** A bot token is validated before persistence and
  stored only in the OS credential vault under its connection ID. Vault failure
  leaves no partial connection. No settings, model, API response, log, trace,
  diagnostic, or exception string contains the token.
- **AC-6 — Bot identity binding:** `getMe` must report a bot account. The
  connection stores its immutable bot ID and current username. Token replacement
  that resolves to another bot invalidates the existing pairing and outstanding
  callbacks before the new credential becomes active.
- **AC-7 — One-tap pairing:** **Connect phone** returns a QR payload and HTTPS
  deep link whose `start` parameter has at least 128 bits of entropy, contains
  only Telegram-permitted characters, is at most 64 characters, expires after
  ten minutes, is single-use, and exists only in process memory.
- **AC-8 — Pairing authorization:** Pairing succeeds only for a valid token in a
  private chat. The stored principal ID authorizes every message and callback;
  the separately stored destination ID addresses replies. V1 permits one active
  pairing per connection.
- **AC-9 — Silence and rate limits:** An unpaired sender, invalid token, group
  chat, and unsupported update reveal no installation state. Pairing attempts
  and accepted inbound actions have per-principal and connection-wide rate
  limits that cannot be used as a response amplifier.
- **AC-10 — Immediate revocation:** Desktop unpair, `/unpair`, token replacement,
  and connection removal invalidate applicable callback and menu tokens before
  returning. A later update from the former principal is unauthorized.
- **AC-11 — No stale replay:** Startup removes any webhook, drops pending
  updates, and establishes a fresh offset before accepting live input. An update
  sent while EvoFlux is stopped never creates a session, message, or run.
- **AC-12 — Telegram error taxonomy:** Webhook conflict is cleared once;
  concurrent-consumer conflict enters bounded backoff and a visible
  `used_elsewhere` state; authentication failure stops polling in
  `invalid_token`; `429` honors `retry_after`; transport errors use exponential
  backoff with jitter; an unreachable paired chat affects delivery state without
  crashing inbound polling.
- **AC-13 — Prompt shutdown:** Disabling or stopping the service cancels long
  polling and interruptibly exits backoff without waiting for the configured
  poll timeout or remaining retry delay.
- **AC-14 — Natural first message:** A valid plain-text message with no active
  task creates one top-level Work session and submits the text without requiring
  a command, mode, session ID, or desktop action.
- **AC-15 — Correct interactive ingress:** Remote text resolves the persisted
  session/team and uses `submit_persisted_interactive_message`. Accepted,
  pending, and queued outcomes are reported accurately. It never calls EvoFlux's
  own HTTP API over loopback.
- **AC-16 — Inbound idempotency:** The source key includes adapter, connection
  ID, and Telegram update ID. Redelivery within a process and replay after a
  crash between persistence and offset acknowledgement produce at most one
  persisted user message.
- **AC-17 — Current-task behavior:** Each pairing has at most one current task.
  **Continue this task** changes only that pointer; **New task** clears it; the
  next plain message creates the replacement Work session; deleting a current
  session sets the pointer to null.
- **AC-18 — Addressable session boundary:** Only user-visible, top-level Work and
  Coding sessions may be selected or notified. Team-member, Side Chat, and
  internal sessions are neither listed nor addressable.
- **AC-19 — Non-perturbing observation:** Stream observation performs no await,
  network, database, model, filesystem, or blocking work. It uses `put_nowait`
  into bounded connection-owned queues and records overflow without delaying
  the producing turn.
- **AC-20 — Explicit event allowlist:** Only gate asks/replies, terminal errors,
  `done`, and relevant `desktop_notification` events are candidates for stream
  projection. Thinking, content/tool deltas, widget deltas, summarization,
  usage, inbox, delegation, handoff, member status, goal status, and unknown
  event types are dropped.
- **AC-21 — Completion deduplication:** A turn emitting both `done` and
  `desktop_notification(kind="assistant_done")` produces one completion notice.
  Its body comes from the finalized persisted assistant message, not accumulated
  stream chunks.
- **AC-22 — Quiet lifecycle status:** A phone-admitted turn owns at most one
  lifecycle message. Accepted, queued, running, failed, and completed
  transitions edit that message instead of appending progress. Desktop-started
  tasks produce no activity chatter before a gate, error, or completion.
- **AC-23 — Explicit outbound policy:** Every user-controlled string and every
  agent/session-derived field passes through the policy configured for the
  `remote` outbound channel. Redaction is the default. A block decision emits a
  fixed withheld-content stub and leaves observation running.
- **AC-24 — Safe text rendering:** Model text is sent without Telegram parse
  mode, is split within provider limits without breaking Unicode, and never
  becomes a gate or command solely because its content resembles EvoFlux UI.
- **AC-25 — Gate coverage:** Permission, question, and plan-review gates render
  defined cards. Each `callback_data` payload is opaque, connection-owned,
  principal-bound, process-memory-only, expiring, and at most 64 bytes.
- **AC-26 — Acknowledge first:** A callback query is answered before gate lookup,
  database work, or execution. The subsequent edit communicates success, stale,
  already answered, expired, or refused state.
- **AC-27 — Least durable authority:** Remote permission replies offer only
  `once` or `reject`. Plan approval uses the existing exact request and session;
  questions use the existing validated answer schema. Remote actions cannot
  create durable permission rules.
- **AC-28 — Answered elsewhere:** Existing permission, question, and plan reply
  events remove buttons from the matching Telegram card and mark it answered,
  regardless of whether the resolution came from desktop or phone.
- **AC-29 — Safe interruption:** `/stop` interrupts only the pairing's current
  active turn through the existing team interrupt path. It does not stop the
  sidecar, delete the task, cancel unrelated sessions, or imply success when no
  turn is active.
- **AC-30 — Existing approval boundaries:** An unapproved or changed Workflow
  definition retains its existing refusal. Remote access cannot approve the
  definition, add a Coding repository, change workspace authorization, or set
  bypass permission mode.
- **AC-31 — Secondary run coverage:** Through the optional menu, an approved
  Workflow, an authorized Coding project task, an eligible Evo Agent Specs
  action, and an existing manually-triggerable scheduled task can be started.
  Every refusal from the owning service is preserved and rendered safely.
- **AC-32 — No remote secrets or settings writes:** No Telegram command, menu
  action, or natural-language shortcut accepts a credential value or changes
  connection/provider/sandbox/outbound settings. Status output contains no
  environment values or secret presence details beyond the current connection's
  configured state.
- **AC-33 — Local API posture:** Packaged desktop authentication remains
  unchanged. An external/LAN sidecar configuration must satisfy its existing
  access-key policy; remote access neither bypasses nor self-calls that API.
- **AC-34 — Diagnosable:** Connection status reports lifecycle state, last safe
  error class, last successful poll time, pairing state, phone reachability, and
  bounded queue-drop counters. Logs contain no bot token, pairing token,
  callback token, forwarded content, or raw Telegram payload.
- **AC-35 — Retention is explicit:** Setup and Help state that Telegram stores
  bot chats on its service and that pairing permits bounded task information to
  leave the machine. EvoFlux persists only normal session messages and the
  connection/pairing metadata defined below.
- **AC-36 — Documented and localized:** The shipped feature contract,
  configuration and HTTP references, Settings copy, and in-app Help in English,
  Vietnamese, and Japanese describe setup, offline behavior, privacy, revocation,
  and desktop-only operations.
- **AC-37 — Clean integration:** Focused backend/frontend tests, schema-head and
  upgrade-path tests, Ruff, format check, ty, frontend lint/typecheck/build, and
  `git diff --check` pass without incorporating unrelated worktree changes.

## API, event, tool, and UI contracts

### Desktop HTTP API

All routes use existing desktop authentication and expose no Telegram-authenticated
HTTP surface.

| Route | Purpose |
|---|---|
| `GET/PUT /api/settings/remote` | Read or update `outbound_data_policy` and `outbound_pii_policy`; connection enablement remains on the connection record |
| `GET /api/remote/connections` | Return the zero-or-one v1 connection summary and safe runtime state |
| `POST /api/remote/connections` | Validate a write-only token, save it to the vault, and create the connection; `409` when one already exists |
| `PATCH /api/remote/connections/{id}` | Change label or enabled state; adapter kind and bot identity are immutable |
| `PUT /api/remote/connections/{id}/token` | Validate and atomically replace the write-only token; re-pair if bot identity changes |
| `DELETE /api/remote/connections/{id}` | Stop and remove the connection, pairing, tokens, and vault credential |
| `POST /api/remote/connections/{id}/pairing-links` | Mint a single-use deep link and return link, QR payload, and expiry |
| `GET /api/remote/connections/{id}/pairing` | Return safe paired-account decoration or `null` |
| `DELETE /api/remote/connections/{id}/pairing` | Revoke the paired account and outstanding interaction tokens |
| `GET /api/remote/connections/{id}/status` | Return adapter lifecycle, last safe error, poll time, reachability, and drop counts |

Secret-bearing request models use write-only fields. OpenAPI examples and error
payloads contain placeholders, never realistic tokens. `GET` responses report
`token_configured: true|false`, not the credential or its fingerprint.

### Internal channel seam

`app/remote/contracts.py` defines provider-neutral values such as:

- `RemoteAdapterKind`, initially `telegram`;
- `RemotePrincipal` with `principal_id`, `destination_id`, and untrusted display;
- `RemoteInboundAction` for text, callback, and pairing-start updates;
- `RemoteOutboundMessage` with plain text, buttons, correlation, and priority;
- `RemoteAdapterStatus` and safe error classes;
- `RemoteAdapter`, whose lifecycle and send/edit/ack methods never decide
  EvoFlux authorization.

`RemoteService` owns connection limits, credential access, adapter lifecycle,
pairing, principal authorization, current-task routing, source-key generation,
event projection, callback-token ownership, and status aggregation.
`TelegramAdapter` owns Bot API translation, long-poll offsets, provider limits,
and Telegram error classification. Generic services never import Telegram
payload models.

The adapter is constructed lazily only for an enabled, credential-complete
connection. The first release uses EvoFlux's existing `httpx` dependency rather
than adding a Telegram framework with its own scheduler or global state.

### Telegram update contract

Long polling supplies `allowed_updates=["message", "callback_query"]`. The
adapter accepts only new private-chat text messages from non-bot users and
callback queries for bot-authored messages. It ignores edited messages and all
media/service-message variants except the `/start <token>` pairing input.

The poller processes updates in update-ID order. It advances the next offset
only after an update is safely classified and any accepted text has reached
durable message admission. A crash between admission and offset confirmation is
safe because the source key deduplicates the repeated update. Restart backlog
discard intentionally provides no across-restart delivery promise for updates
that never reached admission.

### Stream observer contract

`app/services/memory_stream_store.py` gains process-wide observer registration.
Observers are synchronous callbacks invoked after the stream state has accepted
an envelope. Registration returns an idempotent unregister handle. Observer
failure is isolated, logged without payload content, and cannot fail the stream
producer.

The remote observer copies only minimal allowed fields into immutable queue
items. A bounded high-priority queue carries gates and terminal notices. Phone
admission status is produced by the remote service and uses a separate bounded
informational queue. Informational overflow drops the oldest informational
item. High-priority overflow leaves the underlying gate unresolved, increments
a critical delivery-failure counter, and keeps desktop resolution available;
the design does not claim impossible losslessness from a bounded, non-blocking
queue.

No new SSE event type is needed. The observer consumes existing normalized
events and reply events.

### Remote interaction contract

Buttons contain only a compact random token and action code. The in-memory token
record owns connection ID, principal ID, destination ID, session ID, source
event/request ID, allowed action set, Telegram message reference, creation time,
and expiry. Provider callback data never contains a raw session ID, database ID,
path, command, plan, or answer.

Callback acknowledgement is transport-only and precedes resolution. Resolution
calls the existing permission, question, plan, interrupt, Workflow, Scheduler,
or Evo Agent Specs service directly. The remote service does not make loopback
HTTP requests and does not duplicate owning business rules.

### Settings UI

Settings adds one **Remote access** section using the existing Settings overlay
primitives. Its normal state contains:

- a short explanation that EvoFlux must remain running;
- the one-time personal bot-token field;
- validated bot identity;
- enabled/disabled control;
- **Connect phone** with QR code and **Open Telegram** fallback;
- paired-account display and **Unpair phone**;
- connection health and last safe error;
- **Remove connection**;
- visible disclosure that task text sent through the bot is retained by
  Telegram and is not end-to-end encrypted bot chat.

The primary Telegram keyboard contains **New task**, **Status**, and **More
actions**. Gate and completion messages add contextual inline buttons. Internal
terms such as session UUID, SSE, update offset, adapter, and pairing row are not
shown in the normal user flow.

## Data model, migration, and retention

Migration `00000064` with `down_revision = "00000063"` creates two tables and
updates the schema-head marker.

### `remote_connections`

| Column | Contract |
|---|---|
| `id` | UUID primary key |
| `adapter` | bounded adapter kind, initially `telegram` |
| `label` | user-editable installation-local label |
| `enabled` | desired lifecycle state |
| `adapter_principal_id` | validated immutable bot identifier, not the token |
| `adapter_username` | current validated bot username, untrusted display/routing decoration |
| `created_at`, `updated_at` | timezone-aware timestamps |

The vault account key derives from the connection ID and never appears in API
responses. Runtime status, last errors, offsets, queues, and retry state remain
in process memory.

### `remote_pairings`

| Column | Contract |
|---|---|
| `id` | UUID primary key |
| `connection_id` | required FK to `remote_connections`, cascade delete |
| `principal_id` | channel-attested account identity used for authorization |
| `destination_id` | channel address used for replies |
| `label` | user-editable local label |
| `display` | channel-reported untrusted decoration |
| `active_session_id` | nullable FK to `chat_sessions`, `ON DELETE SET NULL` |
| `created_at`, `last_seen_at` | timezone-aware timestamps |

The table is unique on `(connection_id, principal_id)` and on
`(connection_id, destination_id)`. The service enforces one pairing per
connection in v1. Database cardinality remains connection-aware for later
product expansion.

Revocation deletes the pairing instead of retaining identity history. Removing
a connection cascades its pairing. Session deletion only clears the active
pointer. No remote operation deletes session messages.

Pairing tokens, callback/menu tokens, update offsets, progress-message IDs,
deduplication caches, outbound queues, rate-limit windows, and error/backoff
state are deliberately ephemeral. The normal persisted user and assistant
messages remain governed by existing session retention. EvoFlux stores no extra
copy of Telegram message content or raw update bodies.

## Permissions, security, privacy, and trust

Pairing is installation-level operating authority. A paired account may create
and continue tasks, interrupt its current task, answer transient gates, and
invoke already-approved actions. It may not configure or widen the installation.

Telegram bot chats are an external retention boundary and are not end-to-end
encrypted. Telegram, anyone controlling the user's Telegram account, and anyone
holding the bot token may be able to read bot-chat content. This consequence is
shown before pairing and documented in Help. Redaction, event allowlisting, and
bounded replies reduce exposure but do not make the channel local or encrypted.

The bot token is a root credential. Its holder can impersonate the bot and read
updates delivered to it. EvoFlux stores it only through an OS-vault
abstraction modeled on the existing Conductor credential pattern, but
implemented as an independent module used only by remote access. Conductor's
own credential handling is left unchanged: it is an external integration point
relied on by `evo-conductor`, and this feature must not alter its behavior or
its constructor contract. Vault unavailability is a setup failure, not a
reason to create a plaintext fallback. Recovery from suspected token theft is
regeneration through `@BotFather` and token replacement in EvoFlux.

The Telegram principal ID, not username or display name, authorizes inbound
actions. Usernames and display names can change and remain decoration. Every
callback rechecks connection, pairing, principal, destination, allowed action,
expiry, and underlying EvoFlux request state.

Remote natural language has the same potential to trigger tools as desktop
natural language. Existing permission mode, sandbox roots, workspace
authorization, outbound model policy, tool policy, and workflow approval remain
authoritative. The adapter cannot invoke tool functions directly.

Agent-controlled text is untrusted channel content. It is plain text, carries a
fixed EvoFlux/task provenance header, and never creates Telegram buttons. Only
the remote service constructs buttons from normalized internal events.

Gate context can contain commands, paths, or user data. Every field passes
through the explicit `remote` outbound channel policy. The existing
`OutboundChannel` contract gains `remote`; policy selection is explicit rather
than inherited from ambient sandbox state.

Pairing and callback tokens are capability secrets with short lifetimes. They
are generated with a cryptographic RNG, compared without logging, invalidated
on successful use or ownership change, and never stored in session content.

## Concurrency, failure, recovery, and idempotency

One adapter task owns polling for one connection. Update classification is
sequential to preserve offset ordering. Outbound delivery uses separate worker
tasks so a slow Telegram send cannot hold a stream lock, database transaction,
or inbound poll loop.

The service never performs network I/O, model calls, process startup, or file
operations within a database transaction. It reads or mutates the smallest
durable unit, commits it, then performs external delivery. Compensating cleanup
removes a connection record if vault persistence fails during creation.

Telegram allows one `getUpdates` consumer per bot and disallows polling while a
webhook is installed. Startup calls the provider operation that removes an
existing webhook and drops queued updates, then begins long polling with an
explicit allowed-update set. A polling conflict is a visible connection state,
not a tight retry loop. The UI tells the user to configure a different personal
bot for each EvoFlux installation.

Inbound accepted text is at-least-once within a process but effect-once through
the persisted source key. Restart deliberately discards never-admitted backlog.
Callback resolution is idempotent because the underlying gate service resolves
one request once and the remote token becomes terminal after the first attempt.

Outbound messages have no durable delivery guarantee. Informational delivery
may be dropped under bounded pressure. A failed gate delivery never auto-allows
or auto-denies the request; the task remains blocked and resolvable on desktop.
The status surface exposes the failure.

Disable and shutdown follow structured cancellation: stop accepting new
actions, cancel long polling, wake retry waits, stop delivery workers, unregister
the stream observer, clear ephemeral tokens/queues, then close the HTTP client.
Repeated stop is safe.

## Observability and diagnostics

Connection state is one of:

```text
disabled | starting | pairing | polling | backoff | rate_limited |
used_elsewhere | invalid_token | phone_unreachable | credential_missing | error
```

The status response includes connection ID, adapter kind, enabled state,
validated bot decoration, paired/unpaired state, phone reachability, last
successful poll time, last safe error class, current backoff deadline, and
informational/high-priority drop counters. It never includes raw provider
responses or credential/token material.

Metrics cover received updates by accepted/refused reason, admission outcomes,
delivery attempts/results, callback outcomes, rate-limit waits, polling state,
queue depth, queue drops, and redaction/block decisions. Labels use bounded
enums and never principal, destination, session, username, task title, or
message content.

Logs cover lifecycle transitions, safe provider error classes, pairing creation
and revocation by internal record ID, and bounded counters. Principal and
destination identifiers are omitted or one-way pseudonymized for correlation.
The diagnostics snapshot checks that no token-like URL or authorization header
is present.

## Compatibility, rollout, and rollback

The feature is additive and disabled by default. Existing installations create
no adapter runtime until the user configures and enables a connection. No
existing route or SSE shape changes meaning. Process-wide observer registration
is inert when no observer exists.

The first release permits one connection at the service/API/UI layer. Tables and
internal contracts have connection IDs and no singleton database constraint.
Supporting several bots later requires lifting the admission limit and adding
selection/notification policy; it does not require rekeying pairings,
credentials, callbacks, or inbound idempotency.

Each computer requires its own bot token. Moving a user to another installation
means configuring another bot there; EvoFlux never transfers a bot token or
pairing automatically.

Rollout is controlled by the connection record's `enabled` field. Disabling is
the immediate operational rollback. Removing the connection clears its durable
metadata and vault secret. Migration downgrade drops only the two remote tables
and leaves all chat sessions/messages intact.

Implementation proceeds in independently verifiable vertical slices:

1. connection/pairing schema, vault abstraction, routes, and Settings setup;
2. Telegram polling, one-tap pairing, authorization, lifecycle, and status;
3. natural-language Work task creation/continuation and inbound idempotency;
4. stream projection, persisted completion delivery, and task continuation;
5. gate cards, races, revocation, and interruption;
6. optional advanced actions, documentation, localization, and final regression.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1, AC-2 | Disabled-lifespan/import/network test; route/auth and socket inventory inspection |
| AC-3, AC-4 | Connection admission tests plus two-connection service isolation tests for credentials, sources, callbacks, and queues |
| AC-5, AC-6 | Credential-store failure/rollback, masked response/log/diagnostic tests, `getMe` bot validation, and bot-identity replacement tests |
| AC-7, AC-8, AC-9 | Pairing token entropy/charset/length/expiry/single-use tests; private-chat principal/destination and rate-limit cases |
| AC-10 | Desktop and remote revocation tests proving callback/menu invalidation before return |
| AC-11, AC-12, AC-13 | Mock-transport tests for webhook/backlog disposal, error classes, retry timing with fake clock/jitter, and interruptible shutdown |
| AC-14, AC-15, AC-16 | Service tests for first-message Work creation, existing interactive ingress, accurate status, and duplicate update/source-key handling |
| AC-17, AC-18 | Current/new/continued/deleted task tests and refusal of child, Side Chat, and internal sessions |
| AC-19, AC-20 | Stream-store observer tests proving no await/blocking work and exhaustive event allowlist/drop behavior |
| AC-21, AC-22, AC-24 | Persisted completion/dedup tests, single-message lifecycle transitions, Unicode-safe splitting, and plain-text rendering tests |
| AC-23 | Remote outbound redaction and blocking-policy tests for every user/agent-derived field |
| AC-25, AC-26, AC-27, AC-28 | All three gate families, callback byte limit/ownership/expiry, acknowledgement ordering, least authority, stale races, and edit-on-reply tests |
| AC-29, AC-30 | Current-turn-only interrupt test and Workflow/repository/policy mutation refusal tests |
| AC-31 | Focused service-contract tests for approved Workflow, Coding task, eligible Evo Agent Specs action, and scheduled-task manual trigger |
| AC-32, AC-33 | Command/route inventory and desktop-auth regression tests |
| AC-34 | Status, bounded-metric-label, log capture, and diagnostics secret-absence tests |
| AC-35, AC-36 | Settings disclosure plus feature/config/API and three-locale Help review |
| AC-37 | Migration head/upgrade tests, focused suites, backend/frontend quality gates, and `git diff --check` |

## Ownership and source map

- Connection-aware core, service, adapter contracts, Telegram transport,
  pairing, projection, interaction tokens, and status: `app/remote/`.
- OS-vault abstraction modeled on the existing Conductor precedent but kept as
  independent, standalone infrastructure used only by remote access:
  `app/core/credential_store.py`. `app/conductor/client.py` and
  `app/conductor/service.py` are not modified; Conductor is an external
  integration point (`evo-conductor`) and keeps its own credential
  implementation and constructor contract unchanged.
- Persistence: `app/models/remote.py`, model registration, and
  `app/migrations/versions/00000064_create_remote_pairings.py`; schema marker:
  `app/core/schema_version.py`.
- Thin schemas/routes and application lifecycle: `app/api/schemas/remote.py`,
  `app/api/routes/remote.py`, `app/api/routes/settings.py`, and `app/api/app.py`.
- Stream observation: `app/services/memory_stream_store.py`.
- Existing task/session creation and interactive ingress:
  `app/services/chat_service.py`, `app/services/interactive_message_service.py`,
  and `app/services/team_manager.py`.
- Gate owners: `app/agent/permission.py`, `app/agent/ask_user.py`, and
  `app/agent/plan.py`.
- Explicit remote outbound policy: `app/agent/outbound_redaction.py` and the
  existing sandbox/runtime-settings boundary.
- Existing action owners: `app/workflow/`, `app/scheduler/`, and the Evo Agent
  Specs services/routes. The remote layer calls services rather than copying
  their approval rules.
- Settings client and UI: `web/src/api/types.ts`, `web/src/api/client/settings.ts`,
  `web/src/components/settings/`, and the existing Settings navigation.
- In-app Help: `web/src/help/locales/en.ts`, `web/src/help/locales/vi.ts`, and
  `web/src/help/locales/ja.ts`.
- Current feature contract to create when implementation ships:
  `documents/features/remote-access.md`, plus a catalogue row in
  `documents/features/README.md` and trust cross-reference from
  `documents/features/security-and-permissions.md`.
- Current references to update when implementation ships:
  `documents/reference/configuration.md` and
  `documents/reference/http-api.md`.

The plan remains historical/proposed until implementation is verified and the
current feature/reference/Help documents are reconciled. This file does not by
itself claim that remote access is available.
