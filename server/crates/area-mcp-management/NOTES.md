# area-mcp-management NOTES

Python source: `app/api/routes/mcp.py`, `app/api/schemas/mcp.py`,
`app/agent/mcp/{config,models,oauth,manager,runner,transport,lazy}.py`, plus the
parts of `app/plugin_platform/runtime.py` (`plugin_mcp_runtime`) that the routes
call. Unit `plugins-mcp` (`/api/plugins/**` and `/api/mcp/**`; pin breaker
`adapter:plugins-mcp`, services `mcp` and `plugin_mcp`, see `server/routing.toml`).
This lane owns `/api/mcp/**`; `/api/plugins/**` is the sibling lane
`plugins-marketplace` (`area-plugins-marketplace`). Contract tests:
`contract-tests/mcp-management/` (175 cases, 174 pass and 1 skips on Windows, the
POSIX `.env` mode check, against Python v3.1.1; snapshots under `snapshots/`).

**Status:** La (this crate's stub, NOTES, contract tests). The crate is not mounted:
a mounted empty router would answer 404 for a unit still owned by Python. Lb sizing
and dependencies are at the end. The unit is one cutover unit, so Lb of both lanes
must land (and `adapter:plugins-mcp` must pin) before `/api/mcp/**` leaves Python.

Test fixtures (no network, no third-party servers):

- `stdio_server.py` is a stdlib MCP stdio server (newline-delimited JSON-RPC:
  `initialize`, `tools/list`, `tools/call`). `--dump FILE` writes its argv, cwd,
  environment and pid, so every launch parameter is observed from the child.
- `http_server.py` is a stdlib MCP Streamable-HTTP server on `127.0.0.1:<port>`; it
  records every request (method, path, headers) and can require a bearer token or
  serve `/.well-known/oauth-authorization-server`.
- App-tool tests insert a `chat_sessions` row and a tool `session_messages` row
  straight into `evoflux.db` (nothing in the public API makes an `mcp_app` without
  a real tool run). Under Rust the database layout is the same file.

## Endpoints

Every route needs auth: `401 {"detail":"Unauthorized — EvoFlux access key required."}`
for a missing or wrong token, before body validation. FastAPI `422` bodies are
`{"detail":[{"type","loc","msg","input"...}]}`; other errors are `{"detail":"<text>"}`;
an unhandled exception is a plain-text `500 Internal Server Error` and **uvicorn closes
that connection** (the next request on the same keep-alive connection fails, the
tests use a fresh client after a 500).

`ServerStatusResponse` = `name, transport (stdio|http), enabled, state, error,
tool_names[], started_at (ISO-8601 UTC with microseconds, or null), config
(ServerBody or null), source ("global"|"plugin"), plugin_installation_id,
plugin_name, plugin_server_name`. `state` is one of `stopped` (disabled), `starting`,
`ready`, `error`, `auth_required`. `config` echoes the saved entry with **header
values and OAuth client id/secret replaced by `********`** and env values as stored
(refs). Status of a server with an empty `command` or a bad URL is a normal `201`
with `state: "error"`; start-up failures are never an HTTP error.

| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `GET /api/mcp/servers` | - | `200 {"servers":[status]}`: global runners in runner (file) order, then plugin runtime runners (`source:"plugin"`, `config:null`) | `500` if `mcp.json` does not load (M1) |
| `GET /api/mcp/servers/{name}` | - | `200 status`; looks in the live global runners first, then plugin runners by `runtime_name` | `404 MCP server '<n>' not found.`; `500` for an existing runner when `mcp.json` does not load (M1) |
| `POST /api/mcp/servers` | `{"name","server":{"transport":"stdio"\|"http",...}}` (discriminated, `extra=forbid`) | `201 status` after the runner restarts (waits up to 15 s for `ready`/`error`; a server that never answers is returned as `starting`) | `422 {"detail":"Invalid MCP server name 'x': must match ^[a-zA-Z][a-zA-Z0-9_-]*$ (letters, digits, underscore, hyphen; starting with a letter)."}`; `409 MCP server '<n>' already exists.`; `422` list for the schema; `500` (S2, M1) |
| `PUT /api/mcp/servers/{name}` | `{"server":{...}}` | `200 status` (replaces the entry, restarts the runner; transport may change) | `404 MCP server '<n>' not found.` (the name in the URL is not validated); `422` list; `500` |
| `DELETE /api/mcp/servers/{name}` | - | `200 {"name"}` | `404`; `500` (M1) |
| `POST /api/mcp/servers/{name}/restart` | - | `200 status` (restart, waits up to 15 s; `stopped` for a disabled server) | `404`; `500` (M1) |
| `POST /api/mcp/servers/{name}/oauth/connect` | - | `200 status` (state `ready`) | `404`; `400 MCP server '<n>' is not configured for OAuth.` (stdio, or http without `oauth`); `409 <runner error or "MCP server '<n>' did not connect.">` when the state is not `ready`; `500` (M1) |
| `POST /api/mcp/apply` | - | `200 {"servers":[status]}` (global runners only, no plugin entries) after reconciling with `mcp.json` | `422 {"detail": "<load error>"}` for a missing-`{`, wrong-shape, invalid-name or schema-invalid file (text is pydantic's, e.g. `4 validation errors for MCPConfig ...`) |
| `POST /api/mcp/app-tools/call` | `{"session_id","tool_call_id","server","tool","arguments"?}` | `200 {"result": CallToolResult}` (`model_dump(by_alias, exclude_none)`: `content[]`, `isError`, `resultType:"complete"`) | `422 Invalid session_id.` (not a UUID); `404 MCP app artifact not found.`; `403 MCP app server mismatch.`; `404 MCP server not found.`; `409 MCP server '<n>' is not connected.`; `403 MCP tool '<t>' is not available.`; `502 MCP app tool call failed.` (any other failure) |

Behaviour worth knowing for the port:

- **Mutations are write-then-restart.** `POST`/`PUT` validate, move secrets to `.env`
  (below), `save_config`, then `mcp_manager.restart_server(name)` which re-reads the
  file; `DELETE` saves then `remove_runner`. The status returned is the runner's
  state after at most 15 s (`restart` with `ready_timeout`; OAuth connect waits 300 s).
- **`GET /servers/{name}` needs a live runner.** A name present only in `mcp.json`
  is `404` until the watcher (0.5 s poll) or `/apply` creates its runner.
- **`mcp_manager.start()` runs at boot in the background** (`mcp` service in the
  lifespan, not waited on); the first listing right after boot can show `starting`.
- **App-tool check order:** UUID parse (422) → artifact lookup in
  `session_messages` (`role='tool'`, matching `session_id` and `tool_call_id`,
  `extra.mcp_app` must be an object; else 404) → `mcp_app.server == body.server`
  (403) → global runner (`KeyError` falls through to the plugin runtime; both
  missing → 404) → runner `ready` with a session (409) → the **unprefixed** tool name
  must be one the server advertised (403; `mcp_<server>_<tool>` is rejected) →
  arguments pass through `protect_outbound_value` (secret/PII redaction, channel
  `mcp`; not exercised by a test, the fixture arguments contain nothing it matches)
  → `session.call_tool`.
- `ValueError` from the call is `403`, `RuntimeError` `409`, `KeyError` `404`,
  anything else `502`.

## Files read and written

| Path | Access | Detail |
|---|---|---|
| `<EVOFLUX_CONFIG_DIR>/mcp.json` | read on every route that loads config and by the watcher; written by `POST`/`PUT`/`DELETE` | `{"servers": {name: entry}}`, `json.dumps(indent=2, sort_keys=True) + "\n"` of `model_dump(mode="json")`, atomic (`mkstemp(".mcp.json.", ".tmp")` in the same dir, `os.replace`, so mode 0600 on POSIX). Written in text mode, so **CRLF on Windows** (tests fold). Stdio entry keys: `args, capabilities, command, cwd, enabled, env, transport`; http: `capabilities, enabled, headers, oauth, transport, url`. Missing file = empty config. First start copies the seed `{"servers": {}}` to it (`seed/mcp.json`). Names are validated (regex above) on every load and save. The aliases `type` (for `transport`) are accepted in the file but not in request bodies |
| `<EVOFLUX_CONFIG_DIR>/.env` | read for `${VAR}` expansion (`dotenv_values`) and by the watcher fingerprint; **written by create/update** | one `KEY="value"` line per literal secret (`\` and `"` escaped, newlines kept raw), existing lines kept, a matching `KEY=` line updated in place, new keys appended, final `\n`; `write_text` (not atomic), `chmod 0600` (POSIX; skipped on Windows). Shared with the provider API keys (settings-providers lane writes the same file) |
| `<EVOFLUX_CACHE_DIR>/mcp-oauth/<name>.json` | read by `has_cached_oauth_tokens` and the SDK token storage; written by the SDK (`tokens`, `client_info`); deleted by `oauth/connect` (`clear_cached_oauth`) | `json.dumps(indent=2)`, `chmod 0600`. Keyed by server **name** (not validated as a path component at this point, but names are validated on create); never deleted with the server (O1) |
| `evoflux.db` `session_messages` | read by `app-tools/call` | `extra` JSON, `extra.mcp_app.server` |
| `<EVOFLUX_CONFIG_DIR>/settings.yaml`, `<state>/conductor/...` | not touched | |

Other writers of `mcp.json` (not routes of this unit): the imports unit
(`/api/import/*`, `app/services/importers/{claude_code,cursor,generic}.py`), the
`mcp-installer` builtin skill script `mcp_apply.py` (calls these routes, falls back to
a direct atomic write of `mcp.json` when the sidecar is unreachable) and agents or
users editing the file; the watcher reconciles all of them within 0.5 s.

## Processes the unit starts

One long-lived `asyncio.Task` per enabled server, `mcp-<name>`, owned by the
process-wide singleton `mcp_manager` (`MCPManager(watch_config=True)`, a subclass of
`MCPRuntime`). The plugin runtime (`plugin_mcp_runtime`, a second `MCPRuntime` with
the watcher off, fed from installed plugins) is the sibling lane's; `/api/mcp` only
lists it and falls back to it for `GET /servers/{name}` and app-tool calls.

**stdio server (`transport.py`, `runner.py`).**

- *Start:* `resolve_stdio_launch`: effective `PATH` = `env["PATH"]` if configured,
  else the user's login-shell `PATH` (`_get_user_path`: spawns the acceptable shell
  from `shell_runtime` with `printf "__EVOFLUX_PATH__%s\n" "$PATH"`, 3 s timeout,
  cached for the process, forced refresh when the command is not found), else the
  sidecar's `PATH`. `shutil.which(command, path=effective_path)`; if it is not found
  the **raw `command` string is used**. The child environment is **only** that
  `PATH` plus the configured `env` (values `${VAR}`/`$VAR` expanded from
  `os.environ`, then `<config>/.env`, left as written when unknown) plus the MCP
  SDK's own default safe variables (on Windows `SYSTEMROOT`, `APPDATA`, `TEMP`, ...);
  the sidecar's `EVOFLUX_*`, `PYTHONPATH` and provider keys do not reach the child.
  `args` and `cwd` are passed literally (no expansion, no confinement). Launched by
  the SDK's `stdio_client(StdioServerParameters(command, args, env, cwd))`
  (stdin/stdout pipes, stderr to the sidecar's stderr). Then `ClientSession.initialize()`
  and `list_tools()`; state `ready`, `tool_names = ["mcp_<server>_<tool>"]`,
  `started_at = now (UTC)`.
- *Supervision:* none beyond the session. A server that exits after start leaves the
  runner `ready` until the next tool call fails; there is no restart-on-exit and no
  health check. A start failure sets `error` with `"<Type>: <msg>"` or
  `"ExceptionGroup (...)"` nesting (pinned: `ExceptionGroup (ExceptionGroup (MCPError:
  Connection closed))` for a server that exits during `initialize`). The watcher
  (0.5 s) restarts runners whose config entry changed (or all when `.env` changed:
  `force`).
- *Stop:* `runner.shutdown.set()`; the task leaves both SDK contexts (the SDK closes
  stdin, waits, then terminates, then kills; behaviour is the SDK's, the contract
  tests only observe the pid gone after delete, restart, update and disable). A task
  that does not finish in 10 s is cancelled. `mcp_manager.stop()` does this for every
  runner at shutdown (lifespan, before the DB is closed). A hard kill of the sidecar
  leaves it to the child to notice its closed stdin (P1).

**http server.** `httpx2.AsyncClient(headers=resolved headers, auth=OAuth provider,
timeout 30 s / read 300 s, follow_redirects=False)` + `streamable_http_client(url)`.
Headers are `${VAR}`-expanded the same way as env values at connect time. The MCP
handshake the fixture saw: `POST initialize`, `POST notifications/initialized`,
`GET /mcp` (the SSE listener; a `405` is fine), `POST tools/list`; on stop `DELETE
/mcp`.

**OAuth (http servers with an `oauth` object, `oauth.py`).**

- `auth_required` before any network call when: `oauth` is set, there are no cached
  tokens (`tokens` key non-empty in the cache file) and no connect is in progress; or
  the host is `mcp.slack.com` and `oauth` is missing.
- `POST .../oauth/connect` adds the name to `_interactive_oauth` (in-memory set,
  removed in `finally`), deletes the cache file, restarts with `ready_timeout=300`.
  If the config has no resolvable client id, it first GETs
  `<origin>/.well-known/oauth-authorization-server` with `httpx` (10 s) and needs
  `registration_endpoint` or `client_id_metadata_document_supported`, else `409`
  "requires OAuth app credentials". If the server then answers 401, the SDK runs the
  authorization-code flow: **`webbrowser.open(authorize_url)` on the host** and a
  `http.server` on `127.0.0.1:<random>` (`/callback`, up to 300 s) for the redirect;
  tokens and registered client info go to the cache file. No contract test goes
  through this path (it would open a browser); the connect tests use a server that
  never answers 401, so it ends in `ready` without tokens. **The Rust port needs its
  own loopback listener and browser launch, and a way to test them.**
- A 401 or "unauthorized" message from a server **without** `oauth` is mapped to
  `auth_required` only when the error text contains `missing_token`, `unauthorized`,
  `401` or `authentication`; with this SDK a bare 401 from the fixture is an `error`
  state with `ExceptionGroup (ExceptionGroup (MCPError: Server returned an error
  response))` (pinned).

## In-memory registries other code reads

| Registry | Readers | Notes |
|---|---|---|
| `mcp_manager.get_tools_dict()` → `{ "mcp_<server>_<tool>": Tool }` of every `ready` runner | `app/agent/loader.py` (merged into the agent tool registry with `plugin_mcp_runtime.get_tools_dict()`, plugin tools win on a name clash) | The chat loop's tool list for MCP (agent-loop-chat, mcp-client lanes). A tool's `session_provider` reads `runner.session` at call time. Names are not unique across `_` boundaries (T1) |
| `mcp_manager.get_tools_for_server(name)` (`None` unknown, `[]` not ready), `server_names()` | `loader.py` (an agent's `mcp: [...]` list; unknown names are logged and skipped), `resolve_plugin_server_name`, `all_mcp_server_names` | |
| `mcp_manager.list_status()` / `get_status()` | `/api/health` diagnostics (`app/api/routes/health.py`, MCP check), `/api/diagnostics` (`servers` count) | state strings are shown to the user |
| `mcp_manager.call_app_tool()` | this unit | |
| `config_path()` mtime stamp (`app/agent/drift.py`, `member.py`) | agent loop prompt/tool drift detection: a changed `mcp.json` rebuilds the running agent before the next turn | The file's bytes, not the API, are the signal; `team_manager` does not invalidate on `/api/mcp` calls |
| `_interactive_oauth` set | `manager._run_server` | per connect |

The Rust server must keep `mcp.json` the source of truth, expose the same registry to
the Rust chat loop (mcp-client lane) and honour the mtime-stamp drift check.

## Request fields that become a command, argument, env var, path, URL or header

| Field (route) | Becomes | What Python does | Pinned by |
|---|---|---|---|
| `server.command` (POST/PUT, stdio) | the executable that is **spawned** | `min_length=1` only; resolved with `shutil.which` on the effective `PATH`, else used as given (absolute or relative path, anything). No allowlist, no confirmation, no sandbox: any holder of the access key runs any program as the sidecar's user. A missing file is `state: "error"` | `test_runtime_processes.py`, `test_servers_crud.py` (**C1**) |
| `server.args[]` (stdio) | argv, literal | no expansion, no validation, any strings including empty | `test_command_args_and_cwd_reach_the_child_unchanged`, `test_refs_are_only_expanded_in_env_values...` |
| `server.cwd` (stdio) | child working directory | not resolved, not confined to a workspace root, not checked to exist (a bad one is `error`); `null` inherits the sidecar cwd | `test_cwd_is_not_confined...`, `test_a_cwd_that_is_not_a_directory...` (**C2**) |
| `server.env` keys (stdio) | the child's environment **and** a key in `<config>/.env` **and** `os.environ[key]` of the sidecar | no key validation at all: `A=B`, empty and NUL keys are an unhandled `ValueError` 500 (**S2**); newline in a key writes a second `.env` line (**S1**); `a b`, `1BAD`, `PATH`, `OPENAI_API_KEY`, `EVOFLUX_*` are accepted and overwrite whatever `.env` already holds | `test_secrets_env.py` |
| `server.env` values (stdio) | child env value; literal values also `.env` `KEY="<escaped>"` and `os.environ` | a value matching `^\$\{NAME\}$` passes through as a ref; anything else, including `$NAME`, is a secret: replaced by `${KEY}` in `mcp.json`; empty stays `""` and is not stored. `\` and `"` escaped; newline kept raw inside the quotes | same |
| `server.url` (http) | the URL the sidecar connects to, and the origin of the OAuth well-known fetch | `min_length=1` only: `file://`, `ftp://`, free text accepted (error state); any host including loopback and link-local is allowed (SSRF surface, **U1**) | `test_http_oauth.py` |
| `server.headers` (http) | request headers on every MCP request | values `${VAR}`/`$VAR`-expanded from `os.environ`/`.env` at connect, so a header can read **any** process variable or `.env` secret and send it to the configured URL (**H1**); stored plaintext in `mcp.json`, masked only in responses; `********` merges with the previous value, or is stored literally for a new key (**S4**) | `test_secrets_env.py` |
| `server.oauth.client_id/client_secret` (http) | `.env` keys `<NAME>_MCP_CLIENT_ID/SECRET` (name upper-cased, runs of non-alphanumerics folded to `_`) and the OAuth client registration | literals moved to `.env` (and `os.environ`), refs and empty kept; `********` on create is stored literally | same |
| `name` (POST) | the dict key in `mcp.json`, the tool prefix `mcp_<name>_`, the runner task name, the OAuth cache filename `<name>.json`, the `.env` key prefix | `^[a-zA-Z][a-zA-Z0-9_-]*$`, no length limit; PUT/DELETE/restart/connect/GET take any name from the URL and only look it up | `test_servers_crud.py` |
| `server.capabilities[]` | stored; read by the chat loop as tool capabilities (`webbridge-safe`, `browser`...) | any strings accepted | `test_servers_crud.py` |
| `tool`, `arguments` (app-tools) | `call_tool(name, arguments)` on the bound server | name must be advertised by that server; arguments any JSON object, run through outbound redaction | `test_app_tools_and_errors.py` |
| `session_id`, `tool_call_id` (app-tools) | DB lookup parameters | UUID parse; bound parameters | same |

## Suspected bugs and findings (Python is not fixed; tests pin today's behaviour)

Security (needs the owner's decision before Lb; hardening needs KNOWN_DIFFERENCES entries):

- **S1 `.env` key injection and overwrite.** Env names are written raw. A newline in
  the key plants an extra line; a name equal to a provider key (`OPENAI_API_KEY`) or
  `PATH`/`EVOFLUX_*` replaces the user's stored secret and changes the sidecar's own
  environment. The file is shared with settings-providers (its S2 finding is the same
  hole).
- **S2 500s and partial effect.** `A=B`, `""` and NUL keys fail in `os.environ[...]`
  after earlier keys of the same request were already exported; nothing is saved but
  the process environment is changed, and the response is a connection-closing 500.
- **S3 secrets are exported process-wide** and are never unset: a deleted server's
  secret still expands for later servers, headers and OAuth.
- **S4 masked placeholders are stored.** `********` for a header key with no earlier
  value, or for OAuth values on create, is saved as the real value.
- **S5 delete does not clean up:** `.env` lines, the OAuth cache file and the exported
  environment stay; a new server with the same name reuses the old OAuth tokens (**O1**).
- **S6 header secrets live in plaintext in `mcp.json`** (only env and OAuth values are
  moved to `.env`).
- **C1 arbitrary command execution** by design: `POST`/`PUT` of a stdio server runs
  any executable with any args and cwd for anyone with the access key; no
  confirmation, sandbox, allowlist or audit entry. The `mcp-installer` skill makes an
  agent a second caller. **C2 `cwd` not confined** to a workspace root.
- **U1 / H1 URL and header expansion:** any URL scheme and host (incl. link-local and
  loopback) and header values that expand any environment variable or `.env` secret
  toward an arbitrary host.
- **O2 `oauth/connect`** opens a browser on the host and holds the request for up to
  300 s with a loopback listener bound to `127.0.0.1`; the well-known fetch goes to
  the configured origin with no host restriction.
- **P1 no supervision:** a server that dies after start stays `ready`; a killed
  sidecar relies on the child noticing EOF on stdin.

Correctness:

- **M1** a malformed or schema-invalid `mcp.json` is an unhandled 500 on list, get
  (of an existing runner), create, update, delete, restart and connect, while `apply`
  answers 422 and an unknown name still 404; the connection is closed.
- **M2 `.env` is not written atomically** (`write_text`) while `mcp.json` is.
- **M3 start-up state is eventually consistent:** `GET /servers/{name}` of a name in
  the file but without a runner is 404; `POST` can return `201` with `starting`.
- **M4 auth detection by substring** (`401`, `unauthorized`, `authentication`) in the
  exception text; the same server gives `error` or `auth_required` depending on its
  body.
- **T1 tool names collide:** `mcp_<server>_<tool>` is ambiguous (`a` + `b_c` and
  `a_b` + `c` both give `mcp_a_b_c`); the later runner overwrites the earlier in
  `get_tools_dict()`.
- **L1 no name length limit** (a 200-character name is accepted).
- **E1 error strings are Python-specific** (`FileNotFoundError: [WinError 2] ...`,
  nested `ExceptionGroup (...)`, pydantic validation text in the `apply` 422); Rust
  can match the shapes it controls (`Invalid MCP server name ...`, `... not found.`,
  `... already exists.`, the OAuth messages, `ExceptionGroup (ExceptionGroup (MCPError:
  Connection closed))` for an exit during start) but not the OS and pydantic text; the
  tests assert prefixes for those.

## Pins check

`adapter:plugins-mcp` has to guard both lanes: while any of `/api/mcp/**`,
`/api/plugins/**` is on Python, the Rust server must not hold a second runner set
(two supervisors for the same `mcp.json` would double-start servers). The adapter
needs the shared view `mcp_manager.list_status()` / `plugin_mcp_runtime.list_status()`
for `/api/mcp/servers`.

## Test map

All in `contract-tests/mcp-management/`.

| File | Covers |
|---|---|
| `test_auth_routes.py` | `401` on all 9 routes (missing and wrong token) before validation; a rejected write changes nothing |
| `test_servers_crud.py` | list/get/create/update/delete/restart shapes, snapshots, byte-exact `mcp.json`, name rules, 409/404, FastAPI 422 bodies, transport switch, disabled servers, 405/404 for other methods, T1 |
| `test_secrets_env.py` | `.env` movement, refs, quoting, in-place update, no cleanup, mode 0600 (POSIX), S1 to S4 findings, OAuth names, masked merges, header expansion |
| `test_runtime_processes.py` | launch (command, args, cwd, env isolation, PATH), failure states, `starting` after 15 s, stop on delete/restart/update/disable, boot load from a pre-seeded file, watcher add/remove, `apply` (unchanged, changed, invalid files) |
| `test_http_oauth.py` | http handshake, 401 handling, bad URLs, Slack rule, cached tokens as bearer, `oauth/connect` branches (404/400/409/200, dynamic registration, cache deletion), O1 |
| `test_app_tools_and_errors.py` | every app-tool branch and its order, 422 bodies, M1 (500s for a malformed file), a deleted file |

Not covered (reasons): the interactive OAuth redirect (opens a browser), `502` of app
tools (needs a server that fails mid-call), plugin-sourced entries in the list (the
`plugins-marketplace` lane installs plugins), redaction of app-tool arguments,
POSIX modes and process-tree termination on Windows.

## Lb: size and dependencies

**Size: large, about 2,200 lines of non-test Rust**, most of it not the routes.

1. *Routes and config (about 500 lines):* the nine routes, `mcp.json` load/save with
   pydantic-compatible validation and the exact byte output, name rules, `.env`
   read/write with the exact line format, secret refs and masking.
2. *Runtime (about 900 lines):* runners with start/stop/restart/timeouts (10 s stop,
   15 s ready), reconciliation and the 0.5 s watcher with its fingerprint (file and
   `.env`), status states and error strings, login-shell `PATH` resolution, the tool
   projection (`MCPTool`: schema, naming, capabilities, apps) and the registry other
   units read.
3. *MCP client (about 600 lines):* initialize, tools/list, tools/call, stdio framing
   and Streamable HTTP (POST/SSE, session id, DELETE) with redirect rules.
4. *OAuth (about 250 lines):* discovery, dynamic client registration, authorization
   code with PKCE, loopback callback, token store and refresh, browser launch.

**Depends on:** (a) an MCP client library or its own implementation (the Python side
uses the `mcp` SDK 2.x and `httpx2`; the `mcp-client` lane owns `manager/runner/tools/
transport` in the board, so this lane and that one must agree on one runtime;
the board row lists `app/agent/mcp/{config,models,oauth}.py` for this lane only);
(b) process spawning with a controlled environment and tree termination on Windows
and POSIX, and a login-shell PATH probe (the tools unit's shell runtime); (c) a
`.env` reader with dotenv semantics (quotes and escapes) and the same writer shared
with settings-providers; (d) pydantic-equivalent validation messages for the
`apply` 422 (or a KNOWN_DIFFERENCES entry); (e) the `plugins-marketplace` Lb for the
plugin runtime's `list_status`/`call_app_tool`; (f) the chat loop's tool registry
(`agent-loop-chat`, `mcp-client`) and outbound redaction (`protect_outbound_value`);
(g) the DB layer for `session_messages`; (h) the owner's decisions on S1 to S5, C1/C2,
U1/H1 and M1, plus a `KNOWN_DIFFERENCES.md` entry for each hardening and for the
error-text cases in E1; (i) the adapter `adapter:plugins-mcp` described under Pins
check. **Needs a security review at Lb** (credentials, `.env` writes, environment
injection, process spawning, SSRF, OAuth).
