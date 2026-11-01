# Known differences

## providers (AR1, `server/crates/area-providers`)

- **No models.dev catalog.** Thinking fields, budgets and service tiers follow Python's path for a model the catalog has no row for: fallback levels per dialect, budgets from the ceilings alone, and `service_tier` forwarded as is. For a model the catalog does describe, Python may clamp levels, size budgets from the model's output limit or apply a catalog tier patch.
- **Providers in scope.** `router9`, `xiaomi`, `cliproxy`, `mistral`, `cohere`, `groq`, `cerebras`, `together`, `deepinfra`, `sambanova`, `perplexity` and `vercel`. Other registry IDs are `ProviderError::NotPorted`. Unknown IDs get Python's "Unsupported provider" message without a catalog or plugin lookup.
- **Settings are a snapshot.** Python reads `os.environ` at call time, so keys saved in Settings → Providers apply without a restart. Rust reads the `Settings` it is given. Like Python, a `.env` file only sets the fields `app/core/config.py` declares; other provider variables (`MISTRAL_API_KEY`, `GROQ_BASE_URL`, ...) come from the process environment alone.
- **Event shape.** The assembled tool call carries parsed JSON arguments (an empty string becomes `{}`) where Python keeps the string. `Done.finish_reason` is `""` when the provider sent none. Python's `cache_probe` diagnostics are not ported.
- **Size caps.** Python buffers without limit. Rust ends a stream with `ProviderError::TooLarge` (not retried) when one SSE line passes 16 MiB or one tool call's arguments pass 16 MiB, and keeps only the first 64 KiB of an error body (after gzip decoding), decoded as lossy UTF-8 instead of by the response charset.
