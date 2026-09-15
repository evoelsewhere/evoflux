---
name: coding-verify
description: Use this skill to establish that code is correct without being the one to change it — audit a local diff or supplied implementation for production-impacting correctness, data-loss, concurrency, compatibility, and resilience defects; audit or harden a concrete trust boundary involving attacker-controlled input, authentication, authorization, tenant isolation, secrets, or injection; or design and repair a test strategy around observable contracts, failure modes, flakes, and integration boundaries. Do not use it to implement the changes it asks for, or to manage a remote pull-request lifecycle.
---

# Verify code correctness

This skill owns the adversarial posture: assume the code is wrong and find out
where. It routes to one focused workflow; the workflow body is the
authoritative contract for that work.

## Route the request

Pick the narrowest match, then read that workflow file completely before
acting. Do not read a workflow you did not select.

| Evidence in the request | Workflow |
| --- | --- |
| An existing diff or supplied implementation needs a read-only defect audit | `references/workflows/review.md` |
| A trust boundary, attacker-controlled input, authorization, tenant isolation, secret, or injection path is in scope | `references/workflows/security.md` |
| Coverage itself is the deliverable — test level, failure modes, flakes, nondeterminism, or cross-version proof | `references/workflows/test.md` |

Read a workflow with `skill(action="read_resource")` using the path exactly as
written above; resource paths are relative to this skill directory.

Routing notes that decide close cases:

- A security boundary must be named to choose `security.md`. "Review this
  formatting helper for bugs" is `review.md`; "can another tenant read this
  export" is `security.md`.
- A correctness symptom alone does not make a security task, and a 500 after
  login is debugging, not review.
- `test.md` is for deciding what proof is owed and at which level. Running one
  already-written test command needs no workflow at all.
- Review and security both stop at findings. If the user's primary request
  authorizes the fixes, that work belongs in `coding-change`.

## Shared discipline

`references/code-context-contract.md` is the indexed-code contract for every
workflow here. Read it only on ambiguity, truncation, stale index data,
cross-repository edges, or dynamic wiring — not preemptively.

`references/finding-contract.md` defines how a reported defect must be stated.
It applies to `review.md` and `security.md` alike.

Every workflow in this skill shares these limits:

- Use `code_context`, `read`, `grep`, and `glob` for source discovery. Do not
  use shell `cat`, `sed`, `head`, `tail`, `nl`, `rg`, or `find` to reread source
  or bypass an observation receipt.
- Report only actionable findings with a concrete trigger and a file/line
  anchor. Severity requires reachability, not category.
- Do not pad the report once the candidate defects are resolved, and do not
  sweep for unrelated issues outside the requested scope.
- Weakening an assertion until a suite passes is never a valid outcome.

## Do not use this skill for

- Understanding code or diagnosing an unknown-cause failure — use
  `coding-investigate`.
- Implementing the fixes, refactoring, or staging a migration — use
  `coding-change`.
- Measured performance work or telemetry design — use `coding-operate`.
- Reviewing, commenting on, or merging a remote pull/merge request — use
  `review-pull-requests`.
