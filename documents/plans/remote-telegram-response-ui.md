# Remote Telegram: rich responses, live status, and settings visibility

Status: proposed

**Amends `documents/plans/remote-channel-telegram.md`.** That document remains
normative for everything not listed below. This document changes exactly two
of its accepted contracts and adds new, additive scope on top of the rest:

- **AC-24** (no Telegram parse mode) is revised to allow HTML parse mode under
  a strict escaping rule. See Requirements.
- The **Non-goals** entry forbidding remote changes to "outbound-data policy"
  and the matching clause in **AC-32** are narrowed to carve out outbound
  redaction policy specifically. Model-provider configuration, sandbox policy,
  connection settings, credentials, and `permission_mode` remain forbidden,
  unchanged.
- **AC-20** and **AC-22** (event allowlist, quiet lifecycle) are **not**
  amended; this document's status-card design is written to satisfy them as
  written.

## Problem and outcome

Tasks 1-6 of the Telegram remote-access feature are complete; Tasks 7-9
(stream projection, gate cards, secondary actions) are in progress and
currently send plain, unformatted text with no parse mode, no live status
before completion, and no way to see current model/permission/redaction state
from the phone. The bot's command surface is also narrower than its own
"Advanced actions" design: starting a Coding task requires already knowing
which project you want, with no prompt guidance for someone typing on a phone
keyboard.

The outcome is a visibly better remote experience within the accepted
feature's existing boundaries: readable HTML-formatted messages instead of
raw text, a live "still working" feel via Telegram's native typing indicator,
completion notices for desktop-started and scheduled/workflow work (finishing
a Goal already stated but not yet built), a guided project-and-prompt picker
for starting new work from a phone, and a read-mostly `/settings` view. Two
narrow, explicit amendments to the accepted spec make the formatting and
redaction-visibility parts possible; everything else is completed within the
existing contract.

## Goals

- Render bot messages with Telegram HTML formatting (bold, code blocks,
  links) instead of plain text, without weakening the existing anti-injection
  guarantee.
- Give a phone-admitted turn a visible "working" feel using Telegram's native
  typing indicator, without exceeding the existing one-lifecycle-message
  budget or mirroring tool/content deltas.
- Complete the existing Goal of delivering completion notices for
  desktop-started top-level sessions, and extend the same delivery to
  Workflow/Scheduler runs that produce a user-visible top-level session.
- Let the user choose, per pairing, whether notifications cover every
  addressable session or only ones the phone itself started.
- Add a read-mostly `/settings` view covering connection, current model,
  permission mode, and outbound redaction policy.
- Allow outbound redaction policy — and only that setting — to be changed
  from the phone, as a narrow, explicit amendment.
- Add a guided "pick a project, then pick or type a prompt" flow so starting
  a Coding task from a phone needs minimal typing.
- Let the user pull a turn's own full diff or tool log on demand, without
  turning the channel into a session browser.

## Non-goals

- No change to model-provider configuration, permission mode, sandbox policy,
  connection settings, or credentials from the phone — this boundary from the
  accepted spec is explicitly preserved, not just left alone by omission.
- No multi-turn session history browsing or transcript export. Drill-down
  buttons return only the single most recent completed turn's own output.
- No new "always animate everything" mechanism. Only the typing indicator
  animates; there is no per-tool-call progress text, spinner glyph cycling
  inside an edited message, or additional lifecycle messages.
- No change to the one-connection/one-pairing v1 product limit, pairing flow,
  gate mechanics, or callback-token ownership rules — all unchanged from the
  accepted spec.
- No new durable notification log or outbox; notification delivery keeps the
  accepted spec's best-effort, non-durable outbound guarantee.

## User flows and states

### Receiving a formatted response

Every outbound message (status, done, error, gate, settings, picker) is built
by one shared rendering layer and sent with Telegram's HTML parse mode. Task
titles, file paths, diffs, and tool output render in `<code>`/`<pre>` blocks;
labels render in `<b>`; nothing else uses formatting. Every value that did not
originate as a static string written by `formatting.py` is escaped with
`html.escape` before it is placed inside any tag, including already-redacted
agent text — redaction happens first, escaping happens last, in that order.

### Watching a turn run

When a phone-admitted turn is accepted, the bot sends one status message
containing the task title and starts Telegram's native typing indicator
(`sendChatAction`, re-issued roughly every 4 seconds, since Telegram clears it
automatically after about 5). The status message is edited — not resent — on
each of the existing lifecycle transitions (accepted → queued → running →
done/error), exactly as today's accepted design already allows; the only
content change is that the running-state text shows the task title and
elapsed time and nothing else. No individual tool call, file edit, or content
delta is ever mirrored into the message, preserving the existing event
allowlist. The typing indicator stops the moment the turn reaches a terminal
state, is interrupted, or the adapter shuts down.

Desktop-started sessions and Workflow/Scheduler runs never had a live turn
observed from the remote side, so they never get a status message or typing
indicator — they go straight to a single done/error card when the run
finishes, matching the "no activity chatter" rule that already applies to
desktop tasks today.

### Seeing the outcome

The done card shows a compact summary: files changed with +/- counts, a tool
call count, and (when applicable) a bounded test-result excerpt — all sourced
from the turn's already-persisted, already-redacted final state, not
reconstructed from streamed deltas. Two buttons, **Full diff** and **Tool
log**, are attached. Tapping one fetches that same turn's own persisted
diff/log content (nothing from any other turn or session), redacts it through
the existing outbound policy, chunks it exactly like today's long-message
splitting, and sends it as a follow-up message. The buttons use the existing
opaque, expiring capability-token mechanism and carry no session ID, path, or
content in their callback data.

The error card shows the error text and a **Tool log** button on the same
terms; it does not add a remote retry mechanism beyond what already exists.

### Getting notified for work started elsewhere

`RemotePairing` gains a `notify_scope` preference (`all` or `remote_only`,
default `all`). When `all`, `RemoteProjection` observes every addressable
top-level session regardless of where it started — completing the accepted
spec's stated Goal of notifying about desktop-started tasks, which the
current Task 7 implementation has not yet built. It also observes
Workflow/Scheduler runs that produce a user-visible top-level session,
sending the same bounded completion card, with no live status phase. When
`remote_only`, observation is scoped to `remote_origin`-tagged sessions only,
matching today's narrower behavior. The preference is changeable from
`/settings` and takes effect on the next observed event, with no restart.

### Checking settings from the phone

`/settings` renders: the paired connection's label and username; the current
session's model and permission mode, both as plain read-only text with no
buttons; the current outbound redaction policy (`strict`/`standard`/`off`)
with buttons to change it; and the current `notify_scope` with a toggle.
Changing redaction policy calls the existing `PUT /api/settings/remote`
contract — `/settings` is a new surface for an existing setting, not a new
setting. No other value in the card is writable.

### Starting a task with guidance

`/new` (and the "Coding projects" entry in the existing secondary menu) is
extended: after picking a project, the bot shows a short list of suggested
prompts for that project — a fixed curated set ("Fix failing tests", "Review
my changes", "Add a feature…") plus, when a prior session exists for that
project, a "Continue last session" option — alongside the existing ability to
just type a free-form message. Selecting a suggestion starts the task with
that text; typing anything at any point works exactly as it does today.
Project selection is still bounded to existing authorized Coding projects,
unchanged from the accepted spec.

## Requirements and acceptance criteria

IDs continue from the accepted spec's AC-37. AC-24 and AC-32 below are
revisions of the originals; all others are new.

- **AC-24 (revised) — Safe HTML rendering:** Messages are sent with Telegram
  HTML parse mode. Every field not authored as a static string inside
  `app/remote/formatting.py` is passed through `html.escape` before
  interpolation, applied after outbound redaction. Tests prove that
  adversarial content — literal `<`, `>`, `&`, and strings that resemble tags
  — can never alter the rendered message structure, add a link, or add a
  mention. Splitting stays within Telegram's 4096-character limit and remains
  Unicode-safe.
- **AC-32 (revised) — No remote secrets or settings writes, redaction
  excepted:** No Telegram command, menu action, or natural-language shortcut
  accepts a credential value or changes connection/provider/sandbox settings
  or `permission_mode`. Outbound redaction policy (`outbound_data_policy`,
  `outbound_pii_policy`) is the sole exception and may be changed only through
  `/settings` calling the existing `PUT /api/settings/remote` contract. Status
  output contains no environment values or secret presence details beyond the
  current connection's configured state.
- **AC-38 — Bounded lifecycle liveliness:** A phone-admitted turn's status
  message is edited only on accepted/queued/running/done/error transitions,
  never more often. A repeating `sendChatAction(typing)` runs only while that
  same turn is unresolved and is never counted as, or substitutes for, a
  message. Running-state text contains only the task title and elapsed time;
  no tool call, file path, or content delta is ever mirrored into it.
- **AC-39 — Bounded on-demand detail:** "Full diff" and "Tool log" return
  only the current turn's own already-persisted, already-redacted output,
  chunked like any other outbound message, expiring on the same TTL as other
  capability tokens. They never return another turn's or another session's
  content, and no new durable content store is introduced.
- **AC-40 — Guided task start:** The project-picker/prompt-suggestion flow
  offers only existing authorized Coding projects (unchanged authorization
  boundary) plus a curated static prompt set and, when applicable, one
  dynamic "Continue last session" suggestion. Free-form text remains accepted
  at every step; no suggestion is mandatory.
- **AC-41 — Read-only model and permission visibility:** `/settings` displays
  the current session's model and permission mode as plain text. No command,
  button, or callback in the entire remote surface can change either value.
- **AC-42 — Notification scope preference:** `RemotePairing.notify_scope`
  (`all` default, `remote_only`) governs whether `RemoteProjection` observes
  every addressable top-level session or only `remote_origin`-tagged ones.
  Changing it via `/settings` takes effect on the next observed event with no
  restart required.
- **AC-43 — Cross-origin completion delivery:** With `notify_scope=all`, a
  desktop-started top-level session and a Workflow/Scheduler run that
  produces a user-visible top-level session both deliver the same bounded
  completion/error card a phone-started turn would get. Neither ever receives
  a live status message or typing indicator, since no turn was observed from
  the remote side for either.
- **AC-44 — Redaction visibility and control:** `/settings` shows the current
  `outbound_data_policy`/`outbound_pii_policy` value and offers buttons to
  change it, calling the existing settings service; the displayed value and
  the enforced value never diverge.

## API, event, tool, and UI contracts

### New module

`app/remote/formatting.py` — the single place literal HTML tags are written.
Exposes one escaping helper and one builder function per card type (`status`,
`done`, `error`, `gate`, `settings`, `project_picker`, `prompt_suggestions`),
each returning `(html_text: str, buttons: list[RemoteButton] | None)`.
`outbound.py`, `gates.py`, and `actions.py` call these builders instead of
constructing text/redaction calls themselves, retiring the duplicated
`_redact_text` helpers in favor of one redact-then-escape pipeline.

### Telegram client

`TelegramClient.send_text`/`edit_text` always pass `parse_mode="HTML"`.
`TelegramClient` gains `send_chat_action(chat_id, action="typing")`, a thin
wrapper over the Bot API's `sendChatAction`.

### Commands

`_SLASH_COMMANDS` in `actions.py` gains `settings`. `/new` and the existing
Coding-project entry in the secondary menu route through the new
project-picker/prompt-suggestion builders before falling through to today's
session-creation call. Drill-down buttons register three new capability
action codes (`diff`, `toollog`, `notify_scope`, `redaction`) in the existing
opaque-token dispatch used by Tasks 8-9 — no new token mechanism.

### Stream observation

`RemoteProjection.observe` (outbound.py) changes its session filter from
"tagged `remote_origin`" to "addressable top-level session, and (tagged
`remote_origin` OR pairing's `notify_scope == "all"`)". A second, similarly
gated hook is added where Workflow/Scheduler run completion already publishes
its own terminal event (exact integration point to confirm during planning —
if no such event currently reaches `memory_stream_store`, one is added
following the existing `desktop_notification` pattern rather than inventing a
parallel channel).

## Data model, migration, and retention

One migration adds `notify_scope` (bounded enum, default `all`) to
`remote_pairings`. No other schema change. Redaction policy already persists
via existing settings storage; model and permission mode are read from
existing session/team configuration, not duplicated.

Per the accepted spec's retention model, the in-memory `status_message_id`
and lifecycle state per turn remain ephemeral (already anticipated as
"progress-message IDs" in the accepted spec's retention section). Diff/tool-log
content shown via drill-down is read from existing persisted turn data under
existing session retention — no new content store, no new retention policy.

## Permissions, security, privacy, and trust

The HTML-escaping rule in AC-24 (revised) is the load-bearing safety property
for the entire formatting change: it replaces "no parse mode" with "no
unescaped interpolation," which must hold for every card, including error
text and tool-log content, since those can contain arbitrary agent- or
tool-produced strings. `formatting.py`'s tests are the primary evidence for
this guarantee, not the individual call sites.

The redaction-policy carve-out (AC-32 revised) is deliberately narrow: it
changes how aggressively outbound content is *hidden*, never what the phone
can *cause* the installation to do. It cannot be used to weaken any other
boundary — model, permission mode, sandbox, and connection configuration stay
exactly as forbidden as before.

Drill-down content passes through the same outbound redaction pipeline as
every other field; a `block` policy decision produces the same fixed
withheld-content stub used elsewhere, not a bypass.

## Concurrency, failure, recovery, and idempotency

The typing-indicator timer is owned by the same per-turn lifecycle that owns
the status message; it is cancelled wherever that lifecycle already tears
down today (completion, error, interrupt, adapter shutdown, pairing removal),
so no new failure mode is introduced — a missed `sendChatAction` call is
logged and ignored, never retried aggressively, since Telegram's own indicator
timeout already bounds the damage of a missed refresh.

A drill-down tap for a turn whose persisted diff/log is no longer available
(pruned, or the session was deleted) returns the same friendly "no longer
available" reply used for other expired-capability cases, not a silent
failure or a stack trace.

Cross-origin notification (AC-43) reuses the existing bounded, non-blocking
observer contract (AC-19) unchanged; widening which sessions are observed
does not change how observation is performed.

## Observability and diagnostics

Status/metrics gain: `notify_scope` distribution across active pairings,
typing-indicator send success/failure counts, and drill-down button
usage/expiry counts. None of these labels carry session, path, or content
data, consistent with the accepted spec's existing metric-label rules.

## Compatibility, rollout, and rollback

Additive on top of Tasks 1-6 (complete) and layered into Tasks 7-9 (in
progress, not yet shipped) rather than reopening finished work. Existing
pairings default to `notify_scope=all` on migration, which is a behavior
change from today's `remote_origin`-only projection — called out explicitly
since it is the one default-on behavior change in this document; a user who
wants the narrower, current behavior switches to `remote_only` in
`/settings`. Everything else is opt-in by construction (buttons a user must
tap) or purely presentational (HTML formatting, typing indicator).

Rollback is the same disable/remove path as the accepted spec; no new
irreversible state is created.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-24 (revised) | `formatting.py` escaping unit tests with adversarial input; golden-output tests per card type; Unicode/4096-boundary splitting tests |
| AC-32 (revised), AC-44 | `/settings` redaction-toggle round-trip tests against the existing settings service; refusal tests proving every other listed setting stays unwritable |
| AC-38 | `RemoteProjection` lifecycle tests asserting exact edit count/timing and typing-indicator start/stop boundaries; AC-20 regression test proving no tool/content delta ever appears in status text |
| AC-39 | Drill-down capability-token tests: correct turn scoping, redaction applied, expiry, and refusal of cross-turn/cross-session access |
| AC-40 | Project-picker/prompt-suggestion flow tests: authorized-project-only listing, free-form fallback, dynamic suggestion presence/absence |
| AC-41 | Inspection/dispatch test proving no code path can mutate model or permission mode from any remote command |
| AC-42, AC-43 | `notify_scope` filtering tests across remote-origin, desktop-origin, and workflow/scheduler-origin sessions; no-status-message assertion for cross-origin completions |

## Ownership and source map

- Rendering layer: `app/remote/formatting.py` (new).
- Telegram transport additions: `app/remote/telegram/client.py`.
- Turn lifecycle and cross-origin observation: `app/remote/outbound.py`.
- Commands, settings, guided picker, drill-down dispatch:
  `app/remote/actions.py`.
- Gate cards switch to the shared renderer: `app/remote/gates.py`.
- Schema: one migration adding `remote_pairings.notify_scope`.
- Workflow/Scheduler completion integration point: to be confirmed against
  `app/workflow/` and `app/scheduler/` during planning.

This document remains historical/proposed until implementation is verified
and reconciled into current documentation, per the accepted spec's own
lifecycle rules.
