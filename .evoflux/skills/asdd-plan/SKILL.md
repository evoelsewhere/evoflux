---
name: asdd-plan
description: Turn approved ASDD specs into a design document and an executable task checklist. Use when a change is in `designing`, `designed`, `tasking` or `tasked`; do not use for proposals, specification, implementation or verification.
---

# Plan an ASDD change

## Repository contract

Read `.evoflux/asdd/config.json`, then `.evoflux/asdd/RULES.md` and `project.md`
in the resolved `data_directory`. Read the change's `proposal.md`, every
`specs/<capability>/spec.md` under the change, and the current catalogue spec
for each capability. Read the code the change will touch before proposing how to
touch it.

## State gate

Work only when `approvals.specs` carries a timestamp. Which artifact you write
depends on the declared status:

- `designing` or `designed` → write `design.md`.
- `tasking` or `tasked` → write `tasks.md`.

A change whose `risk` is `trivial` or `standard` never enters `designing`; if
you are asked for a design at those tiers, say the tier does not call for one
and write the tasks instead.

## Design (`cross_layer` and `critical` only)

Write `changes/<change-id>/design.md`:

- `## Approach` — the shape of the solution, specific enough that someone could
  build it two ways and recognize which one this is.
- `## Alternatives rejected` — each with the reason. An alternative listed
  without a reason is an omission, not a rejection.
- `## Boundaries` — trust, process and data boundaries crossed, what guards
  each, and what existing callers must keep working.
- `## Migration and rollback` — how existing state reaches the new shape, and
  how to get back.
- `## Open questions` — anything implementation will have to decide.

Set `status: designed` when it is complete.

## Tasks

Write `changes/<change-id>/tasks.md` as a checklist an agent executes top to
bottom:

```markdown
## 1. <Group>

- [ ] Add the delta parser → Slug identity
- [ ] Reject a MODIFIED naming an absent requirement → Slug identity
```

- One task, one outcome, verifiable on its own. A task nobody can mark done
  without judgment is two tasks.
- Point each implementation task at the requirement it serves with
  `→ <Requirement name>`, using the exact name from the delta. **Every requirement
  in every delta is named by at least one task**; a requirement with no task is
  behavior nobody has agreed to build.
- Order by dependency, and group so each group leaves the repository working.
- Include a verification group that runs this repository's checks and records
  evidence, and a documentation group for the docs and changelog `project.md`
  asks for.
- Do not tick a box. Boxes are ticked by the agent that does the work.

Set `status: tasked` when the checklist is complete.

## Code graph navigation

`code_context` is the primary discovery tool for this phase. The ASDD context
block already names the catalogue and the open changes, so do not probe for them
and do not sweep for build manifests to guess the toolchain.

- Order tasks from resolved relationships, not from guesses: `action="callers"`
  and `action="impact"` tell you what has to move first and what breaks if it
  does not.
- Use `action="neighborhood"` at depth 1 to size one task. A task whose blast
  radius you have not looked at is a task nobody can estimate.
- Let the repository's own scripts name the verification commands; do not invent
  a check the project does not already run.

Read `references/code-context-contract.md` for full action selection and
interpretation rules. It is normative here. In short: call `code_context`
with one `action="search"` to expose a declared identifier, then skip
further search and call the exact-symbol action on that identifier; start
at depth 1 unless the question is explicitly transitive; and never bulk
scan. Keep `refresh=true` for the first indexed query and after any edit,
and use `refresh=false` only for an immediate follow-up that intentionally
reuses the returned index version. Do not repeat an unchanged query.

## Stop condition

Stop after writing the artifact. Report the requirement-to-task coverage, the
dependency order, the commands verification will run, and anything you could not
plan without a decision from the user. Do not touch product files.
