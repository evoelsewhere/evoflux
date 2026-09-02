---
name: coding-api-design
description: Use this skill to design or change a public API, event, schema, module boundary, or write path with an idempotency requirement — endpoint shape, status/error semantics, versioning, or a discriminated-union contract. It treats every observable field as a durable consumer contract and requires an explicit success/failure/unknown outcome model; do not use it for an internal-only change with no external or independently-deployed consumer, or once the contract shape is already decided and only the implementation remains.
---

# Design an API or interface contract

Every observable field, status code, ordering guarantee, and error shape
becomes part of the contract the moment a consumer depends on it (Hyrum's
Law): design as if it will be relied upon exactly as built, not only as
documented.
Do not load bundled references when this skill activates.

## Establish the boundary and its consumers

1. Identify the producer, every current consumer, and which ones deploy
   independently of it. A consumer that cannot upgrade atomically with the
   producer makes this a compatibility change, not a free-form redesign.
2. Separate what is already observable (and therefore load-bearing) from what
   is still a private implementation detail with room to change.
3. Define the three outcomes for every operation — success, failure, and
   unknown (timeout, partial write, disconnected client) — and what a caller
   must do for the unknown case specifically, not only the first two.
4. Read [references/api-contract-checklist.md](references/api-contract-checklist.md)
   when choosing an HTTP status/error shape, a discriminated-union variant, an
   idempotency-key design, or a versioning strategy.

When the existing boundary is known only by route, event name, field, or error
text, call `code_context` with `action="search"` once to find its declared
symbol. Skip search when the exact type or handler is already known.

For an exact endpoint, schema, or type symbol, use `code_context` to find
direct `callers`/`references` — every consumer that already depends on its
current shape — before changing it. Start at depth 1; treat an unresolved
cross-repository reference as an unknown consumer, not as evidence none
exists. Once the boundary and its consumers are located, make the graph the
next structural observation instead of continuing broad discovery.

Keep `refresh=true` for the first indexed query and after edits. Use
`refresh=false` only for an immediate follow-up that intentionally reuses the
same index version.

Read [references/code-context-contract.md](references/code-context-contract.md)
only after a result exposes ambiguity, cross-repository scope, or another
static fallback gap.

## Shape the contract

Choose names, defaults, and error semantics that stay correct under future
extension: additive fields over overloaded ones, an explicit enum/discriminant
over an inferred shape, and one canonical error taxonomy over ad hoc strings.
Prefer one supported way to do a thing over two equivalent ones (the
one-version rule) to avoid diamond-dependency drift for consumers who must
pick between them.

For a write a caller may retry or duplicate, derive the idempotency key from
caller intent, not the attempt — the same logical request must produce the
same key across retries. Claim it atomically through a unique constraint or
equivalent, never check-then-insert. Reject a reused key carrying a different
payload, and decide explicitly what happens to a second request that arrives
while the first is still in flight: reject, wait, or return an in-progress
status.

## Verify against real consumers

Confirm the shape against every located caller, not only the one being added:
does an existing consumer's parsing, default handling, or error matching still
hold? For a breaking change, confirm a compatibility or migration path exists
before this boundary changes (switch to a migration workflow when old and new
must coexist across a rollout).

## Execution discipline and design stop

Locate the boundary and its consumers once; batch independent graph queries
and reads. Use `code_context`, `read`, `grep`, and `glob` for source; do not
use shell `cat`, `sed`, `head`, `tail`, `nl`, `rg`, or `find` to reread source
or bypass an observation receipt. Reserve shell for formatter, lint/type,
build, and verification commands.

Stop once the contract, its outcome model, and its consumer impact are stated
and any required compatibility path is named. Do not implement beyond what is
needed to prove the shape, and do not redesign an adjacent contract the
request did not name.

## Deliverable

State the contract (fields, status/error shape, idempotency behavior), the
consumers it affects, the compatibility or migration requirement if any, and
what remains unverified until implementation lands.
