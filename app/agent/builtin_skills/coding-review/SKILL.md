---
name: coding-review
description: Use this skill for a read-only audit of a local diff or supplied implementation to find production-impacting correctness, data-loss, authorization, concurrency, compatibility, resilience, performance, and test defects. Report only actionable findings with concrete triggers; do not use it to implement requested changes or manage a remote pull-request lifecycle.
---

# Review a code change

Remain read-only unless the user separately authorizes fixes. Optimize for
defects that change production behavior, not commentary volume.

## Establish intent and scope

1. Determine the intended contract from the request, specification, tests, and
   existing behavior.
2. Inspect the complete diff, including generated/configuration changes, then
   read enough surrounding code to understand every changed state transition
   and public boundary.
3. Trace affected producers, callers, consumers, persistence, asynchronous
   work, and independently deployed dependents where behavior can propagate.

For exact changed symbols, use native `code_graph` to verify direct
`callers`/`references`, outbound `callees`, and bounded `impact` rather than
guessing propagation from filenames. Start at depth 1, disambiguate duplicate
definitions, preserve repository labels, and reuse returned call-site source.
Read [references/code-graph-contract.md](references/code-graph-contract.md)
when graph freshness, dirty files, pending cross-repository edges, dynamic
wiring, or truncation limits review coverage.

## Review by risk

Check in this order:

1. Incorrect result, lost or duplicated data, invalid state transition
2. Authorization, tenant isolation, unsafe input, and secret exposure
3. Concurrency, cancellation, retry, idempotency, and partial failure
4. API, schema, serialization, configuration, and rollout compatibility
5. Resource exhaustion, latency regression, and unbounded work
6. Missing tests for changed behavior and failure modes

Construct a concrete input, state sequence, or deployment pairing for each
candidate finding. Reject style preferences, speculative hypotheticals with no
reachable path, and issues unchanged by the diff.

Read [references/finding-contract.md](references/finding-contract.md) before
reporting findings, when assigning severity, or when several observations may
share one root cause.

## Validate findings

Use narrow, non-mutating checks when they materially increase confidence.
Confirm exact line anchors against the final working diff. Deduplicate symptoms
that one fix would resolve, and separate an unverified risk from a demonstrated
defect.

## Deliverable

Order findings by severity. Each finding must state trigger, impact, causal
code path, exact location, and concrete fix direction. If no actionable defect
remains, say so and list verification gaps separately. Do not pad the review
with praise, summaries of the diff, or low-value nits.
