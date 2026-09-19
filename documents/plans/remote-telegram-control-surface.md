# Remote Telegram: decidable approvals, remote control, and live activity

Status: proposed

**Amends `documents/plans/remote-channel-telegram.md` and
`documents/plans/remote-telegram-response-ui.md`.** Both remain normative
for everything not listed below. This document changes five accepted
contracts and adds new scope on top of the rest:

- **AC-20 / AC-22** (event allowlist, quiet lifecycle) are revised to permit
  tool, skill, and agent names in status text — **only** under an opt-in
  `live` response mode that is off by default.
- **AC-28** (remote permission replies limited to `once`/`reject`) is revised
  to admit `always`, which is session-scoped in the owning service and not
  the permanent grant the original restriction assumed.
- **AC-32** (no remote settings writes, redaction excepted) is widened to
  admit exactly three additional writes: permission mode, model, and lead
  agent. Credentials, provider configuration, and sandbox policy remain
  forbidden, unchanged.
- **AC-38** (bounded lifecycle liveliness) is revised: `live` mode edits the
  status card on a throttled cadence rather than only on lifecycle
  transitions. `summary` mode keeps AC-38 as written.
- **AC-41** (model and permission mode are read-only remotely) is superseded
  by AC-48/AC-49, with `bypass` carved out as permanently desktop-only.

## Problem and outcome

The remote channel can start work and report completion, but it cannot be
*trusted with* work. Three concrete failures:

**Approvals are undecidable.** `app/remote/gates.py:113` renders a permission
request as `f"Permission requested: {tool}"` — the tool name only. A request
to run `rm -rf build/ && git clean -fdx` reaches the phone as "Permission
requested: shell" with Allow/Reject buttons. The actual command is already in
the event payload (`patterns[0]`, `app/agent/hooks/stream_publisher.py:309`)
and is discarded. The operator is asked to authorize something they cannot
see.

**Approvals never fire in the default configuration.** `ChatSession.permission_mode`
defaults to `auto` (`app/models/chat.py:153`), and `auto` never blocks
(`app/agent/permission.py:386`). The gate machinery is unreachable until the
mode changes — and AC-41 forbids changing it from the phone. The approval
feature is, in practice, structurally dead.

**Turns are opaque while they run.** A phone-admitted turn shows one static
status card and a typing indicator for its whole duration. For a multi-minute
turn there is no signal about what the agent is doing, which tool it is
running, or which agent in the team is active.

The outcome is a remote surface that behaves like a real coding client: an
approval card that names the command and its blast radius, the ability to put
the session into a mode where approvals actually happen, live narration of
tools and skills when asked for, read-only insight into system health and
code changes, and a first-run flow that points at all of it.

## Goals

- Render permission requests with the actual command, a derived severity, and
  the exact glob a session-scoped allow would grant.
- Fix the gate card lifecycle so an answered card visibly resolves instead of
  keeping dead buttons forever.
- Let the phone change permission mode, model, and lead agent — never
  `bypass`, never credentials.
- Add read-only `/health` and `/changes` surfaces backed by existing
  diagnostics and turn-change services.
- Add an opt-in `live` response mode that narrates tools, skills, and active
  agent on a throttled cadence, and keep today's quiet behavior as the
  default.
- Replace the dead-end pairing confirmation with a first-run card that offers
  the next useful action.
- Keep the command surface short enough that every command means something
  concrete.

## Non-goals

- **`bypass` permission mode is never settable remotely**, under any command,
  button, callback, or natural-language shortcut. A phone that can silently
  disable every approval prompt is a privilege-escalation path into the
  host, not a feature.
- No credential entry and no provider configuration writes from the phone.
  `PUT /api/settings/providers/{id}` writes API keys into `.env`
  (`app/api/routes/settings.py:1340`) and stays desktop-only.
- No token-by-token streaming. Telegram flood-limits edits to roughly one per
  second per chat and rejects unchanged-text edits outright; an agent turn
  emits deltas far faster than that. `live` mode coalesces, it does not
  stream.
- No `ToolOutputDeltaEvent` (raw stdout/stderr) in v1 — the least bounded
  content in the system, deferred until the bounded cases are proven.
- No second permission policy in the remote layer. Derived severity is
  **advisory display only** and never changes what is gated; gating stays
  entirely `PermissionService`'s decision.
- No persistent "allow forever" grant. `always` is session-scoped in the
  owning service (`app/agent/permission.py:372`) and the remote label says so.
- No change to the one-connection/one-pairing v1 limit, the pairing flow, or
  callback-token ownership rules.

## User flows and states

### Approving a dangerous command

When `PermissionService.ask` raises a request, the gate card renders the
command, not the tool name:

```
🔴 Dangerous command
<pre>rm -rf build/ && git clean -fdx</pre>
shell · evoflux · "Fix failing tests"

[ Allow once ]  [ Allow for session ]  [ Reject ]
```

Severity is derived, displayed, and advisory (AC-46). "Allow for session"
shows the glob it would grant, because `always` broadens the request to a
pattern (`always_patterns[0]`, e.g. `git push *`) and the operator must see
that blast radius before granting it:

```
[ 🔒 Allow for session — git push * ]
```

On reply the card is edited in place to its resolved form, losing its
buttons and stating what was decided:

```
✅ Allowed once
<pre>rm -rf build/ && git clean -fdx</pre>
```

Today none of that final edit happens: `_PendingGate.chat_id`/`message_id`
(`app/remote/gates.py:72`) are never assigned, so the guard at `gates.py:192`
is permanently false; the card is sent without a `correlation_id`, so the
adapter has no record to edit (`app/remote/telegram/adapter.py:209`); and
`_do_edit_remove` edits with `text=""` (`gates.py:401`), which Telegram
rejects. All three layers are fixed by AC-47.

### Changing how the agent works

`/settings` opens one hub card showing current state, with a button per
changeable value:

```
⚙️ Settings

Mode        ask
Model       mimo-v2.5-pro
Lead agent  evoflux
Responses   summary
Providers   3 configured

[ Mode ] [ Model ] [ Agent ] [ Responses ] [ Providers ]
```

Each button opens a bounded picker; each pick calls one existing service
entry point and re-renders the hub. The mode picker lists `ask`,
`accept-edits`, `plan`, and `auto`, and displays `bypass` as present but
unavailable from the phone — shown rather than hidden, so the card never
misrepresents the session's actual state when `bypass` is set at the desktop.

Lead-agent changes are refused while a turn is running (the owning endpoint
409s, `app/api/routes/team/chat.py:1720`); the card surfaces that as "finish
or /stop the current task first", never a raw error.

### Watching a turn in live mode

With `response_mode = live`, the turn's single status card is edited on a
throttled cadence with a rolling activity window:

```
🔧 Fix failing tests · 1m 12s

explorer · 💭 thinking
📚 Skill: test-driven-development
🔧 grep    "def test_auth"
🔧 read    tests/test_auth.py
⏳ shell   pytest tests/test_auth.py -q
```

Skills are not a distinct event; they are a tool call carrying `skill_name`
in its arguments (`app/agent/tools/builtin/skill.py:193`) and are
special-cased in rendering. The `agent` field present on every event
(`app/agent/schemas/events.py:31`) names which team member is active.

The window holds the most recent entries only, so the card cannot grow toward
Telegram's 4096-character limit. When the turn ends this same message becomes
the done card — one message per turn, start to finish, in both modes.

With `response_mode = summary` (default), behavior is exactly today's: one
status card, one final done/error card, typing indicator in between.

### Checking health and changes

`/health` renders `GET /api/health/diagnostics`, whose response is already
shaped for this (`{id, label, status: ok|warn|fail, detail, hint}`,
`app/api/routes/health.py:193`):

```
🩺 Health

✅ Database          ok
✅ Migrations        at head
⚠️ Providers         1 of 3 unreachable
✅ MCP servers       none configured
❌ Disk space        2.1 GB free
```

`/changes` renders the current session's turn changes (files plus line
counts, `app/api/routes/team/chat.py:1675`) with a drill-down button per file
that fetches real diff text through the existing capability-token and
chunking machinery.

### First run

The pairing confirmation becomes a starting point rather than a dead end:

```
✅ Paired! This phone is connected to EvoFlux.

Mode is auto — the agent won't ask before running commands.

[ ⚙️ Set up ]  [ 🩺 Health check ]  [ 💬 Just start working ]
```

The mode line is stated because `auto` means no approval prompts will ever
reach this phone, which is the single most consequential default the operator
should know about at pairing time.

## Requirements and acceptance criteria

IDs continue from AC-44. AC-20, AC-22, AC-28, AC-32, AC-38 and AC-41 are
revised as described above; all others are new.

- **AC-45 — Decidable permission cards:** A permission card renders the
  requested command from the event's `patterns[0]`, the tool name, the owning
  agent, and the session title. Command text passes through outbound
  redaction and then HTML escaping, in that order. A card offering a
  session-scoped allow displays the glob that allow would grant
  (`always_patterns[0]`). No card asks for a decision without showing what is
  being decided.
- **AC-46 — Advisory severity only:** Severity is derived from the tool name
  and command text: `high` for a destructive-pattern match, `elevated` for
  `shell`/`python`/`process`/`rm`, `normal` otherwise. Severity changes only
  the rendered icon and label. Tests prove that no severity value alters
  which requests are gated, which replies are accepted, or how any reply
  resolves — gating remains entirely `PermissionService`'s decision.
- **AC-47 — Gate cards resolve visibly:** A gate card is sent with a
  `correlation_id`, and on reply the same message is edited to a resolved
  form that states the decision and carries no buttons. The dead
  `chat_id`/`message_id` fields are removed rather than populated, since the
  adapter already maps correlation ids to sent messages. Tests cover reply,
  expiry, and adapter-edit failure.
- **AC-48 — Remote permission mode, bypass excluded:** `/settings` can set
  `ask`, `accept-edits`, `plan`, or `auto` through
  `PATCH /api/team/sessions/{id}/permission-mode`. `bypass` is rejected by
  the remote layer independently of what the endpoint accepts, and a test
  asserts no remote code path can produce it. A session already in `bypass`
  displays as such and may be changed *out of* bypass from the phone.
- **AC-49 — Remote model switching:** `/settings` can set the session model
  from the registry-validated catalog. Requires a new
  `PATCH /api/team/sessions/{id}/model` for team sessions, mirroring the
  existing side-chat endpoint (`app/api/routes/team/webbridge.py:883`),
  including its registry and `accepts_thinking_level` validation.
- **AC-50 — Remote lead agent switching:** `/settings` can change the lead
  agent through `PATCH /api/team/sessions/{id}/lead`, and renders the
  endpoint's running-session 409 as a bounded, actionable message.
- **AC-51 — Health surface:** `/health` renders every check from
  `GET /api/health/diagnostics` with per-check status. No check value
  containing a secret, key, path, or environment value is rendered beyond
  what that endpoint already returns.
- **AC-52 — Changes surface:** `/changes` lists the current session's changed
  files with line counts; per-file drill-down returns that file's diff text,
  redacted and chunked like any other outbound content, under the existing
  capability-token TTL.
- **AC-53 — Providers stay read-only:** The phone may list providers and
  their configured state and usage. No remote path reaches
  `PUT /api/settings/providers/{id}`, `POST /providers/{id}/test`, or any
  other credential-accepting endpoint. Proven by an inspection test over the
  remote dispatch surface.
- **AC-54 — First-run card:** A successful pairing sends a card naming the
  current permission mode and offering setup, health check, and start-working
  actions. A rejected pairing sends nothing, unchanged from AC-9.
- **AC-55 — Response mode preference:** `RemotePairing.response_mode`
  (`summary` default, `live`) is set from `/settings`, persists across
  restarts, and takes effect on the next turn with no restart.
- **AC-56 — Live mode content and bounds:** In `live` mode the status card
  shows a rolling window of the **6 most recent** activity entries — tool
  name plus an argument summary truncated to **80 characters**, skill name,
  thinking state, and active agent — each redaction-processed then escaped.
  Six entries at 80 characters bounds the activity block under ~600
  characters, well clear of Telegram's 4096-character limit even with a long
  title and header.
  `ToolOutputDeltaEvent` is never rendered. In `summary` mode no activity
  entry is ever rendered, preserving AC-20 as originally written.
- **AC-57 — Throttled, budgeted edits:** Live-mode edits are coalesced to at
  most one per `LIVE_EDIT_INTERVAL` (3s) per turn, skipped entirely when the
  rendered text is unchanged, and drawn from one shared per-connection edit
  budget across all concurrently live turns. On a Telegram `429` the budget
  honors `retry_after` and the cadence degrades; updates are never dropped
  silently in a way that loses the final card.
- **AC-58 — Bounded command surface:** The command set is `/help`,
  `/status`, `/new`, `/stop`, `/settings`, `/health`, `/changes`,
  `/actions`, `/unpair`. Configuration lives behind `/settings`; `/health`
  and `/changes` stay top-level as actions. Telegram's native command menu
  advertises exactly this set and never a command that is not implemented.

## API, event, tool, and UI contracts

### New modules

- `app/remote/severity.py` — derives advisory severity from tool name and
  command text. Pure, no I/O, no dependency on `app.remote` state.
- `app/remote/control.py` — the three write operations (mode, model, lead)
  plus the read aggregation `/settings` renders. Owns the bypass refusal and
  the 409 translation. Keeps `actions.py` from absorbing a second
  responsibility.
- `app/remote/live_activity.py` — the rolling activity window and its
  rendering. `app/remote/outbound.py` is already 889 lines and `actions.py`
  753; live-mode buffering and window management go here rather than growing
  either further.
- `app/remote/edit_budget.py` — the shared per-connection edit budget and
  `retry_after` backoff used by AC-57.

### Changed modules

- `app/remote/gates.py` — command-bearing permission cards, `always` reply,
  correlation-id send, resolved-form edit, dead field removal.
- `app/remote/formatting.py` — builders for permission, settings, picker,
  health, changes, onboarding, and live-activity cards.
- `app/remote/actions.py` — `/settings`, `/health`, `/changes` dispatch and
  their capability action kinds.
- `app/remote/outbound.py` — live-mode observation and throttled edit path.
- `app/remote/runtime.py` — onboarding card, response-mode wiring.
- `app/remote/telegram/adapter.py` — command menu updated to AC-58's set.

### Event observation

`RemoteProjection.observe`'s allowlist becomes mode-dependent: `summary` keeps
today's set exactly; `live` additionally observes `tool_call`, `tool_start`,
`tool_end`, and `thinking`. `observe` stays synchronous, bounded, and
non-blocking — activity entries are buffered in memory and rendered on the
async delivery path, never inside `observe()`.

### New endpoint

`PATCH /api/team/sessions/{session_id}/model` — team-session model change,
mirroring `webbridge.py:883`'s validation. This is the one backend gap the
design requires; every other operation reuses an existing endpoint.

## Data model, migration, and retention

One migration (`00000066`) adds `remote_pairings.response_mode` (bounded
enum, default `summary`), revising `down_revision` from the current head
`00000065` and bumping `SCHEMA_HEAD` in `app/core/schema_version.py:16`
to match — the same two-step the `notify_scope` migration performed.
Permission mode, model, and lead agent already persist on `ChatSession`
(`permission_mode`, `model`, `agent_name`) and are not duplicated.

Activity windows, severity values, and edit budgets are in-memory and
ephemeral, consistent with the accepted spec's treatment of progress-message
state. Diff and health content is read on demand and never cached beyond the
existing capability-token TTL. No new durable store.

## Permissions, security, privacy, and trust

The `bypass` exclusion (AC-48) is the load-bearing boundary of this document.
Everything else the phone gains is recoverable or observable; a remote
`bypass` toggle is neither, because it disables the very prompts that would
reveal its misuse. It is excluded in the remote layer itself, not merely
omitted from a menu, so a forged or replayed callback cannot reach it.

Advisory-only severity (AC-46) is the second boundary. A remote layer that
derived its own notion of "dangerous" and acted on it would be a second
permission policy that can silently diverge from `PermissionService`. Severity
may change an icon; it may never change an outcome.

Tool arguments are the highest-risk text this feature renders — they carry
file paths, command strings, and occasionally secrets. Every rendered field
passes through `protect_outbound_text(context=OutboundContext(channel="remote"))`
and then `html.escape`, redaction first, escaping last, matching AC-24
(revised). `ToolOutputDeltaEvent` is excluded from v1 precisely because it is
the least bounded of these.

Provider read-only (AC-53) is enforced by inspection test rather than by
convention, since the credential-writing endpoint sits one call away from the
provider-listing one the phone legitimately uses.

## Concurrency, failure, recovery, and idempotency

The shared edit budget (AC-57) is the new contention point: several turns can
be live at once when `notify_scope=all`, and each independently wants the
same per-chat edit allowance. The budget is owned per connection and consulted
by every live turn, so contention degrades cadence rather than producing 429s.
A turn's final done/error card is drawn from the same reserved allowance and
is never starved by activity updates — liveliness is best-effort, completion
is not.

Live-mode buffering reuses the existing per-turn lifecycle: the activity
window is owned by the same `_TurnDeliveryState` that owns the status message
and typing task, and is discarded wherever that state is already torn down
(completion, error, interrupt, adapter shutdown, unpairing). No new teardown
path.

A control operation that fails at its owning endpoint (validation, 409,
transport) re-renders the settings hub with the failure stated and the
unchanged current value, so the card never shows a value the backend did not
accept.

## Observability and diagnostics

New counters: severity distribution across rendered permission cards, remote
reply distribution (`once`/`always`/`reject`), `response_mode` distribution
across pairings, live-edit attempts versus budget-deferred edits, and
control-operation outcomes by kind. No label carries session, path, command,
or content data, consistent with the accepted spec's metric-label rules.

The gate-card resolution fix (AC-47) is itself an observability improvement:
an unresolved card is currently indistinguishable from a resolved one.

## Compatibility, rollout, and rollback

Every behavior change is default-off or default-unchanged. `response_mode`
defaults to `summary`, which is exactly today's behavior. Permission mode is
untouched until explicitly changed, so no existing session's gating changes
as a result of this document. The permission-card and gate-lifecycle fixes
(AC-45/AC-47) change only what an already-sent card contains and whether it
resolves — both strictly more correct than today.

The one behavior change visible without opting in is the pairing card
(AC-54), which replaces a one-line confirmation.

Rollback is the accepted spec's disable/remove path. The migration is
additive with a default; no irreversible state is created.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-45 | Gate-card golden-output tests including adversarial command text (`<`, `>`, `&`, tag-like strings); redaction-before-escaping order test; glob-display test |
| AC-46 | Severity unit tests per class; inspection test proving no severity value reaches any gating or reply path |
| AC-47 | Reply/expiry/edit-failure lifecycle tests asserting exactly one edit, resolved text, zero buttons; regression test that a card is sent with a correlation id |
| AC-48 | Mode-set round-trip tests per allowed mode; refusal test for `bypass` via command, callback, and forged token; display test for a desktop-set `bypass` session |
| AC-49 | Model-set round-trip against the registry; invalid-model and thinking-level rejection tests; new endpoint's own route tests |
| AC-50 | Lead-change round-trip; 409-while-running translation test |
| AC-51, AC-52 | Render tests against fixture diagnostics/changes payloads; drill-down scoping, redaction, chunking, and expiry tests |
| AC-53 | Inspection test over the full remote dispatch surface proving no path reaches a credential-accepting endpoint |
| AC-54 | Pairing-success card content test; pairing-rejection silence test (AC-9 regression) |
| AC-55 | Migration default test; `/settings` round-trip; next-turn effect without restart |
| AC-56 | Window-cap and 4096-boundary tests; skill-vs-tool rendering test; `summary`-mode assertion that no activity entry is ever rendered (AC-20 regression) |
| AC-57 | Throttle-interval test; unchanged-text skip test; multi-turn budget contention test; `429`/`retry_after` degradation test; final-card-not-starved test |
| AC-58 | Command-set test; native-menu registration test asserting no unimplemented command is advertised |

## Ownership and source map

- Severity derivation: `app/remote/severity.py` (new).
- Control operations and settings aggregation: `app/remote/control.py` (new).
- Live activity window: `app/remote/live_activity.py` (new).
- Edit budget: `app/remote/edit_budget.py` (new).
- Gate cards and lifecycle: `app/remote/gates.py`.
- Card rendering: `app/remote/formatting.py`.
- Command dispatch: `app/remote/actions.py`.
- Turn observation and delivery: `app/remote/outbound.py`.
- Onboarding and wiring: `app/remote/runtime.py`.
- Schema: one migration adding `remote_pairings.response_mode`.
- New endpoint: `PATCH /api/team/sessions/{id}/model`.

This document remains proposed until implementation is verified and
reconciled into current documentation, per the accepted spec's lifecycle
rules.
