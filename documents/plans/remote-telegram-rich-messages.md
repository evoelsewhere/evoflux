# Remote Telegram: Rich Messages

Status: proposed — blocked on AC-67

**Depends on `documents/plans/remote-channel-imessage.md`.** That document
introduces the transport-neutral `Card` value (AC-67) and the streaming
seam (AC-74) this one builds on. Nothing here is implementable until both
have landed; attempting it earlier means rewriting fourteen renderers
twice.

This document revises one accepted contract:

- **AC-24** (outbound text is sent with Telegram HTML parse mode, callers
  having rendered through `app/remote/formatting.py`, which HTML-escapes
  every non-static field) is revised for the rich renderer only. Rich
  messages carry structured block trees, not markup, so escaping is
  replaced by a different and stricter guarantee — see AC-98. The HTML
  renderer and AC-24 remain in force wherever the rich renderer is not
  used.

## Problem and outcome

Every card EvoFlux sends to Telegram fakes structure that the platform did
not previously offer. `app/remote/formatting.py` carries `_STATUS_ICON`,
`_SEVERITY_ICON`, `_RESOLUTION_ICON` and `_HEALTH_ICON` tables — emoji
standing in for semantics because there was no other way to mark one.
`_format_token_count` compresses `128000` to `128K` because a usage
footer has to survive on one line. `derive_card_heading` truncates at
`_CARD_HEADING_MAX_LENGTH = 60` because a bold first line is all a heading
can be.

The drill-downs are worse than cramped; they are a round trip. A full diff
or a tool log cannot appear in the card that references it, so
`app/remote/actions.py` issues a capability token, renders a button, waits
for a tap, and sends a second message. The operator taps to see something
that could have been one collapsed section.

Bot API 10.1 through 10.3 removed the constraint these workarounds exist
for. Rich Messages carry real block trees: native tables with borders,
striping and captions; expandable block quotations; real headings; nested
lists; buttons as blocks. The outcome is cards that stop simulating
structure — a usage footer that is a table, a diff that expands in place,
a resolved permission card whose buttons are disabled rather than
replaced.

## Goals

- A fourth renderer over `Card`, emitting `InputRichBlock*` trees through
  `sendRichMessage`.
- Retire the drill-down round trip for diffs and tool logs by rendering
  them as expandable blocks in the card that references them.
- Usage footers and changed-file lists as native tables.
- Resolved cards marked by disabling their buttons rather than
  re-rendering the card.
- Composition with `DraftStreaming` through `sendRichMessageDraft`.
- The HTML renderer retained, unmodified, as the fallback path.

## Non-goals

- iMessage. It has no equivalent; `formatting/images.py` serves the same
  need there, and this document does not touch it.
- Ephemeral messages (`ephemeral_message_parameters`). They exist to show
  a message to one user inside a group; remote pairing is a private
  conversation, so there is nothing for them to solve.
- Math formulas, footnotes, and inline media blocks. Available, but no
  card needs them.
- Replacing the HTML renderer. It stays as the fallback and as the
  regression baseline.
- Rich formatting on inbound. Bots receive what users type.

## User flows and states

**First rich send.** On the first outbound card of a connection's life,
the adapter attempts `sendRichMessage`. Success marks the connection
rich-capable for its lifetime. Failure marks it HTML-only, logs the
classified reason once, and re-renders the same `Card` through the HTML
renderer. The operator sees a card either way and is never told about the
negotiation.

**A completed turn.** The done card carries a heading, the answer, a
usage table (model, input, output, cached, cost), and — when the turn
changed files — a changed-files table. If a diff exists it is an
expandable block quotation inside the same message, collapsed by default.
No drill-down button, no second message, no capability token.

**A permission request.** The card names the command and its severity as a
heading and a block quote, with its resolutions as a `RichBlockButtons`
block. On resolution the buttons are re-sent with `disabled` set and the
chosen one marked, so the card reads as a decided record rather than a
live prompt.

**Streaming.** A rich turn streams through `sendRichMessageDraft`. It is
never streamed by editing: `editMessageText` applied repeatedly to a rich
message destroys its formatting.

## Requirements and acceptance criteria

- **AC-87.** The rich renderer is a fourth renderer over the `Card` value
  introduced by AC-67, alongside the HTML, iMessage, and image renderers.
  It shares every card builder; no builder learns that it exists.
- **AC-88.** Rich capability is negotiated by attempt, not by
  interrogation — the Bot API exposes no version query. The first
  `sendRichMessage` of a connection's lifetime decides. A rejection marks
  the connection HTML-only for that lifetime and is logged once with a
  classified reason, never a raw provider response. The card is then
  re-rendered and delivered through the HTML renderer, so no card is lost
  to the probe.
- **AC-89.** The usage footer renders as an `InputRichBlockTable` with
  `is_compact` set: model, input tokens, output tokens, cached tokens,
  cost. Token counts are rendered in full rather than abbreviated;
  `_format_token_count`'s compression exists for line-length reasons that
  a table removes.
- **AC-90.** A turn's changed files render as an `InputRichBlockTable`
  with a caption stating the file and line counts.
- **AC-91.** A full diff renders as an expandable block quotation inside
  the card that references it, collapsed by default. The diff drill-down
  capability token and its button are not issued when the connection is
  rich-capable. `app/remote/actions.py` is not modified; the rich renderer
  simply does not request a token, and the HTML renderer continues to.
- **AC-92.** A tool log renders as a nested list inside an expandable
  block quotation, under the same rule as AC-91.
- **AC-93.** Card actions render as an `InputRichBlockButtons` block. A
  resolved card is re-sent with every button carrying `disabled` and the
  chosen action labelled as taken, replacing today's separate
  resolved-card render.
- **AC-94.** Rich messages are streamed with `sendRichMessageDraft` and
  never by repeated `editMessageText`. `DraftStreaming` selects the rich
  draft method when the connection is rich-capable and the plain draft
  method otherwise.
- **AC-95.** Any rich send that fails after the connection was marked
  rich-capable falls back to the HTML renderer for that card, and demotes
  the connection to HTML-only. A card is never dropped because rich
  delivery failed.
- **AC-96.** Behaviour on Telegram clients predating Bot API 10.1 is
  established by observation before this document is implemented, and the
  result is recorded here. If degradation is not clean, rich capability is
  gated behind an operator opt-in rather than negotiated automatically.
  This is the one open question in this document and it is not resolvable
  from published documentation.
- **AC-97.** `formatting/imessage.py`, `formatting/images.py`, and
  `app/remote/imessage/` are not modified.
- **AC-98.** Rich blocks replace HTML escaping with a stronger guarantee,
  and the stronger guarantee is what is tested. `escape()` exists today
  because model-authored text placed inside a markup string could
  manufacture links, mentions, or formatting. In a rich block tree,
  model-authored text is a leaf value in a structured document and cannot
  become markup at all — provided it is *always* placed as a leaf and
  never used to build a block. Every dynamic field continues to pass
  through `protect_outbound_text(..., context=OutboundContext(channel="remote"))`
  before placement, unchanged. A test asserts that no block tree is ever
  constructed from model-authored text.

## API, event, tool, and UI contracts

`TelegramClient` gains `send_rich_message` and `send_rich_message_draft`,
built on the existing `_call` helper. Block construction lives in a new
`app/remote/formatting/telegram_rich.py`; no `InputRichBlock*` shape
escapes it.

`RemoteAdapterStatus` gains a rich-capable flag so the desktop can state
which rendering path a connection is on, which is the only way an operator
can tell why their cards look plain.

No route, schema, or event contract changes.

## Data model, migration, and retention

None. Rich capability is negotiated per adapter lifetime and held in
memory; a restart re-negotiates. There is nothing worth persisting, since
the answer can change when Telegram updates.

## Permissions, security, privacy, and trust

AC-98 is the whole of it. The escaping discipline that AC-24 established
does not translate — there is no markup to escape — so it is replaced by a
placement discipline, which is the stronger property and the one the tests
assert. Redaction is unchanged and applies identically on both renderers.

## Concurrency, failure, recovery, and idempotency

Capability negotiation is a per-connection latch, set once and only ever
demoted, so concurrent turns cannot disagree about which renderer is in
use. Demotion mid-turn is safe: the streaming strategy finishes the turn
on the HTML path, and the operator sees a formatting change rather than a
failure.

## Observability and diagnostics

One log line on negotiation, one on demotion, both carrying a classified
reason and no provider payload. The rich-capable flag appears in status.

## Compatibility, rollout, and rollback

Every path is negotiated and reversible. Rollback is forcing the HTML
renderer, which is never modified by this work and remains covered by
`tests/remote/test_formatting.py`.

AC-96 gates rollout. If old clients do not degrade cleanly, automatic
negotiation is replaced by an opt-in and this document's rollout posture
changes from silent to explicit.

## Verification matrix

| Requirement | Verified by |
| --- | --- |
| AC-87 | `tests/remote/test_telegram_rich.py` — same `Card` renders through both renderers |
| AC-88, AC-95 | `tests/remote/test_telegram_rich.py` — probe failure and mid-life demotion both deliver the card |
| AC-89, AC-90 | `tests/remote/test_telegram_rich.py` — table shape, caption, uncompressed counts |
| AC-91, AC-92 | `tests/remote/test_telegram_rich.py` — no drill-down token issued when rich-capable; unmodified `tests/remote/test_actions.py` |
| AC-93 | `tests/remote/test_telegram_rich.py` — resolved card disables buttons |
| AC-94 | `tests/remote/test_streaming.py` — rich turns never call `editMessageText` |
| AC-96 | Manual observation on a real bot, recorded in this document before implementation |
| AC-97 | Unmodified iMessage test suites |
| AC-98 | `tests/remote/test_telegram_rich.py` — no block tree built from model-authored text; redaction on every dynamic field |

## Ownership and source map

| Area | Location |
| --- | --- |
| Rich block rendering | `app/remote/formatting/telegram_rich.py` (new) |
| Rich send and draft methods | `app/remote/telegram/client.py` (modified) |
| Capability latch | `app/remote/telegram/adapter.py` (modified) |
| Strategy selection | `app/remote/streaming.py` (modified) |
| Status surface | `app/remote/contracts.py` (modified) |
| HTML renderer | `app/remote/formatting/telegram.py` (unmodified — fallback and baseline) |
