# EASD realtime and collaboration

Status: implemented

## Problem and outcome

Active EASD Run detail currently polls every 2.5 seconds. Repository events are
durable but the browser cannot subscribe, reconnect from a known sequence, or
see that another window is viewing the same Run. Polling delays mission/evidence
updates and cannot explain stale collaboration conflicts.

The outcome is one Run-scoped SSE feed that replays repository events, delivers
new post-commit events, reports ephemeral presence, and invalidates the existing
TanStack Query projections without creating a second durable client store.

## Goals

- Replay events after the client's last sequence and then stream live events.
- Register the live subscriber before replay so no event is lost at the seam.
- Deduplicate replay/live overlap by sequence on the client.
- Publish lifecycle, artifact, mission, evidence, deviation, and recovery events
  only after their repository write succeeds.
- Show connection state and viewer count in the Run header.
- Refresh detail, trace, recovery, and Run lists surgically through query keys.
- Preserve repository generation/CAS conflict UX.

## Non-goals

- Collaborative Spec/Plan text editing, comments, cursor sharing, or CRDTs.
- Remote cloud transport between different EvoFlux hosts.
- Persisting presence in repository or database state.
- Replacing the repository event ledger with the in-memory broker.

## User flows and states

- Opening a Run connects with a stable client ID and last observed sequence.
- The server replays newer repository events, then sends live events.
- A second window updates viewer count in both windows.
- Disconnect changes the indicator to reconnecting; reconnect resumes after the
  last sequence and does not duplicate activity.
- Queue overflow sends `easd_resync_required`; the client invalidates all Run
  queries and resumes from the durable repository ledger.
- A stale recovery or lifecycle write still returns `409`; realtime refresh
  helps the user see the newer state but never silently overwrites it.

## Requirements and acceptance criteria

- **AC-1:** `GET /runs/{id}/stream` authorizes the Run and emits SSE replay for
  events with `sequence > after_sequence`.
- **AC-2:** Subscriber registration precedes repository replay and the client
  deduplicates overlap by monotonically increasing sequence.
- **AC-3:** Post-commit lifecycle/artifact/recovery events publish to every live
  subscriber for that Run only.
- **AC-4:** Reconnect uses the last sequence and missed events are replayed from
  repository YAML.
- **AC-5:** Presence join/leave is ephemeral, scoped to one Run, and exposes no
  identity beyond the random client ID and count.
- **AC-6:** Slow-client overflow produces a resync event rather than unbounded
  memory growth.
- **AC-7:** TanStack Query remains the durable frontend authority; SSE only
  invalidates existing detail/trace/recovery/list keys.
- **AC-8:** Run header displays connecting, live viewer count, and reconnecting
  states accessibly.
- **AC-9:** The 2.5-second EASD polling loop is removed after SSE integration.
- **AC-10:** Stale repository generation continues to fail with `409` and no
  optimistic client state overrides it.
- **AC-11:** Tests cover broker isolation, replay filtering, presence,
  deduplication, resync, reconnect, and query invalidation.
- **AC-12:** Docs/Help and a multi-window/reconnect sampleproject audit match
  implemented behavior.

## API, event, tool, and UI contracts

```text
GET /api/easd/runs/{id}/stream?after_sequence=7&client_id=<uuid>

event: easd_event
data: { type, run_id, sequence, repository_generation?, event }

event: easd_presence
data: { type, run_id, client_ids[], count }

event: easd_resync_required
data: { type, run_id, reason }
```

Keepalive events carry no product state.

## Data model, migration, and retention

No migration. Event YAML remains durable. Broker queues and presence are
bounded in-memory state discarded on process restart; reconnect replay rebuilds
the client view from repository files.

## Permissions, security, privacy, and trust

The stream resolves the authorized Run before opening and reads only its event
ledger. Presence IDs are random per UI instance and have no account/session
meaning. The endpoint exposes no credentials or hidden model reasoning.

## Concurrency, failure, recovery, and idempotency

Each client tracks the highest sequence. Duplicate or older delivery is ignored.
Queue size is bounded; overflow forces durable resync. Repository CAS and
recovery idempotency remain the mutation controls.

## Observability and diagnostics

Logs report connection/disconnection, replay count, and overflow without client
or Run IDs as metric labels. Keepalive prevents idle intermediary timeouts.

## Compatibility, rollout, and rollback

The endpoint is additive. Clients without SSE continue using explicit query
refresh; restoring polling is a client-only rollback.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1–6 | broker, repository sync, and route tests |
| AC-7–10 | realtime hook and panel tests |
| AC-11 | focused backend/frontend gates |
| AC-12 | docs/Help and sampleproject two-client audit |

## Ownership and source map

- Broker: `app/services/easd_event_stream.py`
- Publishers: `app/services/easd_repository_sync.py`
- SSE route: `app/api/routes/easd.py`
- Client/hook: `web/src/api/client/easd.ts`, `web/src/queries/`
- UI: `web/src/components/EvoAgentSpecsPanel.tsx`
- Tests/docs: `tests/`, `documents/`, `web/src/help/locales/`
