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

`TEMPLATE.md`, beside this file, is what this phase leaves behind — in the change folder and in the chat.

Work only when `proposal.md` reads `status: implementing` and
`approvals.tasks` or `auto_approvals.tasks` carries a timestamp. Approved tasks
are the authorization to modify product files; without them, stop.

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

## Durable pages are part of the work, not paperwork

Some tasks change a surface or a boundary rather than only the code behind it.
Those carry a page with them, written in this change:

- A changed endpoint, config key, schema, event or CLI flag → update the
  matching page under `reference/`. It is the one document a caller will not
  re-derive from the source, so a stale line there is a false statement.
- A moved process, storage, concurrency or trust boundary → update the page
  under `architecture/` that describes it.
- A decision that would be expensive to reverse → an ADR under
  `architecture/decisions/`, numbered and shaped as that directory's
  `README.md` says, citing this change.

Capability specs are the exception: they are deltas under the change and the
archive folds them. Everything above is written directly, now. Read the target
directory's `README.md` before adding a page to it.

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
change is archived. Never touch `approvals`.

Without autopilot, do not advance `status` past `implementing`; verification is
a separate phase the user starts.

With `autopilot: true`, carry it: once every task in `tasks.md` is ticked and
the work matches the approved requirements, set `status: verifying` and go
straight on to `asdd-verify`. Stop and write a `hold` instead — naming
`gate: implementing` and the reason — when a task turned out to be wrong, when
the implementation needs behaviour the approved delta does not describe, or
when you had to touch something the proposal's impact section does not
mention. A change that quietly grew past its own spec is the thing autopilot
most needs to hand back.

## Tools

- `todo_manage` — mirror `tasks.md` at the start and tick both together. The
  checklist in the repository is what the product reads; the todo list is what
  keeps a long run from losing its place.
- `code_context` and `lsp_definition` / `lsp_references` — before editing a
  symbol, read its real declaration and its dependents. An edit made from a
  grep hit is an edit made without its callers.
- `shell` — run the repository's checks as you go, not only at the end.
- `lsp_diagnostics` / `static_diagnostics` — after each group of edits. A task
  is not done while it leaves a new diagnostic behind.
- `ask_user` — only when the approved delta turns out to be wrong or silent on
  something you cannot proceed without. Prefer stopping and reporting: changing
  direction mid-implementation is the user's call, not a question to work
  around.

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
