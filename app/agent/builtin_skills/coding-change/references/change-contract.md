# Change contract

Read this reference for changes that cross module, persistence, process, API,
or repository boundaries.

## Contract map

Capture only applicable fields:

- Current behavior and new behavior
- Inputs, normalization, validation, and defaults
- Outputs, side effects, ordering, and error semantics
- State ownership, persistence, idempotency, and retry behavior
- Producers, direct consumers, and independently deployed consumers
- Compatibility expectation and rollback behavior
- Observability needed to distinguish success from partial failure
- Proof: regression test, contract test, integration path, or runtime check

## Boundary rules

- Change one owner, then adapt callers; do not duplicate policy across layers.
- Preserve a public default unless the requirement explicitly changes it.
- Treat serialization, database schema, events, queues, and configuration as
  public contracts even when their code is private.
- For asynchronous work, define cancellation, duplicate delivery, and partial
  completion behavior.
- For UI work, verify loading, empty, success, failure, and stale-state paths
  when they are affected.

Escalate to a staged migration when consumer upgrades cannot be atomic or
persisted data must remain readable across versions.
