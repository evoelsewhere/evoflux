# Prompt prefix stability for automatic-cache providers

Status: implemented

Companion to [provider prompt-cache optimization](provider-prompt-cache-optimization.md),
which established the accounting, the wire-level cache controls, and the
session routing key. That work made caching *possible* and *measurable*. This
work is about what EvoFlux itself puts on the wire: a provider with automatic
prefix caching reuses exactly the leading byte run a request shares with an
earlier one, so a single rewritten character anywhere upstream is worth nothing
cached after it.

## Problem and outcome

Three parts of the harness rewrote already-sent prompt bytes on every turn.
None of them was visible in aggregate telemetry, because a turn's hit rate
averages the damage across its calls.

Measured on `xiaomi:mimo-v2.5` driving a two-turn architectural review of an
external repository:

| Symptom | Evidence before |
|---|---|
| The skill-resolution pre-pass never cached | 1,667-token prompt, **0** cached tokens, every turn |
| The skill catalog reordered the system prompt per turn | 83,176-token prompt, **4,096** cached (4.9%) |
| Tool-result compaction slid by one batch per batch | 59,311 → 20,480 (34.5%) then 81,948 → 20,480 (25.0%) |

Shipped outcome, same two prompts, same model:

| | Before | After |
|---|---|---|
| Turn 1 | 242,792 input / 156,416 cached — 64.4% | 270,685 / 198,784 — **73.4%** |
| Turn 2 | 319,784 input / 121,216 cached — 37.9% | 476,198 / 332,928 — **69.9%** |
| Combined | **49.4%** | **71.2%** |

The single call that had collapsed to 4.9% now serves at 87.3%.

## Goals

- Keep the request prefix byte-identical between turns whenever the underlying
  conversation is unchanged, for every automatic-prefix provider.
- Leave model-visible *content* alone: the same instructions, the same catalog,
  the same history. Only byte order and rewrite timing change.
- Make a prefix break inspectable after the fact instead of inferable from a
  turn average.
- Show the hit rate where a user is already looking at token usage.

## Non-goals

- Relocating turn-varying system-prompt content out of the system prompt.
  See "Known remaining break" below — that one needs a design decision, not a
  byte-order fix.
- Changing Anthropic/Bedrock behavior. Those providers take explicit
  `cache_control` breakpoints and already split at `CACHE_VOLATILE_MARKER`.
- New user-facing settings. The one relevant knob,
  `keep_recent_tool_batches`, already exists.

## Requirements and acceptance criteria

- **AC-1 — Resolver payload order:** The skill-resolution request serializes
  `mode` and `skills` before `request`, so the resolver's system prompt plus
  the sorted catalog form a prefix that is stable across turns and across
  sessions.
- **AC-2 — Resolver routing:** The resolver call carries a constant cache
  affinity key rather than the session key, because its prefix is
  session-independent. Providers that take no routing key are unaffected.
- **AC-3 — Catalog byte order:** `render_skill_catalog` emits entries in name
  order. Query ranking still decides which entries survive the budget; it no
  longer decides the byte order. Two turns with different queries and the same
  included set render byte-identical text.
- **AC-4 — Compaction boundary:** The number of compacted tool batches is a
  pure function of how many batches exist, advancing in steps of
  `keep_recent_batches`. It is therefore identical between calls and between
  turns, and never un-compacts a batch.
- **AC-5 — Diagnosability:** With `EVOFLUX_CACHE_PROBE=1`, every outbound
  OpenAI-shaped request logs which prompt segment first differs from the
  best-matching earlier request, and every response logs prompt/cached tokens.
  Disabled by default and never alters a request.
- **AC-6 — Cache hit in the UI:** The context-usage popover shows the cache-hit
  share for the latest prompt and for the turn, and shows nothing when the
  provider reports no cache signal. The popover is reorganised around that
  reading: one window meter carrying the compaction threshold, then two
  parallel accounting blocks each led by its own ratio bar and hit rate, then
  the threshold control — rather than statistics and controls interleaved.

## API, event, tool, and UI contracts

No API, SSE, tool, or persistence change. `ContextBudgetBar` derives the two
hit rates from data it already receives and regroups its existing sections;
the section headings become "Latest prompt" and "This turn".

## Data model, migration, and retention

None.

## Permissions, security, privacy, and trust

The resolver's constant affinity key is a fixed literal and carries no session,
user, or prompt content — strictly less identifying than the session-derived
key it replaces on that call. The probe writes to a path the operator names and
is off unless the environment variable is set; it records prompt bytes, so it
is a debugging tool for a developer's own machine, not a production default.

## Concurrency, failure, recovery, and idempotency

All three fixes are pure functions of their inputs, so retries and fallback
providers reproduce the same bytes. The probe swallows its own exceptions.

## Observability and diagnostics

`EVOFLUX_CACHE_PROBE=1`, optionally with `EVOFLUX_CACHE_PROBE_PATH` for a JSONL
transcript. Each request line reports the stable-prefix share and the first
divergent segment; each response line reports what the provider actually
cached. The gap between the two separates "we rewrote the prompt" from
"the provider chose not to reuse it".

## Compatibility, rollout, and rollback

Every change is local to one function and reverts independently. No stored data
depends on any of them.

## Known remaining break

`MemoryContextHook` searches memory with the latest user message and appends
the result to the system prompt. When those results differ between turns, the
system prompt differs at position 0 and the whole conversation's cache is lost
— the same failure the catalog had. It did not fire in the measured sessions
because memory returned nothing for those queries.

`CacheBoundaryHook` already marks where the volatile tail begins, but only
Anthropic and Bedrock consume it; automatic-prefix providers get one flat
string. Fixing it properly means giving the per-turn block a permanent home in
history rather than a rewritten one at position 0, which changes what is
persisted — a design decision, not a reordering.

A second, smaller residual: compacting history that the provider has already
cached trades a cache-read for a full re-read of everything after it. Stepping
the boundary makes that rare, not free. Its remaining value is context-window
management, so raising `keep_recent_tool_batches` trades context for cache.

## Verification matrix

| AC | Implementation owner | Evidence |
|---|---|---|
| AC-1 | `app/agent/skills/resolution.py` | `test_resolver_payload_keeps_the_volatile_request_last`; live: resolver call 0% → 99.2% |
| AC-2 | `app/agent/skills/resolution.py` | `tests/agent/skills/test_resolution.py` provider double records the constant key |
| AC-3 | `app/agent/skills/catalog.py` | `test_catalog_text_is_byte_identical_across_different_queries`; live: 4.9% → 87.3% on the turn-2 opening call |
| AC-4 | `app/agent/hooks/tool_context_projection.py` | `test_boundary_holds_still_while_the_conversation_grows` |
| AC-5 | `app/agent/providers/cache_probe.py` | probe transcripts backing every number in this document |
| AC-6 | `web/src/components/ContextBudgetBar.tsx` | `bun run typecheck`, `bun run lint`, popover screenshot |

## Ownership and source map

- Resolver payload and routing: `app/agent/skills/resolution.py`.
- Catalog byte order: `app/agent/skills/catalog.py`.
- Compaction boundary: `app/agent/hooks/tool_context_projection.py`.
- Diagnostics: `app/agent/providers/cache_probe.py`, called from
  `app/agent/providers/openai/completions.py` and `.../responses.py`.
- Hit-rate display: `web/src/components/ContextBudgetBar.tsx`.
