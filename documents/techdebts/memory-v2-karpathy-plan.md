---
title: Memory v2 — Karpathy-style Dream Wiki Plan
status: active
updated: 2026-06-01
---

# Memory v2 — Karpathy-style Dream Wiki Plan

## Goal

EvoFlux memory should be a simple, editable, LLM-maintained markdown wiki compiled from canonical raw sources, with raw fallback search and benchmarkable retrieval quality.

The design adapts Karpathy's LLM Wiki pattern directly:

1. **Raw sources** stay canonical and mostly immutable.
2. **Dream** maintains a markdown wiki from those raw sources.
3. **SCHEMA.md** defines the maintainer rules and conventions.
4. **INDEX.md** helps humans and agents navigate the wiki.
5. **LOG.md** records Dream activity.
6. **memory_search** searches wiki + raw sources with citations.

This intentionally avoids a heavy memory ontology. No mandatory `USER.md`, `topics/`, `entities/`, `sources/`, `comparisons/`, graph DB, or structured fact table for the first implementation.

## Non-goals for v2 MVP

- Do not duplicate every DB session into markdown by default.
- Do not require a rigid wiki taxonomy.
- Do not start with embeddings/vector DB.
- Do not make Dream the only retrieval path; raw DB fallback remains available.
- Do not enforce pure YAML user memory.

## Storage layout

`{EVOFLUX_MEMORY_DIR}` initially reuses the existing wiki root setting/path unless renamed later.

```text
{EVOFLUX_MEMORY_DIR}/
  SCHEMA.md
  INDEX.md
  LOG.md

  notes/
    2026-05-31.md

  imports/
    karpathy-llm-wiki.md

  wiki/
    user.md
    EvoFlux.md
    memory-system.md
    coding-style.md
    decisions.md
```

### Raw source of truth

| Source type | Canonical raw source |
| --- | --- |
| Chat sessions/messages | SQLite `chat_sessions` + `session_messages` |
| Notes | `notes/*.md` |
| Imported docs/articles | `imports/*.md` |
| Compiled memory | `wiki/*.md` |
| Navigation/activity/schema | `INDEX.md`, `LOG.md`, `SCHEMA.md` |

DB sessions are raw sources even though they are not files. Wiki citations should use stable source references that can resolve back to DB rows.

## Source references

Use URI-like refs in wiki pages and search results:

```text
session:<session_uuid>
message:<message_uuid>
note:<filename>#<entry_id>
import:<slug>
wiki:<slug>
```

Examples:

```markdown
Sources:
- session:019e7e9e-4a49-7770-8cd3-19c5e85d575a
- message:019e7ea1-...
- note:2026-05-31.md#1432-utc-a7f3
- import:karpathy-llm-wiki
```

## Processing state

Replace filename-only/session-only processing state with content-aware source processing.

Proposed table:

```text
memory_processed_sources
  id integer primary key
  source_type text          # session | note_entry | import
  source_id text            # session uuid, note entry id, import slug
  content_hash text
  processed_at datetime
  pages_changed text|null   # JSON array
  status text               # processed | skipped | failed
  error text|null
```

Rules:

- For sessions, hash visible/non-excluded messages.
- For note entries, hash each timestamped entry, not the daily note filename.
- For imports, hash file content.
- If content hash changes, source is pending again.
- Failed sources remain retryable and record the error.

## Dream maintainer contract

Keep the term **Dream** externally and internally as the user-facing concept. Dream v2 is the wiki maintainer.

Current implementation note: `process_memory_sources()` is deterministic. It keeps raw-source compiled pages for provenance and promotes simple durable statements into curated flat pages (`wiki/user.md`, `wiki/EvoFlux.md`, `wiki/memory-v2.md`) with inline source citations. This is intentionally conservative and not full LLM synthesis yet.

Dream input:

- `SCHEMA.md`
- `INDEX.md`
- one source payload (DB session transcript, note entry, or import file)
- small search result set of likely related wiki pages

Dream output:

- edits to `wiki/*.md`
- edit to `INDEX.md`
- append to `LOG.md`

Rules for Dream:

- Never edit `notes/` or `imports/`.
- Never alter DB messages.
- Prefer updating existing wiki pages over creating duplicates.
- Create new wiki pages only when useful for future recall/reasoning.
- Cite source IDs.
- Do not store secrets, credentials, private keys, or temporary noise.
- Respect explicit “do not remember this” requests.
- If a source contradicts an older wiki claim, update the claim and mention that the older claim was superseded.
- Keep `INDEX.md` concise and navigable.
- Append exactly one service-visible activity entry to `LOG.md` per successful run.

## Search MVP

Add `memory_search` as the primary memory tool. Keep `wiki_search` only as a compatibility wrapper or alias later.

Initial deterministic search, no embeddings:

1. Search `INDEX.md`.
2. Search `wiki/*.md`.
3. Search `notes/*.md` and `imports/*.md`.
4. Search DB session/message text.
5. Rank by token overlap / simple BM25-ish scoring.
6. Return structured results with source refs, excerpts, and scores.

Later improvements only if benchmarks demand them:

- SQLite FTS5.
- Body-aware BM25.
- Optional local embeddings.
- Optional reranker.

## Prompt injection

Remove the special pure-YAML `USER.md` requirement.

Use `wiki/user.md` as a normal markdown page. Initial prompt injection can be:

- capped excerpt of `wiki/user.md` if present;
- hard cap around 4k chars;
- otherwise rely on `memory_search`.

Do not auto-inject the whole wiki.

## Migration

Breaking changes are acceptable. Keep migration simple:

```text
USER.md              -> wiki/user.md
topics/*.md          -> wiki/*.md
entities/*.md        -> wiki/*.md
comparisons/*.md     -> wiki/*.md
sources/*.md         -> wiki/source-*.md or imports/legacy-source-*.md
notes/*.md           -> notes/*.md
INDEX.md             -> INDEX.md
LOG.md               -> LOG.md
```

Avoid perfect compatibility. Provide a one-time migration helper or startup migration if old layout is detected.

## Manual tooling

Manual commands around memory and Dream have been removed. Use the `memory_search` tool and direct service calls for memory inspection and benchmarking.

The benchmark harness does not download datasets; provide a local JSON/JSONL
file with `--data`.

Benchmark outputs:

```text
.EvoFlux/evals/runs/<timestamp>/
  config.json
  results.jsonl
  metrics.json
  failures.jsonl
  report.md
```

## Benchmark plan

Implement benchmark harness early enough to compare memory designs.

### LongMemEval

Primary benchmark for long-term chat memory.

Modes:

- `raw`: search DB/session raw sources only.
- `wiki`: search compiled wiki only.
- `wiki-plus-raw`: search wiki first with raw fallback.

Metrics:

- Recall@1
- Recall@5
- Recall@10
- MRR@10
- per question type

### LoCoMo

Second benchmark for natural long conversation memory and temporal/adversarial questions.

### EvoFlux lifecycle tests

Custom manual tests for:

- note -> Dream -> wiki -> future answer
- same-day note append after prior processing
- preference update / supersession
- abstention when memory is absent
- source citation resolution
- wiki drift / duplicate pages

## Implementation order

1. Seed new layout and path validation.
2. Add migration helper from old wiki layout.
3. Add processing-state DB model + Alembic migration.
4. Add memory tree/read/write/search service MVP.
5. Add `memory_search` tool.
6. Update prompt injection to capped `wiki/user.md`.
7. Rework Dream to process DB sessions, note entries, and imports into flat `wiki/`.
8. Add manual memory commands.
9. Add LongMemEval retrieval harness.
10. Update docs.

## Quality gates

Before calling Memory v2 “good”:

- `memory_search` returns structured citations for wiki and raw DB results.
- Same-day appended notes are processed by entry hash, not skipped by filename.
- Dream never modifies `notes/` or `imports/`.
- `wiki/user.md` injection is capped.
- LongMemEval retrieval harness can run in at least raw mode.
- Wiki pages can cite `session:`, `message:`, `note:`, and `import:` refs.
