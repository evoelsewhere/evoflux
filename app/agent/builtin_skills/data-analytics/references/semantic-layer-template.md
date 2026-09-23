# Semantic Layer Template

File shapes for a generated `<area>-semantic-layer` skill. Keep `SKILL.md` small and operational; put metric dictionaries, table catalogs, query patterns, and evidence in references.

## Contents

- Directory layout
- Generated SKILL.md
- Generated semantic-layer.md
- Generated source-inventory.md
- Generated evidence.md
- Drafting rules

## Directory layout

```text
<area>-semantic-layer/
  SKILL.md
  references/
    semantic-layer.md
    source-inventory.md
    evidence.md          optional
```

Split further (`metrics.md`, `tables.md`, `query-patterns.md`, `gotchas.md`) only when the area is large; link each split file from `SKILL.md`. Use one directory per area.

## Generated SKILL.md

```markdown
---
name: <area>-semantic-layer
description: Provides source-backed data context for <area>: canonical definitions of <key metrics>, table choice (<key tables>), joins, filters, dashboard reconciliation, freshness, and known caveats. Use when answering or checking <area> metric questions, writing <area> SQL, or reconciling <area> dashboards.
---

# <Area> Semantic Layer

Answer <area> data questions with the source-backed context in LINK(references/semantic-layer.md).

## Start here

1. Read LINK(references/semantic-layer.md).
2. Use the listed canonical metrics, tables, grains, joins, filters, and caveats.
3. Check freshness before answering time-sensitive questions.
4. When sources disagree or coverage is weak, say so and verify against the cited source.

## References

- LINK(references/semantic-layer.md): metrics, tables, filters, query patterns, gotchas, freshness, open questions. Read for every <area> data question.
- LINK(references/source-inventory.md): sources checked, coverage, permissions, update boundaries. Read when refreshing the layer or judging source coverage.
- LINK(references/evidence.md): detailed provenance. Read when a fact is disputed or high stakes.

## Answering rules

- This skill guides source selection; it does not replace live reads.
- Preserve metric grain, time zone, date columns, filters, and join keys.
- A data question answered with SQL is not a request for SQL; show SQL only when the user asks to see, write, review, or debug it.
- Label stale, inferred, partial, or conflicted evidence.
```

In the generated file, write each `LINK(x)` as a standard Markdown link whose text and target are both `x`; the placeholder only keeps this template from linking to files that do not exist here. Drop the `evidence.md` bullet when that file is not created.

## Generated semantic-layer.md

Path: `<area>-semantic-layer/references/semantic-layer.md`.

```markdown
# <Area> Semantic Layer

## Quick reference

- Area:
- Intended users:
- Coverage level: Limited | Directional | Strong | Conflicted | Blocked
- Last synthesized: <date>
- Freshness expectations:
- Default date and time zone rules:

## Entity clarification

| Entity | Means | Does not mean | Primary IDs | Grain notes | Sources |
| --- | --- | --- | --- | --- | --- |

## Key metrics

| Metric | Definition | Numerator | Denominator | Time grain | Canonical source | Caveats |
| --- | --- | --- | --- | --- | --- | --- |

## Standard filters and dimensions

| Filter or dimension | Default logic | Override when | Applies to | Sources |
| --- | --- | --- | --- | --- |

## Key tables

| Table | When to use | Grain | Join keys | Freshness | Caveats | Sources |
| --- | --- | --- | --- | --- | --- | --- |

## Query patterns

- Pattern:
  - Use when:
  - Key tables:
  - Required filters:
  - Common joins:
  - Example skeleton:

## Gotchas

- Gotcha:
  - Impact:
  - How to avoid:
  - Source:

## Related dashboards and docs

| Source | Use it for | Caveats |
| --- | --- | --- |

## Open questions

- Question:
  - Why it matters:
  - Best owner or source to check next:
```

## Generated source-inventory.md

Path: `<area>-semantic-layer/references/source-inventory.md`. Create it whenever the generated skill is written. Intake-only runs may return the same inventory in chat.

```markdown
# Source Inventory

## Coverage

- Coverage level:
- Sources checked:
- Missing high-value lanes:
- Rejected or lower-confidence candidates:

## Sources

| Source | Type | Locator | Tool used | Permission status | Last checked | Supports | Gaps or caveats | Refresh eligible | Update boundary |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
```

`Sources checked`, `Missing high-value lanes`, and `Rejected or lower-confidence candidates` are the pre-save checkpoint. `Refresh eligible` separates sources a scheduled refresh can poll directly from ones that need a manual export, one-off permission, or user review. `Update boundary` says whether a refresh may update references automatically, must draft a proposed change, or may only report changes.

## Generated evidence.md

Path: `<area>-semantic-layer/references/evidence.md`. Create it only when separate evidence tracking helps (conflicting sources, several high-stakes metrics, a large crawl); small layers keep source pointers in `semantic-layer.md`.

```markdown
# Evidence Register

| Fact or claim | Source type | Source link or path | Retrieved or observed | Confidence | Notes |
| --- | --- | --- | --- | --- | --- |
```

## Drafting rules

- Durable semantic facts go in the generated references, not chat-only prose.
- Keep setup policy and evidence procedures out of the generated `SKILL.md`.
- Keep the source inventory current enough for a scheduled refresh to know what to check and what it may change.
- Use source links, file paths, dashboard IDs, table names, and repo paths as provenance.
- Label stale, inferred, query-history-only, or team-communication-only facts.
- Record unresolved conflicts as open questions.
- No raw sensitive data, credentials, long message quotes, or copied dashboard exports.
