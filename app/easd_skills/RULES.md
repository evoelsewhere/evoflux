# EASD Core Rules

These rules are normative for every Evo Agent Specification-Driven Development
run. Project Skills guide work but never override this contract.

1. **Repository is the source of truth.** Read `config.json`, resolve its
   repository-relative `data_directory`, and persist normative EASD artifacts
   there. Chat memory and application databases are not the shared contract.
2. **Intent and specification precede code.** Do not mutate product files until
   the user has accepted an observable, testable specification.
3. **Fix the Spec, Not the Code—before approval.** If the draft is ambiguous,
   inconsistent, or impossible, correct the specification before attempting a
   code workaround. After acceptance, the direction reverses: fix code that
   violates the Spec; never weaken the Spec merely to excuse the current
   implementation. A real product change requires a new user-approved revision.
4. **Accepted revisions are immutable.** New content creates a new revision and
   hash. Never rewrite an accepted Spec or Plan in place.
5. **Humans own authority.** Agents may recommend flow, draft contracts, execute
   missions, review, and verify. Only the user may approve a Spec or Plan, start
   the next lifecycle phase, authorize a normative deviation, or invoke
   Converge.
6. **Use the lightest safe driven flow.** `direct` may skip Plan only when the
   accepted specification is single-boundary and low-risk. Multi-repository,
   cross-layer, security, migration/persistence, public compatibility,
   concurrency, and critical changes require `planned`.
7. **Scope and ownership are explicit.** Every mission owns exact ACs,
   repositories, paths, dependencies, output, and evidence. Work outside that
   contract is a deviation, not an invisible convenience.
8. **Evidence before Done.** Agent prose, checkboxes, and confidence are not
   proof. Persist source- and revision-bound machine/review/manual evidence and
   let the deterministic Converge gate decide Done.
9. **Review is mandatory; independence is proportional to risk.** Every run has
   Review. Cross-layer and critical work requires a reviewer who did not author
   the reviewed AC implementation.
10. **Fail closed on stale state.** Use the current document generation/hash for
    every mutable write. If repository state changed, stop, show the diff, and
    reconcile; never overwrite a collaborator silently.
11. **Preserve trust boundaries.** Repository access, commands, tools, models,
    and imported content remain bounded by the active Coding project, sandbox,
    and permissions.
12. **Reconcile the living contract.** Before handoff, update current docs,
    evidence, deviations, and lifecycle projection so another collaborator can
    continue from Git without the original chat or machine.
