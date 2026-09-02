---
name: coding-implementation
description: Use this skill for a focused feature or bug-fix implementation whose desired behavior is sufficiently clear and whose contracts, tests, or consumers span more than a trivial edit. It coordinates a minimal repository-native change and evidence-based verification; do not use it for read-only investigation or review, unknown-cause debugging, or staged compatibility migrations.
---

# Implement a focused code change

Deliver the smallest coherent change that satisfies the observable contract.
Preserve unrelated user work and avoid architecture that the requirement does
not demand. A focused change is one work lane; do not create a todo unless the
request contains independent deliverables.

Use the following phases in order. Leaving a phase requires its exit criterion;
after leaving it, do not return to broad discovery unless a compiler, test, or
runtime result names a concrete missing fact. These are efficiency boundaries,
not correctness limits: when a real gap remains, name it and continue narrowly.

## Phase 1 — Lock the contract and owner

In one batched model turn, inspect only applicable repository instructions, the
owning source, and the nearest existing regression seam. Do not read general
README, manifests, architecture, or unrelated tests unless they determine a
required command or contract.

- State the changed observable behavior and the invariants that stay unchanged.
- If the owner is unknown, call `code_context(action="search")` once using the
  stable behavior or literal. In a multi-repository workspace omit repository,
  path, and language filters until evidence identifies the owner.
- If an exact changed symbol is known, skip search and call the smallest graph
  action (`references`, `callers`, or `callees`) immediately. Use `impact` only
  for explicitly transitive risk and start at depth 1.
- Keep repository identity. Ordinary file tools require the displayed absolute
  path for a non-primary repository.
- Batch independent graph queries and source reads in one model turn. Graph and
  `read` results already contain source and line numbers; reuse them.

Keep `refresh=true` for the first indexed query and after edits. Use
`refresh=false` only for an immediate follow-up that intentionally reuses the
same index version.

Choose the regression seam with one bounded search/read pass. Reuse the closest
fixture or public API already observed. If no seam exists, create the smallest
new focused test and let compiler diagnostics reveal exact missing fields; do
not survey multiple unrelated test suites first.

**Exit criterion:** one owning symbol/file, its direct affected boundary, and
one regression seam are identified. At that point edit; do not keep proving the
same ownership.

Read [references/change-contract.md](references/change-contract.md) only when
the change crosses a public/persistence/process/repository boundary. Read
[references/code-context-contract.md](references/code-context-contract.md) only
for ambiguity, truncation, stale index data, cross-repository edges, or dynamic
wiring. Do not load either reference preemptively.

## Phase 2 — Implement one coherent slice

Change the narrowest owner and its regression coverage together. Reuse existing
abstractions, preserve public defaults, and handle failure at the layer that can
enforce the contract. Update types, fixtures, generated artifacts, telemetry,
or documentation only when the observable contract requires them. Switch to a
migration workflow if old and new behavior must coexist across releases.

When the change relies on a specific framework or library API whose behavior
at the installed version is uncertain, verify against that dependency's
installed version rather than assumed or memorized behavior before writing
the call.

## Phase 3 — Run the decisive check

Run formatter/diagnostics and the smallest test that exercises the changed
behavior. Batch independent verification commands when safe. Do not start with
the full repository suite. If a command returns a process handle, use one
`process(action="wait", wait_seconds=60)` observation rather than repeated short
polls; wait again only when that result still reports running.

When a command fails:

1. Read the exact diagnostic.
2. Name the single missing fact it exposes.
3. Inspect only the cited symbol/range or one established fixture.
4. Apply one coherent correction and rerun the same command.

Do not reopen whole modules, restart repository discovery, or inspect several
alternative fixtures after the diagnostic already identifies the gap.

## Phase 4 — Expand verification proportionately

After the focused check passes, run only the affected package/surface checks
required by repository guidance and risk: tests, lint/type checks, build, or a
runtime/UI path. Treat skipped or failed commands as unverified. Re-run graph
navigation only if the edit changed a public symbol boundary.

## Phase 5 — Stop and deliver

Inspect the scoped diff once for unrelated edits, stale names, debug output, and
tests that merely mirror implementation. When the regression check and required
surface checks pass, stop. Do not add an unsolicited broader review or search
for adjacent improvements.

## Observation discipline

- Use `code_context`, `read`, `grep`, and `glob` for source discovery. Do not use
  shell `cat`, `sed`, `head`, `tail`, `nl`, `rg`, or `find` to reread source or
  bypass an observation receipt.
- A revision-aware reuse/covered-range receipt is authoritative. Read again only
  after an edit changed that source or when the required range is not covered.
- Reserve shell for repository-native formatter, test, lint, build, diagnostics,
  and runtime commands.
- A typical focused fix should finish orientation within two model turns and
  recovery within two turns per failing command. If it cannot, state the named
  blocker rather than expanding silently.

## Deliverable

Lead with the observable result. Summarize the contract, key files changed,
checks actually run, and any remaining verification gap. Name any adjacent
issue noticed but intentionally left untouched; do not fix it silently and do
not omit it. Do not narrate every edit or claim success from inspection alone.
