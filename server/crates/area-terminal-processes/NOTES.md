# area-terminal-processes NOTES

Python source: `app/api/routes/team/{terminal,processes,preview}.py`, the two watch
routes of `app/api/routes/team/files.py`, `app/api/schemas/processes.py`,
`app/services/{terminal_service,process_manager,workspace_file_watcher,user_shell}.py`,
`app/agent/tools/builtin/{preview,process}.py` (the registries the routes compose),
`app/core/desktop_auth.py` (`websocket_authorized`). Unit `terminal-processes`
(`server/routing.toml`; pin breaker `adapter:terminal-processes`). Contract tests:
`contract-tests/terminal-processes/` (see "Test status").

**Status:** La (this crate's stub, NOTES, contract tests). The crate is not mounted:
`units.rs` is untouched, as for the other La lanes.

## Scope: which routes the unit serves

`/api/team/{session_id}/terminal` (WebSocket), `/{session_id}/terminals`,
`/processes`, `/preview/**`, `/workspace/watch`, `/{session_id}/files/watch`. The two
watch handlers sit in `files.py`, next to the `workspace-files` routes, but
`routing.toml` gives them to this unit. A route matcher must keep `/workspace/watch`
before `/{session_id}/...` (Python registers the literal one first).

Every HTTP route: `401 {"detail":"Unauthorized — EvoFlux access key required."}`. The
WebSocket does not pass through the HTTP middleware: `terminal_ws` authenticates itself
and refuses with an HTTP `403` at the handshake (close code 4401 once open) for a
missing or wrong `?_token=`; see S1.

## Endpoints

| Endpoint | Behaviour | Errors |
|---|---|---|
| `WS /{session_id}/terminal?_token&tid&cols&rows` | accept, then PTY shell per `(session_id, tid)` (`tid` default `1`); replays the scrollback; server frames are binary PTY output and `{"type":"exit"}`; client frames (JSON text): `input` (`data` str), `resize` (`cols`, `rows` ints), `close`; anything else (not JSON, wrong types) is ignored; `cols`/`rows` non-integers fall back to 80 and 24 | `403` before accept; attach failure sends `{"type":"error","message"}` and closes |
| `GET /{session_id}/terminals` | `{"terminals":[{"id"}]}`; any string is a session id | – |
| `DELETE /{session_id}/terminals/{terminal_id}` | kills that shell; `204` also when it does not exist | – |
| `GET /processes` | `{"processes":[...]}`: tracked agent commands (`proc_*` ids), running preview servers (`preview_<20 hex>`), live terminals (`terminal_<20 hex>`); sorted preview, command, terminal then by label; fields `id, kind, label, command, session_id, pid, cwd, elapsed_seconds, killable, metadata, session_title` | – |
| `DELETE /processes/{process_id}` | `proc_*` through the command tracker, others by recomputing the opaque id; `204` | `404 Process not found` |
| `GET /preview/targets?workspace` | `{workspace, source, suggested_source (".evoflux/launch.json"), error, targets[{name,port,url,command,cwd,depends_on,configured,running,reused,pid}]}`; `.evoflux/launch.json`, else `.claude/launch.json`; a launch file that fails to load gives `targets: []` and `error` | `422` workspace |
| `POST /preview/start {workspace,name}` | starts one configuration; `{ok,message,url}` (`url` only when running afterwards); an already-open port is reused (`reused`, not killable) | `422` unknown name or unreadable launch file (message lists the configurations that exist), `422` workspace |
| `POST /preview/stop {workspace,name}` | stops the managed server; always `{ok:true,message}` | `422` workspace |
| `GET /workspace/watch?workspace` | SSE: `fs_change` with a JSON array `[{"type":"added\|modified\|deleted","path":"rel/posix"}]`, `keepalive` with `{}` every 30 s of silence; `watchfiles` with a 300 ms debounce | `422` workspace |
| `GET /{session_id}/files/watch` | the same stream for the session folder; no UUID check, no row needed | – |

Watch filter: hidden segments (any path part starting with `.`) are dropped, except the
single root `.gitignore`. One watcher task per folder, started on the first subscriber
and stopped with the last; events fan out to every subscriber queue and to registered
callbacks.

## Processes, files and state

| Resource | Used by |
|---|---|
| PTY shells (POSIX `openpty`, Windows ConPTY through `pywinpty`) | one per `(session, tid)`, idle shells with no client are killed after a timeout; the shell is the user's login shell, environment from `user_terminal_environment()` plus `EVOFLUX_MODE`; cwd is the session folder (Coding: the bound workspace) |
| preview child processes | started from the launch file with the scrubbed shell environment plus the configuration's `env`, own process group, output kept for the `preview` tool's logs |
| memory registries: `terminal_manager`, `_servers` (preview), `tracked_processes`, `workspace_file_watcher` | shared with the agent: the `shell`, `process` and `preview` tools read and write the same registries |
| `<workspace>/.evoflux/launch.json`, `.claude/launch.json` | read only |
| `ChatSession` row | read for the terminal's mode and workspace; absence is tolerated |

## Pins check

`rg "terminal_manager|process_manager|workspace_file_watcher|preview_servers"` outside
the unit: the agent's `shell`, `process`, `preview` and `browser` tools, `shell_service`,
`chat_service` (watch callbacks for the diff cache), `app/api/app.py` (shutdown of
terminals and preview servers). **Needs adapter** per `server/AGENTS.md` §9 before
cutover: the registries are in-process Python objects the agent tools mutate, so a Rust
unit would list nothing and kill nothing of what the agent started (and the reverse).
`adapter:terminal-processes` must bridge them. La adds none.

## Odd behaviour (pinned as is)

- `DELETE .../terminals/{id}` is `204` for an id that never existed; `GET /terminals`
  accepts any string as a session id.
- `DELETE /processes/{id}` answers `404` for ids that match nothing, including malformed
  ones; there is no id validation.
- `preview/stop` is `{"ok":true}` even when nothing runs; `preview/start` returns
  `ok:false`-style outcomes inside a `200`, except unknown names (`422`).
- A port that already serves is "reused": the entry lists `reused: true`, `pid: null`,
  `killable: false`, and `DELETE /processes/{id}` for it never kills the foreign server.
- The session watch has no `uuid.UUID` check (unlike every other session route in
  `files.py`).
- A hidden directory inside the watched folder produces no events at all.

## Security findings (for the owner)

- **S1: the terminal is an unsandboxed shell for anyone holding the access key**, by
  design ("a real shell for the human at the keyboard"). The key travels in the URL
  (`?_token=`), so it lands in any proxy or access log that records query strings.
  The socket skips the HTTP middleware; each socket must authenticate itself before
  `accept`. The packaged app sets a per-launch token; the open-loopback CLI tier relies
  on an origin check instead (WebSocket handshakes are not subject to CORS), which a
  Rust port must keep.
- **S2: `preview/start` runs a command taken from the workspace's own
  `.evoflux/launch.json` or `.claude/launch.json`** (any executable, arguments, `cwd`,
  `env`) with one authenticated call and no confirmation: opening a downloaded
  repository and pressing Start runs its code. The environment is scrubbed and the
  `cwd` is checked against the sandbox, but `runtimeExecutable` and `env` are not
  restricted (an `env` of `PATH` or `LD_PRELOAD` is accepted).
- **S3: any folder can be watched** (`/workspace/watch`): the access key is the only
  gate; names of files below it are reported.
- Terminals and previews started by the UI and by the agent share one registry, so
  `DELETE /processes/{id}` lets the UI kill an agent's long-running command.

## Test status

Contract tests: 34 cases, all passing against Python v3.1.1 (`TARGET=python`, Windows/ConPTY
`cmd.exe`, `-n 4`, twice in a row). Output markers are shell-agnostic (ANSI and OSC title
sequences are stripped) so the same tests apply to a POSIX shell. The default terminal id
is `"1"`. The terminal tests use `websockets` and a real PTY shell, the preview tests start
`python -m http.server` on a free loopback port and stop it, the watch tests write files
and wait for the debounce. `TARGET=rust` is not applicable until Lb mounts the crate.
Not covered: idle-shell reaping, the attach-failure frame, `exit` frames, large
scrollback, watcher fan-out to many subscribers, `dependsOn` start ordering.

## Lb: size and dependencies

Largest pieces: the PTY layer (POSIX and ConPTY) with scrollback and idle reaping; the
preview registry and launch-file validator, which the agent's `preview` tool also uses
(so the Rust unit owns the registry and the agent needs the adapter); the file watcher
(`notify` crate, debounce, filter); the process list that composes three registries.
Depends on `core::auth` (including the WebSocket origin check), a process-supervision
helper shared with area-tools, and `core::paths`. Slices: processes and terminals list,
terminal socket, preview, watch.
