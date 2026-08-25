---
name: easd-verify
description: Run the final EASD integration and evidence gate against accepted AC policies, then prepare a convergence recommendation. Use after implementation and any required independent review; not for task-local code review or ordinary tests outside EASD.
---

# Verify and prepare EASD convergence

## Repository contract

Read `.evoflux/easd/config.json`, its `rules_file`, and the current run under
`data_directory` before phase work. Confirm the common `specs/` revision and
Run-local accepted snapshot have the same hash. Inspect affected living
knowledge sections and existing project docs without migrating them implicitly.
Repository documents are the shared source of truth. Stop on a missing file,
stale hash, or generation conflict; never reconstruct authority from chat memory
or SQLite. Verify and Converge remain mandatory for both `direct` and `planned`.

Challenge the integrated result against the exact accepted specification. This
skill helps gather and assess evidence; only the EASD service computes Done.

## State gate

Re-read the persisted run detail, accepted revision/hash, AC matrix, missions,
evidence, deviations, and convergence state on every invocation. Evaluate only
the current accepted hash. Only `verifying` may perform the final gate;
`reviewing` waits for the user's Run verify action. If already `converged`,
report the existing durable result without duplicating evidence or rerunning
convergence. Any other state returns to its owning phase.

## Verify claims

1. Load the accepted run ID/hash, current AC matrix, risk tier, planned commands,
   missions, evidence, and deviations. Reject stale-spec evidence.
2. Check three dimensions: **completeness** of required AC/mission/command/doc
   coverage; **correctness** of behavior and scenarios; and **coherence** of the
   integrated architecture, interfaces, terminology, and current documentation.
3. Inspect the integrated result and consume independent `easd-review` findings
   where the risk/evidence policy requires them. Execute approved verification
   missions through EASD-bound delegation so the runtime can persist a fresh,
   revision-bound CompletionContract even though this phase is read-only. Re-run
   safe required checks and relevant negative, recovery, authorization,
   compatibility, smoke/liveness, and cross-layer paths. Read fresh full output
   and exit status before stating that a command or behavior passed.
4. Map each result to an AC and its evidence policy. Preserve machine, review,
   manual, and waiver provenance; never manufacture command IDs, exit codes,
   revisions, artifact hashes, or reviewer independence.
5. For cross-layer or critical runs, ensure review is performed by an agent or
   human independent of the implementation owner and covers the integrated
   revision rather than an abandoned worktree.
6. Reconcile adopted EASD `features/`, `architecture/`, and `reference/`
   documents, existing project docs, localized Help, and release or migration
   notes where the accepted behavior requires them. Never move existing docs as
   an implicit verification side effect.

If a required command, runtime environment, manual observation, or independent
review cannot be completed, report `manual verification required` or the exact
evidence gap. Never broaden a claim beyond the verification actually performed.

## Verification report

Report the exact spec hash and integrated revision, then summarize:

- every required AC with computed state, policy, supporting evidence IDs, and
  the precise missing evidence when not satisfied;
- planned commands/smoke checks with fresh result or manual-required status;
- non-terminal missions, blocking deviations, independent-review coverage, docs
  reconciliation, and remaining risk;
- decision: `ready for convergence`, `rework required`, or
  `manual verification required`.

Recommend convergence only when persisted evidence appears to satisfy every
gate. Do not approve a specification, fabricate evidence, or declare the run
converged from the Skill itself.
