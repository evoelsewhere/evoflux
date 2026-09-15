# Source evidence chain

Read this only after evidence confirms a cross-repository boundary, competing
exact roots, or a static path that ends at a dynamic/generated boundary. Do not
load it preemptively for an ordinary multi-file flow.

## Evidence record

For each material step capture:

| Claim | Exact root | Relationship | Condition | Evidence kind | Confidence |
| --- | --- | --- | --- | --- | --- |
| Observable statement | Qualified symbol or key | calls / reads / registers / emits | Branch, flag, state | source / generated / runtime | confirmed / bounded / unknown |

## Resolution order

1. Exact definitions and qualified identity
2. Direct structural relationships
3. Local branch and state semantics
4. Configuration or registration wiring
5. Generated artifacts and build-time substitution
6. Runtime observation for remaining dynamic behavior

For cross-repository paths, keep repository identity on every root and edge.
Package names and matching symbol text do not prove that one repository ships
or invokes another.

## Stop conditions

Stop expanding when the requested entry point, deciding condition, and effect
are all proven. Report a gap instead of inferring across an unobserved dynamic
edge. An impact assessment is bounded by analyzed repositories, languages, and
generated/runtime mechanisms; state those boundaries explicitly.
