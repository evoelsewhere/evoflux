---
title: Model capabilities registry
status: open
owner: providers
opened: 2026-05-17
updated: 2026-05-28
---

# Tech debt: per-model capability metadata

## Current state

`app/agent/providers/capabilities.py` resolves capability flags via an
**exact-match lookup** against the shared model registry. Registry data comes
from the bundled minimized JSON snapshot (`app/agent/providers/model_registry.json`),
the cached/refreshed `https://models.dev/api.json` feed, and an optional local
YAML overlay at `{EVOFLUX_CONFIG_DIR}/model_registry.yaml`. The same registry
also contains token limits, cost, support flags, status/release metadata, and
advertised thinking levels consumed by `app/agent/providers/model_metadata.py`.

Lookup rule:

1. Exact `provider:model` match with a `capabilities:` block → those flags, sparse-merged
   onto the all-false defaults.
2. Otherwise → all-false / text-out-only defaults.

There are no prefix fallbacks and no name-substring heuristics. Exact model
metadata is refreshed from models.dev at runtime unless
`EVOFLUX_MODEL_REGISTRY_REFRESH=false` is set. Runtime provider/model IDs
that differ from models.dev source IDs are handled through provider-owned
compatibility aliases.

## Why this shape

- **Bundled JSON lists only special-capability models for modalities.** A model that does
  plain text-in / text-out doesn't need an entry — it gets the right
  defaults by virtue of *not* being listed. That keeps the file small
  and the maintenance question trivial: "does this new model have
  vision / image-output / audio / video?" If no, do nothing.

- **Conservative on unknowns.** An un-curated model can't accidentally
  trip the chat attachment gate or the read tool's image handler. The
  worst-case for a forgotten entry is a vision-capable model refusing
  images until someone notices and adds a small registry entry.

- **One registry shape.** Modality, limits, cost, support flags, lifecycle data,
  and thinking metadata now live together, so adding a new flagship model does
  not require keeping multiple exact-match files in sync.

- **Fresh before and after release.** Maintainers refresh the bundled JSON with
  `uv run python scripts/update_model_registry.py` before shipping. Installed
  apps also refresh from models.dev into `{EVOFLUX_CACHE_DIR}/models-dev.json`
  so users do not need a new app release for routine model metadata updates.

## Why the previous prefix-fallback design was discarded

The interim design (commits before this one) resolved capabilities by
longest-prefix match on the `provider:` portion of the ID, e.g.
`openai:` → vision-true, `deepseek:` → vision-false. That was simpler
than a per-model table but had two failure modes:

- **Over-permissive.** `openai:text-embedding-3-small` inherited
  vision=true from the `openai:` prefix and would only fail at the
  upload boundary if a user actually attached an image to a request
  bound for an embedding endpoint.
- **Over-conservative.** `bedrock:` defaulted to vision=false because
  Bedrock hosts both vision (Claude 4.x, Nova) and text-only (Titan
  small) models. Real Claude-on-Bedrock requests rejected image
  attachments needlessly.

The exact-match table fixes both while models.dev plus the release script reduces
the curation burden.

## Long-term direction

The runtime-fetched registry is now in place through models.dev. If we need
metadata that models.dev does not expose, evaluate extending the upstream schema
or introducing a project-owned supplemental feed. The closest historical
reference remains CLIProxyAPI's `models.json`:

- <https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/registry/models/models.json>
- <https://github.com/router-for-me/CLIProxyAPI/blob/main/internal/registry/model_definitions.go>

That schema carries `display_name`, `context_length`,
`max_completion_tokens`, `supportedGenerationMethods`,
`thinking: {min, max, levels}`, and `supported_parameters` per model,
grouped by channel/provider.

## Out of scope until then

- Re-introducing prefix fallbacks or name-substring heuristics. They
  drift faster than provider catalogs evolve.
- Per-user override files other than `{EVOFLUX_CONFIG_DIR}/model_registry.yaml`.

## Symptoms that warrant prioritising this

- The YAML grows past ~200 entries and PRs adding new models start
  blocking on review latency.
- Users routinely surprised that a model is missing a capability the
  provider already supports.
- Need for any capability beyond the current axes (e.g. routing on
  context length, gating reasoning effort, distinguishing
  image-generation vs. chat models).
