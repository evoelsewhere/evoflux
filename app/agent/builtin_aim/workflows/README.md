# AIM core workflows (draft — inert)

Three generic (stack-agnostic) AIM pipeline definitions, per `documents/research/aim-framework.md` §3.11: `aim-assess`, `aim-convert-unit`, `aim-test-compare`. Written against the Workflows v5 schema (`documents/plans/workflows-feature-plan.md`) so the pipeline shape is fully specified ahead of time, not invented during implementation.

**Status: not executable yet.** Two things have to exist first: the Workflows engine itself (M1-M6, not yet implemented) and a one-line extension to its `scope` enum to add `"aim"` alongside `forge`/`coding`. Until then these files are documentation of intent, validated by hand against the v5 spec (node kinds, edge/`when` semantics, no cycles) rather than by a running engine.

These reference two tools that don't exist yet either: `aim_units` and `aim_compare` (AIM-1). Once AIM-1 and Workflows M1-M6+scope-aim both land, these become the seed for AIM-4.
