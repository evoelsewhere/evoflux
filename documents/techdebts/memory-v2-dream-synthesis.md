---
title: Memory v2 Dream Synthesis Iteration
status: active
updated: 2026-06-01
---

# Memory v2 Dream Synthesis Iteration

## What changed

Dream v2 now does more than flat source compilation:

1. Keeps one deterministic provenance page per raw source under `wiki/`.
2. Extracts simple durable statements into curated flat pages:
   - `wiki/user.md`
   - `wiki/EvoFlux.md`
   - `wiki/memory-v2.md`
3. Preserves inline raw citations on every promoted fact.
4. Records possible duplicates/changed facts under `Conflicts / stale candidates` instead of silently overwriting.
5. Records opt-out/secret/noise skips without copying sensitive text.
6. Writes changed curated pages into `memory_processed_sources.pages_changed`.

This remains a simple Karpathy-style markdown wiki. The curated pages are conventional useful pages, not mandatory taxonomy directories or a database ontology.

## Current limits

- Synthesis is deterministic and lexical; it is not a general LLM summarizer yet.
- Fact grouping is intentionally conservative and supports only broad durable categories.
- Conflict handling surfaces possible duplicates/staleness but does not resolve truth automatically.
- Conflict handling surfaces possible duplicates/staleness but does not resolve truth automatically.
- Release-hardening tests now cover duplicate fact merging, raw citations, opt-out/secret skipping, and basic conflict recording.

## Next useful work

- Add manual eval rows for source citation correctness, stale facts, and multi-session durable preferences.
- Add LoCoMo-style temporal/context questions before calling Memory v2 stable.
- Consider optional LLM-assisted synthesis after deterministic behavior is stable and benchmarked.
