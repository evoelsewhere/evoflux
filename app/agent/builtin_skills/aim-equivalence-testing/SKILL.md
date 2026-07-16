---
name: aim-equivalence-testing
description: Builds golden-master test coverage and runs functional-equivalence compares between legacy and migrated systems. Use when a migrated unit needs to be proven equivalent to its legacy counterpart, not just "probably correct". Use when designing test plans, golden cases, or canonicalization for a migration test-compare harness.
---

# AIM equivalence testing

## Overview

Test compare is the hardest part of most migration projects — harder than the conversion itself, according to every industry case study this framework draws on. It's hard because there's usually no test suite to inherit (the legacy system's behavior *is* the spec), the legacy environment is often hard to reach, and raw output diffs are dominated by noise (encoding, timestamps, sort order) that has nothing to do with correctness. This skill covers building coverage that actually means something and reading compare runs honestly.

## When to Use

- Designing a test plan for a migration unit — what cases are needed, and why.
- Capturing or constructing golden-master cases (legacy input/output pairs) for a unit.
- Deciding what a canonicalizer profile needs to normalize before a diff is meaningful.
- Running and interpreting `aim_compare` (or an equivalent deterministic compare tool) for a unit.

## When NOT to Use

**When NOT to use:** for classifying an individual diff as a defect vs. an acceptable difference once a compare has already run — that judgment call belongs to the `aim-diff-triage` skill. This skill is about building and running the test, not adjudicating its results.

## The method

1. **Plan by business function, not by code path.** Organize test cases around what the confirmed business rules say should happen — including their documented edge cases and boundary values — rather than just exercising obvious happy-path inputs. A unit with ten business rules and one generic smoke test is not adequately covered, no matter how much code that one test happens to execute.
2. **Cover both sides of every boundary.** If a rule has a threshold, a cutoff date, or a rounding point, you need cases just below, at, and just above it — that's precisely where implementations diverge in practice.
3. **Be honest about provenance.** Every golden case's `meta.yaml` records how it was obtained: `captured` (from a real legacy run — the strongest kind), `prod_log_replay`, or `synthesized` (constructed rather than captured — needs an explicit SME sign-off before anyone treats it as trustworthy). Never record a synthesized case as captured; the entire harness depends on this field being truthful, because a bad "golden" case that's trusted blindly can certify a real defect as equivalent.
4. **Canonicalize before diffing, always.** Encoding differences (EBCDIC vs UTF-8), timestamps, run/request IDs, whitespace, non-deterministic sort order — normalize all of it through a configured profile before comparing. A raw byte-for-byte diff on un-canonicalized output is not a meaningful equivalence check; it's noise.
5. **Compare is deterministic; judgment is not.** The compare tool produces a report — matches, diffs, missing, extra. Reading what a diff *means* (defect vs. acceptable vs. bad golden case) is a separate, higher-judgment step; don't collapse the two.

## Verification

Before calling a unit's test coverage sufficient: does every confirmed business rule with a boundary condition have cases on both sides of it? Does every golden case have an honest, complete `meta.yaml`? Has the canonicalizer profile been checked against a real sample of legacy output to confirm it actually normalizes the noise that shows up in practice, rather than being written from assumptions? If a compare run comes back "all pass" on a unit with thin coverage, treat that as a coverage gap, not a success.
