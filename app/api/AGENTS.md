# app/api/ — Agent Instructions

FastAPI application assembly, dependencies, schemas, and HTTP/SSE routes.

## Where to look first

```
app.py       FastAPI app factory, middleware, static web mount
deps.py      Shared dependencies
routes/      Route modules grouped by product area
schemas/     API request/response schemas
```

## Common feature checks

- New endpoint: add route logic in `routes/`, schemas in `schemas/` when shared, and tests in `tests/api/routes/`.
- Streaming/SSE change: check frontend SSE parser/store handling in `web/src/api/` and `web/src/stores/`.
- Desktop-only auth behavior: check `app.core.desktop_auth` tests and make sure browser/dev flows still work.
- Keep routes thin; move durable business logic to `app/services/` or `app/agent/`.

## Commands

```bash
uv run pytest --no-cov -q tests/api
uv run ruff check app/api tests/api
uv run ty check app/
```

## Gotchas

- Tests can fail with `401` if `EVOFLUX_DESKTOP_TOKEN` is inherited; unset it for normal route tests.
- Preserve response shapes consumed by `web/src/api/client.ts` and query hooks.
- Use FastAPI dependency overrides in tests instead of monkeypatching route internals when possible.
