# API contract checklist

Read this reference when shaping status/error semantics, a discriminated
union, an idempotency-key design, or a versioning strategy.

## Status and error shape

| Situation | Prefer |
| --- | --- |
| Caller error (bad input, missing auth, not found) | A specific 4xx with a stable machine-readable error code, not just a message |
| Server fault | 5xx; never reuse it for a caller-fixable condition |
| Partial success | An explicit per-item result, not a single aggregate status |
| Async accepted work | 202 plus a way to poll or receive completion, not a bare 200 |

Keep one canonical error code taxonomy per contract; do not let each endpoint
invent its own strings for the same condition.

## Discriminated unions over inferred shape

Give every variant an explicit, stable discriminant field instead of asking
the consumer to infer the type from which optional fields are present.
Reserve an `unknown`/default arm so a future variant does not silently fall
through to today's default branch.

## Versioning as a promise

A version number is a promise to consumers, not a commit counter: a "patch"
that changes observed behavior is a major change in disguise once a consumer
depends on the old behavior (Hyrum's Law). Prefer additive, backward-compatible
change within a version; require an explicit migration path before a breaking
one ships.

## Idempotency-key mechanics

- Derive the key from the caller's intent (the logical request), not from the
  attempt — a retried request must carry the same key as the original.
- Claim the key atomically via a unique constraint or equivalent; check-then-insert
  has a race window that a concurrent retry can exploit.
- Reject a reused key whose payload differs from the first use.
- Decide explicitly what a request does when its key is already in flight:
  reject, block until resolved, or return the in-progress state — do not leave
  this undefined.
