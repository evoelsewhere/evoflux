# Task 6 brief: natural-language ingress and current-task behavior

Status: ready after Tasks 1-4; may be implemented while Task 5 is in progress

Parent specification: [Remote access through Telegram](remote-channel-telegram.md)

Implementation plan: [Remote access through Telegram implementation](remote-access-telegram-implementation.md#task-6-natural-language-ingress-and-current-task-behavior)

## Objective

Implement the provider-neutral service that turns an authorized remote text or
task action into EvoFlux session behavior. A paired user can send ordinary text
from their phone, continue one current desktop task, clear that selection for a
new Work task, or stop only the current live turn.

This task covers `AC-14`, `AC-15`, `AC-16`, `AC-17`, `AC-18`, and `AC-29`.

## Observable result

- The first authorized plain-text update creates one top-level Work session,
  marks it with remote provenance tags, stores it as the pairing's current
  session, and submits the text through the shared interactive ingress.
- Later text for the pairing uses that current session and reports the real
  `accepted`, `pending`, or `queued` result.
- Redelivery of the same Telegram update has at most one persisted user-message
  effect, including the recovery path after persistence but before the adapter
  advances its update offset.
- **New task** clears only the pairing's current-session pointer. It does not
  delete, hide, archive, interrupt, or otherwise mutate the previous session.
- **Continue this task** changes only that pointer and accepts only a
  user-visible, top-level Work or Coding session.
- `/stop` interrupts only a live turn in the pairing's current session. It
  reports a distinct no-active-turn outcome when there is nothing to stop.

## Ownership and coordination

The Task 6 implementer owns:

- Create `app/remote/inbound.py`.
- Modify `app/services/interactive_message_service.py`.
- Modify `app/services/chat_service.py` only to make channel-source delivery
  state recognize `interactive_source` while retaining legacy
  `webbridge_source` behavior.
- Create `tests/remote/test_inbound.py`.
- Modify or create focused service tests under
  `tests/services/test_interactive_message_service.py` and
  `tests/services/test_chat_service.py` as needed for source compatibility.

Claude's Task 5 owns these files; Task 6 must not edit them:

- `app/api/schemas/remote.py`
- `app/api/routes/remote.py`
- `app/remote/runtime.py`
- `app/api/app.py`
- `tests/api/routes/test_remote.py`
- `tests/remote/test_runtime.py`

Do not stage, commit, reset, restore, or rewrite unrelated work. Re-read
`git status --short` before editing because the worktree is shared and dirty.

## Available prerequisite contracts

Use the existing contracts directly:

- `RemoteInboundAction` and `RemotePrincipal` from `app.remote.contracts`.
  The Telegram adapter already supplies a source key in the form
  `telegram:<connection-id>:<update-id>`, which contains all three identity
  parts required by `AC-16`. Preserve this key instead of deriving it from
  message text or provider display values.
- `PairingService.authorize(db, connection_id=..., principal_id=...)` from
  `app.remote.pairing`. It reads the pairing fresh and returns `None` for every
  unauthorized or rate-limited request.
- `RemotePairing.active_session_id`. Its foreign key uses `ON DELETE SET NULL`,
  so deleted-current-session recovery should use the resulting null pointer.
- `create_chat_session`, `resolve_team_for_session`, and
  `submit_persisted_interactive_message` from the existing service layer.
- `agent_service.interrupt_team(team, session_id)` for a live current team.
  Do not use `team_manager.stop_sessions`: it evicts sessions and is broader
  than the user-level interrupt required by `AC-29`.

Task 6 has no code dependency on Task 5's routes or lazy runtime. Do not import
from `app.api` or `app.remote.runtime`.

## Service contract

Add `RemoteInboundService` in `app/remote/inbound.py` with four asynchronous,
provider-neutral operations:

```python
async def handle_text(
    db: AsyncSession,
    action: RemoteInboundAction,
) -> RemoteInboundResult: ...

async def new_task(
    db: AsyncSession,
    action: RemoteInboundAction,
) -> RemoteInboundResult: ...

async def continue_task(
    db: AsyncSession,
    action: RemoteInboundAction,
    session_id: UUID,
) -> RemoteInboundResult: ...

async def stop_current(
    db: AsyncSession,
    action: RemoteInboundAction,
) -> RemoteInboundResult: ...
```

The methods may share one private authorization helper. Each public operation
must authorize the action's `connection_id` and `principal.principal_id` before
reading or changing the pointer or resolving a team.

Define a small immutable result type in the same module. It must carry a bounded
outcome code plus optional `session_id` and `message_id`, without Telegram text
or payload types. Required outcomes are:

- `accepted`, `pending`, and `queued` for text admission;
- `current_task_cleared` and `current_task_selected`;
- `interrupted` and `no_active_turn`;
- `unauthorized` and `session_not_addressable`.

The later adapter-integration task owns user-facing Telegram wording.

## Session eligibility rule

Use one private predicate for every remote selection and current-session
revalidation. A session is addressable only when all conditions hold:

```python
session.parent_session_id is None
session.session_type == "main"
session.mode in {"work", "coding"}
```

This excludes team-member, Side Chat, and any future internal session types by
default. Do not infer eligibility from the title, agent name, tags, or whether
the session currently has a live in-memory team.

If an existing current pointer references a row that is missing or no longer
addressable, clear the pointer and treat the next text as a first message.

## First-message and current-message flow

Serialize pointer decisions for one pairing with a connection/pairing-keyed
`asyncio.Lock`. Without this, two simultaneous first messages can both observe
a null pointer and create two current sessions. Keep the lock scoped to this
single-process service and clean unused keyed locks when practical.

For an authorized `handle_text` call:

1. Reject empty text after the adapter's normalization; never create a session
   for it.
2. Load and revalidate `active_session_id` under the per-pairing lock.
3. If no valid current session exists, call `create_chat_session`, then set:
   - `mode = "work"`;
   - `parent_session_id = None`;
   - `session_type = "main"`;
   - `tags = ["remote_origin", f"remote_connection:{connection_id}"]`;
   - `pairing.active_session_id = session.id`.
4. Commit the created session and pointer together before team resolution or
   message dispatch. Do not hold a database transaction across filesystem,
   model, team-start, or agent work.
5. Resolve the persisted session/team with
   `resolve_team_for_session(..., require_existing=True)`.
6. Submit with `submit_persisted_interactive_message`, passing the original
   plain text, `source_key=action.source_key`, the request hash, and the source
   metadata described below.
7. Map the existing `InteractiveMessageResult` without changing its
   `accepted`/`pending`/`queued` meaning.

Use the normal Work session defaults for model, permission mode, workspace, and
follow-up delivery. Remote ingress must not grant broader permissions or select
a special model.

## Channel-neutral source metadata

Store new remote source information under `interactive_source`:

```python
{
    "interactive_source": {
        "channel": "remote",
        "adapter": "telegram",
        "connection_id": str(action.connection_id),
        "key": action.source_key,
        "request_hash": request_hash,
        "state": "persisted",
    }
}
```

Calculate `request_hash` deterministically from the admitted semantic request;
for text, SHA-256 of the normalized UTF-8 text is sufficient. Never include a
bot token, pairing token, callback token, display name, or destination ID.

Generalize source handling through one helper that selects
`interactive_source` first and falls back to legacy `webbridge_source`.
Apply it consistently to:

- lookup by source key;
- request-hash conflict checking;
- delivered-state replay detection;
- `mark_channel_source_delivered` for immediate delivery, post-turn queued
  activation, and in-turn queued injection.

Do not rename or rewrite existing `webbridge_source` rows. Existing WebBridge
callers may continue writing that key, and all current WebBridge retry tests
must remain green.

## New, continue, and stop behavior

`new_task` authorizes, locks the pairing, sets `active_session_id = None`, and
commits. It does not resolve or stop a team and does not create a replacement
session until the next text arrives.

`continue_task` authorizes, loads the requested `ChatSession`, applies the exact
eligibility predicate, then changes and commits only `active_session_id`. It
does not resend history, start a team, or mutate the selected session.

`stop_current` authorizes and revalidates the current session. Resolve the team
using existing session behavior, then call `agent_service.interrupt_team` only
when that team has an active user turn. Return `no_active_turn` when there is no
current addressable session or no active turn. Do not clear the pointer, stop
the sidecar, delete a session, call `stop_sessions`, or report `interrupted`
when no work was canceled.

## Required tests

Write tests before implementation and record the failing test command.

### Source compatibility

- `interactive_source` rows are found by source key.
- Legacy `webbridge_source` rows are still found.
- An `interactive_source` request-hash mismatch raises
  `InteractiveMessageConflict`.
- Replaying a delivered `interactive_source` row returns `accepted` without a
  second dispatch.
- Both source formats transition to `delivered` through
  `mark_channel_source_delivered`.
- Existing WebBridge source tests remain unchanged and pass.

### Text ingress

- Unauthorized principal produces no session, pointer, message, or team work.
- First text creates exactly one top-level Work session with exactly the two
  required provenance tags and sets the pointer.
- Later text reuses the pointed session.
- `accepted`, `pending`, and `queued` pass through accurately.
- Two concurrent first texts create one current session rather than two.
- Duplicate source-key delivery persists one user message and does not dispatch
  twice.
- Recovery after a message was persisted but before update acknowledgement
  returns the prior result without another user-message effect.
- A null pointer left by session deletion causes the next text to create a new
  Work session.

### Pointer actions and boundary

- **New task** clears the pointer and leaves the previous session unchanged.
- **Continue this task** accepts a top-level Work session and a top-level Coding
  session.
- It rejects a child/team-member session, Side Chat, unsupported/internal
  session type, and unsupported mode without changing the existing pointer.
- A missing requested session returns `session_not_addressable`.
- Authorization is checked again on every action.

### Stop

- A live current turn calls `interrupt_team` for that session only and returns
  `interrupted`.
- No current session, a deleted/non-addressable session, or an idle team returns
  `no_active_turn` and never claims interruption.
- The pointer and session remain after interruption.
- No unrelated session or team is stopped.

Use fakes/mocks for team resolution and dispatch where a real team would start
model or filesystem work. Database behavior, pointer persistence, foreign-key
cleanup, and message idempotency should use the repository's real async SQLite
test fixture.

## Execution order

1. Read the current shared files and status; incorporate non-conflicting changes
   made since this brief was written.
2. Add failing compatibility tests for `interactive_source` plus legacy source
   behavior.
3. Add failing inbound service tests for all flows and boundaries above.
4. Implement the smallest channel-neutral source helper and inbound service.
5. Run focused tests and lint.
6. Inspect the complete diff for overlap and accidental changes.

## Verification evidence

Run at minimum:

```powershell
uv run pytest --no-cov -q tests/services/test_interactive_message_service.py tests/services/test_chat_service.py tests/remote/test_inbound.py
uv run pytest --no-cov -q tests/api/test_webbridge.py -k "source or idempot or queued"
uv run ruff check app/remote/inbound.py app/services/interactive_message_service.py app/services/chat_service.py tests/remote/test_inbound.py tests/services/test_interactive_message_service.py tests/services/test_chat_service.py
uv run ruff format --check app/remote/inbound.py app/services/interactive_message_service.py app/services/chat_service.py tests/remote/test_inbound.py tests/services/test_interactive_message_service.py tests/services/test_chat_service.py
uv run ty check app/
git diff --check
```

If a listed test file does not yet exist, create the focused file or place the
cases in the nearest existing service test and report the actual path. Do not
broaden to the full suite until focused behavior is green.

## Handoff requirements

Return all of the following to the lead:

1. Outcome and evidence mapped to `AC-14`, `AC-15`, `AC-16`, `AC-17`, `AC-18`,
   and `AC-29`.
2. Files changed and any public/internal contracts introduced.
3. Exact red and green commands with their results.
4. Assumptions or deviations from this brief and why they were necessary.
5. Remaining risks, blockers, or follow-up work for adapter integration.
6. Confirmation that Task 5 and unrelated dirty-worktree files were preserved.

Do not commit.
