---
name: aim-business-rule-extraction
description: Extracts business rules from legacy source into cited, confirmable knowledge-base entries. Use when reading legacy code that encodes business decisions (eligibility checks, rounding, thresholds, special-case handling) that must survive a migration. Use when building the traceability chain a migration project's test compare and audit will depend on.
---

# AIM business rule extraction

## Overview

In a migration project, "the spec" is the legacy system's actual behavior — including the quirky, undocumented decisions nobody remembers making. A business rule extracted vaguely ("handles special pricing cases") is useless downstream: the target-architect can't map it precisely, the test-engineer can't write a boundary case for it, and the triage-analyst can't cite it to justify an "acceptable difference." This skill is about extracting rules with enough precision that they can be implemented, tested, and cited — not summarized into something softer than the code actually says.

## When to Use

- While documenting a legacy unit (this pairs directly with the `aim-legacy-comprehension` skill — do both in the same pass, not as separate trips through the same code).
- When a diff-triage or design conversation needs a rule that hasn'tbeen extracted yet — go back to the source and extract it properly rather than describing it from memory.

## When NOT to Use

**When NOT to use:** for purely technical/structural code with no business decision in it (a data-access helper, a generic string utility) — not everything in a legacy codebase is a business rule, and extracting non-rules as if they were dilutes the catalog. Also not a substitute for SME confirmation — extraction produces *candidates*, never confirmed rules.

## The method

1. **Extract the specific logic, not a paraphrase.** "Rounds tax down to the nearest 1,000" is a business rule. "Handles tax calculation" is not — it's a description of the function's existence. Quote or closely reproduce the actual thresholds, conditions, and edge cases; those specifics are exactly what test compare will need to verify later.
2. **One rule per file, one file per rule.** `business-rules/BR-<MOD>-####.md`, module-prefixed so IDs from different repos or different people never collide. This isn't bureaucracy — file-per-rule is what makes rules independently citable, independently reviewable in a PR, and mergeable without conflict when multiple people are extracting rules in parallel.
3. **Record status as `candidate` until a human confirms it.** Frontmatter carries `id`, `status` (`candidate` | `confirmed`), and the source location(s) the rule came from. Nothing downstream — mapping, test plans, diff triage — should cite a rule that's still a candidate without flagging that it isn't confirmed yet.
4. **Capture edge cases explicitly**, not just the happy-path rule. A rounding rule with a threshold needs the file to say what happens exactly at the threshold, not just "rounds down" — that boundary is precisely where `aim-equivalence-testing` needs a golden case.
5. **When two rules seem to conflict**, don't silently pick a winner — write both down with the conflict noted, and let the SME confirmation pass resolve it.

## Verification

For every candidate rule: does the file cite where in the source it came from? Is the threshold/condition stated precisely enough that someone could write a test case that fails if it's implemented even slightly wrong? Is the status field present and accurate? If a rule reads like a paraphrase rather than a precise restatement of the logic, go back to the source and tighten it.
