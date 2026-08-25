---
name: easd-plan
description: Compile an accepted EASD specification into a traceable implementation and verification plan. Use only in the planning phase before user plan approval; do not implement or redefine accepted intent.
---

# Plan an accepted EASD specification

## Repository contract

Read `.evoflux/easd/config.json`, its `rules_file`, and the current run under
`data_directory` before phase work. Repository documents are the shared source
of truth. Stop on a missing file, stale hash, or generation conflict; never
reconstruct authority from chat memory or SQLite. If the accepted Spec selected
`direct`, stop: Plan is intentionally skipped and this Skill has no authority.

Build the execution map from the exact accepted specification hash. Planning
does not authorize implementation and must not weaken the accepted contract.

## State gate

Re-read the current run and accepted revision before planning. Stop if there is
no accepted hash, if the hash differs from the one supplied to this turn, or if
the run is terminal. `accepted` waits for the user's Run plan action;
`planning` permits one typed plan submission; `plan_review` is human review and
cannot be overwritten by the agent; `planned` belongs to implementation. If the
accepted revision changes, discard the stale plan and compile from the new hash.

## Compile the work

1. Confirm the run ID, accepted spec hash, status, risk tier, ACs, impact
   targets, constraints, and evidence policies from injected EASD context.
2. Map every required AC to an implementation owner and concrete files/modules,
   dependencies, and expected evidence. Add explicit verification missions that
   collectively own every accepted Proof command; a command without a Verify
   owner is a plan gap, not an implementation detail.
3. Put shared contracts before dependent layers. Record the exact interface each
   slice consumes and produces. Split parallel missions by disjoint ownership;
   name one integration owner wherever overlap is necessary.
4. Add a separate review mission for every run. Apply independence in proportion
   to risk: cross-layer and critical review must be owned by someone who did not
   author the affected change, and its task should explicitly request EASD
   independent review so the repository's `easd-review` Skill can be selected.
5. Include negative paths, migration/compatibility, security, observability,
   documentation, and rollback work only where the accepted specification or
   affected boundary requires them.
6. Order slices so each ends in a behavior that can be tested and reviewed
   independently. For observable changes and regressions, plan the failing test
   or other baseline observation before the implementation that makes it pass.
7. Run an implementability check: a developer or specialist must be able to
   execute every slice without inventing product behavior, interface ownership,
   setup, or verification. Return real gaps to specification/design instead of
   hiding them in task prose.

## Plan output

Emit one row or block per proposed mission with:

- owned AC IDs and observable deliverable;
- owner/role, repository and bounded paths;
- dependencies plus exact interfaces consumed/produced;
- verification/evidence policy and safe canonical commands;
- isolation, integration owner, and independent-review checkpoint when needed.

Make the complete chain easy to inspect:

`AC → owner/mission → repository and path scope → verification/evidence → docs`

Validate that dependencies are acyclic, parallel paths do not overlap, and each
required AC is owned. Flag unsafe commands, ownership conflicts, and unresolved
dependencies before work begins. Every mission must support an AC or a necessary
accepted cross-cutting constraint; avoid orphan work. A discovery that changes
normative behavior is a proposed deviation or new draft revision, never a silent
plan edit.

When the run is `planning`, call `easd_submit_plan` with the exact run ID, full
typed plan, coverage/dependency summary, and honest confidence. Stop after it
returns the persisted plan revision/hash. Never approve the plan, delegate
implementation, or treat the agent message as plan completion.
