# Known differences between the Rust server and Python

Each entry is a place where the Rust port cannot or deliberately does not match
Python. Entries need owner approval.

## shared-dotenv (P-005, `server/crates/shared-dotenv`)

Owner-accepted hardening in the P-005 brief; callers are not switched over yet.

- **Atomic MCP credential writes.** Both writer profiles now use a same-directory
  `.{name}.*.tmp` file, owner-only permissions (0600 on Unix), file fsync and
  atomic replacement, with cleanup on failure. Python's MCP `_save_env_values`
  overwrites the file directly and applies permissions afterwards; a crash can
  leave partial contents. The credential writer already replaces atomically.
- **Refuse environment-line injection (S2).** Both writers reject names outside
  `^[A-Za-z_][A-Za-z0-9_]*$` and values containing NUL or any line boundary of
  Python's `str.splitlines`: LF, CR, VT `\x0b`, FF `\x0c`, `\x1c`, `\x1d`,
  `\x1e`, NEL `\x85`, U+2028 and U+2029 (SR-013), before changing any file or
  creating its parent. python-dotenv reads only CR and LF as line ends, but the
  merge re-splits the existing file with `str.splitlines`, so any of the others
  in a value would become extra assignments on the next write. Python accepts
  these inputs, allowing extra assignments to be injected. Errors name no values.
  A hand-edited file that already holds one of the non-CR/LF boundaries is still
  re-split the way Python does (golden `write-22`). This is the accepted S2
  hardening for settings-providers and MCP-management; it does not add a variable
  allow-list. Callers own updates to the process environment.


## providers (AR1, `server/crates/area-providers`)

- **No models.dev catalog.** Thinking fields, budgets and service tiers follow Python's path for a model the catalog has no row for: fallback levels per dialect, budgets from the ceilings alone, and `service_tier` forwarded as is. For a model the catalog does describe, Python may clamp levels, size budgets from the model's output limit or apply a catalog tier patch.
- **Providers in scope.** `router9`, `xiaomi`, `cliproxy`, `mistral`, `cohere`, `groq`, `cerebras`, `together`, `deepinfra`, `sambanova`, `perplexity` and `vercel`. Other registry IDs are `ProviderError::NotPorted`. Unknown IDs get Python's "Unsupported provider" message without a catalog or plugin lookup.
- **Settings are a snapshot.** Python reads `os.environ` at call time, so keys saved in Settings → Providers apply without a restart. Rust reads the `Settings` it is given. Like Python, a `.env` file only sets the fields `app/core/config.py` declares; other provider variables (`MISTRAL_API_KEY`, `GROQ_BASE_URL`, ...) come from the process environment alone.
- **Event shape.** The assembled tool call carries parsed JSON arguments (an empty string becomes `{}`) where Python keeps the string. `Done.finish_reason` is `""` when the provider sent none. Python's `cache_probe` diagnostics are not ported.
- **Size caps.** Python buffers without limit. Rust ends a stream with `ProviderError::TooLarge` (not retried) when one SSE line passes 16 MiB, one tool call's arguments pass 16 MiB, the arguments of all tool calls in one response pass 32 MiB, or a response has more than 128 distinct tool calls, and keeps only the first 64 KiB of an error body (after gzip decoding), decoded as lossy UTF-8 instead of by the response charset.

## commands (`server/crates/area-commands`)

These are outside the contract tests; they need an owner decision.

- **YAML 1.2 instead of 1.1.** Frontmatter is parsed with `yaml-rust2` (YAML 1.2 core); Python's `yaml.safe_load` is YAML 1.1. A plain `description: yes`, `on` or `2024-01-01` is a bool or date in Python (so `""`) and a string in Rust.
- **Unusual JSON bodies.** A body that is not valid UTF-8 or has a BOM, a lone `\ud800` surrogate, or `NaN`/`Infinity` makes `serde_json` fail where Python succeeds or words the error differently; `json_invalid` then reports offset 0 and `Expecting value`.
- **Links and case.** Symlinked sub-folders are not followed (as `rglob`), and a symlink in the workspace path is resolved after `..` is folded, not before. `*.MD` matches only on Windows in Python.
- **`Location` of the 307** is built from the `Host` header with the decoded path; non-ASCII paths are UTF-8, Starlette sends latin-1.

## tools (`server/crates/area-tools`: `read`, `ls`, `glob`, `grep`, `date`)

Parity is checked by `contract-tests/tools` (324 cases on fixture workspaces) and
`crates/area-tools/tests/golden.rs`. The differences below are outside those cases.

### Hardening (Rust is stricter on purpose)

- **Saved sandbox deny patterns (DS3-003).** Chat-core reloads the `denied_patterns`
  field of `<config>/sandbox.yaml` on the blocking pool once per turn, using the
  shared YAML 1.1 loader; blank strings are dropped, malformed/unreadable policy
  logs `sandbox_config_load_failed` and supplies no user patterns. The built-in
  case-insensitive `.env` floor remains even if the file removes those patterns.
  User patterns match resolved POSIX paths case-sensitively as in Python.
  `read`, `ls` and search-root errors match Python. Rust also filters each `glob`
  result and each opened `grep` file; Python's scans only validate the search
  root. This reader consumes only deny patterns, not the other sandbox settings.
  `write` and `edit` remain Python-only tools, refused by the Rust chat loop;
  future Rust writers must carry the same `ToolCtx.denied_patterns` into path
  validation before mutation.
- **Metadata of link targets (DS3-004).** `ls` hides entries whose link target is
  outside the workspace or denied, before reading target type or size; `glob`
  omits such file hits before reading their modification time. Python exposes
  these entries. Ordinary allowed entries keep the Python formatting.

- **Links found while walking are not followed out of the workspace.** Python's
  `glob` and `grep` follow a symlink or junction inside the search root even when
  it leads outside the workspace, so `grep` can read a file the `read` tool would
  refuse. Rust skips any symlink, junction or other reparse point whose target is
  outside the workspace or matches a deny pattern. `read`, `ls` and the search
  root itself are refused exactly as in Python.
- **A network path is refused before any file-system call.** `\\host\share\...`
  and `\\?\UNC\...` outside the workspace are refused from their text alone, so
  the machine never contacts the remote host (Python stats and resolves the path
  first, which makes Windows connect to that host).
- **`grep` skips files over 64 MiB**; Python reads them whole.
- **`ls` output is capped.** Python lists every entry. Rust cuts the listing to
  the `read` tool's 20,000 characters and appends a truncation notice, so a huge
  directory cannot flood the model context. Smaller listings are unchanged.

### Open confinement gaps (found in the AR2 security review, not fixed)

The Rust checks follow the shape of Python's, so these are not regressions, but
they need a decision before these tools run agents.

- **Check, then open (macOS only).** `validate_path` resolves a path and the tool
  opens it afterwards. On Windows `read` and `grep` open the file through
  `Sandbox::open_confined`, which holds every component from the workspace root
  down (opened as itself, without delete or rename sharing) and refuses one that
  is a symlink or junction, so no folder can be swapped for a link until the file
  handle is open; on Linux it checks the opened handle's real path
  (`/proc/self/fd`) against the root and the deny patterns. macOS has no std way
  to read a handle's path (`F_GETPATH` needs `libc`), so there a process that
  keeps swapping a folder for a link can still win the race, as in Python. A
  workspace folder another program holds open with delete access makes the read
  fail with a sharing violation on Windows. The workspace root's own parents are
  not held.
- **Hard links (owner decision 2026-11-02, DS3-002: accepted, as in Python).** A
  hard link inside the workspace to a file outside it, or to `.env`, reads as an
  ordinary file; only symlinks and reparse points are judged. Whoever creates
  such a link already has write access to the workspace and read access to the
  target, and refusing every file with more than one link would also refuse
  legitimate hard-linked trees (pnpm `node_modules` stores, `git clone --local`
  objects). Std exposes the link count only on Unix, so Windows would also need
  a new dependency.

### Not ported yet (AR3 or later decides)

- **Registry metadata and permissions.** The `Tool` trait has no `read_only`,
  `concurrency_safe`, `capabilities` or observation hooks, and the crate makes no
  allow/ask decision: Python lets all five tools run without a prompt
  (`_SAFE_TOOLS` in `app/agent/permission.py`), and `execution_policy.py` has no
  per-tool rule. `lib.rs` documents the metadata for the caller to apply.
- **Allowed roots.** The tools' only allowed root is `ToolCtx.workspace_root`.
  Python's `SandboxConfig` also allows extra project roots, read-only roots, the
  session uploads directory and EvoFlux's own log and session-artifact
  directories. Rust refuses those paths.
- **`read` of PDF and HTML** returns `Error: Document conversion (PDF and HTML)
  is not available in the Rust agent runtime yet: <path>`; Python converts them
  with `app.services.document_text`.
- **`read` of images** always answers with the no-vision notice; `ToolCtx` has no
  model capabilities, so there is no image block for a vision model.
- **`grep` never starts ripgrep.** Python uses `rg` when one is installed (the
  desktop bundle sets `EVOFLUX_RG_BIN`) and its own scan otherwise; Rust always
  follows the scan. With `rg` Python orders files and matches differently
  (path-sorted), honours `rg`'s own ignore files and types, and accepts `rg`'s
  regex dialect. Without `rg` the outputs are identical.
- **Regex dialect.** `grep` uses the `fancy-regex` crate, not Python's `re`.
  Backreferences, look-around and the common classes behave the same, but some
  Python-only syntax (`(?P=name)`, `\Z`, possessive and atomic corner cases,
  inline flags in the middle of a pattern) differs, and the `Invalid regex: ...`
  text names the Rust parser's complaint.
- **Pydantic error text.** Argument errors reproduce Pydantic 2.13's wording for
  missing fields, strings, integers, booleans and the `output_mode` literal, with
  the same 50-character `input_value` cut. Other value shapes (very large
  integers, `NaN`, nested models) are not covered.
- **Arguments that are not a JSON object** answer `Tool arguments must be a JSON
  object`; Python raises a `TypeError` whose text depends on the value.
- **`date`** prints the UTC offset (`+07:00`) where Python prints the zone name
  (`ICT`, or Windows' `SE Asia Standard Time`); chrono has no local zone name.
- **Operating-system error text.** An unreadable file or directory reports the
  Rust I/O error, not Python's `[Errno 13] Permission denied: '<path>'`. A name
  Windows cannot open (`a?b`, `a<b`, a component over 255 characters) answers
  `File not found: <path>` where Python prints `[WinError 123] ...`.
- **The workspace directory is not created** when it is missing; Python's
  `SandboxConfig` creates it.

## chat-core (AR3, `server/crates/area-chat-core`: `POST /api/team/chat`, `GET /api/team/{session_id}/stream`, `GET /api/team/{session_id}/history`)

Parity is checked by `contract-tests/chat-core` (15 cases, Python-recorded SSE and
history snapshots, and Python reading the rows Rust wrote). Differences:

- **Workspace allowlist (Rust-only, owner decision 2026-11-01, replacing the
  denylist).** The session `workspace` is the file tools' sandbox root. Python
  accepts any absolute path or `~`, so `workspace=~` lets the model read
  `~/.ssh/id_rsa`; four review rounds each found a folder a denylist missed, so
  Rust accepts a workspace only when, after full resolution (`~`, `..`, links and
  canonical form, before anything is created), it is equal to or inside an
  allowed root. The roots are the default workspace folder (`EVOFLUX_WORKSPACE_DIR`,
  what Python uses when no workspace is given) plus the folders of
  `EVOFLUX_WORKSPACE_ROOTS`, an OS path list (`;` on Windows, `:` elsewhere) read
  from the environment or a `.env` file. Each root is resolved once at startup; a
  root that is not absolute, or that is a drive or filesystem root, the home
  folder or above it, a system folder or a credentials folder (the second layer
  below), is ignored with a `workspace_root_ignored_*` warning in the log. Any
  other workspace answers 422 `Workspace path is not allowed: it is <reason>. To
  allow a folder, add it to EVOFLUX_WORKSPACE_ROOTS ...`.
  **Second layer, inside the roots:** UNC, device and non-disk verbatim paths
  (`\\server\share`, `\\localhost\C$`, `\\?\UNC\...`, `\\.\COM1`,
  `\\?\Volume{GUID}\`, `\\?\GLOBALROOT\...`), a path that is not absolute after
  resolving, the home folder or any folder above it, a system folder
  (Windows: `%WINDIR%`, `%ProgramFiles%`, `%ProgramFiles(x86)%`, `%ProgramData%`,
  `<system drive>\$Recycle.Bin`, `<system drive>\System Volume Information`;
  Unix: `/etc /usr /bin /sbin /var /proc /sys /dev /boot /root /System /Library
  /private /run /opt /srv /snap`) equal, inside or above, on Windows
  `C:\Users` itself and any profile in it but your own, the EvoFlux config
  folder and `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config`, `~/.kube`, `~/.docker`,
  `~/AppData`, `~/NTUSER.DAT`, `~/Library`, `~/.local/share`, `~/.azure`,
  `~/.password-store`, `~/.netrc`, `~/.mozilla`, `~/.cargo`, `~/.claude`,
  `~/.codex`, `~/.gem`, `~/.terraform.d`, `~/snap`, `~/.var/app`, `~/.npmrc`,
  `~/.pypirc`, `~/.git-credentials` and `~/.vscode`, and a folder with one of
  those names anywhere below a root (`<root>/sub/.ssh`, so a workspace inside a
  `.vscode`, `Library` or `snap` folder is refused too). On Windows a folder name
  ending in `.` or a space, or containing `:`, is refused because Windows opens
  another folder. The default workspace folder is exempt from the `~/.local/share` rule
  only, and only when `~/.local/share/evoflux-workspace` resolves to itself;
  a symlink or Windows junction to `~/.local/share/keyrings` does not exempt
  its target, even with `EVOFLUX_WORKSPACE_DIR` set directly to that target.
  A default that is any other credential folder is ignored with a warning.
  Credential names are checked below every matching root, so configuring both
  `R` and `R/sub/.ssh` cannot allow `R/sub/.ssh/new`. After the folder is
  created the path is resolved and checked again, allowlist included, and a
  folder this request made that is then refused is removed if empty. Windows and
  macOS compare case-insensitively, Linux case-sensitively. This closes the Linux
  `/home/<other>` gap. A project outside the default folder needs its folder in
  `EVOFLUX_WORKSPACE_ROOTS`.
  Stored session workspaces (also those written by Python-owned routes such as
  fork, import, suggested tasks and webbridge) are resolved and checked again
  before each turn (SR-001, owner decision: refuse, no grandfathering); a
  refusal returns 422 with the allowlist hint, logs `stored_workspace_refused`
  and starts no turn, including for older v3 sessions. The file tools are rooted
  at the checked path, never at a value re-read from the row; the stored text is
  left unchanged. The `commands` and `snippets` routes' `workspace` query is not
  covered. Tests: `test_restricted_workspace_is_refused` (Rust only; Python is
  skipped; the contract harness sets `EVOFLUX_WORKSPACE_ROOTS` to
  `<home>/projects`), the `workspace.rs` unit tests, and the chat-core
  `stored_workspaces_are_resolved_and_checked_again`,
  `stored_disallowed_workspace_is_refused_before_turn` and
  `tools_run_in_the_checked_workspace_of_new_and_stored_sessions` tests.
- **Workspace mkdir race (accepted residual for SR-011(1), owner-authorized
  option 2026-11-03; needs security review).** A local process with write access
  inside an allowed root can replace an already checked parent with a symlink
  or junction between the check and the next `create_dir`. The request can then
  create an empty directory in a credential folder before the final resolved-path
  check refuses the workspace. Rejection attempts `remove_dir` on the paths
  found missing, deepest first, stopping on an error (for example, if the
  racing writer has populated a directory). Cleanup does not verify directory
  identity: an empty replacement can be removed, and a directory can remain
  after a cleanup error. No chat turn or file-tool read starts
  with that refused workspace. Per-create path verification still leaves the
  parent replacement and cleanup races: a reliable fix requires holding parent
  directory handles and creating relative to them across Windows, Linux and
  macOS, beyond a small path-check change with the current std/Tokio APIs.
- **Unported tools end the turn.** A call to one of Python's built-in tools that
  Rust does not run (`shell`, `edit`, `web_search`, `get_goal`, ... the
  `PYTHON_ONLY_TOOLS` list in `turn.rs`) gets the tool result Python gives an
  unknown tool (`Error: Tool '<name>' not found.`), and the turn then ends with
  Python's lead-failure event: `error` with `Lead agent '<agent>' failed: Tool
  '<name>' not found.` and `exception: ToolNotFoundError`, then `agent_status`
  `error`. Python runs the tool. A name Python does not know either gets the same
  result and the loop goes on, as in Python. Only `read`, `ls`, `glob`, `grep`
  and `date` run.
- **Work-mode text turns only.** These answer 422 `... not available in the Rust
  server yet.`: Coding sessions (new or persisted), shell commands (`shell=true`),
  file uploads, and `/goal`. A message while a turn is running answers 409 instead
  of being queued; a session with an undo boundary (`revert`) answers 409 instead
  of cleaning up the reverted tail. `@path` mentions attach nothing. `fast_mode`
  is ignored, and `thinking_level` is not checked against the model.
- **Model check.** `model` is accepted when the provider factory resolves it
  (configured provider, AR1 provider list) rather than when the model registry
  lists it.
- **Prompt and tools sent to the model.** The system prompt is the lead agent
  file's prompt text (or a one-line default); Python composes a much larger
  prompt from hooks, skills, memory and the team protocol. Only the five ported
  tools are offered. No session prefix snapshot (`session_prefix_snapshots`) is
  written; Python creates one on its next turn.
- **Hooks.** Only title generation is ported (non-streamed request through the
  AR1 provider settings, `reasoning_effort: "none"` first, then without it).
  Memory, summarization, telemetry, goal and skills hooks do not run; there is
  no context compaction, so a long session can overflow the model window.
- **Streaming order.** `tool_call` events are published when the provider
  finishes the call (AR1 assembles tool calls), just before that call's `usage`
  event; Python publishes them on the call's first delta, so a model that streams
  text after a tool call's first delta shows the text first in Rust. The `model`
  in event metadata is the configured model without its provider prefix, not
  the name each chunk reports. Tool-call arguments are stored and published as
  compact JSON re-encoded from the parsed value, not the provider's exact text.
- **Echoed tool-call arguments are capped.** Python publishes and stores a tool
  call's arguments as they came. Rust replaces arguments over 1 MiB, in the
  `tool_start` event and in the stored assistant row (so later turns do not
  resend them), with `{"truncated":true,"original_bytes":N}`; the tool still runs
  with the full arguments. The title reply is read up to 64 KiB (the providers'
  error-body cap) and dropped beyond it; Python reads it all.
- **A panic in a turn** releases the session (a later message is accepted, not
  409) and ends its stream. Python's turn runs in an asyncio task whose
  exception is logged.
- **Same as Python, on purpose.** The session `workspace` is created if missing,
  only after the lead and running-turn checks; Python creates it before them.
  Python does not check `Origin` or `Host` (its `CORSMiddleware` allows
  `CORS_ORIGINS = ["*"]`); the gateway now does, for every route (see "gateway:
  Origin and Host checks" below). The step limit per turn is Python's
  `MAX_AGENT_ITERATIONS` (5000).
- **Usage cost.** `cost` is always `null` and `usage` carries no `cost`: there is
  no models.dev pricing catalog in Rust.
- **Retries and interrupts.** When every provider stays rate-limited the turn
  ends idle (like Python) but is not re-activated later. Provider fallback is not
  configured. An interrupt stops the stream and any remaining tool calls and ends
  the turn; partial text is not persisted and the last reply is not marked
  interrupted. Transient transport errors are retried by AR1's retry layer only,
  without the agent loop's resume budget.
- **Stream ownership.** The turn journal lives in the Rust process. Python's own
  readers do not see Rust turns: the sessions list reports `running: false`, and
  `POST /api/team/commands` (Python) cannot continue or compact a Rust turn while
  it runs.
- **Provider settings per turn.** Each turn reads `<config>/.env` (where Settings
  → Providers saves keys) on top of the startup settings, so a key saved while the
  server runs applies to the next turn, as Python's `os.environ` update does.

## gateway: Origin and Host checks (`server/crates/gateway/src/origin.rs`, every route)

Owner decision 2026-11-01, Rust-only on purpose: the security review found no
`Origin`/`Host` check and CORS `*`, so any website open in the user's browser
could call the local API, and a DNS-rebound name could read its answers. The
gateway checks every request before routing, so Rust- and Python-owned routes
alike are covered. Python alone (`evoflux serve` without the gateway) is unchanged.

- **Host.** `localhost`, `127.0.0.1` and `[::1]` on any port, the `--host` the
  gateway is bound to (unless `0.0.0.0` or `::`), and the host of each
  `EVOFLUX_ALLOWED_ORIGINS` entry. Anything else is 403
  `{"detail":"Host not allowed.","code":"host_not_allowed"}`. A request with no
  `Host` (HTTP/1.0 tools) is allowed. Requests carrying the bundled tsnet
  proxy's verified identity (login, `tsnet` marker and this process's secret)
  keep the tailnet name, so their `Host` must instead name a tailnet:
  `<node>.<tailnet>.ts.net`, a Tailscale address (`100.64.0.0/10`,
  `fd7a:115c:a1e0::/48`) or an `EVOFLUX_ALLOWED_ORIGINS` host, on any port; a
  tsnet request with any other `Host` (a DNS-rebound `evil.example`) or none is
  403 `host_not_allowed`. The bundled tsnet proxy itself (`desktop/tailnet`) now
  answers 403 to any `Host` that is not its own MagicDNS name (full or short) or
  one of its own Tailscale addresses, before proxying, so another `*.ts.net`
  name or Tailscale address no longer reaches the gateway; the gap is closed.
  The gateway keeps its own check as defence in depth.
  The gateway alone refuses short MagicDNS names (`http://box/`); the proxy accepts the short name of its own node, so use the URL Remote Control shows.
- **Origin.** When present it must be a loopback page (`http(s)://localhost`,
  `127.0.0.1` or `[::1]`) on the gateway's own port or, in a debug build or with
  `EVOFLUX_DEV=1`, a Vite port (5173 for `vite dev`, the Tauri `devUrl` and
  `make dev-web`; 4173 for `vite preview`; the default 80/443 when no port is
  given), the bound host on those ports,
  the Tauri window (`tauri://localhost`,
  `http://tauri.localhost`, `https://tauri.localhost`), the WebBridge extension
  (`chrome-extension://lghglpnddenmebbhkfachafichhglafi` plus
  `EVOFLUX_WEBBRIDGE_EXTENSION_IDS`), an `EVOFLUX_ALLOWED_ORIGINS` entry, or,
  behind the tsnet proxy, the page's own tailnet origin. Anything else
  (including `null`) is 403 `{"detail":"Origin not allowed.","code":"origin_not_allowed"}`
  for every method, SSE and WebSocket upgrades included. A page served on
  another loopback port (another local program, or Vite on a port of its own)
  needs `EVOFLUX_ALLOWED_ORIGINS`. A release gateway does not trust 5173 and
  4173 (any local program can listen there): list them in
  `EVOFLUX_ALLOWED_ORIGINS`, or set `EVOFLUX_DEV=1` for a dev run. The e2e and
  contract harnesses run the debug binary, and e2e also lists its preview origin.
- **No Origin.** Allowed (CLI, curl, tests, the Tauri shell's own requests),
  except when the browser marks it `Sec-Fetch-Site: cross-site` (another site's
  `<img>`, link, form or navigation), whatever the method: 403
  `{"detail":"Cross-site request not allowed.","code":"cross_site_not_allowed"}`,
  unless it carries the desktop token (bearer or `_token`), as the desktop
  window's own images and links to the API do. `same-origin`, `same-site` and
  `none` pass.
- **CORS.** Every `Access-Control-*` header a route set (Python's
  `CORSMiddleware` included) is removed. An allowed `Origin` is echoed with
  `Access-Control-Allow-Credentials: true`, and every answer carries
  `Vary: Origin`. The gateway answers preflights itself with Starlette's shape
  (200 `OK`, all methods, the requested headers, max age 600), so Rust-owned
  routes now pass preflight too. `CORS_ORIGINS` no longer has any effect behind
  the gateway.
- **Not covered.** LAN access through a wildcard bind and an external
  `tailscale serve` (`EVOFLUX_REMOTE_USE_PROVIDER=external`) need their origin
  in `EVOFLUX_ALLOWED_ORIGINS`.

- **Remote proxy identity (`server/crates/core/src/auth.rs`, SR-003).** A
  `Tailscale-User-Login` with a proxy marker other than the bundled proxy's
  `tsnet` (or none) is trusted in place of the desktop token only when
  `EVOFLUX_REMOTE_USE_PROVIDER=external` is set. Python's
  `_embedded_proxy_required` also trusts it whenever `EVOFLUX_TSNET_BIN` is
  unset (dev runs, `make run`, headless), so any local process could skip the
  token with two forged headers; Rust answers 401 `untrusted_tailnet_identity`
  there. Deployments using `tailscale serve` with `EVOFLUX_TSNET_BIN` unset
  must set `EVOFLUX_REMOTE_USE_PROVIDER=external`. The bundled app sets
  `EVOFLUX_TSNET_BIN` and is unchanged. Tests:
  `auth::tests` and `crates/core/tests/auth.rs`.
  The gateway applies the same check to Python-owned routes (SR-012): it
  removes `Tailscale-User-Login`, `X-EvoFlux-Remote-Proxy`,
  `X-EvoFlux-Remote-Token` and `X-EvoFlux-Device-Label` from every request it
  forwards to Python unless `DesktopAuth::trusted_remote_identity` accepts
  them, so Python sees no identity and asks for the desktop token (401) where
  Python alone would trust the forged headers. Verified `tsnet` requests from
  `desktop/tailnet` and the explicit external provider keep them. Tests:
  `crates/server/tests/app.rs`, `crates/gateway/tests/proxy.rs` and
  `contract-tests/gateway/test_remote_identity.py`.

Tests: `origin::tests` (unit, DNS rebinding through tsnet included) and
`contract-tests/origin` (no Origin, own and app origins, fetch metadata other
than `cross-site`, a cross-site request with the token on both backends; evil
Origin, other loopback ports, cross-site without the token, evil Host, SSE,
stripped CORS and preflight on Rust only, skipped on Python).

## import (L6a, `server/crates/area-imports`; no Rust routes yet)

No difference exists yet: the crate is a stub and the unit stays on Python.
Recorded ahead of L6b, from `area-imports/NOTES.md`:

- **Python caches.** A Rust writer makes no Python cache stale that is not
  already stale today, because `import_service.py` never invalidates anything
  after it writes. Skills, `mcp.json`, `wiki/sources` and `settings.yaml`
  readers revalidate. Two gaps exist with either writer: a new agent `.md`
  is not spawnable by a running team until `GET /api/team/agents` or idle
  eviction, and a session team cached in `team_manager` outlives an undo that
  deletes its session.
- **Planned for L6b, needs owner approval:** concurrent `execute` of one
  `import_id` answers the losing requests `404` (Python: `200` with everything
  skipped, or `500`); source reads that follow a link out of the source folder,
  oversized files and oversized zip members are refused or skipped (Python reads
  them).

## observability (`server/crates/area-observability`)

Python reads the span files with DuckDB (`read_json`, `union_by_name`); Rust reads the same
`{state}/otel/spans/*.jsonl` line by line and reproduces each query.

- **Read caps.** Python reads without limit. Rust reads at most the newest 2,400 partition files
  (90 days of hourly files plus slack), 64 MiB of one file, 256 MiB over all files, skips a line over
  4 MiB, and stops after 500,000 spans in the window. Past a cap the summary, trace list and trace
  detail cover the spans read so far (files newest-first for the file count, oldest-first inside the
  byte and span caps).
- **Malformed lines.** A line that is not a JSON object, or has no integer `end_time`, is skipped.
  DuckDB fails the whole query on a malformed line (a 500 from Python).
- **Mixed attribute types.** DuckDB unifies an attribute's type across the window (an integer next to
  a float becomes a float, a number next to a string becomes a string). Rust keeps each span's own JSON
  value in the trace detail and casts to text per span for the aggregates, so a whole-number float such
  as `100.0` counts as a non-integer (0 tokens) only in the aggregates, like `try_cast('100.0' AS BIGINT)`.
- **Ties.** Rows with equal `end_time` (trace list), equal `start_time` (trace detail), equal cost
  (`by_model`, `cache_by_step`) or equal calls (`by_tool`) keep the order they were read in; Python's
  order is unspecified there.
- **Settings are a snapshot.** `OTEL_SPAN_SAMPLE_RATIO` and the `OTEL_*RETENTION*` variables are read
  once when the server starts; Python re-reads the environment on each request or sweep.
- **Float text.** A cost below `1e-4` prints as `1e-5` (Rust) instead of `1e-05` (Python); both parse
  to the same number.

## P-006: pinned HTTPS downloads (shared library; not mounted)

Python `app/plugin_platform/marketplaces.py::_fetch_bytes` validates DNS, then
httpx independently resolves again. Rust's `evoflux_net::pinned_client` connects
only to the addresses it validated and disables proxies for these downloads;
the general provider client continues to honor proxies. Each redirect resolves
and validates anew. Explicit private-network permission is per normalized host,
so a redirect to another host does not inherit it. Mapped IPv6 and transition/
unallocated/special-use address ranges are conservatively refused (including
some Python-global special-use exceptions). The URL remains HTTPS with normal
certificate verification and original SNI/Host. A caller-supplied deadline
bounds DNS and each request, including its decoded body; the caller's size cap
applies to decoded bytes. Backslashes in initial URLs are refused. No Python
caller or routing behavior changes until a future consumer adopts the crate.
Needs security review (SSRF, DNS rebinding).

## settings-providers (Lb, `server/crates/area-settings-providers`; unit still on Python)

Ported so far: `/api/auth/**` and the seven P-008 settings section GET/PUT pairs
(`sandbox`, `context`, `version-control`, `team-spawn`, `follow-up`,
`background-tasks`, `response-style`). Other settings routes are pending slices.

- **OAuth flows not ported.** `GET /api/auth/{codex,copilot,xiaomi}/login` answers
  `200 text/event-stream` with one `failed` event (`{"message": "...", "reason":
  "not_ported"}`) and closes; Python runs the provider's device-code or browser
  login in a thread and streams `started` … `success`. Provider plugins are Python
  modules Rust cannot load, so a plugin's login is Rust's `404 Unknown OAuth
  provider` and every `POST /api/auth/{id}/callback` with a valid body is
  `404 OAuth callback unsupported for '<id>'` (Python calls the plugin's
  `oauth_callback`). Both stay Python-owned until `adapter:settings-providers`.
- **Request body size.** Rust reads at most 2 MiB of a request body (axum's
  default limit, `413`); Python reads any size.
- **Settings/sandbox YAML diagnostics.** Invalid YAML retains status 422 and
  `settings.yaml YAML parse error: ...` or `Invalid YAML in <path>: ...`, but the
  shared YAML parser's message tail is not PyYAML's. Shared-settings' documented
  input limits and UTF-8/I/O diagnostic differences also apply to section routes.
- **Windows settings file newlines (shared dependency).** Shared-settings
  `RuntimeSettings::save_unlocked` writes the shared dump as LF bytes, whereas
  Python's text-mode tempfile writer emits CRLF on Windows. P-008 cannot alter
  that owned dependency or inject a newline conversion into `modify`; sandbox's
  own atomic writer does preserve Windows CRLF. Parsed settings are identical.
- **Sandbox file validation text.** Invalid file fields return a string `detail`
  with the pydantic model name, field, message, type and input. String/container
  repr and truncation, the pydantic documentation version in its URL, and YAML
  non-JSON values (dates, non-string keys and non-finite floats converted through
  shared YAML's JSON projection) may differ from Python's `str(ValidationError)`.
  HTTP request validation still uses the golden-tested pydantic JSON error list.
- **S1, key echoed in a 422 (Python bug, fixed in Rust only).** Python's
  `POST /api/settings/providers/{id}/test` without `model` answers a 422 whose
  `detail[].input` is the whole body, `api_key` included (NOTES S1). Rust never
  echoes a request value in a 4xx on the provider routes: their validation errors
  carry no `input`. The provider routes come with slice P-009 under SR-004; until
  then this crate does not serve them and they stay on Python, and
  `test_known_leak_a_missing_model_422_echoes_the_whole_request_body` pins the
  Python behaviour only.
- **S2, `.env` name and newline injection (Python bug, fixed in Rust only).**
  Python's `PUT /api/settings/providers/{id}` writes any `extra` name and value to
  `.env` and `os.environ`, so `{"FOO": "x
BAR=y"}` adds two lines (NOTES S2).
  Rust limits `extra` to the provider's declared credential and base-url
  variables, refuses values holding CR, LF or NUL with a 422 and writes nothing,
  never writes `PATH`, `PYTHONPATH`, `LD_PRELOAD`, `DYLD_*`, `NODE_OPTIONS` or
  `EVOFLUX_*`, and writes `.env` 0600 where the OS supports it. Same slice (P-009,
  SR-004): the P-008 section routes write no `.env` and no credentials.

## P-007: shared archive extraction (library; not mounted)

`shared_archive` serves future plugin/import/seed ports; format-specific plugin
root checks and GitHub prefix/subtree selection remain caller responsibilities.
Compared with Python plugin extraction, all archive links and special files are
refused, portable Windows names and case collisions are screened on every OS,
components shaped like Windows 8.3 short names (base name ending in `~` and
digits, such as `LONGDI~1`; SR-014) are refused on every OS, and existing files
are never overwritten. Destination root/components use
capability-based no-follow directory opens; file creation is exclusive, including
when an existing file is a hard link to outside the destination. The caller grants
access to the destination's existing parent, owns staging, and must run these
synchronous APIs on the bounded blocking pool from async code. Errors may leave
partial staging output and do not publish or install it.

Limits apply to actual file bytes plus declared entry sizes; ZIP entry ratios are
checked without Python's 1 MiB threshold. Tar input, decoded stream (file budget
plus bounded metadata allowance), total extracted bytes, entries and compression
ratio are capped, whereas Python seed extraction has no corresponding bounds.
Malformed PAX records, sparse/device/link entries and global PAX path/size/link
overrides are refused; GNU long names, local PAX paths and GitHub global comments
are supported. Only the Unix executable signal is preserved, as in plugins;
archive ownership, setuid and writable mode bits are never applied. Async request
cancellation and installation policy remain the adopting caller's responsibility.
Needs security review (path confinement, archive writes, resource limits).
P-007 review clarification: ZIP uses the exact-pinned 9.3.0 iterable reader to bound
entry counts before central-directory metadata allocation and checks local/central
header consistency. Duplicate detection uses full Unicode 16 case folding; Python's
Unicode table depends on its interpreter version. Local PAX `size` must agree with
the raw header size: conflicting layouts are deliberately refused before extraction,
although Python can accept them. This conservative restriction preserves the raw
special-record screening pass. A regression covers both refusal and agreeing sizes.
A local PAX header that repeats `size` is refused (tar-rs takes the first value,
Python the last), so the screening and extraction passes cannot disagree.
