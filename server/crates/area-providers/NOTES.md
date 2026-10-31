# area-providers — NOTES

Lane `providers`, unit `agent-runtime` (task AR1). A library crate, so no HTTP routes.
AR3 (the agent loop) is its consumer. Python sources:
`app/agent/providers/{base,streaming,factory,registry,options,transform,thinking}.py`,
`app/agent/providers/openai/{completions,compatible,compatible_provider,schemas,tool_content,sanitization}.py`,
`app/agent/providers/{router9,xiaomi}/`, the tool-call assembly in
`app/agent/agent_loop/streaming.py` and the retries in `app/agent/agent_loop/retry.py`.

## Public interface

- `ChatRequest { model, messages, tools, options }`, `ProviderEvent`, `Provider::stream`, `provider_for(settings, "provider:model")`.
- `Message`, `ContentBlock`, `ToolCall`, `ToolSpec` and `Usage` serialize as the Python `ChatMessage`, `ContentBlock`, `ToolCall`, tool dicts and `Usage`.
- `retry::stream_with_retry(primary, fallback, req)` is the port of `stream_with_retry`. The hook calls (`on_rate_limit`, `on_provider_retry`, `on_provider_exhausted`, `on_provider_fallback`) and `STREAM_RESTART` come through as `RetryItem`s, in the order Python calls them. Dropping the stream is the interrupt.
- `ChatRequest.model` may be `provider:model`, the bare model, or empty (meaning the resolved model). Only this provider's own `id:` prefix is stripped, so `router9:gpt:latest` sends `gpt:latest`.

## Scope

Chat Completions with streaming for `router9`, `xiaomi` and every registry entry that `_build_from_registry` turns into a plain `ChatCompletionsOnlyProvider` with a curated URL: `cliproxy`, `mistral`, `cohere`, `groq`, `cerebras`, `together`, `deepinfra`, `sambanova`, `perplexity` and `vercel`. Every other registry ID is `ProviderError::NotPorted`. Unknown IDs get Python's "Unsupported provider" message.

## Behaviour ported as is

- **Factory:** the error texts for an empty model, the `__PROVIDER_MODEL__` placeholder, a missing `:` and a missing key. The `mimo:auto` alias routes to `xiaomi:mimo-v2-flash` until 2026-07-26T10:00Z and is an unconfigured error after it. `ROUTER9_API_KEY` and `CLIPROXY_API_KEY` default to `sk_9router` and `sk_cliproxy` (the `Settings` defaults). A blank `*_BASE_URL` falls back to the registry URL, and trailing `/` are stripped.
- **Request body:** `sanitize_openai_tool_pairs`, `convert_messages`, assistant turns with neither content nor tool calls skipped, `convert_tools` (only `function`, `description` defaulting to `""`), `max_completion_tokens`, `stream_options.include_usage`, `prompt_cache_key`, the catalog-less `service_tier` path, `apply_model_sampling_defaults` and tool content flattening for mimo/glm/xiaomi models. MiMo adds the `reasoning_content` echo, `" "` for an otherwise empty assistant turn, no cache key, tier or sampling defaults, and the legacy `reasoning_effort` clamped to `high`.
- **Stream:** `iter_sse_data` (only `data: ` with a space, `[DONE]` stops reading, non-JSON skipped), `OpenAIStreamChunk` validation (a bad chunk ends the call with `ValidationError` after the events before it), `reasoning_content or reasoning_text`, and `_usage_from_openai` (details, then DeepSeek's `prompt_cache_hit_tokens`).
- **Tool calls:** the assembly of `stream_and_assemble`: first id wins, arguments stop growing once they parse as JSON, and Copilot's split arguments and late names are handled. Calls with no name or with arguments that are not JSON are dropped, and a missing id becomes `call_<24 hex>`.
- **Retry:** 5 attempts, delays of 1, 3, 9 and 27 s, `Retry-After` and the body patterns, the quota markers that stop a 429 retry, a 429 waiting 60 s or more that stops retrying, 400/401/403/404/413/422 classification and messages, the final `ProviderRateLimitError`, and fallback with restart.
- **Timeouts:** Python's `httpx` `timeout=120` (connect and per-read) becomes `evoflux_net::build_client_with` with 120 s connect and read timeouts, and no total timeout.

## Secrets

The key only goes into the `Authorization` header, which is marked sensitive. `Resolved`'s `Debug` masks it, and `Settings::provider_var` stores it as a `Secret`. Logs carry the status, a body prefix of at most 500 characters (as in Python), the model label and tool-call ids, never headers or the key.

## Test map

| Python behaviour | Rust test |
|---|---|
| `build_provider` / `_resolve_config_key_and_url` / `require_api_key` | `factory::tests::*` |
| `thinking_request_fields`, `normalize_thinking_level`, `clamp_thinking_level`, `thinking_budget` | `thinking::tests::*` |
| `sanitize_openai_tool_pairs`, `flatten_tool_content_for_provider`, option types, MiMo effort, tiers, sampling defaults | `request::tests::*` |
| `iter_sse_data`, chunk schema, `_usage_from_openai`, tool-call assembly | `stream::tests::*` |
| `stream_with_retry`, `parse_retry_after`, `is_non_retryable_429`, `classify_provider_http_error`, `is_context_overflow_response` | `retry::tests::*` |
| headers, wire model, status errors, transport error names, read timeout | `client::tests::*` |
| End-to-end: 30 cases recorded from the Python provider against `contract-tests/mock_provider` (text, reasoning, tool calls, usage, 400/401/403/404/413/422/429/500/503, connect refused, request bodies) | `tests/parity.rs` (in-process replay), `contract-tests/providers` (`TARGET=python` and `rust`, against the real mock) |

The parity files in `tests/parity/` come from `contract-tests/providers/record_parity.py`. Each holds the case, the recording as the mock parses it, and the Python requests and events.
