# EASD recovery UX

Status: implemented

## Problem and outcome

EASD exposes Redraft and Replan at their mutable review boundaries, but users do
not have one place that explains which current phase can be retried, what state
will be reused, or what history will be preserved. Implementation, Review, and
Verify can be reopened in chat manually, but that action is not recorded as a
Run recovery attempt.

The outcome is a server-derived Recovery workspace that previews safe retries,
records explicit retry attempts, and opens the matching phase chat without
deleting prior revisions, attempts, evidence, or events.

## Goals

- Offer only retries valid for the persisted Run status.
- Explain reused contract identities, preserved history, and state transition.
- Keep Redraft/Replan on the existing revision-preserving service paths.
- Record same-phase implementation/review/verification retries as repository
  events before reopening chat.
- Reject stale repository generations and cross-session recovery.
- Display recovery lineage in Trace through ordered events.

## Non-goals

- Reopening a converged Run; users create a new Run instead.
- Returning Review/Verify to implementation or invalidating accepted evidence.
- Automatically redispatching a failed member without the lead agent.
- Deleting failed attempts or overwriting Spec/Plan revisions.
- Retrying provider transport errors inside the agent runtime.

## User flows and states

- `draft`: Redraft specification; existing draft remains until replacement.
- `plan_review`: Replan; accepted Spec and prior Plan draft remain visible.
- `active`: Retry implementation in the linked chat without phase change.
- `reviewing`: Rerun Review and append fresh review evidence.
- `verifying`: Rerun Verify and append fresh machine evidence.
- other statuses show why no safe retry is available.
- A confirmation summarizes current phase, next phase, reused identities,
  preserved data, and repository generation.

## Requirements and acceptance criteria

- **AC-1:** Recovery preview is computed from persisted Run/Spec/Plan/session
  state and returns stable action IDs with reusable/preserved effects.
- **AC-2:** Execute requires the current repository generation and rejects stale
  callers with `409` before changing state.
- **AC-3:** Redraft uses the existing `draft → authoring` retry service and
  preserves the prior Spec draft until replacement persistence.
- **AC-4:** Replan uses `plan_review → planning` and preserves the prior Plan
  draft until replacement persistence.
- **AC-5:** Active/Reviewing/Verifying retries are same-phase, append an explicit
  retry event, and do not delete missions/evidence/deviations.
- **AC-6:** Recovery requires the Run's bound authorized Coding session.
- **AC-7:** Repeated execution with the same idempotency key returns the first
  result and does not append a duplicate event.
- **AC-8:** Recovery UI shows unavailable, stale, loading, confirmation, and
  execution-error states without optimistic lifecycle changes.
- **AC-9:** Successful recovery opens the matching phase chat and exact EASD
  skill prompt only after server persistence.
- **AC-10:** Trace shows recovery events in attempt order.
- **AC-11:** Backend/frontend tests cover each allowed status, stale generation,
  wrong session, duplicate key, and confirmation handoff.
- **AC-12:** Docs, localized Help, and a live sampleproject audit match behavior.

## API, event, tool, and UI contracts

```text
GET /api/easd/runs/{id}/recovery
  -> { run_id, store_generation, actions[], unavailable_reason? }

POST /api/easd/runs/{id}/recovery
  { action_id, session_id, expected_generation, idempotency_key }
  -> { run, recovery }
```

Action IDs: `redraft_specification`, `replan`, `retry_implementation`,
`retry_review`, and `retry_verification`.

## Data model, migration, and retention

No schema migration. Existing revision tables, DelegationTask attempt lineage,
evidence rows, and repository events are retained. A bounded in-process
idempotency cache prevents duplicate execution within the local runtime; the
repository event remains the durable audit result.

## Permissions, security, privacy, and trust

Recovery never widens workspace/project/session authorization and does not
grant additional tools. Agent phase guards and server lifecycle validation
remain authoritative after chat opens.

## Concurrency, failure, recovery, and idempotency

The caller supplies the observed repository generation. Any newer collaborator
write fails closed and requires refresh. The event is queued after DB commit,
matching existing repository synchronization.

## Observability and diagnostics

Existing trace operation metrics record recovery action/status without Run IDs.
Events include action, actor, session, from/to status, and reused hashes.

## Compatibility, rollout, and rollback

Recovery endpoints and tab are additive. Existing phase buttons remain valid.
Removing Recovery leaves existing Redraft/Replan routes unchanged.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1–7 | trace service/API tests |
| AC-8–10 | panel/query component tests and Trace assertions |
| AC-11 | focused quality gates |
| AC-12 | docs/Help and sampleproject audit |

## Ownership and source map

- Policy/service: `app/services/trace_service.py`
- API: `app/api/schemas/easd.py`, `app/api/routes/easd.py`
- Client/query: `web/src/api/`, `web/src/queries/`
- UI: `web/src/components/easd/`, `EvoAgentSpecsPanel.tsx`
- Tests/docs: `tests/`, `documents/`, `web/src/help/locales/`
