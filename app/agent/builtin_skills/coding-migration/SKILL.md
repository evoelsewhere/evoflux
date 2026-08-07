---
name: coding-migration
description: Use this skill for compatibility-sensitive transitions across APIs, schemas, storage, frameworks, packages, modules, deployments, or repositories when old and new contracts must coexist or rollout order matters. It defines staged change, verification, rollback, and cleanup; do not use it for an atomic internal refactor or a focused feature that can ship in one compatible change.
---

# Migrate a code system

Make each migration stage independently deployable, observable, and
reversible until evidence proves the old path can be removed.

## Inventory the transition

1. Identify current and target contracts, producers, consumers, persisted data,
   deployment units, generated artifacts, and ownership boundaries.
2. Determine which components can upgrade atomically and which cannot. Include
   older clients, delayed jobs, replayed events, rollback versions, and data
   written during the compatibility window.
3. Define invariants that must hold in mixed-version operation.
4. Read [references/expand-contract-playbook.md](references/expand-contract-playbook.md)
   for a compatibility matrix and phase gates when the transition spans
   deployments, stored data, or multiple repositories.

## Choose and sequence a strategy

Select the smallest safe strategy: expand/contract, adapter, dual read, dual
write, backfill, feature-gated cutover, shadow traffic, or atomic replacement.
State why its failure modes are acceptable here.

Order work by dependency:

1. Add backward-compatible producer or reader capability.
2. Deploy observability and verify mixed-version behavior.
3. Move consumers or traffic in bounded cohorts.
4. Backfill or reconcile persisted state with resumable, idempotent work.
5. Prove no old consumer, writer, or data remains.
6. Remove compatibility code and old observability only at the named cleanup
   gate.

Keep temporary code named, measurable, and attached to a deletion condition.
Never migrate consumers before the compatible provider exists.

## Verify and roll back

Test both directions during coexistence: new producer with old consumer, and
old producer with new consumer where rollback permits that pairing. Verify
partial deployment, duplicate delivery, interrupted backfill, and rollback
after new-format data has been written.

Every irreversible step needs a precondition, owner, evidence source, and stop
condition. A backup is not a rollback plan unless restoration time and data
loss are acceptable.

## Deliverable

Provide affected surfaces, ordered phases, compatibility matrix, verification
gates, telemetry, rollback procedure, and explicit cleanup criteria. Separate
implemented phases from future operational steps.
