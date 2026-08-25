# EvoFlux Memory Architecture

EvoFlux memory uses three layers with different retention and trust rules.

## Layers

1. **Working memory** is the current session's visible transcript. Context
   compaction replaces old provider-visible turns with a durable summary while
   retaining the full audit history in `session_messages`.
2. **Episodic memory** is provenance: `memory_fact_evidence` links each learned
   fact to the session and message that established it.
3. **Semantic memory** is the deduplicated `memory_facts` store used by
   automatic recall. Repeated independent evidence reinforces a fact without
   copying it into every prompt.

The Markdown wiki is an inspectable consolidation/export surface. It is not the
only copy of newly extracted memory and does not gate whether a fact can be
recalled.

On the first upgraded startup, historical extraction-note projections are
imported idempotently. Because old bullets carried no scope, they are kept
local to their source project/workspace/folder/session; legacy wording is never
used to guess a user-global preference. The import commits per source session
and writes a completion sentinel so it cannot monopolize SQLite's writer lane
or reinforce the same evidence on every restart.

## Scope contract

Every semantic fact has one explicit scope:

| Scope | Visible to |
| --- | --- |
| `user` | Every session; restricted to explicit durable preferences/profile |
| `project` | Sessions in the same Coding project |
| `workspace` | Sessions using the same normalized workspace path |
| `folder` | Sessions in the same Work folder |
| `session` | The owning session and its team context only |

Technical decisions cannot be promoted to `user` scope. When an extractor asks
for an unavailable scope, the store coerces it to the most specific available
project/workspace/folder/session scope.

## Turn lifecycle

1. The current session window is loaded from SQLite.
2. `USER.md` is injected as bounded profile **data**, not executable policy.
3. The latest real user request searches compatible semantic scopes.
4. At most three cited JSONL facts are attached as untrusted data.
5. The normal model/tool loop runs and the checkpointer persists its state.
6. After the third completed lead response, then every ten additional completed
   responses, extraction claims a durable `memory_extraction_states` cursor.
7. Successful extraction upserts scoped facts and evidence. Failure leaves the
   cursor retryable; restart can reclaim a stale processing lease.

Intermediate assistant tool-call rounds do not count as completed responses.
Copied side-chat source context and raw tool output are not extraction input.

## Retrieval

Automatic recall:

- searches only scoped semantic facts;
- abstains on generic single-token prompts;
- ranks exact lexical evidence with scope, confidence, and reinforcement;
- runs CPU ranking outside the asyncio event loop;
- wraps results in an explicit untrusted-data boundary.

The explicit `memory_search` tool additionally searches the legacy Markdown
wiki and scoped dialogue evidence. Dialogue lookup excludes tool messages,
hidden side-chat copies, and unrelated projects/workspaces/folders. It uses the
dedicated read database lane.

## Consolidation (Dream)

Dream processes top-level sessions only. Team-member and side-chat sessions do
not become duplicate sources. `dream_log.processed_at` is an incremental
watermark: adding a visible message makes a previously processed session
eligible again. Daily note files are similarly re-queued when modified after
their recorded source version.

When sessions and notes are both pending, a scheduled run admits at least one
of each so notes cannot starve behind a session backlog. A filesystem lock
serializes server and CLI Dream processes. Wiki service appends use a
cross-process lock and atomic replacement.

## Forget semantics

Deleting a session first removes its episodic evidence. A semantic fact is
deleted only when no other session supports it. This preserves shared knowledge
while allowing the final supporting source to be forgotten.

Legacy wiki pages remain manually inspectable during migration; automatic
recall does not depend on those unscoped pages.
