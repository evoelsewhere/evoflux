---
name: coding-implementation
description: Use this skill for a focused feature or bug-fix implementation whose desired behavior is sufficiently clear and whose contracts, tests, or consumers span more than a trivial edit. It coordinates a minimal repository-native change and evidence-based verification; do not use it for read-only investigation or review, unknown-cause debugging, or staged compatibility migrations.
---

# Implement a focused code change

Deliver the smallest coherent change that satisfies the observable contract.
Preserve unrelated user work and avoid architecture that the requirement does
not demand.

## Establish the change contract

1. Read repository instructions, owning modules, nearby tests, and the existing
   behavior before editing.
2. State the changed observable behavior and unchanged invariants. Cover input,
   output, error behavior, persistence, compatibility, and user-visible state
   only where relevant.
3. Identify producers, consumers, public types, configuration, generated
   artifacts, and cross-repository dependents that could invalidate a local
   edit.
4. Read [references/change-contract.md](references/change-contract.md) when the
   change crosses a public boundary, touches persistence, alters asynchronous
   state, or affects more than one independently deployed consumer.

## Implement

1. Choose the narrowest owning boundary and reuse established abstractions.
2. Make the behavior change and its regression coverage in one coherent slice.
3. Keep compatibility code explicit and temporary; if old and new behavior
   must coexist across releases, switch to a migration workflow.
4. Handle failure at the layer that can enforce the contract. Do not hide
   invalid state with broad fallback behavior.
5. Update documentation, types, fixtures, generated artifacts, or telemetry
   only when the changed contract requires them.

## Verify in layers

Run the fastest check that can fail on the touched behavior, then the affected
test, lint, type, and build surfaces in proportion to risk. Exercise the actual
runtime or visible UI path when static checks cannot prove the outcome. Treat a
command that was not run, was skipped, or failed as unverified.

Before finishing, inspect the final diff for accidental scope, stale names,
debug output, unreachable compatibility branches, and tests that only mirror
the implementation.

## Deliverable

Lead with the observable result. Summarize the contract, key files changed,
checks actually run, and any remaining verification gap. Do not narrate every
edit or claim success from inspection alone.
