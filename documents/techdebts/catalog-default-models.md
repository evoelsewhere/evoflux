---
title: Trim catalog default_models
status: resolved
owner: providers
opened: 2026-05-18
resolved: 2026-05-18
---

# Tech debt: shrink `catalog.py` to the structural metadata only

## Resolution (2026-05-18)

Resolved by commit removing `default_models` from 12 of 13 catalog
entries. The single remaining entry is `vertexai`, where the upstream
API has no usable model-listing endpoint — `publisherModels.list`
returns hundreds of mixed-purpose models (PaLM, Codey, Imagen,
custom-trained, etc.) and there is no provider-side notion of "the
Gemini models a chat client should expose." Until that changes, the
catalog carries a small curated list under the renamed
`fallback_models` field. The name signals intent: this is a fallback
because no listing endpoint exists, not because we're stockpiling
defaults.

Behavioural changes that shipped with the cleanup:

- `/api/agents/registry` no longer contributes any model unless its
  provider is *configured* on this machine. Previously every catalog
  entry's `default_models` was added unconditionally, which is how
  unconfigured providers (e.g. CLIProxyAPI on a machine without it
  installed) leaked into the agent settings dropdown.
- `/api/settings/providers/{id}/models` returns the curated
  `fallback_models` only when live discovery fails *and* the provider
  has the field set. The response's `source` field renamed
  `default → fallback` to match.
- 12 providers (OpenAI, OpenRouter, Z.AI, NVIDIA, xAI, DeepSeek, 9Router,
  CLIProxyAPI, Ollama, Copilot, Codex, Google Gemini) now rely entirely
  on `app/agent/providers/model_discovery.py` for their model lists.
  Each has a working `/models` (or equivalent) endpoint upstream.

## Why one entry stayed

The original tech-debt doc named Bedrock, Codex, Copilot, and Vertex
AI as discovery-unsupported. Re-auditing during this fix found that
Bedrock, Codex, and Copilot now have working `discover_provider_models`
branches (Bedrock via `boto3.client("bedrock").list_foundation_models`,
Codex/Copilot via their OAuth-authenticated model listing endpoints).
Vertex AI remained the lone exception.

## What still warrants reopening

- Vertex AI adds a chat-models-only listing endpoint (or the
  `publisherModels.list` filter improves enough to be usable). Drop
  `fallback_models` from that entry too.
- A provider added to the catalog without working live discovery. Add
  `fallback_models` rather than reverting the cleanup.
