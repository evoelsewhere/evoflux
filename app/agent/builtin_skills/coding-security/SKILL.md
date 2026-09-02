---
name: coding-security
description: Use this skill to audit or harden a concrete code path involving trust boundaries, attacker-controlled input, authentication, authorization, tenant isolation, secrets, unsafe parsing, injection, external requests, or supply-chain-sensitive execution. It requires a reachable abuse case and invariant-level remediation; do not use it for generic quality review with no security boundary.
---

# Secure a code path

Model the reachable attacker and protected operation before enumerating
vulnerability categories. Never treat a dangerous-looking primitive as an
exploit without tracing control and impact.
Do not load bundled references when this skill activates.

## Establish the security boundary

1. Identify assets, actors, credentials, trust zones, entry points, privilege
   transitions, and the exact operation being protected.
2. Define authorization invariants at the resource and action boundary,
   including object ownership, tenant isolation, role changes, replay, and
   confused-deputy behavior.
3. Trace attacker-controlled data through parsing, normalization, validation,
   policy checks, persistence, rendering, logging, and outbound calls.
4. Read [references/threat-boundary-checklist.md](references/threat-boundary-checklist.md)
   when the path crosses tenants, interpreters, file/network boundaries,
   redirects, deserializers, privileged workers, or third-party dependencies.

When the source, sink, or policy boundary is known only by behavior, route,
error, field, or API text, call `code_context` with `action="search"` once to locate its declared
identifier. Skip search when exact source identifiers are already known.

Use `code_context` on exact identifiers to bound the
trust path: `callers` for reachable entry sites, `callees` for sensitive sinks,
`references` for registration or callback wiring, and `impact` for upstream
exposure. Start at depth 1. Static relationships support reachability analysis
but never replace runtime authorization, data-flow, or exploit evidence.
Once the boundary exposes an exact source and sink relationship, make the graph
the next structural observation instead of continuing broad grep.

Keep `refresh=true` for the first indexed query and after edits. Use `refresh=false` only for an immediate follow-up that intentionally reuses the same index version.

Read [references/code-context-contract.md](references/code-context-contract.md) for
ambiguity, cross-repository limits, and dynamic-wiring fallbacks only after the
graph reports such a gap.

## Prove findings

For each candidate issue, establish:

- attacker capability and required preconditions;
- exact source-to-sink or authorization path;
- input or state sequence that violates an invariant;
- confidentiality, integrity, availability, or privilege impact;
- existing controls and why they do not block the path.

Check injection, traversal, unsafe parsing, request forgery, cross-site output,
secret exposure, cryptographic misuse, dependency execution, denial of
service, race conditions, and fail-open behavior only where the boundary makes
them relevant.

Assign severity from reachability, privilege, blast radius, persistence, and
recoverability—not from the vulnerability label alone. Avoid live secrets and
destructive exploitation against real systems.

## Remediate when authorized

Restore the invariant at the narrowest owning boundary. Prefer allowlists,
parameterization, established parsers, resource-level authorization, bounded
work, and vetted cryptographic primitives. Do not invent sanitizers or custom
cryptography.

Add negative tests for bypasses and adjacent tenants/resources. Verify secure
failure behavior, auditability, and any required key rotation, data cleanup,
configuration change, or deployment sequence.

For dependency-execution risk, identify the actual lockfile/installation
boundary first, block install scripts before their first run, and avoid
blanket auto-remediation (e.g. force-installing a major version bump) that
trades a known vulnerability for unreviewed breakage.

## Execution discipline and threat stop

Select one reachable attacker-to-operation boundary before enumerating checks.
Batch independent source/sink graph queries and reads. Use `code_context`,
`read`, `grep`, and `glob` for source; do not use shell `cat`, `sed`, `head`,
`tail`, `nl`, `rg`, or `find` to reread source or bypass an observation receipt.
Reserve shell for bounded negative tests, formatter, lint, build, dependency
audit, and runtime checks. Await long commands with
`process(action="wait", wait_seconds=60)`.

Stop expanding when reachability, control failure, and impact are either proven
or one named dynamic boundary remains. After the invariant fix and negative
tests pass, stop; do not sweep unrelated vulnerability categories. A failed
check reopens only the source, control, or sink named by its evidence.

## Deliverable

Report scope and threat model, proven findings with severity and evidence,
invariant-level fixes, negative regression coverage, and residual or
operational risk. If no reachable issue is found, state the examined boundary
and remaining verification gaps.
