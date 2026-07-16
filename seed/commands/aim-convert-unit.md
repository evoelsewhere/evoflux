---
description: AIM Phase 2+3 — design (and, once approved, implement) the target mapping for one migration unit.
---

Drive Design and Convert for the migration unit: `$ARGUMENTS`.

1. **Design** — delegate to `aim-target-architect`: produce or refresh `mapping/<unit>.md`, citing only *confirmed* business rules and conforming to `target-conventions.md` / `ui-conventions.md` (if the unit has a UI). Do not propose a different architecture than what the target base already has.
2. Stop for human approval of the mapping before implementation starts.
3. **Convert** — once approved, delegate to `aim-converter`: implement the unit into the target repo in an isolated worktree, write unit tests, and run `aim_compare` against the unit's golden smoke cases, iterating fix → compare until it passes or a reasonable number of rounds is exhausted.
4. Mark the unit `converted` via `aim_units` and hand off to `/aim-compare-unit` for full test compare — a passing smoke run is not equivalence certification.

Reminder: the base (legacy) source is read-only. Nothing in this command ever writes to it.
