# evoflux-server

The v4 product binary (Phase 0 Task 11): the gateway from `evoflux-gateway` in
front of the Python sidecar, started the way the desktop shell starts Python.

```text
evoflux-server serve [--host HOST] [--port PORT] [--handshake]
                     [--generate-token] [--parent-pid PID] [--python-root DIR]
```

The flags mean what they mean for Python's `serve` (`app/cli/commands/serve.py`).

- **Handshake.** `EVOFLUX_HANDSHAKE {"port":…,"pid":…,"version":"…","token":"…"}`
  is printed only after Python has printed its own, so a slow first start
  (database migrations) never hands the shell a port that cannot answer yet.
  `version` is `app/version.txt`. `token` is the generated token or
  `EVOFLUX_DESKTOP_TOKEN`, and `""` when there is neither.
- **Python wait.** Up to 85 s (`EVOFLUX_GATEWAY_PYTHON_WAIT_S`), under the
  shell's 90 s first-attempt budget. Without a Python handshake the server
  exits with code 3. Python's output, including its last lines, is already on
  stderr by then.
- **Locating Python.** `--python-root` or `EVOFLUX_SIDECAR_ROOT` names the
  bundled layout (`python/` and `site-packages/`).
  `EVOFLUX_GATEWAY_PYTHON_BIN`, `EVOFLUX_GATEWAY_SITE_PACKAGES` and
  `EVOFLUX_GATEWAY_CLI_ENTRY` override each part for development and tests.
- **Routing.** The repository's `server/routing.toml` is built in.
  `EVOFLUX_GATEWAY_ROUTING` replaces it with a file, and `EVOFLUX_ROUTE_OVERRIDE`
  works as in the gateway.
- **Parent watch.** With `--parent-pid`, a thread polls the parent every 500 ms.
  When the parent is gone, the server shuts down (exit code 1) and is forced out
  after 15 s. A reused PID does not count as the parent, and the watch works on
  Windows too.
- **Own routes.** `/metrics/gateway` serves the gateway's Prometheus metrics.
  `/metrics` stays Python's. The 100 ms stall watchdog is on, and every handler
  runs inside `CatchPanicLayer`, so a panic answers 500
  `{"detail":"Internal Server Error"}` and the server keeps running.
- **Exit codes.** 0 after a normal shutdown, 1 for a startup failure or a dead
  parent, 2 for a usage error, and 3 when Python never became ready.
- `EVOFLUX_GATEWAY_STATE_FILE` (tests only) receives `{"pid":…,"port":…}` of the
  current Python child each time it becomes ready.

## Auth

Python stays the auth authority for every route it serves. It gets the
generated token or `EVOFLUX_DESKTOP_TOKEN`, and it reads `EVOFLUX_ACCESS_KEY`
and `settings.yaml` itself.

Rust-owned routes go through `evoflux_core::auth::DesktopAuth` with Python's
`expected_desktop_token` order: `EVOFLUX_DESKTOP_TOKEN`, then
`EVOFLUX_ACCESS_KEY`, then `server.access_key` from `{config}/settings.yaml`.
The server does not start when it cannot read that key: invalid YAML, a
non-mapping `server`, a non-string key, or a YAML 1.1 boolean spelling such as
`yes`. Python would drop such a value and run without auth.

## Open items

1. **Remote lock claim and WebSocket auth are not ported.** Python claims the
   single-device lock for every trusted tailnet request
   (`remote_use_service.claim`) and checks WebSocket tokens itself
   (`websocket_authorized`). Until Rust ports both, Rust-owned routes refuse
   trusted tailnet requests with 403 `{"detail":"Remote access is not available
   for this route yet.","code":"remote_route_unavailable"}`. Python-owned routes
   are unaffected, so remote use keeps working through the proxy. Port both
   before any unit that serves tailnet traffic is cut over to Rust.
2. **`server.access_key` is read once.** Python re-reads `settings.yaml` on each
   request. For Rust-owned routes a changed key applies after a restart.
