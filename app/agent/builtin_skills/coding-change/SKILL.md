---
name: coding-change
description: Use this skill to change code under a stated contract — implement a focused feature or bug fix whose desired behavior is clear, refactor existing code for clarity without changing observable behavior, stage a compatibility-sensitive transition where old and new contracts must coexist, or design a public API, event, schema, module boundary, or idempotent write contract. It requires a minimal repository-native change and evidence-based verification; do not use it for read-only investigation, unknown-cause debugging, or auditing a change someone else wrote.
---

# Change code under a contract

This skill owns the mutating posture: the observable contract is decided (or is
being decided here), and the job is the smallest coherent change that satisfies
it with proof. It routes to one focused workflow; the workflow body is the
authoritative contract for that work.

## Route the request

Pick the narrowest match, then read that workflow file completely before
acting. Do not read a workflow you did not select.

| Evidence in the request | Workflow |
| --- | --- |
| Desired behavior is clear and the change spans more than a trivial edit | `references/workflows/implement.md` |
| Observable behavior must stay identical; the problem is clarity, nesting, naming, or duplication | `references/workflows/simplify.md` |
| Old and new contracts must coexist across releases, deploys, or clients, or rollout order matters | `references/workflows/migrate.md` |
| The contract shape itself is undecided for a public API, event, schema, module boundary, or idempotent write | `references/workflows/api-design.md` |

Read a workflow with `skill(action="read_resource")` using the path exactly as
written above; resource paths are relative to this skill directory.

Routing notes that decide close cases:

- Coexistence is the migration test, not size. A three-service rename that can
  ship atomically is implementation; a one-field rename that old mobile clients
  must survive is migration.
- Contract design stops at the decided shape. Once the endpoint, error codes,
  and idempotency model are settled, continue in `implement.md` — do not stay
  in `api-design.md` to write the handler.
- Simplification refuses behavior change. The moment a fix or new behavior is
  required, it is `implement.md`, even if the code is also messy.
- Contract design may precede any of the other three. When it does, run it
  first and then re-enter this table once.

## Shared discipline

`references/code-context-contract.md` is the indexed-code contract for every
workflow here. Read it only on ambiguity, truncation, stale index data,
cross-repository edges, or dynamic wiring — not preemptively.

`references/change-contract.md` applies to any workflow whose change crosses a
public, persistence, process, or repository boundary.

These limits bind every workflow here and are not repeated in the workflow
bodies, which state only what they reserve shell for and where they stop.

- Discover source with `code_context`, `read`, `grep`, and `glob`; never with
  shell `cat`, `sed`, `head`, `tail`, `nl`, `rg`, or `find`. A revision-aware
  covered-range receipt is authoritative — read again only after an edit changed
  that source or the range is not covered.
- `refresh=true` for the first indexed query and after edits; `refresh=false`
  only for an immediate follow-up reusing the same index version.
- Batch independent graph queries and reads in one turn; graph and `read`
  results already carry source and line numbers.
- On a process handle, use one `process(action="wait", wait_seconds=60)` rather
  than repeated short polls.
- Reuse existing abstractions and preserve public defaults; do not add
  architecture the requirement does not demand.
- Verification is proportional and actually run. Treat a skipped command as
  unverified and never claim success from inspection alone.
- Preserve unrelated user work. Name any adjacent issue noticed and left
  untouched instead of silently fixing it.

## Do not use this skill for

- Understanding code, diagnosing an unknown cause, or reproducing a browser
  defect — use `coding-investigate`.
- Auditing a diff, designing a test strategy, or a security review — use
  `coding-verify`.
- Measured performance work, telemetry design, or commit/PR structuring — use
  `coding-operate`.
