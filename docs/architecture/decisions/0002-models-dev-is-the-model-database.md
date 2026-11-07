# 0002. models.dev is the model database

| | |
| --- | --- |
| Status | Accepted |
| Date | 2026-11-05 |
| ADD sections | [7. Data view](../README.md#7-data-view) |
| Related | [App database SDD](../../features/app-database/sdd.md) |

## Context

Model lists, context and output limits, costs and thinking options change
every week. Hardcoding them in code or in the provider catalog went stale and
needed a release for every new model.

## Decision

models.dev (`https://models.dev/api.json`) is the source of model facts. The
engine caches it in `evo.db` and refreshes it; a bundled snapshot only seeds
an offline first run. The provider catalog holds connection facts only
(endpoints, auth, wire API). evo does not send `temperature`.

## Consequences

- No model ID, limit, price or thinking option is hardcoded in code or
  catalogs; read `evo_runtime::models_dev`.
- Provider-specific behaviour is catalog data, not per-model code.
- A model missing from models.dev is added there or in the user's
  `models.json`, not in evo's source.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Hand-maintained catalog in the repo | stale quickly; a release per model |
| Each provider's models endpoint | inconsistent metadata; many lack limits and prices |
