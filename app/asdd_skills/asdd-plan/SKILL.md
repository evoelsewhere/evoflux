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

Work only when `approvals.specs` or `auto_approvals.specs` carries a timestamp.
Which artifact you write depends on the declared status:

- `designing` or `designed` → write `design.md`.
- `tasking` or `tasked` → write `tasks.md`.

With `autopilot: true` you may clear the tasks gate yourself once the
checklist covers every approved requirement: write `auto_approvals.tasks` and
set `status: implementing`. Never write `approvals`. The **design** gate is
different — `cross_layer` and `critical` reserve it for the user no matter
what autopilot says, so write `design.md`, set `status: designed`, then write
a `hold` naming `gate: design` and stop.

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
- `## Decisions` — each question this design had to settle, and the answer. A
  decision the user made is recorded with their words, not your paraphrase.
- `## Open questions` — see below. Empty by the time you stop.

`TEMPLATE.md`, beside this file, is the exact shape.

## Decisions outlive the change

`## Decisions` is where this design settles questions, and the durable ones do
not belong to the change folder: a storage engine, a protocol, an ordering
guarantee, a trust boundary. Each of those becomes an ADR under
`architecture/decisions/`, numbered and shaped as that directory's `README.md`
says — written during implementation, confirmed before the archive.

Name them here as you decide them, so the tasks below can carry one task each.
A decision found only by reading an archived change folder is a decision the
next reader will re-litigate.

## Ask; do not defer

An open question is not a section to fill in. It is work you owe the user
before the design can be approved, and the design gate refuses a `design.md`
that still lists any.

When you hit something the approved deltas do not settle — a format, a default,
a boundary, a compatibility call, anything where two reasonable builds diverge
— **call `ask_user`**. Batch them: it takes a list, so one round trip can carry
every question the design raised instead of stopping the user four times. Give
each a real recommendation and say why; a question with no recommendation makes
the user do your thinking.

```
ask_user(questions=[
  {"question": "PDF page size?",
   "options": ["A4", "US Letter"],
   "context": "A4 fits a Vietnamese-context project. Letter if the audience is US."},
])
```

Then write the answers into `## Decisions` and delete the questions. Anything
the user says is out of scope leaves the design entirely — it becomes a
follow-up change, named in the proposal's non-goals, not a question parked in a
document someone is being asked to approve.

Stop and say so if `ask_user` is unavailable or the user does not answer. With
`autopilot: true`, write a `hold` naming `gate: design` and every unanswered
question. Guessing a default and writing it down as though it were decided is
the failure this section exists to prevent.

Set `status: designed` only when `## Open questions` is empty.

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
- **Give every durable page its own task.** A change that alters an endpoint,
  a config key, a schema, an event or a CLI flag carries a task to update
  `reference/`; one that moves a process, storage, concurrency or trust
  boundary carries a task to update `architecture/`; and each decision in
  `## Decisions` that would be expensive to reverse carries a task to write the
  ADR under `architecture/decisions/`. These ship in this change, not after it
  — only `specs/` waits for the archive.
- Do not tick a box. Boxes are ticked by the agent that does the work.

Set `status: tasked` when the checklist is complete.

## Tools

- `ask_user` — see **Ask; do not defer**. This is the phase that owes the user
  questions, and the design gate refuses a `design.md` that still lists any.
- `code_context` — see `references/code-context-contract.md`. Read the code
  each task will touch before you write the task.
- `lsp_references` — before a task that changes a signature, find who calls it;
  an unlisted caller is a task you have not written yet.
- `shell` — read-only: the repository's own test and build commands, so the
  verification tasks name the commands this project actually runs.

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
