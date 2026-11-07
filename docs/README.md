# evo documentation

This folder is the single home for evo's design documentation. evo is built
with **Spec-Driven Development (SDD)**, carried out by agents
(**agent-driven development**): a feature starts as a written spec, the spec
is turned into a technical plan and then into small tasks, and agents
implement the tasks. The spec — not the code — is the source of truth for
what a feature does.

Two kinds of documents:

- **ADD — Architecture Design Document** (`architecture/`): how the whole
  system is built — processes, crate layers, interfaces, where state lives,
  cross-cutting rules. One living document, plus **ADRs** (Architecture
  Decision Records) for the decisions behind it. Together with
  [`AGENTS.md`](../AGENTS.md) it is the standing rulebook every plan is
  checked against.
- **Feature specs** (`features/<slug>/`): one folder per feature with three
  files, written in this order:
  - `spec.md` — **what** the feature does and **why**: scope, user
    scenarios, numbered requirements with acceptance checks, success
    criteria, clarifications. No implementation detail.
  - `plan.md` — **how** it is built: the architecture check, components and
    paths, interfaces, data, behaviour, security, alternatives.
  - `tasks.md` — **the work**: ordered, traceable tasks an agent can pick up
    one at a time, and the verification table.

The ADD says *what every feature must fit into*; a feature's spec says *what
the feature must do*, its plan *how it fits in*, its tasks *how it gets
built*. Feature documents link the ADD sections and ADRs they rely on and
never restate them.

## Layout

```text
docs/
  README.md                     this file: map + documentation rules
  architecture/
    README.md                   the ADD
    decisions/
      README.md                 ADR index and rules
      NNNN-<slug>.md            one decision each
  features/
    README.md                   feature catalogue (every spec, its status and area)
    <feature-slug>/
      spec.md                   what and why — the source of truth
      plan.md                   how — design against the ADD
      tasks.md                  the work — ordered tasks and verification
      assets/                   optional: diagrams, screenshots
  templates/
    spec.md  plan.md  tasks.md  copy to start a feature
    adr.md                      copy to record a decision
```

Not in this folder:

- `apps/desktop/README.md` — the desktop's UI map and source layout (a code
  map; it links to feature specs for the design).
- Crate `README.md` files — what a crate offers to its users.
- `crates/evo-engine/embedded-docs/` — user and extension-author docs shipped
  inside the engine for the agent's docs tool. Parts still describe the old
  CLI; they are product docs, not design docs.
- `DESIGN.md` at the root — the visual design language.

## The workflow

Each step produces a document, and each document is checked before the next
step starts. The person who owns the work (the user, for agent-written work)
approves at the two gates; agents do the rest.

```text
 request ──► 1 Specify ──► 2 Clarify ──► [gate A: spec accepted]
                                                │
             3 Plan ──► [gate B: plan accepted] ◄┘
               │
               ▼
             4 Tasks ──► 5 Implement ──► 6 Verify ──► Implemented
                              ▲                          │
                              └──── 7 Evolve: spec first ◄┘
```

1. **Specify.** Copy `templates/spec.md` to `features/<slug>/spec.md` and
   add a row to `features/README.md`. Write the summary, scope, user
   scenarios, requirements (`FR-n`, `NFR-n`) and success criteria from the
   request. Every unknown is written as `[NEEDS CLARIFICATION: <question>]`
   with a proposed answer — never a silent guess. Status `Draft`.
2. **Clarify.** Put the open questions to the owner, a few at a time, most
   important first. Each answer goes into the spec (requirement or scope)
   and is logged in section 6.2. The spec is ready when no
   `[NEEDS CLARIFICATION]` marker is left and every requirement has an
   acceptance check.
   **Gate A:** the owner accepts the spec.
3. **Plan.** Copy `templates/plan.md`. Fill the architecture check first:
   every rule of `AGENTS.md` and the ADD is `ok`, `n/a`, or a deviation
   covered by a new ADR (and an ADD edit). Then the design, with each
   component tied to the requirements it serves. A plan that needs
   something the spec does not ask for goes back to step 1.
   **Gate B:** the owner accepts the plan. Status `Accepted`. Code starts
   here — not before.
4. **Tasks.** Copy `templates/tasks.md`. Break the plan into phases, each
   with a "done when", and the phases into tasks small enough for one
   commit: ID, requirements served, files, check. Tests come before the code
   they prove. Mark `[P]` the tasks of a phase that touch disjoint files and
   do not depend on each other. Fill the verification table: one row per
   requirement. Tasks are reviewed with the plan, but need no gate of their
   own unless they change the plan.
5. **Implement.** Status `In progress`. Work the tasks in order; tick each
   one in the same commit as its code. When building shows the plan or the
   spec was wrong, fix the document first (or in the same commit) — the code
   never leads silently. Deviations from the plan go to its section 5.
6. **Verify.** Run every check in the verification table and record the
   result with its date. Status `Implemented` once every requirement has a
   passing check and the plan describes what was built.
7. **Evolve.** A later change starts by editing the spec (new or changed
   `FR-n`, a History line), then the plan, then new tasks — in that order.
   A redesign that replaces the feature gets a new folder; the old spec
   becomes `Superseded by <link>`.

If a feature changes the architecture (see "When the ADD changes"), the ADD
and an ADR change in the same commit as the plan.

## Agent-driven development

Agents write most specs, plans, tasks and code; the documents are how the
owner steers them and how one agent hands work to the next.

- **The owner decides intent; the agent decides nothing silently.** Scope,
  requirements and trade-offs are the owner's call at gates A and B. The
  agent proposes, records each answer in the spec, and asks again when an
  answer is missing.
- **No code before gate B.** An agent asked to "just build it" still writes
  the spec and plan (a half-page is fine for a small feature) and asks for
  acceptance first. Bug fixes and refactors are exempt (see below).
- **Read before writing.** Before touching a feature, an agent reads its
  `spec.md`, `plan.md` and `tasks.md`, the ADD sections the plan links, and
  `AGENTS.md`.
- **One task at a time, traceable.** Every commit names the task IDs it
  completes (`feat(office): T7 T8 …`); every change to behaviour traces to
  a requirement ID. Work that matches no requirement is either dropped or
  added to the spec first.
- **Parallel work only on `[P]` tasks.** Subagents or parallel sessions take
  `[P]` tasks of the same phase; they never edit the same files. The agent
  that owns the feature merges, ticks the tasks and runs the phase's checks.
- **Prove before ticking.** A task is ticked and a requirement marked
  passed only after its check ran and passed; the result goes in the
  verification table with the date. Checks that did not run say `not run`.
- **Hand off through the documents.** An unfinished feature is resumable
  from its tasks list alone: what is done is ticked, the next task is the
  first unticked one, and open problems are in the spec's clarifications or
  the plan's as-built notes — not only in a chat.

## When a change needs a spec

Needs one:

- a new user-visible capability (a page, a panel, a setting group, an agent
  tool, a slash command);
- a change to `evo-protocol`, the mesh envelope, Tauri commands/events used
  across features, the plugin ABI, or the `evo.db` schema;
- a new crate, a new process, or a new place where state is stored;
- anything touching permissions, the sandbox, credentials or project trust.

Does not need one (but update the existing spec, plan or tasks if what they
describe changes): bug fixes, refactors inside one module, copy and styling
tweaks, dependency bumps, tests, CI.

When unsure, write a short spec — a half-page spec is fine; a missing one is
not.

## When the ADD changes

Update `architecture/README.md` **and** add an ADR when a change:

- adds, removes or merges a crate, or changes which crate may depend on which;
- adds a process, a transport, a protocol plane, or changes who owns a
  responsibility (engine vs shell vs webview);
- adds a persistent store or moves state between stores;
- changes a trust boundary, the permission model or the sandbox;
- adopts or drops a platform, toolchain, framework or external data source;
- reverses an existing ADR.

## Feature document rules

- **Three files, fixed structure.** Every feature folder has `spec.md`,
  `plan.md` and `tasks.md`, each keeping every numbered section of its
  template in order. A section that does not apply says `n/a — <reason>`;
  it is not deleted.
- **What, how, work — kept apart.** `spec.md` holds no file paths, crate
  names or wire shapes unless the feature itself is a technical contract
  (a protocol, a tool schema the model sees). Design goes in `plan.md`;
  phases and progress go only in `tasks.md`.
- **Header table first**, right under the title. `spec.md`: Status, Area,
  Created, Updated, Plan, Tasks, Related. `plan.md`: Spec, Tasks, Updated,
  ADD sections, ADRs. `tasks.md`: Spec, Plan, Updated. Update `Updated` on
  every edit of that file.
- **Status lives in the spec.** Values: `Draft`, `Accepted`, `In progress`,
  `Implemented`, `Superseded by <link>`, `Deprecated`. The catalogue row
  shows the same value. Work still planned for an implemented feature shows
  as unticked tasks, not as a status qualifier.
- **Stable IDs.** Requirements (`FR-n`, `NFR-n`), user scenarios (`US-n`),
  success criteria (`SC-n`) and tasks (`Tn`) are never renumbered; a dropped
  one is struck out (`~~FR-4~~ dropped YYYY-MM-DD: reason`). Code comments
  and commits cite them.
- **Traceability both ways.** Each plan component lists the requirements it
  serves; each task lists the requirements it serves; the verification
  table in `tasks.md` has one row per requirement.
- **Present tense for what is built**, future tense only in open
  clarifications and unticked tasks. The top of each document describes the
  feature as it is now; history goes in the spec's History and the plan's
  as-built notes.
- **Name the code.** The plan's components table lists each component with
  its repository-relative path.
- **Link, don't copy.** Refer to the ADD, ADRs and other features by
  relative link; copy a fact only when the reader cannot follow without it.
- **Diagrams as text** — Mermaid or ASCII in the Markdown, so they diff and
  review. Images go in `assets/` only when text cannot show it (UI
  screenshots).
- **One feature per folder.** The slug is kebab-case, short and stable; it is
  never renamed after `Accepted` (code comments link to it).

## ADR rules

See `architecture/decisions/README.md`. In short: numbered, one decision
each, immutable once `Accepted` — a changed mind is a new ADR that supersedes
the old one.

## Writing rules (all docs)

- English, plain and direct; short sentences; no marketing.
- Repository-relative links (`../../architecture/README.md#5-building-blocks`),
  never absolute file paths or machine-specific paths.
- Code, paths, commands, settings keys, RPC/tool names in backticks; UI names
  in bold (**Settings → Sandbox**).
- The product is "evo". Do not name other vendors' assistant products in docs;
  describe a reference behaviour by what it does.
- Dates as `YYYY-MM-DD`.
- No secrets, tokens, real user data or personal paths in examples.

## Code ↔ docs links

Code that implements a feature links its spec in the module doc comment, and
cites requirement IDs where a piece of code exists for one requirement, e.g.
`//! The session mesh hub (docs/features/session-mesh-protocol/spec.md).`
or `// Annotation chips (docs/features/office-v3-parity/spec.md, FR-10).`
Link `plan.md` instead when the comment points at a design detail (an
interface shape, a data layout). When a feature folder moves or is
superseded, update those comments in the same commit
(`git grep 'docs/features/<slug>'`). **Exception:** never edit an applied
migration in `crates/evo-store/src/migrations/` — its SQL is checksummed and
a changed byte breaks existing databases. Old paths in migration comments
(such as `docs/design/…` or `…/sdd.md`) stay as they are; a moved doc keeps
its slug so the reader can still find it.

## Review checklist

Gate A — before accepting a spec:

- [ ] Goals and non-goals are explicit.
- [ ] User scenarios are prioritised and each has acceptance scenarios.
- [ ] Every FR/NFR has an acceptance check; success criteria are
      measurable and technology-free.
- [ ] No `[NEEDS CLARIFICATION]` marker is left; answers are logged in 6.2.
- [ ] No implementation detail has leaked in (paths, crates, wire shapes),
      unless the feature is itself a contract.

Gate B — before accepting a plan:

- [ ] The architecture check has no unexplained deviation; architecture
      changes have an ADR and an ADD edit.
- [ ] The design names each layer it touches (crate, engine, protocol,
      shell, webview) and stays within the ADD's ownership rules.
- [ ] Every component traces to a requirement, and every requirement is
      covered by a component.
- [ ] Interfaces (protocol messages, tool schemas, settings keys, tables) are
      written out, with compatibility for older engines/clients.
- [ ] Security and trust (3.7) is filled, not `n/a`, for anything that runs
      tools, reads untrusted content, stores credentials or crosses a process.
- [ ] Alternatives considered, with the reason each was rejected.
- [ ] `tasks.md` exists: phases with "done when", tests before code, `[P]`
      only on independent tasks, one verification row per requirement.

Before marking a feature `Implemented`:

- [ ] Every task is ticked or struck out with a reason.
- [ ] Every verification row says `passed (YYYY-MM-DD)` with the check that
      actually ran.
- [ ] The plan matches the code; its as-built notes list every deviation.
- [ ] The catalogue row, `apps/desktop/README.md` UI map (if user-visible) and
      code doc comments link to the feature's spec.
