# AIM knowledge base — index

This repository is the knowledge base (KB) for an AIM migration project: the team's shared understanding of the legacy system, the target mapping, the test-compare evidence, and the decisions made along the way. See `aim.yaml` for which repos play the source/target roles. See the `aim-kb-conventions` skill (in the EvoFlux repo, `app/agent/builtin_skills/aim-kb-conventions/`) for how to read and write here.

- [`inventory/units.md`](inventory/units.md) — the migration-unit inventory and wave plan.
- [`modules/`](modules/) — per-unit reverse-engineering docs, one file per unit, namespaced by module.
- [`business-rules/`](business-rules/) — extracted business rules, `candidate` until an SME confirms them.
- [`data-dictionary/`](data-dictionary/) — record layouts, copybooks, and table field dictionaries.
- [`interfaces/`](interfaces/) — screens, jobs, and API contracts, including cross-module interfaces.
- [`target-conventions.md`](target-conventions.md) — conventions extracted from the already-scaffolded target base.
- [`ui-conventions.md`](ui-conventions.md) — the project's design system and screen-pattern mapping (if this migration has a UI).
- [`mapping/`](mapping/) — per-unit target design mappings.
- [`decisions/`](decisions/) — architecture decision records, including accepted differences from triage.
- [`golden/`](golden/) — golden-master test cases.
- [`runs/`](runs/) — compare run reports (small; raw actuals are gitignored).

## Log

- (append entries here as the project reaches milestones — wave completions, cutover readiness, etc.)
