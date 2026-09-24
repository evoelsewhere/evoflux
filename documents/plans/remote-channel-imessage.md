# Remote channel: iMessage

Status: proposed

**Extends `documents/plans/remote-channel-telegram.md` and the plans built
on it.** Those documents remain normative for the Telegram adapter except
where revised below. This document adds a second transport and, as a
direct consequence of adding one, revises three accepted contracts:

- **AC-1** (off and free by default) is extended verbatim to iMessage: with
  no enabled, credentialed iMessage connection, nothing imports
  `app.remote.imessage.*`, creates a task, or opens a socket.
- **AC-3** (exactly one configured connection) is revised to *one connection
  per adapter kind, at most one enabled at a time*. The schema was already
  connection-aware, so this is a service-level change with no rekeying.
- **AC-57** (shared edit budget for live-mode edits) is revised twice over.
  Answer *text* no longer flows through it on either transport: it moves to
  a streaming-strategy seam, with Telegram private chats using
  `sendMessageDraft` and iMessage using block streaming. The budget
  survives for *status-card* edits, gaining a count-in-window dimension
  that iMessage requires and Telegram opts out of.

## Problem and outcome

The remote channel works, but reaching it costs the operator a Telegram
account and a bot token. For an operator whose phone is an iPhone, the app
they already live in is Messages. The outcome is a second transport that
behaves like the first — pair a phone, send a prompt, watch the answer
arrive, approve or reject a permission — delivered natively in Messages,
with no third-party bot and no account to create.

Three things make this harder than "write a second adapter", and the
design exists to absorb them.

**iMessage has no bot API.** Apple exposes nothing. Every working
integration puts a Mac in the loop: a machine signed into Messages,
reading `~/Library/Messages/chat.db` and sending through Messages.app.
Self-hosted bridges over that Mac (BlueBubbles Server; `imessage-rs`,
which is API-compatible with it) expose a REST surface. Cloud resellers
that rent the Mac cost $39-100/month and send from a business number,
which contradicts this product's premise. The decision is therefore: speak
the BlueBubbles REST protocol, and let the operator supply the Mac. An
operator with no Mac keeps using Telegram, which already works.

**iMessage has no buttons.** The entire interaction surface built in
`remote-telegram-control-surface.md` — permission cards, `/settings`,
project pickers — resolves through inline buttons carrying opaque
capability tokens. iMessage has no equivalent and never will. What it has
instead is tapbacks, threaded replies, and text. The design maps
capability tokens onto those without changing `app/remote/actions.py` or
`app/remote/gates.py`, which never learn that a second transport exists.

**iMessage cannot be edited freely.** Apple permits at most five edits
within fifteen minutes of sending, each one visibly marking the message
as edited and exposing its full revision history. The live-mode design in
`remote-telegram-live-mode-implementation.md` edits a status card roughly
every two seconds; over a fifteen-minute turn that is ~450 edits against
a budget of five. Live mode's *cadence* therefore does not port. What
ports instead is *progressive delivery*: completed blocks of the answer,
sent as ordinary messages as they are produced, with the status card
falling back to a handful of edits spent only on genuine transitions.

That last constraint turns out to be worth acting on for Telegram too.
Telegram Bot API 9.3 (2025-12-31) added `sendMessageDraft` — "allowing
partial messages to be streamed to a user while being generated" — and
9.5 (2026-03-01) opened it to all bots. Today's edit-based live mode is
exactly the workaround that method replaces; `EditBudget.note_rate_limited`
exists only to absorb the 429s it causes. Introducing a streaming seam for
iMessage and not using it to retire that workaround would mean opening
`app/remote/outbound.py` twice.

## Goals

- A second remote transport speaking the BlueBubbles REST protocol, so one
  adapter serves BlueBubbles Server and `imessage-rs` alike.
- The core remote loop on iMessage: pair, prompt, answer, approve or
  reject a permission, stop.
- True progressive delivery of answer text on both transports —
  `sendMessageDraft` on Telegram, block streaming on iMessage.
- Native presentation: subject lines, `attributedBody` formatting,
  tapbacks, threaded replies, rendered images for diffs.
- Graceful degradation when the operator's Mac has SIP enabled and the
  BlueBubbles Private API is therefore unavailable.
- No new inbound network surface. The sidecar keeps binding `127.0.0.1`.

## Non-goals

- Running iMessage without a Mac. Reimplementing Apple's registration
  protocol (rustpush, OpenBubbles) risks the operator's Apple ID being
  banned from iMessage; Apple did exactly this to Beeper users in January
  2024, and OpenBubbles' own documentation recommends a throwaway Apple
  ID. Out of scope, permanently.
- Cloud iMessage APIs. A business sender and a monthly fee contradict the
  product premise.
- Porting `/settings`, `/health`, `/changes`, `/history`, `/clear` to
  iMessage. They stay Telegram-only in v1 and get their own plan once the
  presentation seam has been proven by the core loop.
- Telegram Rich Messages (Bot API 10.1-10.3). Native tables, collapsible
  block quotes, real headings, and `RichBlockButtons` would replace the
  emoji-and-`<b>` structure that cards fake today, and the `Card` value
  introduced here is what makes that a renderer swap rather than a second
  rewrite. Deferred to `documents/plans/remote-telegram-rich-messages.md`,
  which depends on AC-67 landing first. Adopting it here would retire
  AC-68's byte-identical guarantee — the only regression proof covering a
  refactor that already reaches into `app/remote/outbound.py`.
- Native Messages polls. They exist (iOS/macOS 26+, up to 12 options) and
  are the closest thing iMessage has to buttons, but they are not in the
  BlueBubbles protocol, and requiring every device in the conversation to
  run OS 26 is too narrow a v1 gate.
- Group chats. Pairing is one private conversation, as on Telegram.
- Inbound attachments. Images sent to the bot are ignored in v1.
- Two adapters polling at once. At most one connection is enabled.

## Operator setup

Documented, not automated. The operator:

1. Creates a second Apple ID for the bot (email-only; no phone number
   required) and signs it into Messages on a separate macOS user account.
2. Runs BlueBubbles Server (or `imessage-rs`) on that Mac and notes its
   URL and password.
3. Optionally installs the BlueBubbles Private API helper, which requires
   disabling SIP. Without it the channel still works; editing, typing
   indicators, tapbacks, and rich formatting are unavailable.
4. In EvoFlux, adds an iMessage connection with that URL and password, and
   pairs by sending the 8-digit code to the bot's address from their
   iPhone.

The Mac must stay awake and reachable on the same network. This is stated
plainly in the setup UI, because it is the single most common cause of a
channel that "stopped working".

## User flows and states

**Connect.** The operator picks iMessage in Settings, enters the server
URL and password. EvoFlux calls `GET /api/v1/server/info` once. Success
persists a connection row and vaults the password; failure returns a
classified error that names which of the three failure modes occurred
(unreachable, unauthorized, reachable-but-iMessage-broken) without
echoing any provider response.

**Pair.** Identical to Telegram: the desktop shows an 8-digit code, the
operator texts it to the bot's address, the adapter matches it against
`RemotePairing.pair_code_hash` before its expiry. A message from any
unpaired sender receives **no reply of any kind** — not an error, not a
prompt to pair. The sender learns nothing.

**Prompt and answer.** The operator texts a prompt. The adapter admits it,
the turn runs, and the answer arrives as a sequence of blocks — each a
real message, each a completed paragraph or code fence — as the model
produces them. A typing indicator fills the gaps between blocks when the
Private API is available. The turn closes with a compact card carrying
model, token counts, cost, and elapsed time, and no repetition of text
already delivered.

**Approve.** A permission request renders as a card naming the command and
its severity, with its three resolutions presented three ways at once: as
tapback targets, as a numbered list, and as text commands. Any of the
three resolves it. The card is then edited in place if editing is
available, or followed by a resolution message if it is not.

**Degraded.** If the Private API is unavailable, the channel runs on plain
sends alone. Blocks still stream. Cards still render, in plain text with
no attributed runs. Approvals fall back to numbered replies and commands.
The status surface says which features are unavailable and why.

## Requirements and acceptance criteria

### Transport and lifecycle

- **AC-59.** The iMessage adapter polls outward. It opens no listening
  socket and requires no change to the sidecar's `127.0.0.1` bind
  (`desktop/src-tauri/src/sidecar.rs:128`). Inbound updates are fetched by
  polling `GET /api/v1/message/query`, mirroring the owner-task plus
  interruptible-event shape of `app/remote/telegram/adapter.py` so that
  `stop()` never waits out a poll interval or a backoff sleep.
- **AC-60.** No new runtime dependency. The client is built on `httpx`,
  already a dependency. Socket.IO push is explicitly deferred; the polling
  client is the seam it would later occupy.
- **AC-61.** On `start()`, the adapter establishes an inbound watermark of
  `max(now - 300s, last_processed_at)`, persisted on the connection row.
  Any message whose timestamp precedes the watermark is logged and
  discarded, never admitted as a prompt. This is distinct from AC-16's
  `source_key` idempotency, which prevents duplicate processing but not the
  processing of stale messages that Apple flushes after a push recovery or
  that accumulated while EvoFlux was not running.
- **AC-62.** On `start()` and on every reconnection, the adapter probes
  `GET /api/v1/server/info` and derives a capability set: private API
  present, and from it whether edit, typing, tapback, and attributed-body
  sends are available. Every feature gated on those degrades rather than
  raising when the capability is absent.
- **AC-63.** `RemoteConnectionState` gains `ENDPOINT_UNREACHABLE` (no TCP
  route to the bridge), `ENDPOINT_UNAUTHORIZED` (HTTP 401), and
  `IMESSAGE_UNAVAILABLE` (bridge reachable, Messages.app unhealthy). The
  three have different operator remedies and are never collapsed into
  `ERROR`. `ENDPOINT_UNAUTHORIZED` is terminal for the current `start()`
  call and is not retried.
- **AC-64.** AC-1 holds for iMessage verbatim. With no enabled,
  credentialed iMessage connection, `app.remote.imessage.*` is never
  imported. Enforced by extending the existing
  `test_disabled_start_does_not_import_telegram` guard.

### Connections

- **AC-65.** At most one connection exists per `RemoteAdapterKind`, and at
  most one connection across all kinds is `enabled`. `RemoteRuntime`
  continues to own at most one live adapter. Configuring a second kind is
  permitted; enabling it disables the first.
- **AC-66.** A connection credential is a `RemoteCredential(token,
  endpoint)`. Telegram supplies a token and a null endpoint; iMessage
  supplies the server password as the token and the server URL as the
  endpoint. `RemoteAdapterFactory.validate_token` takes this value rather
  than a bare string.

### Presentation

- **AC-67.** Card construction is separated from card rendering. A
  transport-neutral `Card` value (heading, sections, actions) is produced
  by builders that know nothing about any transport; per-transport
  renderers turn it into wire form.
- **AC-68.** The Telegram renderer's output is byte-identical to today's
  for every card. This is verified by leaving
  `tests/remote/test_formatting.py` unmodified — if the refactor changes
  Telegram output, that suite fails.
- **AC-69.** The iMessage renderer emits a subject line for the card
  heading and an `attributedBody` run list for emphasis. Recipients below
  macOS 15 receive clean plain text with no residual markup characters.
  Markdown is never sent literally; iMessage does not render it.
- **AC-70.** Card actions are offered three ways simultaneously: as tapback
  targets when the Private API is available; as a numbered list in the card
  body; and as text commands. Any of the three resolves the card. The
  tapback mapping is positional — thumbs-up, heart, thumbs-down for the
  first three actions in card order. A card with more than three actions
  offers tapbacks for the first three only; the numbered list, which is
  always present, remains the complete surface. A card whose actions are
  not orderable by that convention (a project picker, for instance) omits
  tapbacks entirely rather than mapping them arbitrarily.
- **AC-71.** `app/remote/actions.py` and `app/remote/gates.py` are not
  modified. The iMessage adapter holds a bounded, ephemeral,
  per-destination map from a sent card's action ordinal to its capability
  token, and synthesizes a `RemoteInboundAction` of kind `CALLBACK`
  carrying that token when a tapback or numbered reply arrives. The map is
  bounded in the manner of `MAX_PENDING_CALLBACK_IDS`.
- **AC-72.** Diff and tool-log drill-downs render to PNG and are sent as
  attachments via `POST /api/v1/message/attachment`. Ordinary answer text
  is never rendered as an image; it must remain selectable and copyable.
  Renders exceeding the 16 MB attachment ceiling are truncated with an
  explicit truncation notice.
- **AC-73.** An answer is delivered as a threaded reply to the prompt
  message that produced it, when the capability is available.

### Streaming

- **AC-74.** Answer delivery goes through a `StreamingStrategy` seam with
  `begin`/`push`/`finish`/`abort`. `RemoteProjection.observe` stops
  discarding the payload of `message` events
  (`app/remote/outbound.py:489`) and forwards `text` to the active
  strategy.
- **AC-75.** `DraftStreaming` is used for Telegram private chats against a
  server supporting Bot API 9.5 or later. It streams via
  `sendMessageDraft` with `can_stop=True`, and handles the resulting
  `stopped_message_generation` update as a turn cancellation. Because a
  draft is ephemeral — it disappears shortly after, or as soon as the bot
  sends a real message — `finish()` sends the complete answer text as a
  real message.
- **AC-76.** `EditStreaming` preserves today's behaviour exactly, including
  `EditBudget` and its 429 backoff, and is selected when `sendMessageDraft`
  is unavailable. No Telegram operator loses functionality.
- **AC-77.** `BlockStreaming` is used for iMessage. It accumulates deltas
  and flushes a block when the buffer has reached `min_chars` *and* either
  the stream has been idle for `idle_ms` or the buffer has reached
  `max_chars`. Break points are preferred in the order paragraph, newline,
  sentence, whitespace, hard break. A block is never split inside a fenced
  code block; a forced split closes the fence and the next block reopens
  it. Defaults for iMessage: `min_chars=280`, `max_chars=1200`,
  `idle_ms=900`.
- **AC-78.** Because blocks are durable messages, `BlockStreaming.finish()`
  emits only the completion card — model, tokens, cost, elapsed, changed
  files — and never repeats text already delivered. The strategy tracks how
  much text it has streamed in order to guarantee this.
- **AC-79.** The block chunker performs no I/O and no sleeping. Cadence is
  decided from a caller-supplied clock, as in `app/remote/edit_budget.py`,
  so its tests are deterministic.
- **AC-80.** `_split_text`'s 4096-character bound
  (`app/remote/outbound.py:1069`) is unchanged and applies to both
  transports. It sits below any iMessage limit and below the 4000 default
  that comparable implementations use.

### Live mode

- **AC-81.** Live mode on iMessage surfaces tool activity without editing
  the status card on a time-based cadence. The typing indicator runs for
  the duration of the turn and is the primary liveness signal; the status
  card is edited only on a meaningful transition (a long-running tool
  starting, the active agent changing, a gate opening), and only while a
  count-bounded budget allows. `EditBudget` gains a count-in-window
  dimension — `max_edits` within `window_seconds` — for this purpose;
  Telegram passes `None` for both and its behaviour is unchanged. iMessage
  uses four edits within fifteen minutes, reserving the fifth for the
  completion card. On exhaustion the adapter sends a fresh status card
  rather than failing or silently dropping the update, which starts a new
  fifteen-minute window. `LiveActivityWindow` is reused unchanged; only the
  delivery cadence differs.
- **AC-82.** The completion card is never gated by any budget, on either
  transport, preserving the existing contract that liveliness is
  best-effort and completion is not.

### Security

- **AC-83.** A message from a principal that is not the paired principal
  produces no outbound message of any kind. Unlike Telegram, where a bot
  only receives messages from users who started it, any party who learns
  the bot's iMessage address can send to it; the principal check is the
  only boundary and is therefore silent. Rejections are logged server-side
  with the principal redacted.
- **AC-84.** The BlueBubbles server password is stored in the OS credential
  vault under the existing `connection:<uuid>` account key, never returned
  by any API route, and never logged. The server URL is non-secret and is
  stored on the connection row.
- **AC-85.** Inbound attachments are discarded before reaching the agent.
- **AC-86.** All outbound text passes through
  `protect_outbound_text(..., context=OutboundContext(channel="remote"))`
  unchanged, on both transports and on every streaming strategy.

## API, event, tool, and UI contracts

**Outbound (BlueBubbles REST).** `POST /api/v1/message/text` for sends;
`POST /api/v1/message/edit` and `/unsend` under the Private API;
`POST /api/v1/message/react` for tapbacks; `POST /api/v1/message/attachment`
(multipart) for rendered images; `POST /api/v1/chat/{guid}/typing` for the
typing indicator. Authentication is the `password` query parameter. No
BlueBubbles payload type escapes `app/remote/imessage/`.

**Inbound.** `GET /api/v1/message/query` with an `after` bound, polled on a
two-second interval. Each result is classified into an existing
`RemoteInboundActionKind`; tapbacks and numbered replies are classified as
`CALLBACK` with a synthesized token (AC-71).

**Telegram.** `TelegramClient` gains `send_message_draft`, built on the
existing `_call` helper. `sendMessageDraft` accepts `chat_id`, `text`,
`parse_mode`, `entities`, `link_preview_options`, `reply_parameters`,
`message_thread_id`, `reply_markup`, `can_stop`, `keep_on_stop`, and is
valid only for private chats — which is the only shape remote pairing
produces.

**Contracts.** `RemoteAdapterKind` gains `IMESSAGE`. `RemoteOutboundMessage`
gains `attachment` and `reply_to`. `RemoteConnectionState` gains the three
states of AC-63. `RemoteAdapter` gains `react(message_id, kind)`, a no-op
when the capability is absent.

**Desktop UI.** `web/src/routes/settings.remote-access.tsx` gains an adapter
selector. The iMessage branch collects a URL and a password instead of a
bot token, and surfaces the capability set after connecting so the operator
can see whether the Private API was detected.

## Data model, migration, and retention

Migration `00000071` adds two nullable columns to `remote_connections`:
`endpoint_url` (the bridge's base URL; null for Telegram) and
`inbound_watermark_at` (AC-61). Both are nullable with no backfill, so
existing Telegram rows are untouched. `RemotePairing` is unchanged —
`principal_id` holds the operator's iMessage handle and `destination_id`
the chat GUID, which is exactly the separation the existing docstring
anticipated. The AC-71 ordinal map and all streaming state are in-memory
and discarded with the turn.

## Permissions, security, privacy, and trust

The trust boundary moves. On Telegram, delivery is gated twice: Telegram
only routes to a bot from users who started it, and then the principal
check runs. On iMessage there is one gate. AC-83 makes it silent so that an
unpaired sender cannot confirm the address is live.

Disabling SIP, which the Private API requires, weakens the operator's Mac.
The setup documentation states this plainly and the channel is fully
functional without it; nothing in the product pressures the operator into
it.

The bot's Apple ID is a second account under the operator's control. No
credential for it is held by EvoFlux; the only secret EvoFlux stores is the
bridge password.

## Concurrency, failure, recovery, and idempotency

Inbound polling and outbound delivery remain independent failure domains,
as on Telegram: an unreachable destination affects delivery status, never
the poll loop. Transport failures use exponential backoff with jitter;
`ENDPOINT_UNAUTHORIZED` is terminal (AC-63).

Recovery is where the transports genuinely differ. Telegram's `getUpdates`
offset is a server-held cursor, so a restart resumes exactly. A
`chat.db`-backed bridge has no cursor; it has history. Without AC-61's
watermark, restarting EvoFlux after a weekend would replay Friday's
messages as fresh prompts. `source_key` would correctly suppress the
duplicates of anything already seen, and would do nothing about the rest.

A capability lost mid-session — the operator quitting the Private API
helper — is observed on the next probe, and every dependent feature
degrades. No turn fails because of it.

## Observability and diagnostics

`RemoteAdapterStatus` carries the capability set alongside the existing
fields, so the desktop can state which features are unavailable rather than
leaving the operator to infer it from absence. The chain is long — iPhone,
Apple, Mac, bridge, LAN, EvoFlux — so the three states of AC-63 exist to
place a failure on it. As with Telegram, no raw provider response,
credential, or token ever appears in a status or a log.

## Compatibility, rollout, and rollback

Every change to Telegram behaviour is additive or guarded. `DraftStreaming`
is selected only when `sendMessageDraft` is available; otherwise
`EditStreaming` reproduces today's behaviour exactly (AC-76). The
formatting split is verified by an unmodified test suite (AC-68). The
migration is two nullable columns.

Rollback is per-layer: disabling the iMessage connection returns the system
to a Telegram-only configuration with no code path into
`app/remote/imessage/`; forcing `EditStreaming` returns Telegram to today's
delivery.

Build order is chosen so that value lands before the hardware dependency
does. The `Card` seam and the streaming seam are pure refactors verifiable
by the existing suite; `DraftStreaming` then improves Telegram on its own,
and every step to that point is testable on a machine with no Mac. Only
after that does work depend on a bridge being reachable.

## Verification matrix

| Requirement | Verified by |
| --- | --- |
| AC-59, AC-61 | `tests/remote/imessage/test_adapter.py` — poll loop, prompt `stop()`, stale messages discarded |
| AC-60 | Dependency review; no addition to `pyproject.toml` |
| AC-62, AC-63 | `tests/remote/imessage/test_capability.py`, `test_client.py` — probe and error classification |
| AC-64 | Extended `tests/remote/test_runtime.py` import guard |
| AC-65, AC-66 | `tests/remote/test_connection_service.py` |
| AC-67, AC-69, AC-70 | `tests/remote/test_cards.py`, `tests/remote/imessage/test_renderer.py` |
| AC-68 | Unmodified `tests/remote/test_formatting.py` |
| AC-71 | `tests/remote/imessage/test_adapter.py` — tapback and numbered reply resolve a capability token |
| AC-72, AC-73 | `tests/remote/imessage/test_client.py` — multipart, truncation, reply threading |
| AC-74, AC-77, AC-78, AC-79 | `tests/remote/test_block_stream.py`, `tests/remote/test_streaming.py` |
| AC-75, AC-76 | `tests/remote/test_streaming.py`; unmodified `tests/remote/test_outbound.py` |
| AC-80 | `tests/remote/test_outbound.py`, unmodified |
| AC-81, AC-82 | `tests/remote/test_edit_budget.py` — count-in-window exhaustion rolls a new card; Telegram passing `None` is unchanged |
| AC-83, AC-84, AC-85 | `tests/remote/imessage/test_adapter.py` — stranger silence, tapback from non-principal ignored, attachments dropped |
| AC-86 | `tests/remote/test_streaming.py` — redaction on every strategy |

## Ownership and source map

| Area | Location |
| --- | --- |
| Streaming seam | `app/remote/streaming.py` (new) |
| Block chunker | `app/remote/block_stream.py` (new) |
| Count-in-window edit budget | `app/remote/edit_budget.py` (modified) |
| BlueBubbles client | `app/remote/imessage/client.py` (new) |
| Adapter lifecycle | `app/remote/imessage/adapter.py` (new) |
| Capability probe | `app/remote/imessage/capability.py` (new) |
| Attributed-body rendering | `app/remote/imessage/attributed.py` (new) |
| Card values and builders | `app/remote/formatting/cards.py` (new) |
| Telegram rendering | `app/remote/formatting/telegram.py` (moved) |
| iMessage rendering | `app/remote/formatting/imessage.py` (new) |
| Image rendering | `app/remote/formatting/images.py` (new) |
| Turn projection | `app/remote/outbound.py` (modified) |
| Telegram draft method | `app/remote/telegram/client.py` (modified) |
| Connection limits | `app/remote/connection_service.py` (modified) |
| Adapter dispatch | `app/remote/runtime.py` (modified) |
| Schema | `app/models/remote.py`, `app/migrations/versions/00000071_*.py` |
| Desktop UI | `web/src/routes/settings.remote-access.tsx` (modified) |
