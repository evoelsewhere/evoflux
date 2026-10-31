# Known differences

## providers (AR1, `server/crates/area-providers`)

- **No models.dev catalog.** Thinking fields, budgets and service tiers follow Python's path for a model the catalog has no row for: fallback levels per dialect, budgets from the ceilings alone, and `service_tier` forwarded as is. For a model the catalog does describe, Python may clamp levels, size budgets from the model's output limit or apply a catalog tier patch.
- **Providers in scope.** `router9`, `xiaomi`, `cliproxy`, `mistral`, `cohere`, `groq`, `cerebras`, `together`, `deepinfra`, `sambanova`, `perplexity` and `vercel`. Other registry IDs are `ProviderError::NotPorted`. Unknown IDs get Python's "Unsupported provider" message without a catalog or plugin lookup.
- **Settings are a snapshot.** Python reads `os.environ` at call time, so keys saved in Settings → Providers apply without a restart. Rust reads the `Settings` it is given. Rust also reads `.env` for providers that `app/core/config.py` does not declare (`MISTRAL_API_KEY` and the like), which Python sees only through the process environment.
- **Event shape.** The assembled tool call carries parsed JSON arguments (an empty string becomes `{}`) where Python keeps the string. `Done.finish_reason` is `""` when the provider sent none. Python's `cache_probe` diagnostics are not ported.
