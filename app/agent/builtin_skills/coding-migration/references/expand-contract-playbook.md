# Expand-contract playbook

Read this reference when versions coexist, data formats change, or deployments
span repositories.

## Compatibility matrix

| Producer | Consumer | Must work? | Proof | Rollback implication |
| --- | --- | --- | --- | --- |
| old | old | yes until retirement | current baseline | none |
| new | old | usually yes during expansion | contract/integration test | required for provider-first rollout |
| old | new | yes when new consumer may roll back or deploy first | contract/integration test | required for consumer rollback |
| new | new | yes | target-path test | final state |

Add rows for persisted old/new records, cached values, events in flight, and
replayed messages.

## Phase gate contract

For each phase record:

- deployable change and owning repository;
- prerequisite version or data state;
- invariant preserved in mixed operation;
- telemetry and expected threshold;
- pause and rollback condition;
- irreversible action, if any;
- proof required before the next phase;
- deletion condition for temporary code.

## Backfill rules

Make backfills resumable, idempotent, rate-limited, and observable. Define the
source of truth during execution, reconciliation for concurrent writes, poison
record handling, and a count or checksum proving completion. Never infer
completion solely from the worker exiting successfully.
