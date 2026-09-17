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
5. **Humans own the gates.** Agents draft every artifact, execute tasks, review
   and verify. Only the user approves the proposal, the specs, the design and
   the tasks, and only the user archives.
6. **A delta says what changes, not everything.** Write `## ADDED`,
   `## MODIFIED` and `## REMOVED Requirements` against the capability's current
   spec. Restating unchanged requirements hides the change under its own
   context.
7. **Every requirement carries at least one scenario.** A requirement without a
   `#### Scenario:` that names a **WHEN** and a **THEN** is an intention, not a
   contract, and cannot be verified or approved.
8. **Reuse a capability before coining one.** If a change alters behavior an
   existing `specs/<capability>/spec.md` already contracts, write the delta
   against that capability. A new slug is for behavior the catalogue does not
   cover, and the proposal says which existing capabilities were ruled out.
9. **Evidence before ready.** Prose, checkboxes and confidence are not proof.
   Record machine, review and manual evidence as pages under the change's
   `evidence/`, each naming what it exercised and what it found.
10. **Review is mandatory; independence scales with risk.** Every change is
    reviewed. A `cross_layer` or `critical` change requires a design document
    and a recorded review by someone who did not author the work.
11. **Archive is the only way a spec changes.** Deltas fold into
    `specs/<capability>/spec.md` when the user archives the change, and the
    change folder retires to `changes/archive/YYYY-MM-DD-<change-id>/`. Never
    hand-edit a capability spec to record work a change already describes.
12. **Correct a contradiction; do not route around it.** When a declared status
    disagrees with the files on disk, the product reports it rather than
    rewriting either side. Fix whichever is wrong, in the repository.
13. **Preserve trust boundaries.** Repository access, commands, tools, models
    and imported content stay bounded by the active Coding project, sandbox and
    permissions.
14. **Do not migrate knowledge implicitly.** Setup creates missing ASDD files
    only. Existing repository documentation stays where it is and stays
    authoritative until maintainers move it through an approved change.
