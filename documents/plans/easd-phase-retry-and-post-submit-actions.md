# EASD phase retry and post-submit review actions

Status: accepted

## Problem and outcome

EASD specification and plan tools intentionally stop the agent turn immediately
after a durable draft is persisted. The chat currently ends on a successful tool
row without a clear next action, so users must rediscover the EASD workbench and
Run manually. If authoring or planning needs another attempt, the UI also lacks
a lifecycle-safe retry action.

The outcome is a visible, authoritative handoff from successful typed submission
to the exact Run review surface, plus retry controls that create a new draft
attempt without overwriting prior revisions.

## Goals

- Make the accepted verification-command grammar explicit in `easd-specify`.
- Render a review action for successful Spec and Plan submission tool results.
- Open the EASD workbench and exact Run when that action is selected.
- Let the user retry an in-progress Spec/Plan attempt or request a new draft from
  `draft`/`plan_review` while preserving history.
- Keep user approval, immutable accepted revisions, and runtime evidence gates
  unchanged.

## Non-goals

- Restarting implementation, review, verification, or converged Runs.
- Reopening an accepted Spec or Plan after implementation has started.
- Replacing agent/tool validation with client-side trust.
- Deleting failed attempts or superseded draft revisions.

## User flows and states

### Successful Spec submission

1. `easd_submit_specification` persists a draft and stops the agent turn.
2. The successful tool row shows **Review specification**.
3. Selecting it opens/activates the EASD workbench and exact Run detail.

### Successful Plan submission

1. `easd_submit_plan` persists a Plan draft and stops the agent turn.
2. The successful tool row shows **Review plan**.
3. Selecting it opens/activates the EASD workbench and exact Run detail.

### Retry

- `authoring`: **Retry drafting** resends the current authoring prompt in the
  linked chat; the Run stays `authoring`.
- `draft`: **Redraft in chat** is a user action that moves `draft → authoring`.
  The existing draft remains durable until a new draft is submitted; the new
  submission supersedes it through the existing revision service.
- `planning`: **Retry planning** resends the current Plan prompt; the Run stays
  `planning`.
- `plan_review`: **Replan in chat** moves `plan_review → planning`. The prior
  Plan draft remains durable until a new Plan draft supersedes it.

## Requirements and acceptance criteria

- **AC-1:** `easd-specify` states that verification commands are one executable
  argv-style line, use an approved PATH program/wrapper, and contain none of
  `&&`, `||`, `;`, `|`, `>`, or `<`.
- **AC-2:** The Skill gives valid examples such as
  `python -m pytest tests/test_simple.py`, and rejects `python -c` snippets or
  composed shell commands as Proof commands.
- **AC-3:** A successful `easd_submit_specification` tool result renders a
  **Review specification** action; failed/malformed results do not.
- **AC-4:** A successful `easd_submit_plan` tool result renders a **Review plan**
  action; failed/malformed results do not.
- **AC-5:** Selecting either action opens the EASD workbench and exact Run ID,
  including when the panel was previously closed or mounted after the request.
- **AC-6:** The open-Run request is one-shot and can only be cleared by its exact
  request ID.
- **AC-7:** Retrying Spec from `draft` is explicit, session-bound, changes the
  Run to `authoring`, preserves the current draft, and records a lifecycle event.
- **AC-8:** Retrying Plan from `plan_review` is explicit, session-bound, changes
  the Run to `planning`, preserves the current draft, and records a lifecycle
  event.
- **AC-9:** Retrying while already `authoring` or `planning` is idempotent and
  allows the client to resend the phase prompt without another state mutation.
- **AC-10:** Retry rejects a foreign session, an unsupported phase, terminal
  Run, stale/missing accepted Spec for Plan, or a direct-flow Run.
- **AC-11:** UI mutation success invalidates both Run detail and list caches;
  errors remain visible beside the phase controls.
- **AC-12:** Feature, API, methodology-adjacent Help, and focused backend/
  frontend tests describe and enforce the new handoff and retry behavior.

## API, event, tool, and UI contracts

New endpoints:

```text
POST /api/easd/runs/{run_id}/authoring/retry  {session_id}
POST /api/easd/runs/{run_id}/planning/retry   {session_id}
```

New lifecycle events:

```text
specification_authoring_retried
planning_retried
```

The tool action derives `run_id` only from parsed tool arguments and appears
only when the result matches the runtime success contract. It never infers
success from agent prose.

## Data model, migration, and retention

No schema migration. Existing Run, revision, event, and session fields are
reused. Prior draft revisions and failed tool attempts remain durable.

## Permissions, security, privacy, and trust

- Retry uses the existing authorized Coding session and Run scope validation.
- UI actions do not call approval or mutation endpoints automatically.
- Successful typed tool results—not assistant text—authorize the review link.
- Verification commands remain runtime-parsed and non-shell.

## Concurrency, failure, recovery, and idempotency

- Same-session retry in the same active phase is idempotent.
- Foreign session and unsupported-state retry fail closed.
- A new draft supersedes the earlier draft only after successful persistence.
- If the model/tool attempt fails, the prior draft remains inspectable and the
  retry action remains available.

## Observability and diagnostics

Retry emits structured operation metrics/logs and repository lifecycle events.
Tool-row failure output remains available beside the action-free failed row.

## Compatibility, rollout, and rollback

The endpoints and UI state are additive. Existing Runs and tool results remain
readable. Removing the client action leaves the lifecycle unchanged; removing
retry endpoints leaves existing persisted revisions intact.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1–2 | setup/Skill content tests |
| AC-3–6 | Tool action and UI-store component tests |
| AC-7–10 | trace service and EASD route tests |
| AC-11 | query invalidation and panel tests |
| AC-12 | feature/Help diff plus focused test suites |

## Ownership and source map

- Skill bundle: `app/easd_skills/easd-specify/SKILL.md`
- Lifecycle: `app/services/trace_service.py`
- API: `app/api/routes/easd.py`, `web/src/api/client/easd.ts`
- UI state/action: `web/src/stores/useUIStore.ts`,
  `web/src/components/ToolCall/`, `web/src/components/EvoAgentSpecsPanel.tsx`
- Queries/tests: `web/src/queries/useEasdQuery.ts`, `tests/`, `web/src/__tests__/`
- Current docs/Help: `documents/features/evo-agent-specs.md`,
  `web/src/help/locales/`
