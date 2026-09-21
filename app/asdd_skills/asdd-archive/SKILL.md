---
name: asdd-archive
description: Check that a verified ASDD change is safe to fold into the capability specs, and report what archiving will change. Use when a change is in `ready`; do not use for proposals, specification, planning, implementation or verification.
---

# Archive an ASDD change

## Repository contract

Read `.evoflux/asdd/config.json`, then `.evoflux/asdd/RULES.md` and `project.md`
in the resolved `data_directory`. Read the change's `proposal.md`, every
`specs/<capability>/spec.md` under the change, the current catalogue spec for
each of those capabilities, and every page under `evidence/`.

## What archiving does

Archiving folds each delta into `specs/<capability>/spec.md` and moves the
change folder to `changes/archive/YYYY-MM-DD-<change-id>/`. It is the only way a
capability spec changes, and it is not reversible by running something else — it
is reversible only by a new change.

**EvoFlux performs the fold.** You do not edit catalogue specs and you do not
move folders. Your job is to establish that the fold will be correct, and to say
what it will produce.

## Check before the fold

1. **Names resolve.** Every `MODIFIED` and `REMOVED` heading matches a
   requirement in the current catalogue spec character for character. Every
   `ADDED` heading matches nothing there. A capability with no spec yet is
   normal: the fold creates it.
2. **Structure holds.** Every requirement has a statement and at least one
   scenario with a **WHEN** and a **THEN**.
3. **Evidence covers the contract.** Every requirement in every delta has a
   verdict under `evidence/`, and none of them is `failed`. Say which are
   `inconclusive` and why that is acceptable, or that it is not.
4. **Gates are stamped.** `approvals` or `auto_approvals` carries a timestamp
   for proposal, specs, tasks, and — for `cross_layer` and `critical` —
   design. Say which gates a person signed and which autopilot cleared; a
   `cross_layer` or `critical` change must have `approvals.design` from the
   user, not `auto_approvals.design`, and a passing `kind: review` page.
5. **Tasks are settled.** Every task is ticked, or the unticked ones carry a
   note explaining why they are not needed.

## The catalogue outside `specs/`

The fold covers `specs/` and nothing else, so the durable pages this change
owed are yours to confirm before you call the archive — once the folder moves,
they read as though nobody ever needed them.

1. **Decisions are recorded.** Every entry in `design.md`'s `## Decisions` that
   would be expensive to reverse exists as an ADR under
   `architecture/decisions/`, numbered, dated, naming this change, with the
   rejected alternative and its reason. A decision that lives only in a change
   folder is a decision the next reader will find by archaeology.
2. **Boundaries are current.** If the change moved a process, storage,
   concurrency or trust boundary, the page under `architecture/` says so.
3. **The surface is current.** If the change altered an endpoint, config key,
   schema, event or CLI flag, `reference/` matches what shipped.
4. **Investigations are filed.** Anything under `analysis/` this change
   produced is dated and cited where it was used.

Write what is missing, in this change, before archiving. Do not archive around
a gap and open a follow-up change to write the page: the change that made the
statement true is the only one whose diff explains it.

## Report the result

Say, per capability, what the merged spec will contain: requirements added,
requirements replaced and their old text, requirements dropped. Name any
capability the fold will create for the first time. Then state plainly whether
the change is safe to archive, and if not, the exact list of what has to happen
first.

## Tools

- `shell` — `git status` and `git diff --stat` on the change folder and the
  capability specs, so the report describes the tree as it is rather than as
  the change folder claims.
- `code_context` — see `references/code-context-contract.md`, for checking that
  what the deltas contract is what the code now does.

This phase does not write to the repository and must not archive anything. The
fold is the product's operation and the user starts it.

## Code graph navigation

`code_context` is the primary discovery tool for this phase. The ASDD context
block already names the catalogue and the open changes, so do not probe for them
and do not sweep for build manifests to guess the toolchain.

- Spot-check that the merged contract still describes the code: one
  `action="search"` per requirement, then `action="definition"` on what it
  returns. A spec folded in while the behavior no longer matches is worse than
  no spec.
- Use `action="impact"` when a REMOVED requirement retires behavior, to name
  what still depends on it.

Read `references/code-context-contract.md` for full action selection and
interpretation rules. It is normative here. In short: call `code_context`
with one `action="search"` to expose a declared identifier, then skip
further search and call the exact-symbol action on that identifier; start
at depth 1 unless the question is explicitly transitive; and never bulk
scan. Keep `refresh=true` for the first indexed query and after any edit,
and use `refresh=false` only for an immediate follow-up that intentionally
reuses the returned index version. Do not repeat an unchanged query.

## Stop condition

Stop after reporting. Do not edit catalogue specs, do not move the change
folder, do not set `status: archived`, and do not touch `approvals`. Archiving
is the user's action, taken in the UI once your report says it is safe.
