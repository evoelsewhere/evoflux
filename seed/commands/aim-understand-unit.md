---
description: AIM Phase 1 — reverse-engineer one migration unit into KB module docs and candidate business rules.
---

Act as (or delegate to) `aim-archaeologist` for the migration unit: `$ARGUMENTS`.

1. Confirm the unit's phase is `inventory` (assessed) before starting. Check that every unit it depends on (per the code graph / `aim_units`) already has a `modules/` doc — if not, do those first or say so and stop.
2. Read the unit's own source plus the existing docs (not source) of its already-documented dependencies.
3. Write `modules/<module>/<unit>.md`: purpose, control flow in prose, interfaces, side effects, and anything ambiguous or surprising — flagged explicitly rather than resolved silently.
4. Extract every business decision you find as a candidate rule in its own `business-rules/BR-<MOD>-####.md` file (`status: candidate`), quoting the actual thresholds and conditions rather than paraphrasing them away.
5. Add or update any `data-dictionary/` entries for record layouts, copybooks, or tables you encounter.
6. Mark the unit `understood` via `aim_units` once its doc and candidate rules are written — but do not treat any rule as usable downstream until a human has confirmed it.
