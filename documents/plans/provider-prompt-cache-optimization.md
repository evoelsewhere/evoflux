# Provider prompt-cache optimization

Status: implemented

## Problem and outcome

EvoFlux exposes prompt-cache read telemetry, but provider adapters normalize
cache usage inconsistently, cache-write tokens are not represented, several
high-cost providers are not opted into their supported automatic cache mode,
and provider routing affinity is not tied to the session. The shipped outcome
is a provider-neutral cache accounting contract, safe automatic cache controls
for Anthropic and supported Bedrock Converse models, cache-hit parsing for
DeepSeek, stable routing affinity for providers that document it, and accurate
read/write observability.

## Goals

- Maximize cache reuse without changing model output semantics.
- Keep total input, cache-read, cache-write, ordinary-input, and estimated-cost
  accounting consistent across provider wire formats.
- Enable provider-documented automatic or trailing-checkpoint caching where the
  adapter can do so without a new user decision.
- Keep cache routing keys stable within a session and opaque outside EvoFlux.
- Preserve backward compatibility with older telemetry partitions and provider
  responses that do not report cache fields.

## Non-goals

- A user-facing cache settings panel or per-agent TTL control.
- Automatic explicit Qwen or GPT-5.6 breakpoints that can make a one-call turn
  more expensive when no reuse occurs.
- Explicit Gemini cached-content resource lifecycle management.
- Claiming token-price savings for subscription or local providers such as
  Codex, Copilot, Kimi Code, and Ollama.
- Changing provider selection, model capabilities, conversation content, or
  tool authorization.

## User flows and states

1. A user starts or continues a session with a cache-capable provider.
2. EvoFlux sends the same model-visible prompt as before, plus only the
   provider-supported cache control or opaque affinity hint.
3. On a cache miss, cache-write tokens are recorded when the provider reports
   them; on a hit, cache-read tokens are recorded.
4. Telemetry shows total input, cache reads, cache writes, ordinary input, hit
   rate, and estimated cost without percentages over 100%.
5. Providers or historical spans without cache-write data continue to render
   with zero writes.

## Requirements and acceptance criteria

- **AC-1 — Canonical accounting:** Given any provider usage payload, canonical
  `prompt_tokens` is total input and separately reported cache-read and
  cache-write tokens are non-negative subsets of it.
- **AC-2 — Cost accuracy:** Given pricing for ordinary input, cache reads, cache
  writes, and output, estimated cost prices each disjoint token class exactly
  once. Auxiliary model calls use a qualified `provider:model` identity when
  available.
- **AC-3 — Anthropic cache:** Anthropic and Foundry-Claude requests use
  top-level ephemeral automatic caching and normalize input, cache creation,
  cache read, output, and total usage for streaming and non-streaming calls.
- **AC-4 — Bedrock cache:** Supported Anthropic Claude and Amazon Nova Converse
  requests receive one trailing cache checkpoint; unsupported Bedrock model
  families remain unchanged. Bedrock usage includes read/write tokens in total
  input and cost.
- **AC-5 — Compatible-provider parsing:** DeepSeek's
  `prompt_cache_hit_tokens` is preserved, while OpenAI/OpenRouter/Qwen-style
  nested cache-read and cache-write fields continue to work.
- **AC-6 — Affinity:** Every session produces one deterministic opaque cache
  affinity key. Native OpenAI/Foundry OpenAI and Codex use
  `prompt_cache_key`, OpenRouter uses `session_id`, and xAI Chat Completions
  uses `x-grok-conv-id`; other providers receive no new wire field.
- **AC-7 — Observability:** OTel, summary APIs, and the telemetry model view
  expose cache-write tokens and derive ordinary input as
  `total - read - write`, clamped at zero. Historical spans remain readable.
- **AC-8 — Compatibility:** Existing provider requests without cache fields,
  existing SSE consumers, and existing telemetry partitions remain valid.
- **AC-9 — Documentation:** Current provider and observability documentation,
  plus in-app Help where relevant, describe automatic caching and the meaning
  of read/write metrics.

## API, event, tool, and UI contracts

- Internal `Usage` and optional SSE `UsageEvent` add `cache_write_tokens`.
- Usage dictionaries add optional `cache_write`.
- OTel adds `gen_ai.usage.cache_write.input_tokens`.
- The observability summary adds `cache_write_tokens` to totals, model rows,
  and cache-by-step rows, plus `ordinary_input_tokens` to cache-by-step rows.
- Existing `cached_tokens`, `cache_percent`, and other fields retain their
  names and meanings.
- No tool schema or public mutation endpoint changes.

## Data model, migration, and retention

No database or migration change is required. New data is stored only as
optional fields in message extras, SSE payloads, and OTel span attributes.
Historical JSONL partitions omit the new attribute and aggregate as zero.

## Permissions, security, privacy, and trust

Cache affinity keys are SHA-256-derived from the internal session ID and carry
no raw session, user, workspace, prompt, or secret content. Cache controls do
not weaken outbound redaction, provider authentication, sandboxing, or tool
permissions. Provider retention remains governed by each provider's cache
contract and existing data policy.

## Concurrency, failure, recovery, and idempotency

The affinity key is deterministic for the session and safe across retries.
Fallback providers derive their own supported wire mapping from the same opaque
key. Cache controls are idempotent. Missing or zero usage fields normalize to
zero without failing a stream. Unsupported Bedrock families receive no
checkpoint.

## Observability and diagnostics

Provider model-call spans record total input, output, cache read, cache write,
reasoning, tool-use, and estimated USD where token pricing is meaningful.
Telemetry aggregates old and new partitions with null-as-zero behavior.

## Compatibility, rollout, and rollback

All new usage/event/API fields are additive and optional. Anthropic automatic
cache and supported Bedrock checkpoints can be rolled back independently by
removing their request fields; usage normalization remains compatible. No
stored data requires rollback.

## Verification matrix

| AC | Implementation owner | Evidence |
|---|---|---|
| AC-1, AC-2 | `app/agent/schemas/chat.py`, `app/agent/usage.py` | focused usage/schema tests |
| AC-3 | `app/agent/providers/anthropic/` | payload, streaming, non-stream usage tests |
| AC-4 | `app/agent/providers/bedrock/` | supported/unsupported request and usage tests |
| AC-5 | OpenAI-compatible schemas/handlers and DeepSeek tests | nested and top-level fixture tests |
| AC-6 | provider base, retry loop, OpenAI/OpenRouter/xAI/Codex adapters | per-provider request/header tests plus fallback test |
| AC-7 | OTel, observability service, React telemetry view | backend aggregation/API tests and frontend type/build checks |
| AC-8 | affected provider and agent-loop regression suites | focused pytest suites |
| AC-9 | feature/architecture/help documents | link and content inspection |

## Ownership and source map

- Canonical usage and cost: `app/agent/schemas/chat.py`, `app/agent/usage.py`,
  `app/agent/turn_usage.py`, stream publisher and OTel hooks.
- Provider cache controls and normalization: `app/agent/providers/anthropic/`,
  `bedrock/`, `deepseek/`, `openai/`, `openrouter.py`, `xai/`, and `codex/`.
- Session affinity: `app/agent/providers/base.py`, agent-loop retry/streaming.
- Aggregation/UI: `app/services/observability_service.py`,
  `web/src/api/client/observability.ts`, telemetry model view and tests.
- Current docs: `documents/features/models-and-providers.md`,
  `documents/features/observability-and-diagnostics.md`, and Help locales.
