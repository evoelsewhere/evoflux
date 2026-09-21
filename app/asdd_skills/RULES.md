# ASDD Core Rules

These rules are normative for every Agent Specification-Driven Development
change. Project Skills guide work but never override this contract.

1. **The repository is the source of truth.** A change is the directory
   `changes/<change-id>/`; its phase is the `status` field in `proposal.md`; a
   capability's contract is `specs/<capability>/spec.md`. There is no second
   record to reconcile, and nothing outside these files may decide what a change
   currently is.
2. **Identity is a slug, and only a slug.** A change is named once, in
   kebab-case, and that name is its directory, its URL and the way every agent
   and every chat refers to it. Never mint a second identifier — no UUID, no
   content hash, no session binding — and never make an operation depend on
   restating one.
3. **Specification precedes code.** Do not modify product files until the user
   has approved a delta that states the intended behavior as requirements and
   scenarios.
4. **Fix the spec, not the code — before approval.** If a draft is ambiguous,
   inconsistent or impossible, correct the specification. After approval the
   direction reverses: fix code that violates the spec; never weaken the spec to
   excuse an implementation. A real product change is a new delta.
5. **Humans own the gates, and autopilot does not forge their signature.**
   Agents draft every artifact, execute tasks, review and verify. By default
   only the user approves the proposal, the specs, the design and the tasks,
   and only the user archives. When `autopilot: true` is set on a change, an
   agent may pass a gate on its own judgment — but it records that under
   `auto_approvals`, never under `approvals`. The two maps exist so the
   repository can never claim a person read something no person read.
   Autopilot never covers a gate the risk tier reserves: `cross_layer` and
   `critical` keep `design` and the archive for the user, always.
6. **Under autopilot, stopping is a first-class outcome.** An agent that is
   unsure, that finds the change widening past its proposal, or that is about
   to commit the repository to something it would want a second opinion on,
   writes a `hold` in `proposal.md` naming the gate and the reason, leaves
   `status` where it is, and says so in the chat. Passing every gate is not the
   goal; passing the ones that deserve to pass is.
7. **Ask; do not defer.** When a phase meets a question it cannot answer from
   the repository and the approved artifacts — a format, a default, a boundary,
   a compatibility call — it calls `ask_user` and records the answer. Writing
   the question into a document and carrying on is not deferring the decision;
   it is making it silently and hiding that you did. A `design.md` that still
   lists `## Open questions` cannot be approved, and under autopilot an
   unanswered question is a `hold`, not a guess.
8. **A delta says what changes, not everything.** Write `## ADDED`,
   `## MODIFIED` and `## REMOVED Requirements` against the capability's current
   spec. Restating unchanged requirements hides the change under its own
   context.
9. **Every requirement carries at least one scenario.** A requirement without a
   `#### Scenario:` that names a **WHEN** and a **THEN** is an intention, not a
   contract, and cannot be verified or approved.
10. **Reuse a capability before coining one.** If a change alters behavior an
   existing `specs/<capability>/spec.md` already contracts, write the delta
   against that capability. A new slug is for behavior the catalogue does not
   cover, and the proposal says which existing capabilities were ruled out.
11. **Evidence before ready.** Prose, checkboxes and confidence are not proof.
   Record machine, review and manual evidence as pages under the change's
   `evidence/`, each naming what it exercised and what it found.
12. **Review is mandatory; independence scales with risk.** Every change is
    reviewed. A `cross_layer` or `critical` change requires a design document
    and a recorded review by someone who did not author the work.
13. **Archive is the only way a spec changes.** Deltas fold into
    `specs/<capability>/spec.md` when the user archives the change, and the
    change folder retires to `changes/archive/YYYY-MM-DD-<change-id>/`. Never
    hand-edit a capability spec to record work a change already describes.
14. **Correct a contradiction; do not route around it.** When a declared status
    disagrees with the files on disk, the product reports it rather than
    rewriting either side. Fix whichever is wrong, in the repository.
15. **Preserve trust boundaries.** Repository access, commands, tools, models
    and imported content stay bounded by the active Coding project, sandbox and
    permissions.
16. **Do not migrate knowledge implicitly.** Setup creates missing ASDD files
    only. Existing repository documentation stays where it is and stays
    authoritative until maintainers move it through an approved change.
17. **Every durable page has one home, and the home decides the rules.** The
    catalogue is not one pile of Markdown: `specs/` states behavior the system
    guarantees, `architecture/` states the boundaries it is built from,
    `architecture/decisions/` records why those boundaries are where they are,
    `reference/` states the exact surface a caller types, and `analysis/`
    records an investigation at a date. Each directory's `README.md` says what
    belongs in it and what does not; read that before adding a page, and put
    the page where it belongs rather than where the change happened to start.
18. **Durable pages ship with the change that makes them true.** A change that
    moves a boundary, decides something durable, or alters a public surface
    updates `architecture/`, `architecture/decisions/` and `reference/` in the
    same change as the code — not afterwards, and not in the change folder as
    a copy. Only `specs/` waits for the archive, because only `specs/` is
    approved as a delta. A reference page that lags its code is not an
    omission; it is the product stating something untrue.
