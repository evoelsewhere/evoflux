# 0011. Features follow Spec-Driven Development: spec, plan, tasks

| | |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-07 |
| ADD sections | [11. Architecture decisions](../README.md#11-architecture-decisions) |
| Related | Supersedes [0006](0006-documentation-follows-add-and-sdd.md); [docs/README.md](../../README.md) |

## Context

[ADR 0006](0006-documentation-follows-add-and-sdd.md) gave each feature one
"Software Design Document" (`docs/features/<slug>/sdd.md`) mixing
requirements, design, delivery plan, verification and history in a single
file. Most of evo is now specified, planned and built by agents working for
the owner. In that setting a single design document has three problems:

- what the feature must do and how it is built change at different speeds
  and are reviewed by different readers, but sit in one file;
- there is no unit of work an agent can pick up, tick and hand over — phases
  are prose, and progress lives in chats;
- unknowns are easy to fill with a guess, because nothing in the document
  marks them.

"SDD" in evo means **Spec-Driven Development**: the spec is the source of
truth, and the plan, the tasks and the code are derived from it in that
order.

## Decision

Every feature is a folder `docs/features/<slug>/` with three documents, each
from its template in `docs/templates/`:

- `spec.md` — what and why: scope, user scenarios, numbered requirements with
  acceptance checks, success criteria, clarifications, history. It carries
  the feature's status.
- `plan.md` — how: an architecture check against `AGENTS.md` and the ADD,
  then the design (components with paths, interfaces, data, behaviour,
  security, configuration), alternatives and as-built notes.
- `tasks.md` — the work: phases with a "done when", small tasks with stable
  IDs that name the requirements they serve, the files they touch and their
  check, `[P]` for tasks that can run in parallel; and a verification table
  with one row per requirement.

The workflow is specify → clarify → plan → tasks → implement → verify, with
two owner gates: the spec is accepted before planning, and the plan before
any code. Unknowns are written as `[NEEDS CLARIFICATION: …]` and resolved
with the owner, never guessed. Agents work the tasks in order, tick each in
the same commit as its code, and change the spec first when behaviour
changes. The ADD and ADRs are unchanged in role; with `AGENTS.md` they are
the standing rules every plan is checked against. The full rules are in
`docs/README.md`.

## Consequences

- The fifteen existing `sdd.md` files are split into `spec.md`, `plan.md` and
  `tasks.md`; their requirement IDs are kept so code comments stay valid.
  `docs/templates/sdd.md` is replaced by the three templates.
- Code comments link `docs/features/<slug>/spec.md` (or `plan.md` for a
  design detail). Applied migrations keep their old `sdd.md` comments,
  because their SQL is checksummed.
- Catalogue status values lose their qualifiers ("phase 5 proposed"):
  remaining work is unticked tasks.
- A feature is resumable from its `tasks.md` alone, and parallel agents can
  only split work along `[P]` tasks with disjoint files.
- Small features now need three short files instead of one; a half-page spec
  with a few tasks is acceptable.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep one `sdd.md` per feature and rename "SDD" | does not separate what from how, gives agents no task unit, and leaves unknowns unmarked |
| One file per feature with spec, plan and tasks as sections | progress edits and design edits collide in one file; spec review is buried under design |
| Tasks in an external tracker | splits the source of truth; agents and reviewers lose the link from task to requirement in the repo |
