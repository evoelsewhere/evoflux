---
title: Memory v2 Turbovec Backend Plan
status: proposed
updated: 2026-06-01
---

# Memory v2 Turbovec Backend Plan

Turbovec is a promising future local ANN backend for Memory v2, but it should remain optional until the deterministic markdown + lexical path is stable.

## Current decision

- Keep Memory v2 default retrieval as markdown + deterministic lexical search.
- Add only a narrow optional vector backend interface now.
- Do not add `turbovec` as a required dependency.
- Do not make semantic search part of correctness-critical unit tests.

## Why Turbovec is interesting

From `https://github.com/RyanCodrai/turbovec`:

- Rust vector index with Python bindings.
- `pip install turbovec` package exists.
- `IdMapIndex` supports stable external `uint64` IDs and deletes.
- Index persistence via `write()` / `load()`.
- Search-time allowlists for hybrid retrieval / ACL / time windows.
- Local-only; no managed service.
- Compression-oriented TurboQuant design claims much lower RAM than float32 vectors.

## Why not default yet

EvoFlux still needs product-level semantic-memory primitives before choosing a backend:

1. Stable chunk IDs for `wiki/*.md`, DB messages, notes, and imports.
2. Embedding model selection and dimension tracking.
3. Rebuild/update/delete semantics tied to `memory_processed_sources`.
4. Debug artifacts that show lexical candidates, semantic candidates, reranking, and dropped hits.
5. Benchmarks that compare lexical-only, semantic-only, and hybrid retrieval honestly.

## Interface added

`app/services/memory_vector.py` defines:

- `MemoryVectorChunk`
- `MemoryVectorHit`
- `MemoryVectorBackend` protocol
- `DisabledMemoryVectorBackend`
- `UnavailableMemoryVectorBackend`
- `get_memory_vector_backend()`
- `semantic_memory_search()`

Runtime settings now accept:

```yaml
memory_vector:
  enabled: false
  backend: disabled
  embedding_model: null
  dim: null
  index_path: null
```

`backend: turbovec` is accepted as explicit experimental intent, but currently returns an unavailable backend instead of importing a native dependency.

## Next implementation step

When ready, implement `TurbovecMemoryVectorBackend` behind an optional dependency extra, likely:

```toml
[project.optional-dependencies]
memory-vector = ["turbovec>=..."]
```

Then add manual commands first:

```bash
# Manual memory vector commands have been removed.
# Use the memory_search tool and direct service calls.
```

Success criteria before defaulting semantic retrieval:

- Positive recall improves on local fixtures and larger LongMemEval/LoCoMo-style sets.
- Negative false-positive rate does not regress.
- `failures.jsonl` and `candidates.jsonl` make semantic misses inspectable.
- Desktop packaging remains reliable on macOS/Linux/Windows.
