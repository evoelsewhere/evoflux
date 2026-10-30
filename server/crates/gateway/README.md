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
