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
4. **Gates are stamped.** `approvals` carries a timestamp for proposal, specs,
   tasks, and — for `cross_layer` and `critical` — design. A `cross_layer` or
   `critical` change also has a passing `kind: review` page.
5. **Tasks are settled.** Every task is ticked, or the unticked ones carry a
   note explaining why they are not needed.

## Report the result

Say, per capability, what the merged spec will contain: requirements added,
requirements replaced and their old text, requirements dropped. Name any
capability the fold will create for the first time. Then state plainly whether
the change is safe to archive, and if not, the exact list of what has to happen
first.

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
