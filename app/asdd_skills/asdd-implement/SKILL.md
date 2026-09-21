---
name: asdd-implement
description: Execute the approved task checklist of an ASDD change against its approved requirements. Use when a change is in `implementing`; do not use for proposals, specification, planning, verification or archiving.
---

# Implement an ASDD change

You are executing an approved checklist against approved requirements. This is
the only phase allowed to modify product files, and the approval on `tasks.md`
is what allows it.

**IMPORTANT: when the task and the requirement disagree, the requirement
wins.** The task is a plan someone wrote; the requirement is the contract the
user approved. Never weaken the requirement to fit the code, and never edit the
approved delta to fit what you built.

---

## Read before you write

1. `.evoflux/asdd/config.json` — where the catalogue lives.
2. `.evoflux/asdd/RULES.md` — normative; it outranks this Skill.
3. `<data_directory>/project.md` — this repository's conventions and the checks
   that prove a change works here.
4. `changes/<change-id>/tasks.md` — the checklist, in order.
5. `changes/<change-id>/proposal.md`, `design.md` when present, and every
   `specs/<capability>/spec.md` under the change — what you are building
   against.
6. Every applicable `AGENTS.md` in the repositories you will touch.

`TEMPLATE.md`, beside this file, is what this phase leaves behind — in the
change folder and in the chat.

---

## Check the gate before you touch a file

| Condition | What to do |
|---|---|
| `status: implementing` **and** `approvals.tasks` or `auto_approvals.tasks` is stamped | Execute. The normal case. |
| No tasks approval | **Stop.** Approved tasks are the authorization to modify product files. |
| `status` earlier than `implementing` | **Stop.** The plan is not finished; naming the open phase is more useful than starting. |
| `status: verifying` or later | **Stop.** Implementation is done; reopening it silently undoes a verdict. |

---

## The loop

1. **Take the first unchecked task whose dependencies are done.** Do not skip
   ahead to an easier one — the order encodes what keeps the repository
   working.
2. **Implement it against the requirement it names**, not against the task's
   wording.
3. **Run the checks `project.md` names** for the code you touched, before
   moving on. Not at the end; now.
4. **Tick the box** only when the task is done and its checks pass. The product
   reads a ticked box as progress, so ticking early is a lie the verification
   gate will act on.
5. **Record real check results** under `changes/<change-id>/evidence/` —
   command, exit status, and the part of the output that shows the outcome.

---

## Some tasks carry a page

A task that changes a surface or a boundary ships its documentation in this
change, not after it:

| What the task changed | What you write, now |
|---|---|
| An endpoint, config key, schema, event or CLI flag | the matching page under `reference/` |
| A process, storage, concurrency or trust boundary | the page under `architecture/` describing it |
| Something expensive to reverse | an ADR under `architecture/decisions/`, citing this change |

Read the target directory's `README.md` before adding a page to it.

Capability specs are the one exception: they are deltas under the change, and
the archive folds them. Everything above is written directly.

---

## When the plan turns out to be wrong

Implementation regularly discovers what planning missed. Handle it in the open:

| What you found | What to do |
|---|---|
| A task is impossible or unnecessary | Leave it unchecked, note why under it, report it. Do not delete it — the plan's history is part of the record. |
| Work is needed that no task covers | Add the task in its dependency position, pointed at the requirement it serves, and say so. |
| **The requirement itself is wrong** | **Stop.** Do not bend the code to fit it and do not edit the approved delta. Report what the code needs and let the user decide whether to revise the change. |

---

## Boundaries

Change only what the tasks and the approved `## Impact` call for. Never edit a
catalogue `specs/<capability>/spec.md` — that changes at the archive, and only
then. Never write `approvals`.

**Without autopilot**, do not advance `status` past `implementing`.
Verification is a separate phase the user starts.

**With `autopilot: true`**, carry it: once every task is ticked and the work
matches the approved requirements, set `status: verifying` and continue into
`asdd-verify`. Write a `hold` naming `gate: implementing` instead when a task
turned out to be wrong, when the implementation needs behavior the approved
delta does not describe, or when you had to touch something the proposal's
impact does not mention. A change that quietly grew past its own spec is
exactly what autopilot should hand back.

---

## Tools

- `todo_manage` — mirror `tasks.md` at the start and tick both together. The
  checklist in the repository is what the product reads; the todo list is what
  keeps a long run from losing its place.
- `code_context` — before editing a symbol, read its real declaration with
  `action="definition"` and its dependents with `action="callers"`; an edit
  made from a grep hit is an edit made without its callers. Re-query with
  `refresh=true` after an edit so the next task sees what you changed, and
  reuse returned source instead of re-reading the file. Never bulk scan.
  `references/code-context-contract.md` is normative and carries the full rules.
- `lsp_definition` / `lsp_references` — the same question, answered by the
  language server when the index is stale.
- `shell` — run the repository's checks as you go.
- `lsp_diagnostics` / `static_diagnostics` — after each group of edits. A task
  is not done while it leaves a new diagnostic behind.
- `ask_user` — only when the approved delta is wrong or silent on something you
  cannot proceed without. Prefer stopping and reporting: changing direction
  mid-implementation is the user's call, not a question to work around.

The ASDD context block already names the catalogue and the open changes. Do not
probe for them.

---

## Stop, and report

Stop when every task you can complete is complete:

```text
add-note-search — 7 of 9 tasks done.

Done: storage (3), endpoint (2), reference page (1), ADR 0007 (1).
Checks: `uv run pytest tests/notes -q` 24 passed; `bun run test:unit` 659
passed. Both recorded under evidence/.

Blocked: task 8 "Rank by recency" — the delta says "recently opened" and
nothing defines the window. Not guessing; it needs a decision.

Unsatisfied: "Empty query returns nothing" holds for the API but not the CLI,
which still prints the full list. That is task 9, not yet started.
```

Report which tasks are done, which are blocked and why, the checks you ran with
their results, and any requirement you believe the implementation does not yet
satisfy.

---

## Guardrails

- **Don't tick a box early.** The product acts on it.
- **Don't skip to an easier task.** The order is what keeps the tree working.
- **Don't edit an approved delta** to match what you built. That is the change
  rewriting its own contract.
- **Don't edit a catalogue spec.** Archiving folds deltas; hands do not.
- **Don't widen the change.** Anything outside the approved impact is a
  follow-up change, or a `hold`.
- **Don't leave a new diagnostic behind** and call the task done.
