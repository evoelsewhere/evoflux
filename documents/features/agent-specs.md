# Agent Spec-Driven

Status: implemented

**Agent Spec-Driven** is the Coding-mode product surface for **ASDD — Agent
Specification-Driven Development**. The normative lifecycle lives in
[asdd-methodology.md](../reference/asdd-methodology.md); this page describes
what the product does.

## What it stores

Everything, in the repository. A change is
`<data_directory>/changes/<change-id>/`, a folder of Markdown. Its phase is the
`status` in its `proposal.md`. A capability's current contract is
`<data_directory>/specs/<capability>/spec.md`.

The catalogue has a home for each durable kind of page, and setup writes a
`README.md` into every one saying what belongs there: `architecture/` for
process, storage, concurrency and trust boundaries, `architecture/decisions/`
for the ADR-style records of why they are where they are, `reference/` for the
exact API, configuration, schema and CLI surface, and `analysis/` for dated
investigations. Only `specs/` changes by archiving a delta; the rest ship in
the same change as the code that makes them true.

There is no database table behind any of it. The panel reads the working tree,
and what it shows is exactly what a reviewer sees in a pull request.

## Product flow

1. Open a Coding workspace or session and choose **Agent Spec-Driven** in the
   workbench.
2. **Install** ASDD for the workspace or Coding Project. The repository-relative
   data directory defaults to `documents/asdd`. Setup writes
   `.evoflux/asdd/config.json`, `.evoflux/asdd/RULES.md`, the catalogue skeleton
   and seven Coding-only Skills under `.evoflux/skills/`. All of it is tracked.
3. **Explore** the repository into the catalogue it just got. `project.md`
   ships as placeholders and every phase reads it first, so the board offers
   `asdd-explore` until someone has described the repository: it fills
   `project.md` with cited claims and writes the `architecture/` and
   `reference/` pages the code justifies, leaving `specs/`, `analysis/` and
   `architecture/decisions/` deliberately empty.
4. **New change** asks for a title, the problem, and what should be true when
   it is done. The problem and the outcome are written straight into the
   proposal's `## Why` and `## What Changes`. The slug, the capabilities and the
   risk tier are the propose phase's to derive — the form keeps them behind a
   disclosure for when you want to set them yourself. The title becomes the
   change's slug: its folder name and the only name anything uses for it.
5. Each phase offers a primary action on the rail. Running one returns a prompt
   naming the Skill and the change folder; the panel drops it into the chat you
   are looking at. No chat owns the change, so any chat can run any phase.
6. The user approves the proposal, the specs, the design where the risk tier
   requires one, and the tasks. Approving tasks is what authorizes product-file
   changes. With **autopilot** on, the agent makes that call itself at each
   gate and stops only where it decides a person is needed.
7. Implementation ticks boxes in `tasks.md`. Verification writes pages under
   `evidence/`. Neither can approve anything.
8. **Archive** folds every delta into its capability spec and moves the folder
   to `changes/archive/YYYY-MM-DD-<change-id>/`.

## The action rail

The rail shows the seven phases, the current one, and one primary action.
Blockers are computed from the files: a missing artifact, a missing approval, an
unchecked task, a requirement with no evidence, a delta whose `MODIFIED` names a
requirement that does not exist. Every blocker names something the user can go
and fix.

When the declared `status` disagrees with the folder — a hand-edited status, an
interrupted run — the rail says so and changes neither side. The file is the
source of truth; which side is wrong is the user's call.

## Autopilot

A change carries `autopilot` in its own `proposal.md`, so it is the change that
is on autopilot rather than a chat or a session. With it on, the rail leads with
**Continue** instead of **Approve**, and approving stays available as an
override.

What the agent clears goes into `auto_approvals`; what a person signs stays in
`approvals`. The approval strip draws them differently — a tick for a signature,
a bot for a clearance — because a reader about to archive needs to know which
gates a person actually read. An agent that wants a person writes a `hold` with
its reason, and the rail puts that above everything else.

Autopilot carries implementation and verification as well — those are not
gates, so the agent finishes the phase and moves the `status` on. The rail
keeps **Continue**, **Run implementation**, **Run verification** and **Mark
ready** beside each other, because autopilot is a default and not a lock.

### The product presses Continue

Clearing a gate and then stopping is not carrying a change: for a while
autopilot meant the agent signed for itself and a person still clicked
**Continue** between every phase, which is most of the work of driving it.

A turn that ends now asks the question the Continue button asks —
`_autopilot_next` on the change's status — and starts that phase instead of
rendering a button. The binding is the transcript: a phase prompt says
``Work on ASDD change `<id>``` and nothing else does, so the newest user
message that matches names the change this chat is carrying. No second
identifier, which rule 2 would forbid anyway.

Whether a hop is allowed is the rail's decision, reused rather than
reimplemented: autopilot off, a `hold`, an unmet gate or a standing blocker all
come back as "no next phase" and end the chain. Two bounds are the loop's own.
A hop that leaves the change exactly where it was — same status, same ticked
tasks, same evidence — gets no successor, because a change that cannot advance
would otherwise re-run its phase every turn. And a chain is capped at twelve
hops, which covers a full cycle with implementation re-entering itself while
tasks remain, and bounds a mistake to a turn count rather than a night. Anyone
speaking in the session clears both.

It still stops at `ready`: archiving folds the catalogue and is a person's
click at every tier.

A `cross_layer` or `critical` change keeps the design gate and the archive for
the user whatever autopilot says, and the archive is refused outright if the
design was cleared rather than signed.

## Views

- **Board** groups open changes by phase: Propose, Specify, Plan, Build, Ready.
- **Table** and **List** show the same set flat.
- A change's detail shows its proposal, deltas, design, tasks and evidence as
  the Markdown they are, plus the approval strip and the rail.

### A project's board spans its repositories

A change lives in exactly one repository, and a Coding project has several. The
board lists every one of them: `GET /asdd/changes` takes the project and reads
each member repository's catalogue, and every change already names the
repository it came from, so the board needs no key of its own. With more than
one repository in scope the panel offers a repository filter and names the
owner on each row, and a change is read, actioned and archived through its own
repository rather than through whichever one the session opened on.

Listing them separately was how a project reported an empty board: a session
opens on one repository — the project's first, by insertion order — and every
change filed next door was invisible from it.

Readiness is per repository for the same reason. One installed repository is
enough for a board, and the repositories still to set up are a banner on it
carrying the setup action. Holding the whole panel until every repository was
installed hid work that already existed, which is the opposite of what the
gate was for: what it protects is the **new-change** form, which still offers
only repositories that are set up.

The merged `capabilities` and `archived` counts come with a per-repository
breakdown, because a spec is a file in one working tree — the catalogue reads
each one from the repository that owns it.

## Delegation

A delegated mission may name `asdd_change_id` and the requirements it owns,
spelled exactly as the change's delta spells them. On handoff the product writes
one evidence page into the change folder recording what the mission reported.
A handoff carrying a runtime-generated completion contract records `machine`
evidence; a self-reported one records `review` evidence and says so.

## Staying current

There is no event stream. Agents write a change's files with the ordinary file
tools rather than through this API, so the server has nothing to push: a
proposal an agent just wrote produces no request the product could observe. An
open panel polls the catalogue instead, every few seconds and on window focus,
and stops when it is not on screen.

## Code owners

| Concern | Path |
|---|---|
| Markdown documents and front matter | `app/services/asdd_document.py` |
| Requirement/scenario grammar | `app/services/asdd_spec_format.py` |
| Catalogue reads and writes | `app/services/asdd_store.py` |
| Phase gates and the action rail | `app/services/asdd_lifecycle.py` |
| API orchestration and phase prompts | `app/services/asdd_service.py` |
| Repository installation | `app/services/asdd_setup_service.py` |
| HTTP surface | `app/api/routes/asdd.py`, `app/api/schemas/asdd.py` |
| Phase Skills and skeleton | `app/asdd_skills/` |
| Panel | `web/src/components/AgentSpecsPanel.tsx`, `web/src/components/asdd/` |
