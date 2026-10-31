# evoflux-gateway

The v4 gateway (design §3, Phase 0 Task 10): the routing table, the Python
sidecar supervisor and the front proxy that `evoflux-server` (Task 11) serves.

- `routing.rs` loads `server/routing.toml`. In a route, a literal segment
  matches itself, `{param}` matches exactly one non-empty segment and a final
  `**` matches the rest of the path. The most specific route wins, compared
  segment by segment (literal, then `{param}`, then `**`). So
  `/api/team/{session_id}/terminal/**` beats `/api/team/**`. Unmatched paths go
  to Python. `EVOFLUX_ROUTE_OVERRIDE` overrides owners per unit.
- `supervisor.rs` starts Python with `serve --host 127.0.0.1 --port 0
  --handshake`, keeps it in a Job Object (Windows) or process group (POSIX)
  through `process-wrap`, and restarts it with the 1 s / 4 s / 10 s backoff
  (Review Focus 1).
- `proxy.rs` sends Rust-owned paths to the Rust router and forwards the rest to
  Python.

## Proxy choice

**`axum-reverse-proxy`**, as the plan asked us to try first, for plain HTTP and
SSE. `test_sse_events_not_buffered` passes with it: frames stream as Python
writes them, and no compression, timeout or body limit is added. The
`hyper_util::client::legacy` fallback was not needed for HTTP.

WebSocket upgrades do not go through `axum-reverse-proxy`. The gateway sends
the upgrade request itself over its own `hyper::client::conn::http1`
connection, with a 500 ms connect timeout (see `CONNECT_TIMEOUT`). Once
Python answers `101`, it splices the two upgraded connections at the byte
level. Any other answer, such as the `403` Python returns when it closes a
socket before accepting it, reaches the client unchanged.

## Tests

```bash
cargo nextest run -p evoflux-gateway
uv run --group contract pytest contract-tests/gateway -q --no-cov
```

`evoflux-gateway-harness` (`src/bin/harness.rs`) is a test-only binary used by
the contract and supervisor tests. The product binary is `evoflux-server`.

## Shadow mode and recording

A unit whose owner is `shadow` is answered by Python; the gateway also runs
the same `GET` against the Rust routes in the background, normalizes both
answers (the rules of `contract-tests/normalize.py`) and appends the
differences to `<state_dir>/shadow/<unit>.jsonl`. Other methods go to Python
only, and `RoutingTable::check_shadow_get_only` rejects a shadow unit that owns
a path with a non-GET operation in the OpenAPI document.
`EVOFLUX_SHADOW_PYTHON_TWICE=1` also replays each request against Python to
tell noise from real differences.

`EVOFLUX_GATEWAY_RECORD_DIR=<dir>` writes request/response pairs to
`<dir>/traffic.jsonl` (SSE as event lists) without `Authorization`, cookie and
`_token` values. Request bodies are scrubbed, with bodies over 1 MiB stored as
SHA-256 and length only. `seq` records request order. **Recorded responses can
still hold secrets and personal data.** Run `make scrub FILE=<recording>` (`scripts/migration/scrub.py`) before
sharing or committing a recording.
