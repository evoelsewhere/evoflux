---
title: Memory v2 / Dream Wiki
description: Karpathy-style markdown memory system maintained by Dream with deterministic retrieval and benchmark hooks.
status: hardening
updated: 2026-06-01
---

# Memory v2 / Dream Wiki

**Sources:** `app/services/memory.py`, `app/services/dream.py`, `app/agent/hooks/wiki_injection.py`, `app/agent/tools/builtin/memory_search.py`, `app/core/wiki_seed.py`, [`../../techdebts/memory-v2-fact-contract.md`](../../techdebts/memory-v2-fact-contract.md)

EvoFlux is moving from the legacy taxonomy-heavy wiki to a simpler Karpathy-style Memory v2 system:

1. Raw sources stay canonical.
2. **Dream** maintains editable markdown pages from those sources.
3. Retrieval is benchmarkable through deterministic `memory_search` and LongMemEval-style harnesses.
4. The first implementation avoids a mandatory ontology: no required `USER.md`, `topics/`, `entities/`, `sources/`, `comparisons/`, `INDEX` lint taxonomy, graph DB, or vector DB.

Breaking changes are allowed during the transition. Legacy wiki services still exist for compatibility, but Memory v2 primitives live in `app/services/memory.py`. This work is release hardening, not an experimental-preview feature gate; the known gaps below must be resolved before a normal release claim.

---

## Storage layout

Memory v2 currently reuses `EVOFLUX_WIKI_DIR` as the root while the implementation settles.

```text
{EVOFLUX_WIKI_DIR}/
  SCHEMA.md      # Dream maintainer rules and conventions
  INDEX.md       # human/agent navigation
  LOG.md         # Dream activity log

  notes/         # raw note-tool files; append-only input
    2026-05-31.md

  imports/       # raw imported documents/articles
    karpathy-llm-wiki.md

  wiki/          # compiled memory pages maintained by Dream
    user.md
    EvoFlux.md
    memory-system.md
```

`app/core/wiki_seed.py` seeds the Memory v2 root files and directories. For compatibility during migration it may still seed some legacy paths.

Compiled `wiki/*.md` pages should use small YAML frontmatter that keeps retrieval debuggable without imposing a taxonomy:

```yaml
---
description: Dream v2 compiled memory for session:<uuid>
updated: 2026-05-31
tags: [memory-v2, dream]
memory_kind: conversation   # e.g. profile, conversation, note, import
scope: session              # e.g. user, project, session, note_entry, import
topics: [EvoFlux, memory, response-style]
confidence: medium
sources:
  - session:<uuid>
---
```

`memory_kind`, `scope`, and `topics` are hints for conservative automatic injection and debugging. They are not mandatory directories or ontology tables, and missing metadata falls back to lexical filtering.

---

## Raw sources and citations

| Source type | Canonical source | Citation form |
| --- | --- | --- |
| Chat sessions/messages | SQLite `chat_sessions` + `session_messages` | `session:<uuid>`, `message:<uuid>` |
| Note entries | `notes/*.md` | `note:<filename>#<entry_id>` for Dream state; whole-file search currently returns `note:<filename>` |
| Imports | `imports/*.md` | `import:<slug>` |
| Compiled pages | `wiki/*.md` plus root docs | `wiki:<slug>` |

DB messages are **not** duplicated into `raw/sessions/YYYY-MM-DD/<session-id>.md`; SQLite remains the canonical raw chat store.

---

## Memory service

`app/services/memory.py` provides the Memory v2 primitives:

| Function | Purpose |
| --- | --- |
| `memory_root()` | Current memory root, backed by `EVOFLUX_WIKI_DIR`. |
| `seed_memory()` | Create `SCHEMA.md`, `INDEX.md`, `LOG.md`, `notes/`, `imports/`, and `wiki/`. |
| `validate_memory_path()` | Allow only root Memory v2 files and one-level `notes/`, `imports/`, `wiki/` markdown files. |
| `list_memory_tree()` | Return grouped system/wiki/import/note file metadata. |
| `read_memory_file()` / `write_memory_file()` | Read/write validated Memory v2 markdown files. |
| `search_memory_files()` | Deterministic token-overlap search over Memory v2 markdown files. |
| `extract_memory_facts()` / `search_memory_facts()` | Extract and search cited fact bullets from compiled `wiki/*.md` pages; active facts are separate from stale/conflict candidates. |
| `search_memory_messages()` | Deterministic token-overlap search over visible, non-excluded DB messages. |
| `memory_search()` | Merge file results and optional raw DB message results. |

Search starts with deterministic token overlap for repeatable tests and benchmarks. Embeddings/vector search are intentionally not part of the MVP.

`app/services/memory_vector.py` defines the optional semantic backend seam for future vector search. The default backend is explicitly `disabled`, so Memory v2 still works without embeddings, native dependencies, or a vector database. Runtime settings accept:

```yaml
memory_vector:
  enabled: false
  backend: disabled  # future: turbovec
  embedding_model: null
  dim: null
  index_path: null
```

Selecting `backend: turbovec` is recognized as experimental intent but currently reports unavailable; it does not import `turbovec` or change retrieval behavior yet.

---

## `memory_search` tool

`app/agent/tools/builtin/memory_search.py` is the primary retrieval tool for Memory v2. It searches compiled wiki pages, raw note/import files, root Memory files, and visible chat messages when a DB session is available.

The tool returns cited excerpts such as:

```text
1. source=wiki:user path=wiki/user.md score=0.812
   title: wiki/user.md
   excerpt: Hoang prefers direct, detailed, fact-based dialogue.
```

`wiki_search` remains available for legacy pages under `topics/`, `entities/`, `sources/`, and `comparisons/`.

---

## Prompt injection

`WikiInjectionHook` now reads `wiki/user.md` as a normal markdown page and injects a capped excerpt into the system prompt when present.

- Legacy root `USER.md` is not the Memory v2 injection source.
- The injected user page is capped to keep prompts bounded.
- Other memory pages are not auto-injected; agents should call `memory_search`.

`MemoryContextHook` also runs a conservative automatic lookup against the latest user message and injects a small cited `Relevant memory` block when there are matches. This is the first step toward implicit personalization: durable preferences can help the agent without the user repeating them every turn, while the injected context stays small, cited, and query-relevant.

Automatic injection is stricter than explicit `memory_search`. It searches cited active fact bullets in compiled `wiki/*.md`, ignores stale/conflict candidates, ignores identity-only matches such as “Hoang”, and uses frontmatter `topics` to avoid applying generic preference memory to unrelated domain questions. For example, a `wiki/user.md` page tagged `topics: [preferences, response-style]` can help “How should you answer Hoang?” when it contains a cited active fact, but should not be injected for “What is Hoang's preferred Kubernetes scheduler plugin?” unless there is a Kubernetes-specific cited fact.

Release-readiness note: explicit retrieval and automatic injection are evaluated separately. Explicit `memory_search` is allowed to surface weak cited candidates for debugging; `MemoryContextHook` is the safer path that decides whether those candidates should enter the prompt automatically.

---

## Dream processing state

Memory v2 adds `memory_processed_sources` with migration `00000009_create_memory_processed_sources.py`:

```text
source_type
source_id
content_hash
processed_at
pages_changed
status
error
```

The unique source identity is `(source_type, source_id)`. Content changes are detected by comparing `content_hash`, so missing rows, changed hashes, and failed rows are pending.

Current helper functions in `app/services/dream.py` can hash/select pending sources for:

- DB sessions, excluding Dream's own sessions;
- timestamp-headed note entries;
- import files.

Important transition note: the legacy `run_dream` loop still exists for compatibility and still writes the old taxonomy with `dream_log` / `dream_notes_log`. The explicit v2 maintainer `process_memory_sources()` / `run_memory_maintenance()` is the Memory v2 path. It now does two deterministic steps per pending source:

1. Keep one source-compiled provenance page such as `wiki/session-<uuid>.md`, `wiki/note-entry-<slug>.md`, or `wiki/import-<slug>.md`.
2. Promote durable, cited statements into curated flat pages such as `wiki/user.md`, `wiki/EvoFlux.md`, and `wiki/memory-v2.md`.

The curated pages are still simple markdown, not a mandatory taxonomy. Each active fact is a markdown bullet under `## Facts`, includes a raw source citation like `[session:<uuid>]`, and carries a stable `fact_id=...` marker derived from its canonical content. Dream also records conservative ignored-source notes for opt-out, secret-like, or temporary-noise content without copying the sensitive text.

Dream v2 deduplicates equivalent durable facts by canonical key, merges raw citations onto one active fact line, and records changed/equivalent wording under `## Conflicts / stale candidates` instead of silently duplicating or overwriting. Automatic injection treats that stale/conflict section as non-active; explicit/debug retrieval can still expose it when requested. Dream also filters source-page/frontmatter boilerplate so generated provenance metadata is not promoted back into curated memory.

The deterministic compiler adds frontmatter metadata to source and curated pages:

- `memory_kind`: `conversation`, `note`, or `import` based on source type.
- `scope`: the raw source type (`session`, `note_entry`, or `import`).
- `topics`: a small deterministic token list used by automatic injection reranking and eval debugging.

---

## Manual commands

The `manual/` smoke scripts have been removed. Use the `memory_search` tool and direct service calls for memory inspection and benchmarking.

---

## Benchmark harness

A local LongMemEval-style retrieval harness. It does not download datasets; pass a local JSON/JSONL file.

Run with `python -m app.services.memory_bench` or equivalent benchmark scripts. For the synthetic Memory v2 regression benchmark, seed a matching local corpus and JSONL fixture.

This benchmark is intentionally manual, not a unit test. Unit tests cover parser/search/policy correctness; manual runs record quality metrics and failures.

Outputs are written under:

```text
.EvoFlux/evals/runs/<timestamp>/
  config.json
  results.jsonl
  metrics.json
  failures.jsonl
  candidates.jsonl  # when --write-candidates is set
  report.md
```

Use `--debug-hits` to include matched tokens, missing meaningful tokens, page topics, topic overlap, and rerank multipliers on each result. Use `--write-candidates` to write pre-abstention candidates plus dropped/kept source lists for failure analysis.

Current metrics:

- Positive/answerable rows: Recall@1, Recall@5, Recall@10, MRR@10, and failures.
- Negative/abstention rows: abstention rate, candidate false-positive rate, final false-positive rate, and failures.
- `--mode injection`: searches cited active fact bullets, applies the same MemoryContextHook relevance filter used for automatic prompt injection, and reports `injection_false_positive_rate` separately from candidate false positives.
- Per-type breakdowns when rows include `type` or `question_type`.

Rows are treated as negative/abstention cases when they set `negative: true`, `abstain: true`, `answerable: false`, `should_answer: false`, or have no answers. The harness accepts common query fields (`question`, `query`, `input`, `prompt`) and answer fields (`answer`, `answers`, `evidence`, `reference`).

---

## Known gaps

- Dream v2 currently compiles and promotes facts deterministically; LLM synthesis over those sources is still future work.
- `wiki_search` is still legacy; `memory_search` is the v2 retrieval primitive.
- Existing roots may lack `SCHEMA.md` until seeding runs.
- API routes for Memory v2 are not implemented yet; MVP access is service/manual/tool based.
- The LongMemEval harness is a deterministic baseline, not a complete official benchmark runner.
