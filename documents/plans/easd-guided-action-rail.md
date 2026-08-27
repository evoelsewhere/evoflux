# EASD guided action rail

Status: implemented

## Problem and outcome

The EASD Run header exposes phase-specific buttons, but availability is derived
mostly from the Run status. Review, Verify, or Converge may therefore look ready
before mission/evidence/deviation gates pass; users discover blockers only after
a rejected mutation. Approval actions also execute immediately without a final
summary of the immutable contract being accepted.

The outcome is one compact action rail that explains the current lifecycle
position, names the next primary action, exposes server-derived blockers before
mutation, and confirms Spec, Plan, and Convergence decisions.

## Goals

- Compute action availability from persisted server state.
- Show a compact Intent → Spec → Plan → Implement → Review → Verify → Done rail.
- Make direct flow's skipped Plan explicit.
- Disable blocked actions with actionable explanations and entity IDs.
- Confirm Spec approval, Plan approval, and Converge before mutation.
- Preserve all existing lifecycle authority and API validation.

## Non-goals

- Replacing backend phase validation with client checks.
- A visual mission DAG or full evidence inspector.
- Deviation-resolution UI.
- New persistence tables or lifecycle statuses.

## User flows and states

- The active step is derived from persisted Run status.
- Planned flow shows Plan as required; direct flow shows Plan as skipped.
- The server returns one primary action for the current state plus optional
  secondary retry actions.
- A blocked primary action remains visible but disabled, with a concise blocker
  summary and structured IDs/commands.
- Approve Spec summarizes version/hash, risk, AC count, and selected flow.
- Approve Plan summarizes version/hash, mission count, Spec hash, and review
  policy.
- Converge summarizes satisfied ACs, mission/evidence counts, and warns that the
  resulting report is the server-owned Done decision.

## Requirements and acceptance criteria

- **AC-1:** Run detail returns an `action_rail` derived from persisted Run,
  revision, mission, evidence, deviation, and Plan state.
- **AC-2:** Each action has a stable ID, label, `available|blocked` state, and
  structured blockers with human-readable messages.
- **AC-3:** `start_review` is blocked while any current EASD mission is not
  terminal and lists the blocking mission IDs/statuses.
- **AC-4:** `start_verification` is blocked until review missions are terminal,
  passing review evidence exists, and independent runtime review exists when
  policy requires it.
- **AC-5:** `converge` readiness uses the same reasons as the Convergence service:
  required ACs, mission terminality, blocking deviations, independent review,
  and planned command evidence.
- **AC-6:** Pre-implementation actions reflect direct/planned flow and existing
  retry states without widening lifecycle authority.
- **AC-7:** The frontend renders a compact lifecycle rail and one emphasized
  primary action from the server contract.
- **AC-8:** Blocked actions are disabled and expose blocker text before the user
  attempts the mutation.
- **AC-9:** Spec approval requires an explicit confirmation summarizing immutable
  hash/version, risk, AC count, and direct/planned flow.
- **AC-10:** Plan approval requires an explicit confirmation summarizing Plan
  hash/version, mission count, Spec binding, and review policy.
- **AC-11:** Converge requires an explicit confirmation and remains disabled when
  the server action contract is blocked.
- **AC-12:** Feature, architecture, API, localized Help, and focused backend/
  frontend tests describe and enforce the rail.

## API, event, tool, and UI contracts

`GET /api/easd/runs/{id}` and Run create responses add:

```text
action_rail = {
  phase,
  primary_action,
  actions[] = {
    id,
    label,
    state: available | blocked,
    blockers[] = {
      code, message,
      criterion_id?, mission_id?, deviation_id?, status?, commands?
    }
  }
}
```

The server remains authoritative. A client may hide secondary actions for layout
but must not enable a blocked action.

## Data model, migration, and retention

No migration. `action_rail` is a deterministic response projection.

## Permissions, security, privacy, and trust

The projection reveals only IDs, statuses, and commands already present in Run
detail. It grants no permission and performs no mutation.

## Concurrency, failure, recovery, and idempotency

The rail is advisory at response time; mutation endpoints revalidate all gates.
If state changes after render, the mutation may still fail with the existing
conflict response and the detail query is refreshed.

## Observability and diagnostics

No new metric cardinality. Existing rejected lifecycle/convergence metrics remain
authoritative; blocker codes are visible before action.

## Compatibility, rollout, and rollback

The response field is additive. Older clients ignore it. New clients fall back
to current phase copy if it is absent during mixed-version development.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1–6 | trace service/API projection tests |
| AC-7–11 | panel component tests and local UI run |
| AC-12 | docs/Help/i18n tests |

## Ownership and source map

- Projection/gates: `app/services/trace_service.py`
- API schema: `app/api/schemas/easd.py`
- Client types/UI: `web/src/api/types.ts`,
  `web/src/components/EvoAgentSpecsPanel.tsx`, `web/src/components/easd/`
- Tests: `tests/services/`, `tests/api/routes/`, `web/src/__tests__/`
- Docs/Help: `documents/features/`, `documents/architecture/`,
  `documents/reference/`, `web/src/help/locales/`
