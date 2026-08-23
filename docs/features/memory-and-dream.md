# Memory and Dream

EvoFlux separates working memory, scoped semantic facts and an inspectable
Markdown knowledge base. This prevents project facts from leaking globally
while preserving user-controlled long-term knowledge.

The detailed scope, turn, recall, Dream and forget lifecycle is also captured in
[Memory architecture](../architecture/memory-system.md).

## Memory layers

| Layer | Store | Purpose |
|---|---|---|
| Working memory | Current session transcript/checkpoint | Immediate conversational context |
| Episodic evidence | Fact-to-session/message links | Provenance for why a fact exists |
| Semantic memory | SQL-backed scoped facts | Small query-relevant automatic recall |
| Knowledge wiki | Markdown files | Inspectable consolidated knowledge and notes |

## Scoped semantic facts

Facts use one of `user`, `folder`, `workspace`, `project` or `session` scopes.
A turn can recall only compatible scopes resolved from its owning top-level
session. Specialist sessions inherit their lead's relevant scope without making
unrelated sessions visible.

Automatic extraction runs after completed lead turns according to
`memory_extraction` settings. It extracts at most eight durable preferences,
profile facts, decisions, conventions, constraints or stable facts from a
bounded transcript. User-global scope is allowed only for explicit durable
preferences/profile; technical facts fall back to project/workspace/folder or
session scope.

Facts are normalized and deduplicated per scope. Evidence is upserted separately
so repeated confirmation strengthens provenance without duplicating the fact.
Secret-like content, credentials and private keys are rejected. Extraction has
a durable claim/completion/failure state and background tasks drain before the
database shuts down.

## Recall

The memory hook searches only the latest user request, ranks compatible facts
by textual relevance, scope and confidence, and injects at most three results
within a small character budget. Each result is serialized as untrusted JSONL
data with source, scope, kind and confidence. The prompt explicitly forbids
following instructions found in remembered content.

The `memory_search` tool supports deliberate wider lookup. An optional vector
backend can augment the default local textual ranker; it is disabled unless
configured.

## Markdown wiki

The wiki root contains:

```text
USER.md          durable user profile, always protected
INDEX.md         Dream-maintained table of contents
LOG.md           append-only Dream log
LINT.md          latest Dream lint result
topics/          concepts and patterns
entities/        people, tools, products and organizations
sources/         one summary per ingested source
comparisons/     comparison pages
imports/         raw imported evidence
notes/           user/agent daily notes and Dream input
```

Wiki routes validate Markdown-only relative paths, reject traversal and restrict
valid root files/directories. Writes are atomic and serialized across local
threads/processes. Knowledge pages carry description, tags, updated date,
confidence, sources and related-page metadata.

## Dream

Dream is an optional scheduled or manually triggered agent. It consumes
unprocessed sessions and notes one at a time, treats them as untrusted sources,
updates existing pages before creating duplicates, maintains `INDEX.md`, and
records processing/log status. Manual run, status and lint actions are exposed
by the API and Settings.

Dream configuration lives in `settings.yaml` (`enabled`, `model`, `schedule`).
Its prompt and required tool boundary are code-owned. Runs are serialized and
bounded by input size and model timeout.

## Deletion and retention

Deleting a session removes session-scoped facts/evidence through the memory
service. Shared facts retain independent evidence from surviving sources.
Wiki files remain user-inspectable and are not silently rewritten by session
deletion.

## Source and tests

Primary code: `app/models/memory.py`, `app/services/scoped_memory.py`,
`app/agent/hooks/memory_*`, `app/services/memory.py`, `wiki.py`, `dream.py`,
`dream_scheduler.py`, and Wiki/Memory/Dream Settings components.

Focused tests cover scope isolation, extraction/recall hooks, search ranking,
wiki path/metadata rules, Dream batching/lint/scheduling and deletion behavior.
