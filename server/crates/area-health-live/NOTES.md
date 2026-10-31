# area-health-live — NOTES

Unit `health-live` (edge-stateless). Python source: `app/api/routes/health.py`
(`health_live` only). `/api/health/ready` and `/api/health/diagnostics` stay in
`health-diagnostics`.

## Endpoints

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/api/health/live` | none (exact path is in `desktop_auth._EXEMPT_EXACT`; wrong or missing credentials still get 200) | `200 {"status": "ok", "version": "<app version>"}` |

- Keys are exactly `status` and `version`; `version` is `app.core.version.VERSION`.
- Query parameters are ignored (no validation error exists). Other methods: `405 {"detail": "Method Not Allowed"}` with `Allow: GET`.
- `/api/health/live/<x>` is `404 {"detail": "Not Found"}` (under the exempt `/api/health/` prefix, so no 401 first).

## State, files, side effects

None. No DB, no lock, no file, no event, no background task. The handler is a
plain `async def` returning a dict, so the liveness answer proves the event loop
is alive; the Rust handler must likewise never touch the DB writer, read pool or
any area lock (design §6.3).

## Odd behaviour (port as-is)

- The auth exemption for this path lives in the desktop auth middleware, not in
  the route; the Rust gateway/core auth already carries the same exempt list.
- `version` comes from the build; contract tests only require a non-empty
  string, so Python and Rust need not share a version string.

## Pins check

`rg "health/live|health_live"` outside `health.py` callers:

| Caller | Use | Verdict |
|---|---|---|
| `app/core/desktop_auth.py` | exempt path list | reads the same list, no adapter |
| `app/cli/commands/health.py`, `app/cli/commands/serve.py` | HTTP probe of `/api/health/live` | HTTP only, no adapter |
| `web/src/components/AppBackendDialog.tsx` | UI probe over HTTP | HTTP only, no adapter |

No Python code imports `health_live` as a function.

## Contract tests

`contract-tests/health-live/test_health_live.py` (§5.2 minimum: success, auth
missing/wrong, no validation to fail, empty state n/a, concurrent access;
no pagination, writes, SSE or WS).

## Test map

| Python test | Covered by |
|---|---|
| `tests/api/test_health_endpoints.py::test_live_always_returns_200` | contract `test_live_success_body`, `test_live_needs_no_credentials` |
| `tests/api/test_health_endpoints.py::test_bare_health_returns_404` | n/a: `/api/health` belongs to the `health-diagnostics` unit |
| `tests/api/test_health_endpoints.py::test_ready_*` (3) | n/a: `/ready` stays in `health-diagnostics` |
| `tests/api/test_gateway_mode.py` live cases | n/a: gateway-secret behaviour of the Python middleware, tested on a stub app; the Rust gateway is covered by its own tests |
| `tests/core/test_desktop_auth.py` live exemption | contract `test_live_needs_no_credentials`, `test_live_ignores_wrong_credentials` |
| (new, no Python unit test) | contract `test_live_has_no_parameters`, `test_live_rejects_other_methods`, `test_live_sub_path_is_not_the_probe`, `test_live_concurrent_requests`, `test_live_version_is_stable` |

## Phase 1 notes for L1b

- Must keep `make perf-responsiveness TARGET=rust` green, including the
  scenarios that are `xfail` for Python (`V3_STALLS`).
- `server/Cargo.toml` `members` does not list `crates/area-health-live` yet:
  that file is shared, so the orchestrator adds the member when L1b needs to
  build the crate. The `src/lib.rs` stub needs `axum` (already in the
  workspace through `evoflux-gateway`); no new crate version is introduced.
