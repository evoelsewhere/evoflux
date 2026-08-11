---
name: aim-business-rule-extraction
description: Extracts business rules from legacy source into cited, confirmable knowledge-base entries. Use when reading legacy code that encodes business decisions (eligibility checks, rounding, thresholds, special-case handling) that must survive a migration. Use when building the traceability chain a migration project's test compare and audit will depend on.
---

# AIM business rule extraction

## Overview

In a migration project, "the spec" is the legacy system's actual behavior — including the quirky, undocumented decisions nobody remembers making. A business rule extracted vaguely ("handles special pricing cases") is useless downstream: the target-architect can't map it precisely, the test-engineer can't write a boundary case for it, and the triage-analyst can't cite it to justify an "acceptable difference." This skill is about extracting rules with enough precision that they can be implemented, tested, and cited — not summarized into something softer than the code actually says.

## When to Use

- While documenting a legacy unit (pairs with `aim-legacy-comprehension` — one pass over the code, not two).
- When a diff-triage or design conversation needs a rule that hasn't been extracted yet — go back to the source and extract it properly rather than describing it from memory.

## When NOT to Use

**When NOT to use:** for purely technical/structural code with no business decision in it (a data-access helper, a generic string utility) — extracting non-rules dilutes the catalog. Also not a substitute for SME confirmation — extraction produces *candidates*, never confirmed rules.

## The file contract

One rule per file at `business-rules/BR-<MOD>-####.md`, module-prefixed so IDs never collide across repos or parallel extractors. Frontmatter:

```yaml
id: BR-CORE-0007
status: candidate        # candidate | confirmed — only a human review flips it
unit: core-batch/EODCLOSE     # the unit it was extracted from
source: [cbl/EODCLOSE.cbl:214-231]   # exact location(s) of the logic
```

Body: the precise rule statement, the exact thresholds/conditions/edge cases (quote or closely reproduce the code's logic), and any observed exceptions. After writing, link it: `aim_units action=add_link from_ref='rule:BR-<MOD>-####' to_ref='unit:<module>/<name>' link_kind='extracted_from'`.

## The method

1. **Extract the specific logic, not a paraphrase.** "Rounds tax down to the nearest 1,000" is a business rule. "Handles tax calculation" is a description of the function's existence. The specifics are exactly what test compare will verify later.
2. **One rule per file, one file per rule.** File-per-rule is what makes rules independently citable, independently reviewable in a PR, and mergeable without conflict when several people extract in parallel.
3. **`status: candidate` until a human confirms it** — by PR review on the KB repo, so the approval is in git history. Nothing downstream (mapping, test plans, triage citations) may treat a candidate as confirmed without flagging it.
4. **Capture edge cases explicitly**, not just the happy path. A rounding rule with a threshold must state what happens exactly at the threshold — that boundary is precisely where `aim-equivalence-testing` needs golden cases on both sides.
5. **When two rules seem to conflict**, write both down with the conflict noted and let the SME confirmation pass resolve it — never silently pick a winner.

## Verification

For every candidate rule: does the frontmatter carry `id`, `status`, `unit`, and exact `source` locations? Is the threshold/condition stated precisely enough that a test could fail if it's implemented even slightly wrong? Was the `extracted_from` link recorded? If a rule reads like a paraphrase rather than a precise restatement, go back to the source and tighten it.
