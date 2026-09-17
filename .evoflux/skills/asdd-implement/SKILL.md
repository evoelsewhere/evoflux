---
name: asdd-implement
description: Execute the approved task checklist of an ASDD change against its approved requirements. Use when a change is in `implementing`; do not use for proposals, specification, planning, verification or archiving.
---

# Implement an ASDD change

## Repository contract

Read `.evoflux/asdd/config.json`, then `.evoflux/asdd/RULES.md` and `project.md`
in the resolved `data_directory`. Read the change's `proposal.md`, `tasks.md`,
`design.md` when present, and every `specs/<capability>/spec.md` under the
change. Read every applicable `AGENTS.md` in the repositories you will touch.

## State gate

Work only when `proposal.md` reads `status: implementing` and
`approvals.tasks` carries a timestamp. Approved tasks are the authorization to
modify product files; without them, stop.

## Execute

1. Take the first unchecked task whose dependencies are done. Do not skip ahead
   to an easier one; the order encodes what keeps the repository working.
2. Implement it against the requirement it names, not against the task's
   wording. When the two disagree, the requirement wins — the task is a plan,
   the requirement is the contract.
3. Run the checks `project.md` names for the code you touched, before moving on.
4. Tick the box in `tasks.md` only when the task is actually done and its checks
   pass. A ticked box is what the product reads as progress, so ticking one
   early is a lie the verification gate will act on.
5. Record what you ran under `changes/<change-id>/evidence/` when a task
   produced a real check result — command, exit status, and the part of the
   output that shows the outcome.

## When the plan is wrong

Implementation regularly discovers that the plan missed something. Handle it in
the open:

- **A task is impossible or unnecessary** — leave it unchecked, add a note under
  it saying why, and report it. Do not delete it; the plan's history is part of
  the record.
- **Work is needed that no task covers** — add the task to `tasks.md` in its
  dependency position, pointed at the requirement it serves, and say so.
- **The requirement itself is wrong** — stop. Do not weaken the code to fit it
  and do not edit the approved delta. Report what the code needs and let the
  user decide whether to revise the change.

## Boundaries

Change only what the tasks and the approved impact call for. Do not edit
`specs/<capability>/spec.md` in the catalogue — a spec changes only when the
change is archived. Do not touch `approvals`, and do not advance `status`
past `implementing`; verification is a separate phase the user starts.

## Code graph navigation

`code_context` is the primary discovery tool for this phase. The ASDD context
block already names the catalogue and the open changes, so do not probe for them
and do not sweep for build manifests to guess the toolchain.

- Before editing a symbol, read its real declaration with `action="definition"`
  and its dependents with `action="callers"`. An edit made from a grep hit is an
  edit made without knowing who relies on it.
- After an edit, re-query with `refresh=true` so the next task sees what you
  actually changed.
- Reuse returned definition and call-site source instead of re-reading the file.

Read `references/code-context-contract.md` for full action selection and
interpretation rules. It is normative here. In short: call `code_context`
with one `action="search"` to expose a declared identifier, then skip
further search and call the exact-symbol action on that identifier; start
at depth 1 unless the question is explicitly transitive; and never bulk
scan. Keep `refresh=true` for the first indexed query and after any edit,
and use `refresh=false` only for an immediate follow-up that intentionally
reuses the returned index version. Do not repeat an unchanged query.

## Stop condition

Stop when every task you can complete is complete. Report which tasks are done,
which are blocked and why, the checks you ran with their results, and any
requirement you believe the implementation does not yet satisfy.
