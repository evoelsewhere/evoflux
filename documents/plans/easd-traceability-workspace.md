# EASD traceability workspace

Status: implemented

## Problem and outcome

EASD persists the Run, immutable Spec/Plan revisions, missions, evidence,
deviations, convergence, and append-only lifecycle events. The current detail
panel renders most artifacts as separate sections, so a user cannot follow one
acceptance criterion from contract to owner, attempt, evidence, and blocker.
Repository events are also not exposed through the public Run API.

The outcome is a read-only traceability workspace that projects the existing
repository-owned data into a stable graph and activity feed. It must answer what
happened, who or which session produced it, which contract governed it, and why
the Run is or is not ready for its next action.

## Goals

- Project Run artifacts into stable nodes and typed edges on the server.
- Expose append-only repository lifecycle events in sequence order.
- Let users filter the trace by acceptance criterion and inspect exact entities.
- Preserve a compact timeline in a narrow side panel and a relationship graph
  when the panel has room.
- Reuse the action-rail blocker contract as current trace gaps.
- Establish the event/entity contract later used by Recovery and Realtime.

## Non-goals

- Editing the Spec, Plan, mission graph, evidence, or deviations in the trace.
- Replacing repository YAML with a graph database.
- Realtime delivery, collaborator presence, comments, or retry actions.
- Reconstructing provider-private prompts or hidden chain-of-thought.

## User flows and states

- Overview remains the default Run workspace and action rail.
- Trace shows lifecycle events and contract relationships.
- Selecting an AC filters nodes/edges to its Spec, owner missions, evidence,
  deviations, and related events.
- Selecting a node opens an inspector with hashes, status, actor, timestamps,
  source IDs, and summaries already authorized in Run detail.
- Missing or legacy event references remain visible as lifecycle events; the
  graph is still derived from the durable artifacts.
- Empty, loading, repository-unavailable, and stale-generation states are
  explicit and recoverable.

## Requirements and acceptance criteria

- **AC-1:** `GET /api/easd/runs/{id}/trace` returns a versioned projection with
  Run generation, stable nodes, typed edges, ordered events, and current gaps.
- **AC-2:** Nodes cover Run, Spec revisions, Plan revisions, acceptance
  criteria, missions/attempts, evidence, deviations, and convergence when they
  exist.
- **AC-3:** Edges express Run containment, Spec criteria, Spec→Plan binding,
  Plan/mission ownership, mission dependencies, mission/evidence production,
  evidence/criterion coverage, and deviation/criterion impact.
- **AC-4:** Event reading is bounded, sequence ordered, and ignores malformed
  event documents without hiding valid siblings.
- **AC-5:** Every node and edge is derived from repository/DB artifacts already
  authorized by the Run; the projection grants no new filesystem scope.
- **AC-6:** Current action-rail blockers appear as trace gaps with the same
  codes and entity references.
- **AC-7:** The frontend provides Overview and Trace views without replacing
  TanStack Query as server-state authority.
- **AC-8:** Narrow layout renders an activity-first trace; wider layout adds a
  relationship map and entity inspector without horizontal overflow.
- **AC-9:** AC filtering produces a coherent subgraph and never changes Run
  state.
- **AC-10:** Legacy Runs with minimal events still produce a useful artifact
  graph; unavailable repository events degrade to a diagnostic, not a failed
  Run detail.
- **AC-11:** API/service/component tests cover direct/planned paths, empty and
  malformed events, AC filtering, blockers, and responsive presentation.
- **AC-12:** Feature, architecture, API reference, localized Help, and the
  sampleproject audit describe the implemented behavior and remaining gaps.

## API, event, tool, and UI contracts

```text
GET /api/easd/runs/{run_id}/trace

{
  version: 1,
  run_id,
  store_generation,
  nodes: [{ id, kind, label, status?, timestamp?, entity_id?, data }],
  edges: [{ id, kind, source, target, criterion_ids[] }],
  events: [{ id, sequence, event, actor?, created_at?, from_status?,
             to_status?, entity_refs[], data }],
  gaps: [{ code, message, action_id?, criterion_id?, mission_id?,
           deviation_id?, status?, commands? }],
  diagnostics: [{ code, message }]
}
```

Stable node IDs use `<kind>:<entity identity>`. Edge IDs use their kind and
endpoints. Event payloads remain bounded and exclude repository document hashes
from the generic `data` map when those hashes already have typed fields.

## Data model, migration, and retention

No database migration. Repository YAML remains normative. The trace is a
deterministic read projection and events retain their current append-only files.

## Permissions, security, privacy, and trust

The endpoint first resolves the authorized Run. It reads only that Run's
registered repository directory and returns fields already present in Run
detail or its bounded event documents. It never exposes hidden model reasoning,
credentials, arbitrary files, or broader repository paths.

## Concurrency, failure, recovery, and idempotency

Trace reads are side-effect free. `store_generation` lets later realtime and
recovery actions detect staleness. Malformed event siblings become diagnostics.
If repository events are unavailable, artifact nodes/edges remain available
from the local projection and the response records the degradation.

## Observability and diagnostics

Repository read failures use bounded diagnostic codes. The endpoint does not
add run IDs to metrics. Focused logs record node/edge/event counts and degraded
reads.

## Compatibility, rollout, and rollback

The endpoint and UI tab are additive. Existing Run detail and polling remain
unchanged. Removing the Trace tab leaves lifecycle behavior untouched.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1–6, AC-10 | repository-store, trace-service, and API tests |
| AC-7–9 | frontend query and panel component tests |
| AC-11 | focused backend/frontend quality gates |
| AC-12 | docs/Help updates and live sampleproject narrow/maximized audit |

## Ownership and source map

- Store/event reads: `app/services/easd_repository_store.py`
- Trace projection: `app/services/trace_service.py`
- API schema/route: `app/api/schemas/easd.py`, `app/api/routes/easd.py`
- Client/query: `web/src/api/`, `web/src/queries/`
- UI: `web/src/components/easd/`, `web/src/components/EvoAgentSpecsPanel.tsx`
- Tests: `tests/services/`, `tests/api/routes/`, `web/src/__tests__/`
- Docs/Help: `documents/`, `web/src/help/locales/`
