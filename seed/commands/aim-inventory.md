---
description: AIM Phase 0 — build or refresh the migration-unit inventory and propose a wave plan.
---

Act as (or delegate to) `aim-appraiser` for this AIM project's Assess phase.

1. Scope: `$ARGUMENTS` (a module, repo, or subsystem name — if empty, cover the whole base source).
2. Use the code graph (`code_overview`, `code_search`, `code_graph`, `code_path`) to enumerate migration units in scope and their dependencies. Do not guess dependencies from naming — check the graph.
3. For each unit, determine kind, source paths, size, dependencies, and a low/medium/high complexity score.
4. Group units into dependency-respecting waves (a unit's dependencies must be in the same wave or earlier), with shared/leaf units in wave 0.
5. Record the inventory via the `aim_units` tool and write (or update) the human-readable mirror at `inventory/units.md` in the project's KB repo.
6. Stop and present the wave plan for human approval — do not proceed to Understand or Convert for any unit until the plan is approved.
