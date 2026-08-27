# QwenCloud model provider

Status: implemented

## Problem and outcome

EvoFlux cannot currently authenticate to or select models from QwenCloud as a
first-class provider. Users can point the generic OpenAI integration at the
QwenCloud endpoint, but that conflates credentials and model identity with
OpenAI and does not preserve Qwen's thinking content across tool turns.

The outcome is a built-in `qwencloud` provider that uses QwenCloud's documented
OpenAI-compatible Chat Completions and Responses APIs, discovers the account's
live models, preserves provider-neutral runtime events, and exposes the provider
through Settings, CLI initialization, model metadata, Help, and reference docs.

Research baseline: QwenCloud documentation inspected on 2026-08-27, including
[first API call](https://docs.qwencloud.com/developer-guides/getting-started/first-api-call),
[API key preparation](https://docs.qwencloud.com/api-reference/preparation/api-key),
[OpenAI Chat](https://docs.qwencloud.com/api-reference/chat/openai-chat),
[OpenAI Responses](https://docs.qwencloud.com/api-reference/chat/openai-responses),
[function calling](https://docs.qwencloud.com/developer-guides/text-generation/function-calling),
and [Token Plan quick start](https://docs.qwencloud.com/token-plan/personal/token-plan-personal-quickstart).

## Goals

- Give QwenCloud its own `qwencloud:model` identity and local credentials.
- Support the international pay-as-you-go endpoint by default and allow the
  Base URL to be changed for Token Plan, Coding Plan, or another documented
  QwenCloud API host.
- Support text streaming, reasoning, usage, multimodal input where model
  metadata permits it, and serial/parallel function-tool calls.
- Preserve `reasoning_content` in Chat Completions tool-call history as required
  by Qwen thinking models.
- Reuse the existing provider-neutral OpenAI-compatible transport and metadata
  boundaries rather than exposing Qwen-specific payloads to public APIs.

## Non-goals

- Native DashScope SDK support.
- Image, video, audio, realtime WebSocket, embeddings, reranking, batch, or
  asynchronous generation endpoints.
- QwenCloud built-in web search, code interpreter, file search, or hosted MCP
  tools. EvoFlux continues to send its own function tools.
- Billing/credit analytics or Token Plan quota-reset controls.
- Automated creation, purchase, rotation, or deletion of QwenCloud API keys.

## User flows and states

1. In Settings, a user opens QwenCloud, enters `DASHSCOPE_API_KEY`, and may
   replace `DASHSCOPE_BASE_URL`.
2. EvoFlux calls `<base>/models` with Bearer authentication. A non-empty,
   agent-capable model list verifies the connection and can be saved.
3. The user selects a `qwencloud:<model>` default or session override. Text,
   reasoning, usage, and tool calls stream through the existing chat UI.
4. The default Base URL serves international pay-as-you-go keys. A Token Plan
   or Coding Plan user copies the exact Base URL paired with that key from the
   QwenCloud console/docs.
5. Invalid credentials, an incompatible key/Base URL pair, rate limits, or
   unsupported models remain provider request failures and are surfaced through
   the existing retry/diagnostics path without exposing the key.

## Requirements and acceptance criteria

- **AC-1 — Catalog and credentials:** Given no prior QwenCloud setup, Settings
  and the CLI show a built-in `qwencloud` provider with a secret
  `DASHSCOPE_API_KEY`, editable `DASHSCOPE_BASE_URL`, official documentation
  link, and international OpenAI-compatible default endpoint. Saving and
  clearing credentials use the existing local `.env` contract.
- **AC-2 — Factory and endpoint selection:** Given
  `qwencloud:<model>` plus a configured key, the factory builds a QwenCloud
  provider using the default endpoint or an environment/Settings Base URL
  override. Given no key or an unknown provider, it fails with the standard
  actionable error.
- **AC-3 — Live discovery and metadata:** Given valid credentials, model
  discovery sends a Bearer-authenticated `GET <base>/models`, returns stable
  sorted agent-capable IDs, and imports the `alibaba` models.dev profile under
  the `qwencloud` namespace for known limits, modalities, costs, tool support,
  and reasoning controls.
- **AC-4 — Provider-neutral streaming and tools:** Chat Completions and
  Responses payloads normalize streamed/final text, reasoning, usage, and one
  or more function calls into EvoFlux schemas. Qwen-specific fields never leak
  into public team/session API shapes.
- **AC-5 — Thinking continuity and control:** When Chat Completions history
  contains an assistant reasoning trace, EvoFlux sends it back as
  `reasoning_content` with the corresponding assistant/tool turn. Named effort
  settings use Qwen's documented reasoning controls; explicit `none`/`off`
  disables thinking rather than falling back to the model default.
- **AC-6 — Current documentation and Help:** Provider, credential, endpoint,
  protocol, and plan-matching behavior are documented in the feature page,
  configuration reference, repository map, and all in-app Help locales.
  Documentation warns that QwenCloud plan keys and Base URLs are not
  interchangeable and that Token Plan terms may restrict non-interactive
  automation.
- **AC-7 — Regression safety:** Focused provider, factory, discovery, metadata,
  settings, and CLI tests pass; frontend lint/typecheck pass for changed UI/Help
  files; `git diff --check` reports no whitespace errors.

## API, event, tool, and UI contracts

- Runtime model prefix: `qwencloud:`.
- Authentication: `Authorization: Bearer <DASHSCOPE_API_KEY>`.
- Default Base URL:
  `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`.
- Optional override: `DASHSCOPE_BASE_URL`; users must provide the complete
  OpenAI-compatible root including `/compatible-mode/v1` where required.
- Chat endpoint: `POST <base>/chat/completions`.
- Responses endpoint: `POST <base>/responses`.
- Model discovery: `GET <base>/models`.
- Public Settings and streaming schemas remain unchanged; the provider appears
  through existing generic `ProviderInfo`, model, chunk, usage, and tool-call
  structures.

## Data model, migration, and retention

No database migration is required. The API key and optional Base URL use the
existing local provider credential store backed by the config `.env`. Model
metadata uses the bundled/refreshed registry and the existing runtime overlay;
it is regenerable cache/package data.

## Permissions, security, privacy, and trust

- Credentials are secret UI fields, are masked in responses, never enter Agent
  Markdown or transcripts, and are sent only in the Authorization header to the
  configured Base URL.
- A custom Base URL changes the third-party destination and remains an explicit
  user setting. Existing outbound/sandbox/PII policy applies before model calls.
- QwenCloud Token Plan is Singapore/global and documents cross-border prompt
  and output transfer. Its Individual terms restrict keys to interactive
  programming/agent tools and prohibit automated scripts/backends/batch use;
  EvoFlux documents this because it cannot infer user entitlement or intended
  schedule from a key prefix alone.

## Concurrency, failure, recovery, and idempotency

Credential saves use the existing atomic `.env` writer. Discovery overrides are
request-scoped and do not mutate process environment, so concurrent verification
requests cannot observe another user's candidate key/Base URL. Provider retries,
stream interruption, tool-call assembly, and fallback follow the shared agent
runtime. Repeating discovery or saving the same credential is idempotent.

## Observability and diagnostics

Existing provider logs identify `qwencloud`, model, endpoint class, HTTP status,
and sanitized provider error body. API keys must never be logged. Settings model
verification and Diagnostics distinguish a missing key, unreachable endpoint,
empty model catalogue, and provider HTTP failure through current generic states.

## Compatibility, rollout, and rollback

The change is additive: existing provider IDs, credentials, sessions, and public
API schemas are unchanged. Rollout ships the new catalog/factory entry and model
registry snapshot together. Rollback removes the integration while leaving any
user-owned `DASHSCOPE_*` entries in `.env` untouched; users can delete them from
Settings before rollback if desired.

## Verification matrix

| AC | Implementation owner | Evidence |
|---|---|---|
| AC-1 | catalog, Settings UI constants, CLI init | QwenCloud catalog/config/CLI tests and Settings save/delete route test |
| AC-2 | QwenCloud adapter and provider factory | default/plan endpoint, missing-key, routing, and factory tests |
| AC-3 | discovery and model registry alias | request-scoped discovery test, Alibaba alias test, generated-registry check |
| AC-4 | QwenCloud Chat/Responses handlers | final response, reasoning SSE, usage, and callable-ID stream tests; shared OpenAI suite |
| AC-5 | QwenCloud message and thinking translation | preserved-thinking, explicit-off, effort, and token-limit request tests |
| AC-6 | feature/reference docs and Help locales | feature/config/repository docs; English, Vietnamese and Japanese Help; frontend lint/typecheck/build |
| AC-7 | affected backend/frontend surfaces | full pytest; full Ruff check; focused Ruff format and ty; frontend lint/typecheck/build; `git diff --check` |

## Ownership and source map

- Provider catalog/factory/config: `app/agent/providers/`, `app/core/config.py`.
- QwenCloud adapter: `app/agent/providers/qwencloud/`.
- Model discovery/metadata: `app/agent/providers/model_discovery.py`,
  `model_registry.py`, and `model_registry.json`.
- Settings and provider branding: `web/src/routes/settings.providers.tsx` and
  `web/src/components/providers/ProviderBrandIcon.tsx`.
- CLI initialization: `app/cli/commands/init.py`.
- Tests: `tests/agent/providers/qwencloud/`, shared discovery/registry tests,
  Settings route tests, and CLI tests.
- Current docs: `documents/features/models-and-providers.md`,
  `documents/reference/configuration.md`, `documents/reference/repository-map.md`,
  and `web/src/help/locales/`.
