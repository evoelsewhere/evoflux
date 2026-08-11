---
name: aim-equivalence-testing
description: Builds golden-master test coverage and runs functional-equivalence compares between legacy and migrated systems. Use when a migrated unit needs to be proven equivalent to its legacy counterpart, not just "probably correct". Use when designing test plans, golden cases, or canonicalization for a migration test-compare harness.
---

# AIM equivalence testing

## Overview

Test compare is the hardest part of most migration projects — harder than the conversion itself, according to every industry case study this framework draws on. It's hard because there's usually no test suite to inherit (the legacy system's behavior *is* the spec), the legacy environment is often hard to reach, and raw output diffs are dominated by noise (encoding, timestamps, sort order) that has nothing to do with correctness. This skill covers building coverage that actually means something and running the compare harness correctly.

## When to Use

- Designing a test plan for a migration unit — what cases are needed, and why.
- Capturing or constructing golden-master cases (legacy input/output pairs) for a unit.
- Deciding what a canonicalizer profile needs to normalize before a diff is meaningful.
- Running and interpreting `aim_compare` for a unit.

## When NOT to Use

**When NOT to use:** for classifying an individual diff as defect vs. acceptable once a compare has run — that's `aim-diff-triage`. This skill builds and runs the test; it doesn't adjudicate results.

## The harness contract (exact paths and calls)

1. **Goldens** live in the KB at `golden/units/<module>/<name>/cases/<case-set>/` — case inputs plus an `expected/` directory holding the legacy outputs, plus `meta.yaml`. Standard case sets: `smoke` (small, fast — the converter's repair loop runs this) and `full` (the certification run).
2. **`meta.yaml` provenance is non-negotiable**: `provenance: captured` (from a real legacy run — strongest), `prod_log_replay`, or `synthesized` (constructed — requires an explicit SME sign-off note before anyone trusts it). Never record a synthesized case as captured; a bad "golden" trusted blindly can certify a real defect as equivalent. Record how to re-produce the capture (command, environment, date).
3. **Actuals**: run the target side (rulebook packs may ship `runners/run_legacy.sh` / `runners/run_target.sh` with the invocation contract) and write outputs to `.aim-actuals/<module>/<name>/<case-set>/` under the KB root — the default `actual_dir` that `aim_compare` diffs against.
4. **Compare**: `aim_compare unit="<module>/<name>" case_set=smoke|full [profile=...] [actual_dir=...]`. The tool canonicalizes BOTH sides with the project profile (`aim.yaml`'s `compare_default_profile`, defined in the rulebook's `canonicalizers/*.yaml` — masks, sort rules, encoding normalization), diffs deterministically, writes `runs/<module>/<name>/<run-id>/report.{json,md}` in the KB, records the run row (it appears in Runs & Reports with a Discussion link), and returns JSON: `verdict` (`pass|fail|error`), `diff_count`, `clusters`, `report_path`. `verdict=error` with "No golden case…" means coverage is missing — report that; don't fabricate an expected directory.

## The method

1. **Plan by business function, not by code path.** Organize cases around what the confirmed business rules say should happen — including documented edge cases and boundary values — not just happy-path inputs. A unit with ten rules and one generic smoke test is not covered, no matter how many lines that test executes.
2. **Cover both sides of every boundary.** A threshold, cutoff date, or rounding point needs cases just below, at, and just above it — that's where implementations diverge.
3. **Canonicalize before diffing, always.** If a diff is pure noise (timestamp, run id, EBCDIC/UTF-8 artifact, nondeterministic sort), the fix is a canonicalizer-profile change proposed for human approval — not a looser eyeball on the raw diff.
4. **Compare is deterministic; judgment is not.** The tool produces matches/diffs/missing/extra. What a diff *means* is a separate, higher-judgment step (`aim-diff-triage`) behind a human gate — don't collapse the two.

## Verification

Does every confirmed rule with a boundary have cases on both sides? Does every golden case have an honest, complete `meta.yaml`? Was the canonicalizer profile checked against a real sample of legacy output (not written from assumptions)? If a compare returns all-pass on thin coverage, report it as a coverage gap, not a success — the certify gate needs that caveat in its body.
