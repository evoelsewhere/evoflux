---
title: Memory v2 Evaluation Findings
status: active
updated: 2026-06-01
---

# Memory v2 Evaluation Findings

This log records real evaluation failures. Do not tune the benchmark to hide them.

## 2026-05-31 — Synthetic preference + abstention smoke

Dataset shape:

- 2 positive preference questions.
- 1 negative/unanswerable Kubernetes scheduler preference question.
- Retrieval mode: `wiki`.
- Corpus: `wiki/user.md` plus one deterministic Dream v2 compiled session page.

Result after removing score-threshold/boost tricks:

```json
{
  "items": 3,
  "positive_items": 2,
  "negative_items": 1,
  "recall@1": 0.5,
  "recall@5": 1.0,
  "recall@10": 1.0,
  "mrr@10": 0.75,
  "abstention_rate": 0.0,
  "false_positive_rate": 1.0,
  "failures": 1
}
```

Failure:

```text
query: What is Hoang's preferred Kubernetes scheduler plugin?
expected: abstain / no memory hit
actual hit: wiki:user
reason: lexical overlap on "Hoang" + "preferred/prefers" pulled generic user preference memory.
```

Interpretation:

- Positive retrieval is usable on this tiny smoke but not enough to claim quality.
- Negative/abstention behavior is currently weak.
- We need a real abstention/reranking policy, not benchmark-specific score hacks.
- `tests/services/test_memory_eval_regression.py` now keeps this fixture executable:
  explicit retrieval is expected to expose the false positive, while
  `MemoryContextHook` is expected to abstain for the same negative query.

Next candidates to evaluate honestly:

1. Require stronger topical overlap for automatic `MemoryContextHook` injection than for explicit `memory_search`. Initial implementation filters automatic injection by meaningful token overlap and ignores identity-only matches such as “Hoang” plus generic preference words.
2. Add source/page type hints so `wiki/user.md` generic preference pages do not answer unrelated domain-specific preference queries.
3. Add a reranker or LLM judge for automatic injection only, with citations and strict abstention instructions.
4. Keep failures in `failures.jsonl` as first-class debugging artifacts.

## 2026-05-31 — Metadata-backed automatic injection reranker

Implemented page metadata fields on deterministic Dream v2 compiled pages:

- `memory_kind`
- `scope`
- `topics`

`MemoryContextHook` now uses `topics` as a conservative automatic-injection reranker. Explicit `memory_search` remains broad and still exposes the lexical false positive; automatic injection uses topic overlap so generic preference/response-style user memory is not applied to unrelated Kubernetes scheduler questions.

This is intentionally not a benchmark-specific scoring trick:

- no query-specific thresholds were added;
- explicit retrieval metrics are unchanged and can still fail on hard negatives;
- metadata is visible in markdown frontmatter for debugging;
- missing metadata falls back to the prior lexical policy rather than hiding results globally.

## 2026-06-01 — Expanded local retrieval fixture

Moved the expanded benchmark out of unit tests and into a dedicated eval fixture module, which seeds a synthetic corpus and writes 32 LongMemEval-style rows:

- 21 positive rows covering `preference`, `response_style`, `project_context`, `memory_system`, and `decision`.
- 11 negative rows covering `negative_abstention` and `domain_specific_preference`.
- Corpus: five compiled wiki pages (`wiki/user.md`, a session page, project context, Memory v2 design, and Memory v2 decisions).
- Retrieval mode: `wiki`, top-k 5.

Honest deterministic retrieval result against the same fixture shape:

```json
{
  "items": 32,
  "positive_items": 21,
  "negative_items": 11,
  "recall@1": 0.8571428571428571,
  "recall@5": 1.0,
  "recall@10": 1.0,
  "mrr@10": 0.9206349206349206,
  "abstention_rate": 0.0,
  "false_positive_rate": 1.0,
  "failures": 11
}
```

Per-type summary:

| Type | Items | Positive | Negative | Recall@1 | Recall@5 | MRR@10 | Abstention | False positives | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| decision | 5 | 5 | 0 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 0 |
| memory_system | 5 | 5 | 0 | 0.800 | 1.000 | 0.900 | 0.000 | 0.000 | 0 |
| preference | 3 | 3 | 0 | 0.667 | 1.000 | 0.778 | 0.000 | 0.000 | 0 |
| project_context | 6 | 6 | 0 | 1.000 | 1.000 | 1.000 | 0.000 | 0.000 | 0 |
| response_style | 2 | 2 | 0 | 0.500 | 1.000 | 0.750 | 0.000 | 0.000 | 0 |
| domain_specific_preference | 2 | 0 | 2 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 2 |
| negative_abstention | 9 | 0 | 9 | 0.000 | 0.000 | 0.000 | 0.000 | 1.000 | 9 |

Interpretation:

- Positive retrieval is decent on this small synthetic corpus.
- Explicit lexical retrieval still cannot abstain: every negative row returns at least one hit.
- Frequent false-positive pattern: broad pages containing `Hoang`, `EvoFlux`, `Memory v2`, or generic preference words match unrelated unanswerable questions.
- Automatic `MemoryContextHook` remains stricter than explicit retrieval; explicit benchmark failures are kept visible for future reranking/abstention work.

## 2026-06-01 — Answerability filter v1

Added a conservative answerability filter after file candidate diagnostics:

- Score file candidates with normalized meaningful query tokens instead of generic words like `what`, `which`, `should`, `the`, and `for`.
- Keep candidate diagnostics visible by running the benchmark with `--write-candidates`; dropped candidates are recorded in `candidates.jsonl`.
- Drop strict hits that only match one weak token when answer-bearing query terms like `choose`, `default`, `mandatory`, `prefer`, or `require` are missing from the candidate.
- Down-rank non-user pages when a query explicitly asks about the user, while still preserving candidate visibility.

Manual run:

```bash
# Run the eval fixture directly (manual/ scripts removed)
```

Result:

```json
{
  "items": 32,
  "positive_items": 21,
  "negative_items": 11,
  "recall@1": 0.9523809523809523,
  "recall@5": 1.0,
  "recall@10": 1.0,
  "mrr@10": 0.9523809523809523,
  "abstention_rate": 0.45454545454545453,
  "false_positive_rate": 0.5454545454545454,
  "failures": 7
}
```

Interpretation:

- Positive top-rank quality improved because stopword-only matches no longer outrank substantive hits.
- False-positive rate improved from `0.636` in the prior reranked run to `0.545`, but explicit retrieval still over-answers broad unanswerable questions.
- Known remaining failures include `memory-goal` as a recall miss and negatives involving scheduler plugin, cloud region, vector database default, ontology database, raw session copies, and mandatory `USER.md` taxonomy.
- This remains intentionally imperfect; failures stay in `failures.jsonl` for debugging rather than being hidden with benchmark-specific thresholds.

Next honest eval work:

1. Add stale/conflicting fact cases.
2. Add source citation correctness checks.
3. Add “answer present but buried” cases with long pages.
4. Add multi-session durable preference QA.
5. Add LoCoMo-style temporal/context questions.

## 2026-06-01 — Injection-mode release-readiness eval

Added `memory_bench --mode injection`, which runs compiled-memory retrieval and then applies the same `MemoryContextHook` relevance filter used before automatic prompt injection. The harness now separates:

- `candidate_false_positive_rate`: weak pre-filter candidates existed;
- `false_positive_rate`: final hits for the selected mode;
- `injection_false_positive_rate`: final automatic-injection false positives for `--mode injection`.

Manual run:

```bash
# Run the eval fixture directly (manual/ scripts removed)
```

Result on the synthetic fixture:

```json
{
  "items": 32,
  "positive_items": 21,
  "negative_items": 11,
  "recall@1": 0.9523809523809523,
  "recall@5": 1.0,
  "recall@10": 1.0,
  "mrr@10": 0.9523809523809523,
  "candidate_false_positive_rate": 1.0,
  "injection_false_positive_rate": 0.45454545454545453,
  "failures": 6
}
```

Interpretation:

- Candidate retrieval still surfaces at least one weak candidate for every negative row, which is acceptable for inspectable explicit search.
- Automatic injection filters some but not all negative rows on this fixture; remaining injection failures are visible in `failures.jsonl` and should be treated as release notes / follow-up hardening rather than hidden.
- The metric split is more release-useful than raw retrieval false positives because it distinguishes “candidate existed” from “memory would enter the prompt.”

## 2026-06-01 — Dream synthesis release-hardening tests

Added unit coverage and implementation hardening for deterministic Dream v2:

- duplicate/equivalent durable facts merge into one curated fact line with multiple raw citations;
- changed/equivalent wording is recorded under `Conflicts / stale candidates`;
- note/import promotions preserve `[note:...]` and `[import:...]` citations;
- secret/opt-out/noise content is not copied into curated facts;
- source-page/frontmatter boilerplate is filtered before promotion.

This improves release confidence for the markdown wiki maintainer without introducing an ontology, vector DB, or LLM summarizer.

## 2026-06-01 — Automatic injection hardening iteration

Tightened automatic prompt injection without changing explicit candidate retrieval:

- diagnostics now compare normalized meaningful query tokens against normalized page tokens, so query aliases such as `want -> support` and page words such as `help -> support` can match for recall diagnostics;
- `MemoryContextHook` treats broad product/page topics such as `memory`, `EvoFlux`, and `v2` as generic for automatic injection;
- automatic injection now rejects pages that only match generic product context while query-specific unanswered detail terms remain missing, such as cloud regions, scheduler plugins, vector databases, ontologies, or mandatory taxonomy details;
- explicit `memory_search` remains broader and still writes pre-filter candidates when the eval uses `--write-candidates`.

The manual fixture also grew first-pass quality rows for citation preservation, stale-fact correction, and temporal/context maintainer naming. These are still retrieval/injection checks, not final-answer grading.

Manual run:

```bash
# Run the eval fixture directly (manual/ scripts removed)
```

Result after the hardening change:

```json
{
  "items": 35,
  "positive_items": 24,
  "negative_items": 11,
  "recall@1": 0.625,
  "recall@5": 0.625,
  "recall@10": 0.625,
  "mrr@10": 0.625,
  "candidate_false_positive_rate": 1.0,
  "false_positive_rate": 0.0,
  "injection_false_positive_rate": 0.0,
  "failures": 9
}
```

Interpretation:

- The stricter injection filter eliminates synthetic negative prompt-injection false positives in this fixture.
- Candidate false positives remain `1.0`; broad explicit retrieval is still intentionally inspectable rather than hidden.
- Positive injection recall dropped; that is an honest safety/recall trade-off, not a benchmark win. The remaining positive misses are mostly precise factual QA (`Python 3.14`, `Tailwind v4`, `Dream`, canonical raw sources, eval styles, breaking changes, and the new citation/stale/temporal rows) that explicit retrieval can still surface but automatic injection now avoids unless there is stronger query-specific overlap.
- Next hardening should recover safe positive injection recall with better page metadata or a cited answerability judge, not by adding fixture-specific exceptions.

## 2026-06-01 — Fact-level injection contract

Added a plain markdown fact contract for automatic injection:

- Dream writes active curated memory as cited bullets under `## Facts` with stable `fact_id=...` markers.
- Changed/equivalent facts stay under `## Conflicts / stale candidates`.
- `extract_memory_facts()` and `search_memory_facts()` retrieve cited bullets rather than whole pages.
- `MemoryContextHook` now injects fact-level active bullets and excludes stale/conflict candidates.
- Explicit whole-page `memory_search` remains available for broader debugging.

Manual run:

```bash
# Run the eval fixture directly (manual/ scripts removed)
```

Result:

```json
{
  "items": 34,
  "positive_items": 24,
  "negative_items": 10,
  "recall@1": 0.625,
  "recall@5": 0.625,
  "recall@10": 0.625,
  "mrr@10": 0.625,
  "candidate_false_positive_rate": 1.0,
  "false_positive_rate": 0.0,
  "injection_false_positive_rate": 0.0,
  "failures": 9
}
```

Interpretation:

- Fact-level injection keeps stale/conflict content out of prompts and preserves the conservative false-positive posture.
- Recall did not improve yet; the current missing positives remain visible. This is expected because the change switched the injection unit from pages to cited facts rather than adding benchmark-tuned aliases or thresholds.
- The fixture changed one previous “negative” row about mandatory `USER.md` taxonomy into covered unit behavior: a supported negated fact is answerable, not an abstention case.
- Next work should add final-answer support/citation grading and improve fact answerability generally, without user-specific or fixture-specific scoring hacks.
