---
name: coding-implementation
description: Use this skill for a focused feature or bug-fix implementation whose desired behavior is sufficiently clear and whose contracts, tests, or consumers span more than a trivial edit. It coordinates a minimal repository-native change and evidence-based verification; do not use it for read-only investigation or review, unknown-cause debugging, or staged compatibility migrations.
---

# Implement a focused code change

Deliver the smallest coherent change that satisfies the observable contract.
Preserve unrelated user work and avoid architecture that the requirement does
not demand.
Do not load bundled references when this skill activates.

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

When the owning location or exact identifier is unknown, call `code_context` with `action="search"`
once with the observable behavior, stable literal, or code terms. Promote a
repository-qualified result to a declared symbol, then stop broad discovery.
If the exact changed symbol is already known, skip `code_context` with `action="search"`.

Use `code_context` on the exact changed symbol before editing:
`references` or `callers` to enumerate direct consumers, `callees` to confirm
outbound dependencies, and `impact` only for explicitly transitive risk. Start
at depth 1 and keep repository identity on cross-repository edges. Do not send
the feature request itself as a graph symbol.

Once the contract identifies an exact changed symbol, make the graph the next
structural observation. Do not continue broad discovery or reread source
returned by the graph before choosing the owning edit boundary.

Keep `refresh=true` for the first indexed query and after edits. Use `refresh=false` only for an immediate follow-up that intentionally reuses the same index version.

Read [references/code-context-contract.md](references/code-context-contract.md)
only when the result is ambiguous, stale, truncated, cross-repository, or
mixed with dynamic wiring.

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
the implementation. Re-run the smallest relevant graph query when the edit
changes a public symbol boundary, and compare the post-change consumer set to
the established contract.

## Deliverable

Lead with the observable result. Summarize the contract, key files changed,
checks actually run, and any remaining verification gap. Do not narrate every
edit or claim success from inspection alone.
