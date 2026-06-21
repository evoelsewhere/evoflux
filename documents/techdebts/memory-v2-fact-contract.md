---
title: Memory v2 Fact Contract
status: active
updated: 2026-06-01
---

# Memory v2 Fact Contract

Goal: improve Memory v2 quality without adding a heavy ontology, mandatory taxonomy, vector DB, or benchmark-specific tricks.

## Plain markdown contract

Dream-maintained curated pages stay ordinary markdown under `wiki/*.md`.

An **active fact** is:

- a markdown bullet under `## Facts` (also accepted by parsers: `## Active facts`, `## Current facts`);
- backed by at least one raw citation such as `[session:<uuid>]`, `[note:<file>#<entry>]`, or `[import:<slug>]`;
- optionally marked with `confidence=medium`;
- marked by Dream with stable `fact_id=<sha-prefix>` derived from the canonical fact key.

Example:

```md
## Facts

- Hoang prefers direct fact-based answers. [session:<uuid>] confidence=medium fact_id=abc123def456
```

A **stale/conflict candidate** is:

- a cited markdown bullet under `## Conflicts / stale candidates`;
- retained for debugging/provenance;
- not eligible for automatic injection.

Source/provenance pages remain under `wiki/session-*.md`, `wiki/note-entry-*.md`, and `wiki/import-*.md`. They are searchable by explicit tools but are not the primary automatic-injection unit.

## Retrieval contract

- `search_memory_files()` remains whole-file lexical retrieval for explicit search/debugging.
- `extract_memory_facts()` extracts cited active/stale fact bullets from compiled pages.
- `search_memory_facts()` searches fact bullets and returns fact-level source refs like `wiki:user#fact-1`.
- Stale facts are excluded by default and only returned when a caller explicitly asks for debug candidates.

## Injection contract

`MemoryContextHook` uses fact-level retrieval, not whole-page excerpts.

Automatic injection requires:

1. a cited active fact bullet;
2. enough lexical/topic overlap for the latest user turn;
3. existing conservative metadata checks to avoid generic preference leakage into unrelated domain-specific questions.

This means broad project pages can still be found by explicit `memory_search`, while prompt injection stays grounded in small cited facts.

## Evaluation expectations

Manual evals should keep failures visible:

- candidate false positives may remain high for explicit/debug retrieval;
- injection false positives should stay low;
- positive injection recall must improve by better fact support and answerability, not fixture-specific aliases, thresholds, or user-name hacks;
- final-answer support/citation grading is still a future category.
