---
title: Memory v2 Retrieval Evaluation Log
status: active
updated: 2026-05-31
---

# Memory v2 Retrieval Evaluation Log

Goal: make Memory v2 good enough for implicit personalization without losing the simple Karpathy-style wiki design.

## Current retrieval loop

1. Make a small retrieval/prompting change.
2. Run targeted tests and retrieval benchmarks on local datasets.
3. Evaluate Recall@K, MRR@10, failures, and qualitative false positives.
4. Keep, tune, or revert.

Do not add benchmark-specific thresholds, boosts, aliases, or prompt tricks just
to improve reported metrics. Failed cases should remain visible in
`failures.jsonl` and, when important, be summarized in
`documents/techdebts/memory-v2-eval-findings.md`.

## Baseline implementation

- Deterministic token-overlap search in `app/services/memory.py`.
- `memory_search` tool returns cited excerpts from wiki/imports/notes and raw DB messages.
- `WikiInjectionHook` injects capped `wiki/user.md`.
- `MemoryContextHook` automatically injects a small cited `Relevant memory` block from the latest user message.

## Turbovec assessment

Turbovec is a promising future semantic-search backend, not the default MVP choice.

Pros:

- MIT, local-first Rust ANN/vector index with Python bindings.
- `pip install turbovec`, minimal runtime dependency footprint around NumPy.
- Persistent indexes and stable IDs fit Memory v2 source refs.
- Allowlist filtering could support hybrid retrieval.

Risks:

- PyPI marks it Alpha.
- Native Rust/SIMD/BLAS packaging adds cross-platform complexity.
- It solves vector search only, not memory policy, citations, Dream synthesis, or benchmark quality.

Decision for now: keep deterministic lexical retrieval as the baseline. Revisit Turbovec only after benchmarks show lexical retrieval is the bottleneck and after we choose an embedding provider/model strategy.

## Next benchmark datasets

- Synthetic EvoFlux preference/context set for fast regression.
- Local LongMemEval JSON/JSONL slice.
- LoCoMo-style multi-session temporal/adversarial questions.

## Metrics

- Recall@1/5/10 for positive/answerable rows
- MRR@10 for positive/answerable rows
- abstention rate for negative/unanswerable rows
- false-positive rate for negative/unanswerable rows
- failure count
- per-type breakdowns when local JSON/JSONL rows include `type` or `question_type`
- qualitative review of wrong memory injections

Negative/unanswerable rows are supported with `negative: true`, `abstain: true`, `answerable: false`, `should_answer: false`, or an empty answer list. The harness remains dataset-local: no downloads, pass a local file through `--data PATH`.
