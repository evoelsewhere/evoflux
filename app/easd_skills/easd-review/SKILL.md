---
name: easd-review
description: Independently review an EASD implementation against its accepted specification, ACs, and responsibility boundaries. Use after implementation or remediation; do not use to implement fixes or perform the final convergence gate.
---

# Review an EASD implementation

## Repository contract

Read `.evoflux/easd/config.json`, its `rules_file`, and the current run under
`data_directory` before phase work. Confirm the common `specs/` revision and
Run-local accepted snapshot have the same hash. Inspect affected living
`features/`, `architecture/`, and `reference/` documents plus existing project
docs at their original paths. Repository documents are the shared source of
truth. Stop on a missing file, stale hash, or generation conflict; never
reconstruct authority from chat memory or SQLite. Review is mandatory for both
`direct` and `planned`; independence remains risk-driven.

Act as an independent, read-only challenger. Review the actual integrated change
against the exact accepted spec hash; do not treat the implementer's handoff or
test summary as the source of truth.

## State gate

Re-read the run, accepted Spec hash, delivery flow, assigned review ACs,
integrated revision/diff, optional accepted Plan hash, and current evidence. Review only while the
run is `reviewing`; `active` waits for the user's Run review action and
`verifying` belongs to the next Skill. If an applicable hash or reviewed snapshot
changes during the pass, invalidate the verdict and restart against the new
snapshot; do not patch an old verdict forward.

## Review protocol

1. Confirm the run ID, accepted hash, assigned ACs, risk tier, affected
   repositories/paths, and whether reviewer independence is required. If you
   authored the change and independence is required, stop and request a fresh
   reviewer.
2. Read the accepted contract and inspect the integrated diff and owning files
   directly. Review the integrated revision, not an abandoned worktree or a
   parent summary.
3. Trace each in-scope AC through observable behavior, implementation, tests,
   interfaces, and current documentation. Check applicable happy, error,
   authorization, domain-invariant, recovery/concurrency, and cross-layer paths.
4. Audit responsibility boundaries and dependency direction. Flag changes
   outside accepted impact targets, hidden coupling, undeclared shared ownership,
   or a local task that silently became cross-layer work.
5. Cite every finding with an AC or contract reference plus repository path and
   line/source evidence. Separate blocking correctness/security/scope findings
   from non-blocking suggestions; drop claims that cannot be sourced.
6. Return an explicit per-AC verdict and list the evidence inspected, checks not
   run, uncertainty, and required remediation. After fixes, review the new diff
   afresh rather than assuming the prior finding was resolved.

## Review handoff

When this is a delegated review, use `team_handoff` with one `criteria_results`
entry per assigned AC (`passed`, `failed`, or `inconclusive`). Put cited defects
in `findings`, exact sources/commands in `evidence`, and remediation in
`next_actions`. A clean review still lists the inspected snapshot and checks; an
uncited `APPROVED` is not a review result. Do not attach evidence IDs unless they
already exist in persisted EASD state.

Call `easd_submit_review` with the exact run/spec hash, reviewed Git revision,
per-AC results, cited findings/sources, summary, confidence, and delegation task
ID when delegated. The runtime—not prose—computes reviewer independence. Stop
after persistence; only the user may start Verify.

Do not modify product files while acting as the independent reviewer, approve or
rewrite the specification, manufacture evidence, or declare convergence. Review
output is a claim for the lead/user to record through the EASD evidence boundary;
the final `easd-verify` phase and convergence service remain separate gates.
