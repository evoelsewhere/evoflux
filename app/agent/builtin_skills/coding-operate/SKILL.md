---
name: coding-operate
description: Use this skill for the production-facing side of code — diagnose and improve measured latency, throughput, memory, allocation, I/O, query cost, or bundle size against a representative workload; decide what to log, measure, trace, or alert on so a named on-call question becomes answerable; or structure commits, branch lifetime, and pull-request submission for work that is ready to ship. Each path requires a stated baseline, question, or deliverable; do not use it for correctness work with no metric or visibility gap, or to review someone else's pull request.
---

# Operate code in production

This skill owns what happens to a change once correctness is no longer the
question: how fast it runs, whether anyone can see it run, and how it reaches
production. It routes to one focused workflow; the workflow body is the
authoritative contract for that work.

## Route the request

Pick the narrowest match, then read that workflow file completely before
acting. Do not read a workflow you did not select.

| Evidence in the request | Workflow |
| --- | --- |
| A measurable resource cost is the problem — latency, throughput, memory, allocation, I/O, query cost, or bundle size under a workload | `references/workflows/performance.md` |
| Diagnostic visibility is the problem — what to log, measure, trace, correlate, or alert on, and why | `references/workflows/observability.md` |
| Commit granularity, branch lifetime, PR description, or version-number meaning is the problem | `references/workflows/git-workflow.md` |

Read a workflow with `skill(action="read_resource")` using the path exactly as
written above; resource paths are relative to this skill directory.

`git-workflow.md` additionally requires `shell` and, for submission, the
worktree and pull-request tools. If they are not granted in this session, state
that limit instead of describing commands as if they had run.

Routing notes that decide close cases:

- Performance requires a metric and a workload. "This loop looks inefficient"
  has neither and is a `coding-change` simplification at best.
- Observability answers a question nobody can answer yet; performance improves
  a bottleneck already identified. "Which tenant causes this spike" is
  observability; "this query is slow, speed it up" is performance.
- A temporary print statement for a local debugging session is neither — that
  is `coding-investigate`.
- `git-workflow.md` structures the author's own submission. Reviewing,
  commenting on, or merging an existing remote PR belongs to
  `review-pull-requests`.

## Shared discipline

`references/code-context-contract.md` is the indexed-code contract for the
workflows here that read source. Read it only on ambiguity, truncation, stale
index data, cross-repository edges, or dynamic wiring — not preemptively.

These limits bind every workflow here and are not repeated in the workflow
bodies, which state only what they reserve shell for and where they stop.

- Discover source with `code_context`, `read`, `grep`, and `glob`; never with
  shell `cat`, `sed`, `head`, `tail`, `nl`, `rg`, or `find` — `git-workflow.md`
  is the exception, since git is its subject and it drives `shell` directly. A
  revision-aware covered-range receipt is authoritative — read again only after
  an edit changed that source or the range is not covered.
- `refresh=true` for the first indexed query and after edits; `refresh=false`
  only for an immediate follow-up reusing the same index version.
- Batch independent graph queries and reads in one turn; graph and `read`
  results already carry source and line numbers.
- On a process handle, use one `process(action="wait", wait_seconds=60)` rather
  than repeated short polls.
- A claim about production behavior needs an observation, not an inference:
  before/after numbers from the same protocol, an alert seen to fire, or a
  command actually run.
- Add only the signal, optimization, or commit boundary the stated question
  requires. Stop at the target instead of continuing to the next one.
- Never force-push or rewrite shared history without explicit authorization.

## Do not use this skill for

- Understanding code or diagnosing an unknown-cause failure — use
  `coding-investigate`.
- Implementing behavior, refactoring, or staging a migration — use
  `coding-change`.
- Auditing a diff, designing tests, or a security review — use `coding-verify`.
- Inspecting, commenting on, deciding, or merging a remote pull/merge request —
  use `review-pull-requests`.
