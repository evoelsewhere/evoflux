---
name: aim-diff-triage
description: Classifies functional-equivalence compare-report diffs as defect, acceptable difference, or suspect golden master — always cited, always headed for human review. Use when a test compare run comes back with diffs and someone needs to decide what they mean before a unit can be certified equivalent.
---

# AIM diff triage

## Overview

Every migration project drowns in diffs that turn out not to matter — encoding artifacts, a timestamp, a sort order nobody actually depends on — mixed in with the rare diff that's a genuine defect. The entire value of a triage step is telling those apart reliably; get it wrong in the lenient direction and a real defect quietly ships labeled "expected." This skill exists to make that call defensibly, with a bias toward suspicion, and to make clear that the call is a recommendation for a human, never a final verdict.

## When to Use

- After an `aim_compare` run produces a report with diff clusters needing a disposition — typically the `triage` branch of the `aim-test-compare` pipeline, after a human chose "triage" at the certify gate.

## When NOT to Use

**When NOT to use:** to decide whether test coverage is adequate — that's `aim-equivalence-testing`. Not for making the final equivalence call — triage output always goes to a human; the `equivalent` phase is set only after human certification.

## Your input

`aim_compare` returned (and stored in the KB) `runs/<module>/<name>/<run-id>/report.json` + a readable `report.md`: `verdict`, `diff_count`, and `clusters` — diffs grouped with file and sample lines. Before classifying, read the unit's `modules/` doc and the `business-rules/*.md` it cites; a diff is only judgeable against what the rule says should happen. For suspicious cases, read the golden case's `meta.yaml` — `synthesized` without SME sign-off is the classic bad-golden signature.

## The method

Classify each cluster as exactly one of three things:

1. **`defect`** — the target computed something genuinely different. Route back to the converter with the specific cluster (file, field, the exact divergence), not a vague "doesn't match."
2. **`acceptable_difference`** — the outputs differ but it doesn't matter, **and you can point at exactly why**: a business rule or ADR that establishes the difference is intentional/irrelevant, or a canonicalizer gap you can name precisely (propose the `canonicalizers/` profile change as a diff for a human to approve — never apply it silently). If you cannot cite something specific, it is not acceptable yet — default to `defect` until a human resolves it.
3. **`golden_suspect`** — the legacy side of the golden case itself looks wrong (bad capture, unrepresentative environment, unsigned synthesized case). The case needs a human before its verdict is trusted; the target still gets re-checked later.

## Record the disposition (exact contract)

- `aim_units action=record_run unit="<module>/<name>" run_kind=compare verdict=<fail|acceptable_diff> case_set=<set> report_path=<path> stats={"defects": N, "acceptable": M, "golden_suspect": K}` — your triage verdict row, distinct from the tool's raw pass/fail row.
- Per acceptable difference: `aim_units action=add_link from_ref='unit:<module>/<name>' to_ref='rule:BR-<MOD>-####' link_kind='cites' note='<cluster, why>'` (or the ADR ref). This is the traceability chain an audit follows.

## Why the default is suspicion, not efficiency

The two failure directions are not symmetric. A false `defect` costs someone a few minutes confirming it's fine. A false `acceptable_difference` costs a defect that ships quietly and surfaces in production, in exactly the software that was supposed to have proven itself equivalent before cutover. When genuinely unsure, escalate — don't pick the classification that keeps the pipeline moving fastest.

## Verification

Does every `acceptable_difference` cite a specific rule, ADR, or precisely-named canonicalizer gap — not a general "probably formatting"? Is the reasoning written so the reviewing human could actually disagree, rather than rubber-stamp a label? Did any diff get classified acceptable mainly because reclassifying would be inconvenient? If so, reclassify it. Did the disposition land in `aim_units` (record_run + add_link), not just in prose?
