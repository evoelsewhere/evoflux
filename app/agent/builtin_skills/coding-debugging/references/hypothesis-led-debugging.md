# Hypothesis-led debugging

Read this reference when the failure is intermittent, crosses a boundary, or
has more than two credible causes.

## Hypothesis ledger

| Hypothesis | Predicted observation | Cheapest disproof | Result | Status |
| --- | --- | --- | --- | --- |
| Exact causal claim | What must be true if it is causal | One controlled check | Evidence, not interpretation | open / rejected / supported |

Never list a component name as a hypothesis. “The cache” is a location;
“a stale cache entry survives tenant reassignment because invalidation uses the
old key” is falsifiable.

## Useful failure classes

- Contract: caller and callee disagree on inputs, outputs, or error semantics.
- State: an invalid transition, stale value, or missing initialization occurs.
- Data: shape, encoding, unit, identity, ordering, or persistence is wrong.
- Concurrency: ordering, visibility, cancellation, or ownership is unsafe.
- Integration: protocol, version, retry, timeout, or partial failure differs.
- Environment: configuration, permissions, dependency, clock, or build mode
  differs from the known-good case.
- Presentation: underlying state is correct but rendering or serialization is
  not.

## Causal proof

A root-cause claim is strong when it explains the first bad state, predicts the
observed variation, is contradicted by no collected evidence, and disappears
when the owning invariant is restored. Correlation with a changed line or a
passing retry is insufficient.
