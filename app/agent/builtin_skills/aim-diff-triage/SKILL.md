---
name: aim-diff-triage
description: Classifies functional-equivalence compare-report diffs as defect, acceptable difference, or suspect golden master — always cited, always headed for human review. Use when a test compare run comes back with diffs and someone needs to decide what they mean before a unit can be certified equivalent.
---

# AIM diff triage

## Overview

Every migration project drowns in diffs that turn out not to matter — encoding artifacts, a timestamp, a sort order nobody actually depends on — mixed in with the rare diff that's a genuine defect. The entire value of a triage step is telling those apart reliably; get it wrong in the lenient direction and a real defect quietly ships labeled "expected." This skill exists to make that call defensibly, with a bias toward suspicion, and to make clear that the call is a recommendation for a human, never a final verdict.

## When to Use

- After an `aim_compare` (or equivalent) run produces a report with one or more diff clusters that need a disposition before the unit can move toward "equivalent".

## When NOT to Use

**When NOT to use:** to decide whether test coverage is adequate in the first place — that's `aim-equivalence-testing`. Also not appropriate for making the final equivalence call for a unit — triage output is always subject to a human gate; don't skip straight from a triage classification to marking a unit certified.

## The method

Classify each diff cluster as exactly one of three things:

1. **`defect`** — the target computed something genuinely different from the legacy system. Route back to the converter with the specific diff, not a vague "doesn't match."
2. **`acceptable_difference`** — the outputs differ but it doesn't matter, **and you can point at exactly why**: a specific business rule or ADR that establishes the difference is intentional or irrelevant, or a canonicalizer gap you can name precisely (this diff is a timestamp format nobody depends on; propose the profile change). If you cannot cite something specific, this is not an acceptable difference yet — default to `defect` until the ambiguity is resolved by a human, rather than rounding up to "probably fine."
3. **`golden_suspect`** — the legacy side of the golden case itself looks wrong (a bad capture, a synthesized case that doesn't reflect real legacy behavior). This doesn't clear the target of needing to be checked again later; it means the case needs a human to look at before its verdict is trusted at all.

## Why the default is suspicion, not efficiency

The two failure directions are not symmetric. A false `defect` costs someone a few minutes confirming it's actually fine. A false `acceptable_difference` costs a defect that ships quietly and surfaces in production, in exactly the software that was supposed to have proven itself equivalent before cutover. When genuinely unsure, escalate — don't pick the classification that keeps the pipeline moving fastest.

## Verification

Before finalizing a triage pass: does every `acceptable_difference` cite a specific rule, ADR, or precisely-named canonicalizer gap — not a general impression that it's "probably formatting"? Is the reasoning written clearly enough that the human reviewing it could actually disagree with you if you got it wrong, rather than just seeing a label and rubber-stamping it? Did any diff get classified acceptable mainly because reclassifying it as a defect would be inconvenient? If so, reclassify it.
