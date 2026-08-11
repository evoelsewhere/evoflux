---
description: AIM Phase 4 — run functional-equivalence test compare for one migration unit and triage the result.
---

Run test & compare for the migration unit: `$ARGUMENTS` (unit id, optionally followed by a case set — `smoke` or `full`; default `smoke`).

1. Ensure golden-master case coverage exists for this unit (delegate to `aim-test-engineer` to fill gaps first if it doesn't — coverage should be organized by confirmed business rule, including boundary cases, not just happy-path).
2. Run the target and the compare (`aim_compare`) for the requested case set.
3. If the report has no diffs, mark the unit's compare run recorded via `aim_units` and stop — but a unit is only `equivalent` after a human accepts the verdict at the equivalence gate; don't mark it yourself.
4. If there are diffs, delegate to `aim-triage-analyst`: classify each cluster as `defect`, `acceptable_difference` (must cite a rule or ADR), or `golden_suspect`. Route defects back to `aim-converter` for a repair round, then re-compare.
5. Present the final report and triage disposition for human sign-off before recording the unit as `equivalent`.
