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

There is no database table behind any of it. The panel reads the working tree,
and what it shows is exactly what a reviewer sees in a pull request.

## Product flow

1. Open a Coding workspace or session and choose **Agent Spec-Driven** in the
   workbench.
2. **Install** ASDD for the workspace or Coding Project. The repository-relative
   data directory defaults to `documents/asdd`. Setup writes
   `.evoflux/asdd/config.json`, `.evoflux/asdd/RULES.md`, the catalogue skeleton
   and six Coding-only Skills under `.evoflux/skills/`. All of it is tracked.
3. **New change** asks for a title, the problem, and what should be true when
   it is done. The problem and the outcome are written straight into the
   proposal's `## Why` and `## What Changes`. The slug, the capabilities and the
   risk tier are the propose phase's to derive — the form keeps them behind a
   disclosure for when you want to set them yourself. The title becomes the
   change's slug: its folder name and the only name anything uses for it.
4. Each phase offers a primary action on the rail. Running one returns a prompt
   naming the Skill and the change folder; the panel drops it into the chat you
   are looking at. No chat owns the change, so any chat can run any phase.
5. The user approves the proposal, the specs, the design where the risk tier
   requires one, and the tasks. Approving tasks is what authorizes product-file
   changes. With **autopilot** on, the agent makes that call itself at each
   gate and stops only where it decides a person is needed.
6. Implementation ticks boxes in `tasks.md`. Verification writes pages under
   `evidence/`. Neither can approve anything.
7. **Archive** folds every delta into its capability spec and moves the folder
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
leads with **Continue** the whole way and keeps **Run implementation**, **Run
verification** and **Mark ready** beside it, because autopilot is a default and
not a lock. It stops at `ready`: archiving is a person's click at every tier.

A `cross_layer` or `critical` change keeps the design gate and the archive for
the user whatever autopilot says, and the archive is refused outright if the
design was cleared rather than signed.

## Views

- **Board** groups open changes by phase: Propose, Specify, Plan, Build, Ready.
- **Table** and **List** show the same set flat.
- A change's detail shows its proposal, deltas, design, tasks and evidence as
  the Markdown they are, plus the approval strip and the rail.

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
