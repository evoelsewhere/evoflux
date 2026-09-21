---
name: asdd-plan
description: Turn approved ASDD specs into a design document and an executable task checklist. Use when a change is in `designing`, `designed`, `tasking` or `tasked`; do not use for proposals, specification, implementation or verification.
---

# Plan an ASDD change

This phase answers two different questions, and you are here for exactly one of
them:

| `status` | Question | You write |
|---|---|---|
| `designing`, `designed` | **How should this be built?** | `design.md` → Track A |
| `tasking`, `tasked` | **In what order, and who checks?** | `tasks.md` → Track B |

**IMPORTANT: planning touches no product file.** Not a scaffold, not a stub,
not "just the interface". `asdd-implement` does that, from the checklist you
leave behind.

---

## Read before you write

1. `.evoflux/asdd/config.json` — where the catalogue lives.
2. `.evoflux/asdd/RULES.md` — normative; it outranks this Skill.
3. `<data_directory>/project.md` — when this repository requires a design
   beyond the tier default, and what its tasks must always include.
4. `changes/<change-id>/proposal.md` — scope, tier, non-goals.
5. Every `changes/<change-id>/specs/<capability>/spec.md` — the approved
   requirements. These are what the plan has to cover.
6. The current catalogue spec for each of those capabilities, and **the code
   the change will touch**. Do not propose how to touch code you have not read.

---

## Check the gate before you spend a turn

| Condition | What to do |
|---|---|
| No `approvals.specs` **and** no `auto_approvals.specs` | **Stop.** The contract is not agreed; a plan against a moving spec is waste. |
| `risk` is `trivial` or `standard`, and you were asked for a design | Say the tier does not call for one and write the tasks instead. Those tiers never enter `designing`. |
| `status: designing` or `designed` | Track A. |
| `status: tasking` or `tasked` | Track B. |
| `status: implementing` or later | **Stop.** The plan was approved and the work has started. |

---

## Track A — Design

Only `cross_layer` and `critical` reach here. Write
`changes/<change-id>/design.md` with these sections; `TEMPLATE.md` beside this
file is the exact shape:

- `## Approach` — the shape of the solution, specific enough that someone could
  build it two ways and recognize which one this is.
- `## Alternatives rejected` — each with its reason. An alternative listed
  without a reason is an omission, not a rejection.
- `## Boundaries` — the trust, process and data boundaries crossed, what guards
  each, and what existing callers must keep working.
- `## Migration and rollback` — how existing state reaches the new shape, and
  how to get back.
- `## Decisions` — every question this design settled, and the answer. A
  decision the user made is recorded in their words, not your paraphrase.
- `## Open questions` — empty by the time you stop. See below.

### Ask; do not defer

An open question is not a section to fill in. It is work you owe the user
before the design can be approved, and **the gate refuses a `design.md` that
still lists any**.

When you hit something the approved deltas do not settle — a format, a default,
a boundary, a compatibility call, anywhere two reasonable builds diverge — call
`ask_user`. Batch them: one round trip can carry every question the design
raised instead of stopping the user four times. Give each a real
recommendation; a question with no recommendation makes the user do your
thinking.

```
ask_user(questions=[
  {"question": "PDF page size?",
   "options": ["A4", "US Letter"],
   "context": "A4 fits a Vietnamese-context project. Letter if the audience is US."},
])
```

Write the answers into `## Decisions` and delete the questions. Anything the
user rules out of scope leaves the design entirely — it becomes a follow-up
change named in the proposal's non-goals, not a question parked in a document
someone is being asked to approve.

If `ask_user` is unavailable or the user does not answer, stop and say so. With
`autopilot: true`, write a `hold` naming `gate: design` and every unanswered
question. Guessing a default and recording it as decided is the exact failure
this section prevents.

### Which decisions outlive the change

`## Decisions` settles questions for this change; the durable ones belong to
the repository — a storage engine, a protocol, an ordering guarantee, a trust
boundary. Each of those becomes an ADR under `architecture/decisions/`, shaped
as that directory's `README.md` says, written during implementation and
confirmed before the archive.

Mark them here as you decide them, so Track B can give each one a task. A
decision discoverable only by reading an archived change folder is a decision
the next reader will re-litigate.

### Finishing Track A

Set `status: designed` only when `## Open questions` is empty. Then **stop** —
`cross_layer` and `critical` reserve the design gate for the user whatever
autopilot says. Under autopilot, write a `hold` naming `gate: design` and say
so in the chat.

---

## Track B — Tasks

Write `changes/<change-id>/tasks.md` as a checklist an agent executes top to
bottom:

```markdown
## 1. Storage

- [ ] Add `NoteStore.search(query)`. -> Find a note by title
- [ ] Fold query and title before comparing. -> Search is case-insensitive

## 2. Verification

- [ ] Run the repository's checks and record the result under `evidence/`.
- [ ] Confirm every approved requirement has a scenario that was exercised.

## 3. Catalogue and documentation

- [ ] Record the storage choice as `architecture/decisions/0007-note-store.md`.
- [ ] Update `reference/api.md` for the new `search` parameter.
- [ ] Update the docs and changelog this repository expects.
```

### What makes a task executable

- **One outcome, verifiable on its own.** A task nobody can mark done without
  judgment is two tasks.
- **`-> <Requirement name>`** on every implementation task, spelled exactly as
  the delta spells it. **Every requirement in every delta is named by at least
  one task** — a requirement with no task is behavior nobody agreed to build.
- **Ordered by dependency**, grouped so each group leaves the repository
  working.
- **A verification group** that runs this repository's own checks and records
  evidence, and **a catalogue group** for the durable pages:

| The change… | Gets a task to write |
|---|---|
| decides something expensive to reverse | `architecture/decisions/NNNN-<slug>.md` |
| moves a process, storage, concurrency or trust boundary | the page under `architecture/` |
| alters an endpoint, config key, schema, event or CLI flag | the page under `reference/` |
| is what `project.md` says always needs docs | whatever it names |

Those pages ship inside this change. Only `specs/` waits for the archive.

- **Do not tick a box.** Boxes are ticked by the agent that does the work.

### Finishing Track B

Set `status: tasked`. With `autopilot: true` you may clear this gate once the
checklist covers every approved requirement: write `auto_approvals.tasks`
(never `approvals`) and set `status: implementing`.

Set the next status and stop there. The product reads it and starts the next
phase itself — that is what autopilot means now, so there is no hop for you to
make and no Continue for the user to click. A `hold` is what ends the chain.

---

## Tools

- `code_context` — read the code each task will touch before writing the task.
  `action="callers"` and `action="impact"` tell you what has to move first and
  what breaks if it does not; `action="neighborhood"` at depth 1 sizes one
  task. A task whose blast radius you have not looked at is a task nobody can
  estimate. Never bulk scan. `references/code-context-contract.md` is normative
  and carries the full rules.
- `lsp_references` — before a task that changes a signature, find who calls it.
  An unlisted caller is a task you have not written yet.
- `ask_user` — see **Ask; do not defer**. This is the phase that owes the user
  questions.
- `shell` — read-only: the repository's own test and build commands, so the
  verification tasks name checks this project actually runs. Do not invent one.

The ASDD context block already names the catalogue and the open changes. Do not
probe for them.

---

## Stop, and report

```text
add-note-search — tasked.

9 tasks in 3 groups. Coverage: all 4 approved requirements named; "Empty
query returns nothing" is covered by tasks 2 and 6.

Order: storage before the endpoint — `NoteStore` has 3 callers that break
until the index exists.

Verification runs `uv run pytest tests/notes -q` and `bun run test:unit`,
which is what this repository already uses.

Catalogue: one ADR for the index choice, and `reference/api.md` for the new
parameter.
```

Report requirement-to-task coverage, the dependency order, the commands
verification will run, and anything you could not plan without a decision from
the user. Then stop: no product files.

---

## Guardrails

- **Don't touch product code.** Planning that starts building is planning
  nobody reviewed.
- **Don't declare `designed` with open questions.** The gate refuses it, and
  the user is being asked to approve a document that admits it is unfinished.
- **Don't paraphrase a decision the user made.** Record their words.
- **Don't leave a requirement untasked.** That is behavior with no owner.
- **Don't invent a verification command.** Use what the repository runs.
- **Don't write `approvals`,** and don't clear the design gate at
  `cross_layer` or `critical` — that one is the user's, always.
