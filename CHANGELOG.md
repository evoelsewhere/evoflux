# Changelog

All notable changes to EvoFlux are documented in this file.

## [Unreleased]

### Changed

- Added SQLite compatibility, two-process stress, and write-lane benchmarks (including a multi-statement chat-turn workload); the concurrent lane uses two writers, and the write lanes run their own WAL checkpoints so the `-wal` file stays bounded (about 16 MB) even while several writers overlap. Concurrent Rust writes default off while Python writes after a Windows stress failure.
- Added a v3.1.1 responsiveness diagnostic and Windows freeze investigation, separating cold startup from the approved large repository open and other workloads.
- Remaining v4 migration tasks now land directly on the migration branch after a local review by a second agent, instead of one pull request per task, with a usage budget and model ladder per agent (`documents/plans/rust-migration-execution.md`). No app behaviour changes.
- Regrouped v4 migration cutover units around Python adapters and recorded their reverse dependencies, so backend areas can migrate independently while agent-loop routes stay together. Route patterns with a `{param}` segment now match one path segment, so requests with real session ids reach the unit that owns them, and each unit names its pin breaker (`none`, `adapter:<unit>` and/or `file-lock:<name>`); `routing.toml` documents the exact matching order for the gateway.
- Added a black-box contract test harness and OpenAPI comparison for the v4 migration, with isolated backend settings, SSE deadlines, timestamp format checks, preserved OpenAPI literal values and Windows backend process cleanup.
- Added a Rust backend workspace and migration quality checks for contributors, including lane test counts, path ownership checks, lint verification, cutover branch path rules driven by a new `adapter_call_sites` column in `server/CUTOVER_UNITS.md`, and a Python gate baseline script that fails only on new Ruff, ty and pytest failures.
- The Python backend can now run behind the upcoming Rust `evoflux-server` gateway (EvoFlux v4). Four opt-in environment variables set by the gateway control this: `EVOFLUX_GATEWAY_SECRET` (refuse HTTP and WebSocket requests that lack the `X-EvoFlux-Gateway` header), `EVOFLUX_REMOTE_PROXY_SECRET`, `EVOFLUX_TSNET_TARGET_PORT` and `EVOFLUX_DISABLE_SERVICES` (skip named background services). Nothing changes unless they are set.
- Added the planning documents for EvoFlux v4, which moves the local backend from Python to Rust for better performance and responsiveness: the migration design (`documents/plans/rust-migration-design.md`), the contributor workflow and rules (`documents/plans/rust-migration-workflow.md`), the Phase 0 task plan with Codex/Claude assignments (`documents/plans/rust-migration-phase-0-plan.md`) and the Rust technology research (`documents/research/rust-backend-stack-2026-10-30.md`). It also records the decision that, during the migration, Python calls Rust for areas that have already moved (`documents/architecture/decisions/0001-rust-migration-python-calls-rust.md`), and records adapter cutovers, rollback, reverse dependencies and the protected workflow rules in `server/AGENTS.md`. No app behaviour changes.
- Added the v4 migration board, cutover units and routing table under `server/` (`MIGRATION_BOARD.md`, `CUTOVER_UNITS.md`, `routing.toml`, `KNOWN_DIFFERENCES.md`), with `server/AGENTS.md` as the authoritative copy of the migration workflow, and `scripts/migration/check_board.py` to validate them against the FastAPI routes (including the packaged web UI mount) and lifespan services. All routes still go to Python; no app behaviour changes.
- Added a replaying mock model provider to the contract test suite (OpenAI Chat Completions and Anthropic Messages streaming, scripted from JSONL recordings) and agent-loop contract tests for text, tool-call, reasoning/cache-usage and rate-limit turns, so Python and the future Rust backend can be tested against the same deterministic model. No app behaviour changes.
- Added the shared Rust `core` foundation for the v4 server (`server/crates/core`): settings (process environment and `.env` files) and paths that resolve to the same directories as the Python backend, Python-identical error bodies (including the `database_busy` 503), logging and Prometheus metrics, desktop-token authentication that behaves like `DesktopTokenMiddleware` (bearer header or `?_token=`, exempt paths, tailnet proxy trust), a blocking-work helper and a runtime stall watchdog. Nothing is routed to it yet; no app behaviour changes.
- Added the Rust backend's SQLite layer for the v4 migration: a read pool, a concurrent write lane using `BEGIN CONCURRENT` and an exclusive first-in-first-out write lane, with random rowids for inserts (tables whose id is an integer primary key keep their normal ascending ids), a read-only read pool and the same `database_busy` timeout as today. It uses a pinned SQLite build from the `begin-concurrent` branch (`server/vendor/SQLITE_BRANCH.toml`, rebuilt with `scripts/migration/build_sqlite_amalgamation.sh`), keeps databases in standard `wal` mode so stock SQLite and EvoFlux 3.x can still open them, and can be switched to a single writer with `EVOFLUX_DB_CONCURRENT_WRITES=off`. No app behaviour changes yet.
- Fixed the contract test suite failing to collect when run as a whole folder: the shared provider setup helper now lives in `contract-tests/provider_setup.py` instead of being imported from a `conftest.py` that another folder's `conftest.py` shadowed, and the contract test harness now waits for the backend process itself, not just its Windows launcher, to exit before a test reopens the database, which removes an intermittent `disk I/O error` in the database compatibility tests.
- Added an upgrade fixture for v3.0.0, the oldest schema (a seeded database, config directory and `MANIFEST.json`), with `contract-tests/fixtures/build_upgrade_fixtures.py`, which can build any v3.0.0 to v3.1.1 tag, and a contract test that opens each committed fixture under the current Python backend. This proves v4 can open existing databases in place. No app behaviour changes.
- Added the Rust gateway for the v4 server (`server/crates/gateway`). It routes each request by `server/routing.toml`, where `{param}` matches one path segment, `**` matches the rest and the most specific route wins. It also starts and supervises the Python backend on a private port, restarting it after a crash and stopping it if the gateway dies. Requests for Python, including SSE streams, large uploads and terminal WebSockets, are forwarded without buffering, and the backend answers `backend_unavailable` while Python restarts. The desktop app does not use it yet; no app behaviour changes.
- Added the `evoflux-server serve` command for the v4 server (`server/crates/server`). It takes the same flags as the Python `serve` command and prints the desktop handshake only after the Python backend is ready. It waits up to 85 s on a slow first start; if Python is still not ready, it exits with Python's last log lines on stderr. It also exits when its parent process dies, including on Windows. It never starts without auth while `settings.yaml` sets `server.access_key`, and it refuses tailnet requests on Rust-served routes until the remote session lock is ported. An authenticated `/api/gateway/ping` route proves the key is enforced. The desktop app does not use it yet; no app behaviour changes.
- Added shadow comparison and traffic recording to the v4 gateway. A unit set to `shadow` is answered by Python while the gateway runs the same `GET` against the Rust routes in the background and appends normalized differences to `<state_dir>/shadow/<unit>.jsonl` (`EVOFLUX_SHADOW_PYTHON_TWICE=1` also compares Python with itself to measure noise); a shadow unit is rejected at startup if it owns a path that has a non-GET operation in the OpenAPI document (also checked by `check_board.py`). `EVOFLUX_GATEWAY_RECORD_DIR` records traffic with credentials removed, `make scrub FILE=<recording>` removes secrets, e-mail addresses and home paths from it (recorded response bodies can still contain secrets, so scrub before sharing), and `make shadow UNIT=<unit> ...` replays a recording and prints a diff summary. The desktop app does not use it yet; no app behaviour changes.
- Added the v3.1.1 performance baseline and responsiveness gate for the v4 migration under `contract-tests/perf/`: `baseline-v3.1.1.json` (cold start, idle memory, first SSE event and p50/p99 of 30 boot and session-open endpoints, measured on a named reference machine, each with a noise floor measured from three python-against-python repeats), a gate that probes on a fixed-rate schedule and charges each probe from its scheduled time, so a stall cannot hide. It keeps `/api/health/live` under 50 ms p99 and 1 s max, and a session history page within 2x its idle p99 and under 1 s, during cold start, while a large repository opens, a tool runs, large history pages are read, 20 clients read history at once and an MCP server hangs, plus `make perf`, `make perf-responsiveness` and `make perf-baseline`. Scenarios that already stall v3.1.1 are expected failures for `TARGET=python` only. No app behaviour changes.
- The desktop app now starts its backend through the Rust gateway (`evoflux-server`), which then starts the Python backend from the same bundle. Every request still goes to Python. The desktop token, embedded Tailscale helper, bundled ripgrep, `EVOFLUX_APP_ENV` and `backend.log` work as before. When startup is retried, the gateway waits up to 40 s for Python, so its error and Python's last log lines arrive before the app's 45 s retry limit. `scripts/build_sidecar.py` builds `evoflux-server` in release mode into the sidecar bundle, and `make dev-desktop` runs the source backend behind `cargo run -p evoflux-server` (without auto-reload; `make dev-web` keeps uvicorn `--reload`).

## [3.1.1] - 2026-10-28

### Changed

- Bump EvoFlux package and desktop application versions to 3.1.1.

### Upgrade notes

- To select between running Desktop instances, update each participating Desktop app and restart it once, then use WebBridge 2.12.0 or newer. In the extension, choose **Settings → Connection → EvoFlux endpoint** and **Save & reconnect**.

### Fixed

- WebBridge can pair with a selected running Desktop instance when several EvoFlux apps are open. Each instance publishes its own local discovery record, and closing one no longer removes another instance's record.
- A browser preview no longer shows up in other chats: it appears only in the chat it belongs to and returns when you switch back, while its page and the agent's browser keep running.
- A browser page no longer stays on screen after the panel or preview showing it goes away. Docking the preview into the browser panel and then closing the panel, or switching chats, could leave the page floating over the app at its old position; any page no view is showing is now hidden.

## [3.1.0] - 2026-10-20

### Added

- The built-in browser now shows a virtual cursor while an agent clicks, hovers or drags — in the floating preview and in the workbench panel. It glides to each target and pulses on a click; your real mouse is never moved.

### Changed

- Long commands no longer make the agent poll. `shell` waits for a command and returns its result, or, with `background=true`, starts it and returns at once; the task then tells the agent when it exits and, with `notify_on`, when an output line matches. An idle agent is woken for a new turn by default, so a build that finishes after it stopped talking still reaches it; **Settings → Agents → Background tasks** can switch that to **Wait**, which holds the result for your next message. Finished and matched tasks show as small status cards in the chat, and the desktop notification for a completed background task now follows the real exit.
- The `process` tool now only lists background tasks, shows the latest output of one, or stops one.
- Bump EvoFlux package and desktop application versions to 3.1.0.

### Fixed

- Opening the built-in browser no longer fails with "Something went wrong" (React error #301).
- The usage popover no longer draws the model-call summary over the **% cached** label; long summaries are shortened and show in full on hover.
- A startup failure no longer drops you into an empty app: the launch screen stays up with its error and **Retry** button.
- Suggested next messages no longer ask for tool permission in ask mode, and only the lead agent can suggest them.
- Reopening a session whose widget was replaced and then re-created with the same `block_id` now shows the latest version instead of a stale one.
- Browser pages of chats you are no longer looking at are now released: deleting a chat closes its pages, and the twelve most recently used background chats keep theirs open, so switching between chats does not reload their pages.
- Opening the built-in browser from the workbench and from the preview at the same time no longer risks two blank pages, and a view that changes session releases its old slot.
- Mermaid diagrams rendering at the same time no longer interfere with the editor's loader.
- A chart row with a bare comma (`A ,`) is no longer drawn as `A = 0`, and `1,2,3` is no longer read as 123.
- Pressing **Esc** to cancel an input-method composition no longer dismisses the suggested next message, and an interrupted turn no longer leaves its suggestion for a later turn.
- Suggested next message ghost text is no longer announced by screen readers as a live status.
- Motion artifacts are asked for a single 1920x1080 canvas, which serves both export qualities.
- The live smoke script for Intelligent UI now honours `--timeout-seconds` for a stalled stream.
- Saving a long turn in batches never separates a tool call from its results, so a failed write cannot leave a call without answers.
- Stopping the dev launcher on Windows now ends the whole process tree, and port detection works on non-English Windows.
- Timed-out commands on Windows are stopped with the System32 `taskkill`, and cancelling mid-kill no longer leaves the command running.
- `web_search` gets 15 more seconds before it is cut off, so a slow but successful search is no longer lost at the limit.

### Removed

- `shell`'s `yield_time_ms` and the `process` tool's `poll`, `wait` and `terminate` actions are gone, with no compatibility layer.

### Upgrade notes

- Custom agent instructions, skills or prompts that tell an agent to use `process` with `poll`, `wait` or `terminate`, or to pass `yield_time_ms` to `shell`, need updating: run long commands with `shell(background=true)` and let them report back, and use `process(action="stop")` to end one.

## [3.0.10] - 2026-10-19

### Added

- Settings → Agents now offers Simple / Visual response style, letting the assistant choose prose, native controls, or a richer artifact based on the task.
- Chat supports validated native UI blocks, interactive tables, chart and Mermaid fences, with stable block identities for in-place updates and transcript replay.
- Dashboards, motion explainers, and bounded 3D scenes open in the EvoFlux Workbench, inherit app theme and reduced-motion settings, and can be saved to a project explicitly.
- Motion artifacts support beat timelines, deterministic local MP4 / WebM export, per-frame progress, cancellation, bounded review, and optional synthesized sound effects.
- A built-in diagram-design Skill helps create and redraw focused, accessible architecture, sequence and process diagrams. In Work it follows the existing diagram widget workflow and adapts to the app theme; short diagrams maintained in Markdown can stay Mermaid.
- Suggested next messages in the chat composer: when an agent ends a turn with a useful follow-up in mind — tests after a change, a build check after an edit — it offers the next prompt as ghost text in an empty composer. Press **Tab** to accept it, keep typing to replace it, or **Esc** to dismiss. The suggestion is agent-judged (`suggest_next_message`), appears only when there is a real next step, and is not replayed after a reconnect.

### Fixed

- Chart fences accept label/value rows as well as JSON, Recharts resolves decimal.js-light to its ESM build under Vite 8, and Mermaid failures clean up temporary render nodes.
- The agent tool catalog now includes `todo_manage`, `schedule_task`, and `note`, so lead-managed tools are represented instead of silently omitted.
- Shell process waits are clamped to 60 seconds, and tracked command trees are force-terminated after a 30-minute maximum lifetime. Stopping a command now always returns: the post-kill wait and the output reader are bounded, and a command that survives force-kill is logged instead of blocking the session.
- Transient provider retries now use exponential backoff with jitter, a 60-second deadline, and per-attempt elapsed-time and usage logging.
- WebBridge artifact-retention cleanup uses a partial SQLite index to avoid scanning metadata for every session message.
- Web and image searches now bound DuckDuckGo requests, and network tools have shorter individual limits so a stalled provider cannot hold an agent turn indefinitely.
- The browser tool schema guard now records the definitions shipped after `done_browsing`, `load_state` aliases, tab-group labels, and `release_session` were added.
- Session message persistence now commits in bounded batches and retries temporary writer-pool timeouts, reducing reload and session-write stalls without changing the retryable `database_busy` response contract.
- Diagram widgets now inherit the active light/dark appearance and accent. SVG diagrams with overlapping boxes, missing connector endpoints, obstructed routes, or clipped artwork are returned for correction before they appear in the conversation.

- Token numbers no longer overstate usage. The per-agent token figure on the team workbench is now the conversation's size as the model sees it — the latest prompt plus its response — instead of that prompt plus the output of every turn in the session, which only grew over time. The **Context Usage** popover's **This turn** section names background calls (title, memory, summaries) that are billed to the turn but are not part of the conversation, and model streams that repeat the same usage on every chunk now report it once instead of once per chunk.
- Tasks running in the background can use the in-app browser: a running session keeps its browser presence attached whether or not its chat is on screen, and a mount requested before that is queued and opens the browser the moment the chat connects. `browser_use` on a background task no longer fails with "EvoFlux in-app browser is unavailable for this chat"; the remaining failure message is "EvoFlux in-app browser could not open for this session", which now only appears when EvoFlux Desktop is not running.
- The floating browser preview and the browser panel are now one browser per chat. They share the same tabs and pages: opening the panel shows the pages already open in the preview instead of an empty tab, closing the panel brings the preview back while pages are still open, and switching between them no longer reloads, moves or recreates a page. Closing the preview with no panel open, or closing the session's last page, still ends the browser. The panel now lists the session's tabs above the page: clicking a tab switches the shared active page, and each tab has a close button.

### Changed

- Visual routing weighs task utility and temporal value instead of relying on prompt length or isolated keywords; matching visual skill guidance loads only when the active run has the required tool.
- Bump EvoFlux package and desktop application versions to 3.0.10.
- Coding agents read, search, list, and edit files with the built-in file tools (`read`, `grep`, `glob`, `ls`, `edit`, `write`, `patch`) and keep the **shell** for repository commands such as tests, linters, builds, and git. The built-in prompts and tool descriptions now say so, and the truncation notice on large files points to `grep` instead of shell text utilities.
- The agent runtime no longer writes an internal tool-capability map into session state that nothing read; sessions run slightly leaner with no behavior change.
- The desktop boot splash shows a real error instead of hanging forever when no backend is available; the dev tooling no longer requires `lsof` on Windows.
- Task worktree merges now land as ordinary commits named after the task goal instead of `chore(evoflux): delegation <id>`. When the integration branch has not moved, the merge fast-forwards and keeps the member's own commit messages; only genuinely diverged work records a `Merge task: <goal>` merge commit.
- Worktree snapshot and review diffs no longer fail on deep Windows paths; the delegation Git runner enables `core.longpaths`.

### Removed

- The `load_tool` deferred-tool activation round-trip is gone. Every tool granted to an agent is now visible in the model's tool definitions from the start of a run, so agents call browser, LSP, worktree, visualization, code-review, and MCP tools directly instead of searching a catalog and loading them first. Tool permission and sandbox behavior is unchanged; `skill` and MCP tools keep working, except that MCP tools registered by an agent mid-run now become available from the next turn rather than immediately.
- Team chat no longer switches to **Split** on its own when three or more agents start working; open Split from the view menu or with `Ctrl+V` whenever you want it.

### Upgrade notes

- Remove `load_tool` from any `tools:` list in your agent `.md` files; the tool no longer exists and every other tool is available without activation.

## [3.0.7] - 2026-10-14

### Fixed

- `grep` and `glob` now distinguish a file supplied as the search root, a missing directory, and a file blocking a path component, with guidance to correct the search path instead of retrying the same invalid call.
- The Coding and Work sidebars render correctly again after restoring the missing `framer-motion` import; session panels that use plain `div` elements no longer receive unsupported animation props.
- A lead can no longer end its turn with a delegated worktree left unresolved: `sleep` reports the outstanding tasks back instead of stopping, and a lead that stops anyway is woken with the same list, so a Coding session no longer goes idle with isolated member work unmerged.
- **Built-in Browser** keeps agent pointer actions inside the page instead of moving the desktop cursor; pages that require trusted OS gestures or browser-managed CSS `:hover` may still need another control path.

## [3.0.6] - 2026-10-10

### Changed

- Agent questions (`ask_user`) and permission prompts now rise directly out of
  the chat input instead of appearing as a centered popup over the
  conversation. The transcript stays visible and scrollable behind them.

- The built-in agent and team prompts now ask agents to scale their effort to
  the task instead of always running a fixed, exhaustive procedure. Members no
  longer have to use "3+ sources" for every question, rebuild a weighted matrix
  or full assumptions table for small decisions, or re-read files they just
  wrote; **explorer** and **consultant** now stop once the evidence answers the
  question and lead their reports with the answer or recommendation. The
  Work assistant answers quick questions directly instead of defaulting to long,
  heavily formatted replies. Members are also told correctly that read-only
  research hands off with `verified=False` rather than omitting verification,
  which the runtime would have rejected.

### Fixed

- `load_tool` now searches the supplied query when a model sends an empty
  `tool_name`, instead of reporting the empty name as unavailable.

- **Settings → Telemetry** keeps recording on machines where another tool sets
  `OTEL_EXPORTER_OTLP_ENDPOINT` (the GitHub Copilot CLI, for example). EvoFlux
  no longer treats machine-wide `OTEL_*` variables as its own configuration:
  span and metric files are always written, so the Telemetry page stops going
  blank, `OTEL_RESOURCE_ATTRIBUTES` no longer stamps another tool's host and org
  onto EvoFlux records, and the generic OTLP headers, protocol and certificate
  variables are hidden while EvoFlux builds its exporter so foreign credentials
  never travel with EvoFlux spans. Forwarding to a collector is opt-in through
  `EVOFLUX_OTEL_OTLP_ENDPOINT`, with `EVOFLUX_OTEL_OTLP_PROTOCOL`,
  `EVOFLUX_OTEL_OTLP_HEADERS`, `EVOFLUX_OTEL_OTLP_TIMEOUT` and
  `EVOFLUX_OTEL_RESOURCE_ATTRIBUTES` replacing what the generic variables used
  to do; a missing exporter package logs `otel_otlp_exporter_unavailable`
  instead of failing silently.

### Removed

- The built-in **debate** member is gone from both the Work and Coding teams.
  The lead no longer offers it as a specialist and new workspaces no longer
  create `debate.md`. An existing `agents/debate.md` or
  `agents/coding/debate.md` you never edited is removed on the next start;
  one with your own prompt text stays as an ordinary custom agent.

### Upgrade notes

- If you relied on **debate** for reviews, keep your edited `debate.md` (it now
  runs as a custom agent with only your text as its prompt) or ask the lead to
  have **consultant** or **architect** review the work instead.

## [3.0.5] - 2026-10-08

### Added

- **Waiting Arcade** offers six optional local games from the composer’s **More actions** menu during active Work and Coding runs, including animated 2048, Memory Pairs, and Mini Breakout. Games pause when the panel closes or a run needs the user's attention.
- **Plugins → Marketplace** can add and sync Agent Plugins 1.0.0 and Claude Code
  sources, search their catalogs, and preview compatible components. Marketplace
  installs stay disabled until trust review; importing only supported parts of a
  partially compatible Claude plugin requires explicit consent.
- **Settings → Import** supports local exports from Claude.ai, ChatGPT, Claude
  Code, Codex CLI, Cursor, and supported generic configuration/resource files.
  Imported sessions show their source in the sidebar and conversation view.
  The import welcome flow can help set up a local import.
- Import auto-sync handles new sessions, skills, and agents while EvoFlux is
  open. Import history supports Undo with item-level results; targets changed
  after import are preserved.

### Changed

- Agents now wait with a real **`sleep`** tool instead of replying with the text
  `<sleep>`. The tool takes no arguments, works for the lead and every member,
  and its call is hidden from the transcript. The text marker is gone: a reply
  containing `<sleep>` is just text. Saved conversations are cleaned on upgrade
  — a trailing `<sleep>` / `[sleep]` is removed from old replies and nothing is
  deleted.
- Tool calls that models commonly get slightly wrong are now recoverable. A lone
  string for `team_delegate`'s `to` (and `team_message`, `team_handoff`,
  `team_reject`) is read as a one-element list, and `todo_manage` and
  `team_delegate` now state their call shape — `actions=[{"action": ...}]`, not
  `todos=` — in the description and show a valid example when validation fails,
  so the model no longer repeats the same rejected call.
- **OpenCode Zen** and **OpenCode Go** now send each model to the endpoint
  OpenCode documents for it: Claude, MiniMax and Qwen over Messages, GPT, Grok
  and Muse Spark over Responses, Gemini over its native API, and the open
  models over Chat Completions. Previously every model was sent to Chat
  Completions regardless of family. DeepSeek, Kimi and
  MiMo models keep their reasoning across tool calls, and `OPENCODE_BASE_URL`
  and `OPENCODE_GO_BASE_URL` override each plan's endpoint. Every OpenCode
  request now carries the `x-opencode-session` header OpenCode Go requires, so
  title generation and other calls outside a chat no longer fail with
  `MissingSessionID`.
  **OpenCode Zen** always needs its key: OpenCode serves its free models only
  inside its own app and answers other clients with "free tier can only be
  used from within OpenCode", so EvoFlux no longer tries them keyless.
- **Settings → Providers → OpenCode Go** shows your rolling 5-hour, weekly and
  monthly usage as percent used with each window's reset time, refreshed every
  minute, and flags a window that has reached its limit.
- **OpenCode Go** now keeps its own key (`OPENCODE_GO_API_KEY`) instead of
  sharing Zen's, so saving a Go key no longer shows **OpenCode Zen** as
  connected. Both entries also have proper descriptions in
  **Settings → Providers**.
- **Settings → Providers** no longer has a **List models** button on API-key and
  cloud providers. **Save** verifies the key by listing the provider's models,
  saves it only if the provider answers, and leaves the model list open.
- Plugin API verification applies POSIX credential-file mode checks only on POSIX
  systems, avoiding unsupported permission assertions on Windows.
- **Plugins → Marketplace** reflows setup and source cards to panel width, explains
  why unsupported entries cannot install, and treats `unverified` as a trust
  warning. On wide panels the selected package keeps its review and install action
  pinned in view; narrow panels retain the drawer. Package inspection shows Skills,
  MCP configuration, validation errors, README and read-only package files before
  installation.
- **Plugin Center** uses compact plugin rows, with components, package files and
  technical details available on demand. Search stays visible while filters and
  marketplace management remain secondary controls.
- Import preview supports search, type filters, paging, in-place re-import,
  and explicit review for same-name Skills from other local sources.

### Fixed

- Every OpenCode Go model now answers. `glm-5.1`, `glm-5.2` and `glm-5.3` failed
  with "thinking-only model; disabling thinking is not supported" because the
  runtime asked them to stop thinking, and `kimi-k2.7-code` failed with "invalid
  temperature: only 1 is allowed" because a Kimi default temperature was added
  to a model that takes none. Both parameters are now left out for those models.
  `glm-5.3-flash` failed on the turn after its first tool call with "`name` is
  not supported" because tool results carried the tool name; they now carry only
  the call id, which is all OpenCode matches on.
- The hourly browser-capture cleanup no longer reads and parses every message's
  metadata, and its first run waits two minutes instead of competing with
  startup. On a 33,000-message history the query dropped from about 0.76 s over
  33,151 rows to 0.14 s over none, which also removes the "slow database"
  warnings and pool waits seen while the app was opening.
- Installing a language server on Windows no longer fails with "Access is denied"
  when moving the new install into place. A momentary file lock (antivirus, the
  indexer, or the old server still running) is retried, the running server is
  stopped first, leftover staging folders from a crashed install are cleaned up,
  and a lock that does not clear now says what to close instead of a raw
  `PermissionError`.
- The sandbox's shell-command audit on Windows no longer logs paths that never
  existed. Git Bash spellings such as `/c/Users/...` and `/dev/null`, and
  strings that merely contain a slash (a `curl -w` format, a `python -c` body),
  were turned into `C:/c/Users/...`, `C:/dev/null` and garbage, so the audit
  trail could not be trusted. Drives are mapped to `C:/...`, harmless devices
  and non-path strings are skipped. Commands are still never blocked by this scan.
- Team members can read the large tool results they offload. A member such as
  `explorer#1` was refused its own `.tool_results` file ("is inside a denied
  sandbox root") and had to `cat` it through a shell, repeatedly, at full token
  cost; results now land in the session directory the member's sandbox allows.
- A turn no longer dies when the model connection drops mid-response. "Peer
  closed connection without sending complete message body" and "Server
  disconnected without sending a response" are now retried and resumed like a
  timeout, instead of cancelling the whole turn.
- Claude Code MCP plugins receive a normalized `mcp.json`; invalid component
  diagnostics block marketplace installation, package review masks credentials,
  and remote MCP servers awaiting authorization show **Authentication required**.
- MCP configs using the conventional `type` transport key load correctly, so
  existing stdio servers are not rejected during lead-agent startup.
- **Plugin Center** marketplace package actions stay pinned inside the review
  drawer even when package details are expanded, instead of scrolling below
  the viewport.
- **Plugin Center** marketplace management stays open after you expand it; the
  section no longer snaps shut on the next catalog refresh.
- An empty marketplace result now distinguishes "no plugins match your search
  and filters" from an empty catalog that needs a sync.
- The observability summary no longer returns HTTP 500 when a time-series
  bucket contains null aggregates.
- Claude Code imports retain tool calls/results and subagent provenance while
  keeping sidechain messages out of model context. ChatGPT imports use stable
  provider IDs and safely bridge unique older title-based imports.
- Unsupported settings and credential records are labeled and skipped instead
  of appearing as importable items.

- On Windows and macOS, the notification bell and its **Notifications** inbox
  panel now sit in the window title bar next to the window buttons (left of
  the minimize/maximize/close cluster on Windows, right of the traffic lights
  on macOS) instead of the workbench top bar.

## [3.0.4] - 2026-10-01

### Fixed

- EvoFlux now starts if the operating system cannot register its deep-link
  handlers; it records a warning and continues loading.
- Desktop release builds now bundle the web interface with the sidecar so
  Remote Control works in the packaged app.

### Added

- Actionable desktop notifications for background work and attention requests,
  with deep links and supported quick replies. A notification inbox shows unread
  items, while taskbar and Dock badges surface the unread count.
- Notification sounds can be selected and managed from Settings, including
  uploading, previewing, renaming and deleting local sounds.

### Changed

- Building the desktop sidecar fails fast with `web bundle missing` when the web
  interface has not been built yet, instead of silently producing a bundle that
  cannot serve the UI.

### Fixed

- The **Remote Control** link and QR code open the EvoFlux interface on a phone
  instead of a `{"detail": "Not Found"}` API response. The desktop bundle now
  ships the web interface inside the sidecar, so the private tailnet address
  serves both the app and its API from one origin.
- Reloading EvoFlux on a phone at a nested page such as **Settings → Remote
  Control** returns to that page instead of a not-found error. Missing API
  endpoints still answer with a JSON `Not Found`, and a missing asset still
  fails visibly rather than loading the app shell.

## [3.0.3] - 2026-09-30

### Added

- The agent's `grep` tool takes an `output_mode`: `files_with_matches` lists
  only the matching files, newest first, and `count` gives matching lines per
  file with a total. It pages with `offset`, filters by language with `type`,
  matches literal text with `fixed_strings` and patterns that span lines with
  `multiline`. A partial page ends with a notice naming the next `offset`
  instead of silently stopping at `max_results`, and patterns with
  backreferences or look-around run in ripgrep's PCRE2 engine.

### Changed

- The scheduled models.dev snapshot job now opens a reviewable pull request
  for registry updates instead of writing directly to `main` or failing with
  an unreconciled stale snapshot.
- New research note `documents/research/agent-code-search-tools.md` compares
  the code-search tools of Claude Code, opencode, Gemini CLI, Codex, Cline and
  Roo Code with EvoFlux's `grep`/`glob`, and proposes shipping ripgrep in the
  desktop app plus output modes, pagination and truncation notices.
- The desktop app ships ripgrep 15.2.0, so the agent's `grep` stays fast and
  follows nested `.gitignore` files on computers without ripgrep installed,
  instead of falling back to a slow scan with a 10-second limit. Agent shell
  commands can run `rg` too: the bundled copy is added at the end of `PATH`,
  so a ripgrep you installed yourself still takes precedence.
- The chat shows a finished search as **Searched** `<pattern>` and a finished
  file search as **Found** `<pattern>` (previously **Listed Searching …**),
  naming the filters and output mode, and shows a page notice under the
  results instead of counting it as an entry.

### Fixed

- The agent's `glob` tool returns the newest matching files. It used to keep
  the first 200 matches in name order and only then sort them by date, so a
  recently edited file could be missing; it now sorts every match, pages with
  `offset`, and says when files were left out.
- The Windows desktop app starts on PCs without the Microsoft Visual C++
  Redistributable. The app's built-in Python now ships the C++ runtime
  (`msvcp140.dll`) itself, so startup no longer loops on `auto_migrate_failed`
  with "DLL load failed while importing _greenlet".
- In the Coding sidebar, the project picker row, the **Chats** header and the
  repository rows sit on the same see-through surface as the rest of the
  sidebar instead of showing as darker or grey bands.

## [3.0.2] - 2026-09-29

### Changed

- Suggested-task chips live behind a 💡 **N** button in the chat's top bar,
  beside **WebBridge**, instead of sitting above the message box. The list
  opens as a popover and no longer covers the first lines of the chat.
- The message box keeps its toolbar on one row at every width. On narrow
  windows and phones the attach button, folder, model and permission pickers
  shrink to icons instead of wrapping onto a second row, and the send button
  always stays at the right edge. On phones the message
  box is a fully rounded card floating over the chat, without the divider
  line above it.
- The Coding sidebar is laid out around the selected project instead of a
  boxed card under a **Projects** section header: the project picker heads
  the list with **+** for a new chat and a **⋯** menu for **Add repository…**
  and **Delete project**. The project picker opens at the width of that row
  and ends with **Open folder as project…** and **Set up a multi-repo
  project…**. The repositories open from a quiet **N repositories** row, and
  the chat list fills the rest of the sidebar with its **Chats** header
  pinned while you scroll.
- **Open folder as project**, **Add repository** and **Clone repository**
  open as a centered dialog instead of a panel beside the chat. The
  **Clone repository** form no longer lets its folder list overlap the note
  below it.
- Searchable pickers (project, repository and pull-request filters) no
  longer leave a blank band between the search field and the list, and their
  rows use the same text size as the picker.
- Dark mode uses neutral gray surfaces, borders and text instead of warm
  charcoal, so the message box, chat bubbles, cards, the code editor and the
  terminal no longer look yellowish. The accent colour is unchanged.
- Coding is project-only. The **Workspaces** section is gone from the Coding
  sidebar: the folder **+** on **Projects** opens (or clones) a folder as a
  project named after it and starts a chat there, and a folder that already
  belongs to a project opens that project. **Set up a multi-repo project
  instead** opens the project wizard, and repositories can still be added to
  any project. Every Coding chat, worktree, suggested task, scheduled task and
  `schedule` reminder now belongs to a project; the **Scheduler** picks a
  **Project** for Coding tasks, and palette search opens a repository's
  project. **Create worktree** on a repository shared by several projects
  works from the project it was started in, and the unscoped code-review list
  shows only project repositories. `PATCH /api/team/workspace/visibility` is
  removed, `GET /api/team/workspace/tree` lists only project repositories,
  and starting a Coding session on a folder in no project is refused.
- The Coding home page offers **New chat in <project>** for the project you
  were last in, a link to a deleted or empty project goes back to the Coding
  home page with a notice instead of the "Backend connection failed" screen,
  and removing a repository from a project no longer clears every cached
  panel in the app. A link to a Coding chat that was deleted or removed with
  its project also goes back to the Coding home page with a notice instead of
  an "Agent error", and an old `/coding/<folder path>/<chat>` link to a chat
  that now belongs to a project opens it there.
- A project with a single repository shows repository suggestions such as
  **Explain this repository structure** on its empty chat, instead of
  cross-repository ones.

### Removed

- The **ⓘ Agent info & tools** button next to the model picker in the
  message box, with its capabilities and tools popover.

### Fixed

- On Windows 10 the sidebar, **Settings** rail and title bar no longer turn
  dark over a dark wallpaper while the light (or **System** light) theme is
  active; they now follow the selected theme.

- A file write or edit the agent was refused (for example into the checkout a
  worktree chat may only read) shows as **Write failed** with its error in
  the chat, instead of **Wrote** with a diff of the change that never
  happened.
- **Create worktree** says where the worktree goes as set in **Settings →
  Sandbox**: inside the repository under `.evoflux/worktrees/` (the default),
  or in EvoFlux data. It always said EvoFlux data.
- The **Edited N files** summary under a Coding turn stays after reloading
  the page or restarting EvoFlux, instead of disappearing, and **/undo**
  removes it straight away. **/redo** back to the latest turn brings it
  back.
- The Coding file tree marks each changed file with its git status: **U**
  for a new untracked file, **A** added, **M** modified. Every changed file
  used to show **M**. Changes already staged with `git add` now count too:
  they used to show no mark at all, and the Coding changes view left them
  out.
- **New chat in <project>** on the Coding home page names the project the
  sidebar has selected. It could name a different, earlier project.
- `POST /api/team/sessions/resolve` refuses (`422`) a `workspace` that is not
  a repository of the `project_id` sent with it, instead of ignoring it.
- **Trust this folder?** warns when the folder already belongs to a project:
  confirming (**Trust and open project**) opens that project, and no new
  project is created.
- A link to a deleted Coding project says the project was deleted, instead of
  "Project has no workspaces configured".
- Switching repository in **Source Control** selects a file of the new
  repository, instead of keeping the previous repository's file name over an
  empty diff.
- On Windows, TypeScript and JavaScript files show their type errors again: in
  the editor, in **Problems** and in the agent's post-edit check. The language
  server reported them under a differently spelled file path
  (`file:///c%3A/...`), so every file looked clean. A file whose name
  contains `%` keeps its diagnostics too, and a malformed file path from a
  language server no longer disconnects it.
- A Python file that does not parse shows in **Problems** as an error rather
  than a warning.
- In a narrow desktop window on Windows, the chat header and a maximized
  Workbench no longer show a second sidebar button beside the one in the
  title bar; the title-bar button opens the sidebar drawer, as on macOS.
- In a multi-repository Coding project, **/undo** and **/redo** rewind and
  restore every repository the turn changed, not only the project's first
  one. Turns from before this change still undo their first repository only.
- A Coding chat running in a worktree can read the checkout the worktree was
  made from but no longer write to it, so its edits stay in the worktree
  instead of leaking into every other chat on that repository. The project's
  other repositories stay writable.
- The automatic checks at the end of a turn run in the right repository for
  a file the agent edited in another repository of the project through a
  relative path such as `../web/src/app.ts`, instead of failing with "outside
  repository" and sending the agent back to redo the work.
- The Coding panels follow every repository of a multi-repository project,
  not only its first one:
  - When the agent edits a file in another repository, that repository's
    file tree and changes refresh straight away, and the desktop app watches
    every repository for outside edits.
  - Opening a changed file from the chat, **Problems** or the command palette
    opens it in the repository it belongs to. **Review** on a change opens
    **Source Control** on that repository, and the editor's add-to-chat and
    comment actions cite the file so the agent finds it there.
  - The composer's **@** picker and the command palette list files from
    every repository; another repository's files show as
    `<repository>/<path>`.
  - A chat running in a worktree shows that worktree, labelled
    **<repository> (<worktree>)**, in the file tree and in **Source
    Control**'s repository picker, instead of the checkout it was made from.
  - Applying a ChangeSet refreshes the file tree, changes and **Source
    Control**.
  - **Problems** lists every repository's findings, each naming its
    repository, and **Dismiss**, **Suppress**, **Restore** and **Fix** act on
    the repository the finding came from. Diagnostics after the agent edits
    a file in another repository, and the `lsp` and `static_diagnostics`
    tools, run that repository's language server and file their findings
    under it, instead of the first repository's or not at all.
    `GET /api/team/workspace/problems` accepts `workspace` more than once.
  - **Open in** asks which repository to open when the project has more
    than one.
  - The file tree no longer lists a worktree's `.git` file, and a
    repository's list no longer includes the files of a worktree nested
    inside it, such as one under `.evoflux/worktrees/`.

### Upgrade notes

- The first time EvoFlux starts after upgrading, Coding chats and Coding
  scheduled tasks that belong to no project (the old standalone workspaces)
  are filed under their repository's project when exactly one project owns
  that repository (or the repository a worktree came from). The rest are
  permanently deleted, with their side chats and generated files. The
  repository folders on disk are not touched: open a folder from
  **Projects** to keep working in it. Bookmarks to `/coding/<folder path>`
  go back to the Coding home page.
## [3.0.1] - 2026-09-29

### Added

- **Settings → Desktop** with three switches: **Run on startup** (EvoFlux
  opens at sign-in and waits in the tray), **Show in system tray** (menu bar
  on macOS; with it off on Windows and Linux, closing the last window quits)
  and **Keep computer awake** (stops idle sleep while EvoFlux runs; the
  display can still turn off).
- Windows draws its own title bar: an app menu (File, Edit, View, Go,
  Developer, Help), the sidebar toggle, back/forward and the caption buttons,
  keeping Mica, the window shadow and rounded corners. The window stays
  movable and closable while a dialog is open.
- Suggested-task chips have a split **Run** button. **Run in current
  session** queues the prompt in the session that raised it instead of
  opening a new one (not offered with a worktree or for another project).
- A built-in **browser-use** Skill: which web tool and browser to use, ground
  rules for acting on sites, and one step-by-step routine from opening a page
  to reading the result back.
- Remote Control settings open with a policy warning (**Don't show this
  again** is remembered) and a **How to set up** walkthrough that ticks off
  its four steps from live status.
- WebBridge installs from the Chrome Web Store (Edge uses the same listing)
  instead of a zip loaded unpacked in Developer mode.
- Computer App Control on macOS drives a parked Chrome or Electron window:
  it is captured through ScreenCaptureKit (the preview is no longer white),
  menus are handled inside the action that opens them instead of staying on
  screen, and parked windows are put back after a crash. EvoFlux still starts
  on macOS 11.

### Changed

- `browser_use` follows the live WebBridge state: with WebBridge enabled, the
  agent-browsing switch on and the extension connected, actions run in your
  browser; otherwise in the in-app browser. The switch sits on the workbench
  WebBridge button and in **Settings → Browser** and applies from the agent's
  next action. The per-chat browser picker and the new-chat default are gone.
- Through WebBridge each chat works in a tab of its own instead of whichever
  tab is in front, the agent file-upload switch also covers `set_files`, and
  element screenshots are refused rather than returning the viewport.
- **Phone access** is now **Remote Control** in Settings and Help. The route
  and API keep the `remote-use` name.
- Successful actions no longer raise a toast; the change shows in the UI
  itself. A repeated toast extends the visible one instead of stacking, and
  the stack moved from the bottom-right corner to top-center.
- Sidebars: session rows are a single line (the full date and a scheduled
  task's name are in the tooltip), section headers are quieter, folder chats
  hang under a guide line, primary actions are a tile grid, text reads
  clearly over Mica and vibrancy, and the Coding sidebar cards size to their
  content and load more chats as you scroll.
- Lighter Work and Coding welcome screens with a centered hero and a compact
  usage summary.
- `ask_user` and permission prompts float over the chat as a modal, and the
  composer's task progress floats above the composer, so neither pushes the
  conversation up any more.
- Modal backdrops dim the page without blurring it, and the main and Settings
  content areas are rounded cards on desktop.
- A reasoning-only activity group shows its thoughts directly instead of a
  second **Thought** toggle inside the first.
- The shell tool tells the model which OS and shell commands run in (Git
  Bash, PowerShell or cmd.exe on Windows), so it stops mixing their syntax.
- The Coding lead no longer parks the fix for the problem you asked about as
  a suggested task; it answers in the reply and asks before implementing.
- A closed combobox shows only the option label, not its meta.
- Contributor rules in `AGENTS.md` now require every change to add its entry
  under `[Unreleased]` in this changelog in the same commit.

### Fixed

- Desktop updates no longer download twice or appear stuck while installing.
  The update now downloads in the background and waits: **Restart now**
  installs it, or it installs the next time EvoFlux quits. A download that is
  already on disk is reused after a relaunch, and the Windows installer shows
  its own progress window instead of running invisibly.
- A Dream run overlapping an active chat no longer blocks its database
  writes, which left assistant messages unsaved and errored the team member.
- After the computer wakes from sleep, connected providers keep their models
  instead of every chat reporting its model unavailable or asking to
  configure a provider.
- Non-ASCII text and file names in the Coding Git panel no longer garble on
  Windows.
- `ask_user` accepts options sent as `{label, description}` objects instead
  of failing validation.
- Settings, Providers and Notifications in the native menu and tray open
  Settings instead of a stray page, and a path such as `/settings` is no
  longer treated as a session id and restored on every launch.
- The macOS traffic lights stay in place while the window is resized.
- `backend.log` is plain text with full dated timestamps, `EvoFlux.log` uses
  local time to match it, and an unfinished Tailscale sign-in logs its login
  URL once instead of every five seconds.

### Security

- Tracebacks in the backend log no longer include local variable values,
  which could carry tokens or message contents into logs attached to bug
  reports.

## [3.0.0] - 2026-09-28

### Added

- Remote Control over an embedded Tailscale node: packaged desktop builds no
  longer require Homebrew, the Tailscale CLI, or a system daemon. Connect once
  in the browser, then use the private tailnet URL or QR code from a phone.
- WhoIs-backed remote identity for HTTP and WebSocket control, with a signed
  local proxy boundary and one-device session locking.
- Computer App Control across macOS and Windows with permission guidance,
  background app attachment, live preview, UI inspection, and explicit app
  policy controls.

### Changed

- Mobile interaction layer: larger touch targets, safer-area handling,
  responsive navigation drawers, a two-row chat composer, and settings layouts
  that remain usable at phone widths.
- Desktop packaging now bundles the embedded tailnet helper for macOS Intel,
  macOS Apple Silicon, Windows x64 and Linux x64.
- Chat rendering, sidebar navigation, tool activity and remote-use status use
  bounded surfaces and lighter update paths to reduce layout churn during
  streaming and long sessions.

### Upgrade notes

- Packaged users sign in to the embedded Tailscale node once from Settings →
  Phone access. The phone must use Tailscale and join the same tailnet.
- Computer App Control remains opt-in and still requires the platform's
  Accessibility/Screen Recording permissions where applicable.
- Existing source deployments can continue using the external Tailscale CLI
  provider as a fallback.

### Removed

- Plan mode is gone. The `plan` permission mode, the Plan review panel and its
  Accept / Revise / Reject bar, the `enter_plan_mode` / `exit_plan_mode`
  tools, the `plan_approval_requested` / `plan_approval_replied` stream events
  and `POST /api/team/{session_id}/plan/reply` (plus the WebBridge
  side-panel equivalent) are removed.

### Changed

- Permission modes are down to three, matching how people actually choose:
  **Ask for approval** (`ask`), **Approve for me** (`auto`, the default) and
  **Full access** (`bypass`, shown in orange), on shortcut keys 1–3.
  `accept-edits` is gone. Approve for me still stops for calls flagged
  potentially unsafe, and switching to it mid-run no longer approves such a
  pending request. Revision `00000070` moves sessions saved in `plan` or
  `accept-edits` mode to `ask`.

## [2.0.9] - 2026-09-25

### Added

- Computer App Control on macOS: the `computer_app` tool now drives one app
  window in EvoFlux Desktop on macOS too, with the same actions, preview card
  and policy as on Windows. It reads and operates the app through the
  Accessibility API, captures the window from the window server, and runs
  shortcuts such as ⌘S through the app's own menu bar, so the app can stay in
  the background. `find` searches the menu bar as well (the Apple menu is
  never offered). The user grants Accessibility and Screen & System Audio
  Recording in System Settings; a macOS permissions card in Settings →
  Computer App Control shows both, opens the exact pane for each with one
  click, and offers a restart to apply Screen Recording. `list_windows` also
  says when either is missing.
  Finder, System Settings, Keychain Access and the system UI processes cannot
  be attached. Shortcuts written `cmd+…` mean ⌘ on macOS and Ctrl elsewhere.

## [2.0.8] - 2026-09-25

### Changed

- Tool schemas sent to the model are smaller: the registry no longer emits
  Pydantic's nested `title`s, OpenAPI `discriminator` mappings that pointed at
  removed `$defs`, or the `null` branch of optional fields. With a shorter
  guide and one tab-targeting explanation instead of one per action, the
  `webbridge` definition shrank from about 67k to 35k characters and
  `browser_use` from 32k to 23k.

### Added

- Computer App Control (Windows desktop): the `computer_app` tool lets an agent
  drive one desktop application window in the background — list windows,
  attach, screenshot, read the UI Automation tree, click, type, press
  shortcuts, invoke controls and fill fields — without taking the user's
  mouse, keyboard focus or foreground window. A floating preview card shows
  the app live with a virtual cursor and offers Stop (revoke and interrupt),
  Allow again, Show the app and Close; it closes, and the app is released,
  when the agent's turn ends. Controlled apps are kept just off-screen by
  default so they run from the taskbar without covering the user's work, and
  get their exact placement back afterwards. Web-content apps (Teams,
  Electron, WebView2) are clicked through UI Automation and typed into with
  real keyboard events, so rich editors register the text; hover, double- and
  right-click, scroll (through UI Automation) and drag reach them too, hidden
  or not. Off by default; enable it in Settings → Computer App Control, where
  allowed and blocked apps are picked from the apps on the computer with their
  icons and each action can either ask first or run without asking. Capture and UI Automation are
  ported from evo-computer-use; input is posted to the app's own message
  queue.
- WebBridge debugging actions: `debug_summary`, `console`, `network` and
  `network_body` read the console messages, uncaught exceptions and requests
  (status, type, timing, failures, response bodies) of a tab in the user's real
  browser. Coding sessions record from their first command, so the agent can
  run the edit → reload → check-errors loop against a local dev server.
  Requires evo-webbridge 2.7.0.
- WebBridge `inspect` shows an element's computed styles and the component
  chain and source files that rendered it (React, Vue, Svelte, locator
  plugins); `mock` fakes or fails matching requests; `emulate` throttles
  network/CPU or fakes offline, location, time zone and locale; `performance`
  reports load timing and Web Vitals; `storage`/`cookies` inspect page state;
  `upload_file` fills file inputs with workspace files. Storage/cookie values,
  writes and mocks follow `webbridge.allow_evaluate`. Requires evo-webbridge
  2.8.0.
- WebBridge console stacks and component source locations are source-mapped
  to the original files in Coding sessions (evo-webbridge 2.9.0).
- WebBridge `wait_for_hmr` tells the agent whether a dev server's hot update
  applied, reloaded the page or failed; `debug_summary` adds the build-error
  overlay, hot updates, cross-origin iframe console/network, and the new error
  output of the `preview` server behind the page (evo-webbridge 2.10.0).
- Browser runtime errors, build overlays and failed requests appear in the
  Problems panel under a new `Browser` source, mapped to workspace files and
  cleared when the page is clean again.
- `webbridge` accepts `browser_use`'s spellings of the shared verification
  actions, and `preview` points both browser tools at `debug_summary`.

### Fixed

- WebBridge debugging output, from an end-to-end run against a Vite + React
  19 dev server (evo-webbridge 2.9.1): console messages apply `%s`-style
  formatting; the location is the first frame in the app's own code, library
  frames fold into one line, and warnings raised entirely inside a library
  say so; `inspect` labels React locations as where the element was rendered;
  requests the previous document left unfinished no longer count as the new
  page's pending ones; the "load not recorded" note appears only when no
  document has loaded since recording began; `performance` counters are
  collected from the start of recording.

### Fixed

- The `webbridge` tool now ships its full usage guide to the model; it was
  defined but never attached, so the model saw a one-line description.
- WebBridge `navigate` no longer stalls until timeout when the page lands on
  a different spelling of the requested URL (`http://localhost:3000` →
  `http://localhost:3000/`) or redirects (`/` → `/login`). `back`, `forward`
  and `reload` now wait for the page instead of returning immediately.
  Requires evo-webbridge with the matching extension change.
- Batched WebBridge actions stay on the session's bound tab and origin
  instead of running on whichever tab is active.
- In a WebBridge session, `preview start` names `webbridge` as the next step
  instead of the unavailable `browser_use`.

### Improved

- WebBridge page-loading actions report the address reached, redirects and
  title, and return a compact snapshot of the page when they end a call.
- Coding sessions drive WebBridge clicks and hovers without the human-paced
  pointer glide (72–360 ms per press in Work sessions).

## [2.0.7] - 2026-09-24

### Added

- Added turn file cards with thumbnails and direct navigation into the Files
  workbench for generated artifacts.
- Let agents choose which generated images should appear as turn cards, while
  skipping transient scratch renders.

### Improved

- Improved live PowerPoint deck previews with per-slide placeholders, compact
  page controls, and stable toolbar layout as rendering progresses.
- Let deck QA repair a finished deck without restarting the original live
  preview or reprocessing unrelated slides.
- Scoped slide edits to their target slides and refined the PPTX/Office Skills
  that drive live deck generation and annotation workflows.

## [2.0.6] - 2026-09-24

### Changed

- Agent Skills now follow Anthropic's Agent Skills architecture
  (documents/architecture/agent-skills.md). The system prompt lists each
  Skill's name, description and `SKILL.md` location; the agent reads
  `SKILL.md` with `read` when a task matches, reads referenced files on
  demand and runs bundled scripts with `shell`. This is a clean break with no
  compatibility layer:
  - the `skill` tool, the per-turn resolver model call and the bounded,
    query-ranked catalog are gone;
  - `SKILL.md` frontmatter is the whole bundle contract (`name`,
    `description`, `license`, `compatibility`, `metadata`, `allowed-tools`,
    plus `disable-model-invocation` and `user-invocable`).
    `agents/evoflux.yaml`, `agents/openai.yaml`, `.evoflux.json` and
    in-bundle `evals/` are no longer read, and nested `parent/child` names
    are no longer skills;
  - Skills are no longer scoped to Work or Coding mode, and Settings keeps a
    single on/off switch per Skill. Older `skill-settings.json` overrides
    are ignored;
  - `$skill-name` works anywhere in a message and may name several Skills;
    `/skill:<name>` is removed. An agent's `skills:` field preloads those
    Skills into its system prompt;
  - discovery scans `.evoflux/skills`, `.agents/skills` and `.claude/skills`
    in projects and the user directory, then plugins, then built-ins.
    `.opencode/skills` and `/etc/codex/skills` are no longer scanned.
  - Every bundled Skill was rewritten to the specification and the authoring
    best practices; `data-analytics` folds its 17 nested workflows into
    reference files, and the Codex-only Google Doc/Slides report workflows
    are removed.

### Removed

- Workflows are gone. `/workflow <name>`, the run-inputs dialog, the progress
  pill, workflow hits in Search Everywhere and in the WebBridge side-panel
  composer, `/api/workflows`, and the built-in `pr-hygiene` and
  `second-opinion` definitions are removed; `.evoflux/workflows/*.yaml` files
  are no longer read. Revision `00000068` drops the `workflow_approvals`,
  `workflow_executions`, `workflow_node_runs` and `workflow_gate_requests`
  tables. WebBridge Teach drafts no longer carry a generated `workflow_yaml`,
  and `ask_user` questions no longer have a `strict` mode — it existed only
  for workflow gates.
- The legacy ASDD and code-graph product surfaces are removed from the
  application and repository runtime.

### Added

- StepFun is now a supported provider. `stepfun:` models resolve to the
  global open platform by default, with `STEPFUN_BASE_URL` selecting the
  China host or either Step Plan subscription endpoint. Reasoning traces are
  requested in the spelling EvoFlux renders (`reasoning_content`) rather
  than StepFun's documented default, and the reasoning effort stays inside
  the levels StepFun publishes. StepFun cannot switch thinking off, so the
  off position leaves it at StepFun's own default.

### Added

- `asdd-explore`, a seventh Agent Spec-Driven Skill, fills a freshly installed
  catalogue from the repository it was installed into. Setup wrote `project.md`
  as placeholders and nothing ever filled it, while all six phase Skills read
  it first — so a fresh install ran every phase against blank rules. Explore
  reads what exists (`AGENTS.md`, README, build and test configuration, CI),
  asks only what the repository cannot answer, and writes `project.md` with the
  source beside each claim, plus the `architecture/` and `reference/` pages the
  code already justifies. It writes no `specs/` and no ADR — the first would
  contract whatever the code does today, bugs included, and the second states a
  rejected alternative that does not survive in code — and it defers `AGENTS.md`
  to `/init`, which already writes those properly. The board offers it until the
  repository has been described.

### Changed

- Autopilot now carries a change from phase to phase instead of only signing
  its gates. An agent would clear `auto_approvals`, move the status on and
  stop — every phase Skill says to stop — leaving the rail showing **Continue**
  for a person to click, once per phase. A finished turn now asks the same
  question that button asks and starts the next phase itself, binding the
  session to the change through the phase prompt already in the transcript.
  Whether a hop is allowed stays the rail's decision, so autopilot off, a
  `hold`, an unmet gate or a blocker all end the chain; so do a hop that moved
  nothing and a chain that reaches twelve hops. It still stops at `ready`,
  because archiving is the user's click at every tier.
- The six Agent Spec-Driven phase Skills are rewritten to one shape: the role
  and the single hard boundary first, a gate table that answers "should I even
  be here", the ways an agent arrives at that phase, the decisions it owes with
  the tables behind them, a worked example of the report in the agent's own
  voice, and closing guardrails that each say why. `asdd-plan` now splits its
  two jobs into a Design track and a Tasks track chosen by status rather than
  running them together. The `code_context` instructions each Skill repeated in
  full — 23 lines apiece, on top of the reference file installed beside them —
  are down to the rules that phase actually uses.
- The Agent Spec-Driven catalogue now has a home for each durable kind of
  page — `architecture/` for process, storage, concurrency and trust
  boundaries, `architecture/decisions/` for ADR-style records of why they are
  where they are, `reference/` for the exact API, configuration, schema and
  CLI surface, and `analysis/` for dated investigations — each with a
  `README.md` stating what belongs in it. The phase Skills write into them:
  the plan phase gives every durable page its own task, implementation ships
  the page with the code, and the archive phase refuses to fold a change whose
  decisions and surfaces were never written down. Only `specs/` still waits
  for the archive. An already-installed repository reports `upgrade_required`
  and the existing Upgrade action adds the directories without touching
  anything the repository edited.

### Fixed

- Any turn in which `stepfun:step-5-preview` called a tool died on a schema
  error before the call could run. StepFun sends `type: ""` on the chunks that
  continue a streaming tool call, where the shared OpenAI-compatible schema
  accepted only `"function"` or nothing at all. The kind of a tool call is
  never read — the call is assembled from its index, id and function — so the
  field is now a plain string on the way in, for the non-streaming shape as
  well. What EvoFlux sends is unchanged.
- A StepFun model cost nothing to run on a Step Plan row and something on the
  open platform, for identical tokens against identical weights. models.dev
  leaves `cost` off a subscription row — a plan seat buys a quota, not tokens
  — and StepFun's two `step_plan` rows are the only blank ones in the whole
  catalogue. They now inherit the vendor's own API rates, which is the number
  EvoFlux already reports for every other subscription it meets. A model only
  a plan row lists, such as `step-router-v1`, stays unpriced rather than
  borrowing a rate nobody published. StepFun's China plan row also counts as a
  variant of the curated provider now, so `step-router-v1` arrives with its
  real name and limits instead of as a bare model ID.
- The Agent Spec-Driven board showed only the repository a session opened on,
  so a Coding project whose changes live in a sibling repository reported an
  empty board — and the panel hid it entirely behind setup until *every*
  repository was installed. The board now lists the changes of every
  repository in the project, filters by repository and names the owner of each
  change, reads and actions a change through the repository it lives in, and
  treats the repositories still to set up as a banner rather than a wall.
- The Overview panel described the repository a Coding session opened on as
  though it were the whole project — one branch, one set of changes, no sign
  the others existed. It now names the repository it is describing and, in a
  project, lets the reader switch between them.
- Context compaction could not shrink a long session. The summariser replayed
  the raw transcript while ordinary turns send one with old tool results
  projected to receipts, so its request was about twice the size of the turn
  that triggered it — a 404K-token compaction call plus a 30K output cap
  against a 262K window, rejected with `context_length_exceeded` on all 137
  attempts in one session while the context grew to 950 messages. Compaction
  now sends the same projected prefix an ordinary turn sends, is budgeted
  against the model's window (with the summary's own cap clamped to a quarter
  of it), retries smaller when the endpoint rejects it anyway, and stops
  attempting every turn once it has failed three times in a row.
- Turn token totals counted a model call once per streaming chunk when the
  provider restated the call's usage on every chunk, which StepFun does: a
  33-minute session reported 1.87 billion tokens. A call's usage is now
  folded across its chunks and recorded once, when the call ends, and a
  cache figure that appears on only one chunk is no longer lost.

## [2.0.5] - 2026-09-19

### Fixed

- Fixed plugin uninstall and update failures on Windows caused by access
  restrictions during replacement.
- Normalized Windows extended-length workspace paths before sending them to
  the sidecar and frontend API clients.
- Fixed portal popups being misclassified as title-bar drag regions.
- Restored the lead agent transcript in Agent view mode.

### Improved

- Added multi-folder selection and parent-directory opening to Coding projects.
- Allowed new ASDD changes from multi-repository Coding projects to target a
  selected repository.
- Simplified team activity UI wiring and clarified turn loading feedback.

## [2.0.4] - 2026-09-17

### Changed — EASD is now ASDD, and a change lives in the repository

EASD (Evo Agent Specification-Driven Development) is replaced by **ASDD — Agent
Specification-Driven Development**, built on OpenSpec's file model. A change is
a folder of Markdown under the repository's catalogue: its phase is the `status`
in `proposal.md`, its contract is the delta under `specs/<capability>/spec.md`,
and its identity is the folder's name.

- Removed content-hash binding. No operation restates a `content_hash`,
  `spec_hash`, `plan_hash` or `expected_hash`. Verification still
  content-addresses its own result cache, which nobody has to carry.
- Removed session binding. `trace_runs.session_id` and its one-run-per-session
  unique index are gone; any Coding chat can run any phase of any change, and
  several chats can work on one change.
- Dropped the five `trace_*` tables. `delegation_tasks.trace_run_id` becomes
  `asdd_change_id`, a slug rather than a foreign key.
- Replaced `/api/easd/*` and the hidden `/api/trace` alias with `/api/asdd/*`,
  addressed by change slug and capability.
- Replaced the five `easd-*` Skills with six `asdd-*` Skills, one per phase of
  the Agent-Driven Development cycle. They write Markdown with the ordinary file
  tools; there are no typed submission tools.
- Kept the driven UI: the board, the action rail and the human approval gates
  for proposal, specs, design and tasks.

### Added — Autopilot

A change can carry `autopilot: true` in its own `proposal.md`, and the agent
then decides at each gate whether a person is actually needed.

- What the agent clears is recorded under `auto_approvals`; `approvals` stays
  the user's signature and only the approve endpoint writes it. The panel draws
  the two differently, so a reader can see which gates a person read.
- An agent that wants a decision writes a `hold` naming the gate and the
  reason. The rail shows it above everything else, approving clears it, and it
  suspends autopilot everywhere rather than only at that gate.
- Autopilot carries implementation and verification too. Those are not gates,
  so the agent finishes the phase and advances `status` itself. The rail leads
  with **Continue** throughout and keeps the manual actions beside it. It stops
  at `ready` — archiving is a person's click at every risk tier.
- `cross_layer` and `critical` keep the design gate and the archive for the
  user regardless. Archiving is refused when a reserved gate was cleared by
  autopilot rather than signed.
- `POST /api/asdd/changes/{change_id}/autopilot` toggles it; `POST
  .../actions/autopilot_continue` runs the phase after the current gate.

### Added — every phase Skill ships its output contract

Each `asdd-*` Skill now installs a `TEMPLATE.md` beside its `SKILL.md`: the
exact shape of what the phase produces, and what gets it rejected. A Skill says
how to think about a phase; its template says what the phase has to leave
behind.

- Replaces three shipped templates (`design.md`, `tasks.md`, `spec.md`) that
  nothing ever read and that never reached a repository. Only `proposal.md`,
  which the product itself seeds, remains central.
- Every Skill gained a **Tools** section naming the tools that phase actually
  needs — `ask_user`, `todo_manage`, `shell`, `lsp_*`, `code_context` — instead
  of describing `code_context` alone.
- A repository installed before this reads as `upgrade_required` until setup is
  re-run.

### Changed — a new change asks for three things

The create form takes a **title**, the **problem**, and **what should be true
when it is done**. The slug, the capabilities and the risk tier moved behind a
disclosure and are derived by the propose phase when left blank. Nobody can
tier a change they have not read, and the tier decides whether it owes a design
and an independent review.

- `problem` and `outcome` are written into `proposal.md` under `## Why` and
  `## What Changes` — the file the propose phase reads — rather than stored
  beside the change as a second description that could go stale.
- `risk` is now **omitted** from the front matter rather than defaulted to
  `standard`, and **the proposal gate refuses until something sets it**. An
  unset tier used to silently mean "no design required".

### Changed — open questions are asked, not filed

New rule 7, **Ask; do not defer**. A phase that meets a question it cannot
answer from the repository calls `ask_user` and records the answer; writing the
question into a document and carrying on was making the decision silently.

- `design.md` gained a `## Decisions` section for answers, and its
  `## Open questions` section now means *unresolved*.
- **The design gate refuses a `design.md` that still lists open questions**, and
  the blocker names them. Under autopilot an unanswered question is a `hold`.

### Added — the capability catalogue is reachable from the panel

The counts in the Changes header open a Catalogue view: every
`specs/<capability>/spec.md` the repository contracts today, and the archived
changes that produced them. The spec endpoints existed but nothing rendered
them.

### Changed — the product surface is now **Agent Spec-Driven**

Renamed from "Agent Specs". The method keeps its name, Agent
Specification-Driven Development. A repository installed under the old name
reads as `upgrade_required` rather than `invalid`, and Reinstall rewrites the
manifest — the manifest is not broken, it was written by an older build.

### Fixed — an end-to-end sweep of every ASDD surface

- **A hand-edited `status` returned `500` and blanked the whole list.** The
  response model enforced the twelve-value Literal, so an unrecognised status
  failed validation before `declared_status_problems` could report it — taking
  every other change in the repository down with it. `status` and `risk` are
  plain strings on the way out now; the requests keep their Literals. The panel
  shows the value verbatim, the rail says it is not a phase it knows, and the
  board gained an **Unrecognised** column so the change does not silently
  vanish from it.
- **Archiving needed one evidence page, not evidence.** A change contracting
  five requirements archived on a single unrelated page, and a page citing a
  requirement name that did not exist counted the same. Every requirement a
  delta adds or modifies now needs a page naming it, and a `failed` result
  blocks. `inconclusive` still passes — the archive report names them.
- **A delta for a capability the proposal never named was folded silently.**
  Archiving contracts every delta it finds, so the specs gate now refuses one
  the proposal does not name.
- At `implementing` the rail led with **Run verification**, which is blocked
  until every task is ticked, so arriving at the phase showed a highlighted
  button that refused to run. It now leads with **Run implementation** and
  flips once the checklist is done. A blocked action that is not the primary
  one now carries its blocker as a tooltip.
- A title is no longer validated as though it were already a slug. `Add PDF
  export!!` and `Thêm tìm kiếm ghi chú` now derive `add-pdf-export` and
  `them-tim-kiem-ghi-chu`; a title with no Latin form asks for an explicit
  change id, and the New change form shows the folder before creating it.
- An evidence page written the way `asdd-verify` documents it — with an
  unquoted `recorded:` timestamp — returned `500` for the whole change, because
  YAML types that as a `datetime`. Front matter scalars now read back as the
  text the page meant.
- Approving an artifact is refused unless the change is standing at that gate.
  A new change carries a proposal template, and an existence check alone let an
  untouched one through the proposal gate.
- The panel opens a repository that is set up even when a sibling in the same
  Coding project is not. A catalogue belongs to one repository.

### Upgrade notes

- Migration `00000065` drops the `trace_*` tables. Existing EASD runs are not
  migrated — their state has no equivalent in a file-based catalogue.
- Revisions `00000055`, `00000060`, `00000061` and `00000062` are removed: they
  existed only to build those tables. A database stamped with one of them is
  moved to `00000054` before any migration runs — by the server's automatic
  upgrade, `make migrate` and a bare `alembic upgrade head` alike — and migrates
  forward from there to the same schema. Nothing is lost, because `00000065`
  drops everything those revisions created.
- Re-run setup from the Agent Spec-Driven panel to install `.evoflux/asdd/` and the
  `asdd-*` Skills. Setup writes what is missing and leaves existing files alone.

## [2.0.3] - 2026-09-15

EvoFlux 2.0.3 is a maintenance release focused on updater feedback, coding
skill routing and EASD workspace correctness.

### Highlights

- Added visible updater progress and actionable failure states, including
  recovery that leaves the desktop window usable after a failed update.
- Consolidated thirteen overlapping coding skills into four routing hubs:
  `coding-change`, `coding-investigate`, `coding-operate` and `coding-verify`,
  with refreshed references, eval coverage and loader behavior.
- Centralized observation limits in the new skill hubs so browser and coding
  workflows share consistent context-budget rules.
- Fixed EASD runs so their workspace follows the run context instead of being
  incorrectly pinned to a linked chat request.

### Upgrade notes

- Application, Python, web, Rust, Tauri and lockfile metadata are synchronized
  at `2.0.3`.
- Existing databases continue through the normal Alembic migration path; no
  schema migration is introduced by this release.

For the curated release overview, see
[`documents/releases/v2.0.3.md`](documents/releases/v2.0.3.md).

## [2.0.2] - 2026-09-15

EvoFlux 2.0.2 is a maintenance release focused on deeper WebBridge browser
inspection and more reliable browser interaction workflows.

### Highlights

- Added WebBridge scraping inside a selected element and across shadow roots
  and frames, with `extract_elements` ref/deep traversal controls.
- Added selector/ref-aware scrolling for nested scroll containers through
  `scroll_to_bottom`.
- Added stable element-handle actions, changed-only snapshots, batched action
  chains and broken-chain recovery for WebBridge browser automation.
- Included browser preview handoff, resize/placement, dialog/permission and
  workbench ownership fixes from the 2.0.1 follow-up cycle.

### Upgrade notes

- Application, Python, web, Rust, Tauri and lockfile metadata are synchronized
  at `2.0.2`.
- Existing databases continue through the normal Alembic migration path; no
  schema migration is introduced by this release.

For the curated release overview, see
[`documents/releases/v2.0.2.md`](documents/releases/v2.0.2.md).

## [2.0.1] - 2026-09-14

EvoFlux 2.0.1 is a focused maintenance release for browser workflows, the
Problems panel, and EASD portability.

### Highlights

- Added a complete browser viewing flow: detached pages, drag-to-resize
  previews, device and layout controls, per-site zoom, download history,
  explicit loading/error states, and browser shortcuts that return to the
  panel.
- Made Problems actionable: filters now describe their scope, counts match
  visible results, severity is read correctly, decisions survive restarts,
  dismissed items can return, sending to chat preserves the draft, and fixed
  problems leave the active list.
- Improved Evo Agent Specs import and removed stale EASD documentation
  artifacts so repository-backed methodology stays portable and current.
- Hardened desktop webview capability scoping and remembered workbench posture
  across restarts.

### Fixed

- Browser dialogs and questions now reach the right panel, including detached
  pages and ownership changes.
- Landscape emulation no longer rotates to portrait, and reset restores the
  real browser window properties.
- Work mode has a usable starting surface and the browser preview stays within
  its available desktop layout.
- Problems no longer report incorrect counts, pluralization, severity, or
  stale repository state.

### Upgrade notes

- Application, Python, web, Rust, Tauri, and lockfile metadata are synchronized
  at `2.0.1`.
- This is a backward-compatible maintenance update on the 2.0.0 baseline.
- Existing databases continue through the normal Alembic migration path.

For the curated release overview, see
[`documents/releases/v2.0.1.md`](documents/releases/v2.0.1.md).

## [2.0.0] - 2026-09-14

EvoFlux 2.0.0 is a major workbench, provider, browser, telemetry, and
organization-governance release built on the first stable baseline.

### Highlights

- Added the Evo Conductor client foundation: authenticated realtime resource
  updates, resilient reconciliation, credential recovery, delivery notices,
  registry integration, inventory, and privacy-safe telemetry fields.
- Rebuilt multi-session workbench behavior so terminals, browsers, files, and
  docked tools survive session switches while background work remains visible.
- Introduced a declarative provider and model-capability layer with runtime
  catalog refresh, accurate thinking-level validation, subscription pricing,
  Xiaomi MiMo support, and more cache-efficient Codex request continuity.
- Expanded browser automation with authenticated WebSocket routes, stable
  element references, selected-browser routing, safer reconnect ownership, and
  workspace development-server launch controls.
- Added measurable context-window controls, per-turn token and cost reporting,
  cache-state telemetry, model-stacked consumption charts, and service-tier
  reporting.
- Refined Evo Agent Specs with portable session rebinding, execution options,
  code-context contracts, measured verification commands, and more reliable
  single-agent convergence.

### Added

- Per-team `ask` or `auto` spawn policy and clearer streaming activity phases.
- Document and HTML preview improvements, including JavaScript execution for
  trusted local previews and direct access to newly generated artifacts.
- Self-healing diagnostics, broader managed language-server availability, and
  richer file explorer actions.
- A unified appearance system with a real accent palette and the new Clay
  default theme.

### Changed

- Reworked transcript scrolling around browser-native anchoring and retained
  recently visited sessions for faster switching.
- Consolidated telemetry under Settings and aligned Conductor payloads with the
  fields the control plane actually persists.
- Replaced duplicated provider configuration and capability logic with one
  shared declarative registry.
- Reduced prompt churn and skill-catalog overhead to improve prefix-cache reuse.
- Changed sandbox out-of-scope handling from an unconditional hard block to a
  visible audit warning while retaining explicit permission boundaries.

### Fixed

- Hardened browser bridge authentication, reconnect recovery, panel ownership,
  element lifetime, selected-browser routing, and Linux/Windows edge cases.
- Fixed empty-window telemetry crashes, request pricing, context-limit
  discovery, model availability, and provider turn ordering after compaction.
- Repaired widget sizing and lost-delta recovery, document reopening, CJK IME
  visibility, background process polling, and multi-session tab cleanup.
- Improved EASD portability, verification trust, migration reconciliation,
  session rebinding, and stale-state recovery.
- Strengthened web-fetch DNS-rebinding protection and private-network guards.

### Upgrade notes

- Product, Python, web, Rust, Tauri, and lockfile versions are synchronized at
  `2.0.0`.
- Existing application databases continue through the normal Alembic migration
  path; back up important workspaces before upgrading a production install.
- This release changes provider, workbench, browser, and Conductor integration
  internals. Validate organization-managed resources and browser workflows
  after upgrading.
- Linux direct browser input continues to require X11/XWayland.

For the curated release overview, see
[`documents/releases/v2.0.0.md`](documents/releases/v2.0.0.md).

## [1.0.0] - 2026-08-27

EvoFlux 1.0.0 is the first stable release.

### Highlights

- Introduced Evo Agent Specs (EASD), a repository-backed specification-driven
  workflow with guided actions, phase retry, review handoff, real-time events,
  traceability, recovery, and local runtime data.
- Expanded agent-team workflows with explicit mode-lead team selection and
  safer delegation and handoff behavior.
- Added QwenCloud support and optimized prompt-cache request shaping across
  supported Anthropic, Bedrock, Codex, DeepSeek, Gemini, OpenAI-compatible,
  OpenRouter, and xAI provider paths.
- Expanded code-graph coverage and hardened language parsing across the primary
  and extended parser set, while isolating and caching index builds.
- Improved Coding workspace navigation, multi-repository chat setup, transcript
  preload/rendering, and request-ingress feedback.

### Added

- Repository knowledge-base initialization, portable EASD project contracts,
  durable trace records, and scoped memory.
- Shared browser-tool result plumbing and richer workbench integration.
- Separate context and turn usage totals for clearer token accounting.

### Changed

- Standardized web selection controls and improved command-message
  presentation.
- Removed the aggregate skill-bundle size limit and reduced built-in skill
  catalog overhead.
- Retired the non-executable terminal agent tool in favor of executable process
  and approved tool paths.
- Reorganized contributor and product documentation under `documents/`.

### Fixed

- Hardened SQLite concurrency, foreign-key repair, migration reconciliation,
  runtime teardown, and cleanup behavior.
- Repaired graph API schemas and numerous code-graph parser edge cases.
- Fixed coding repository visibility, chat working state, plugin scaffolding,
  and overlapping lead selectors.
- Improved outbound redaction and prompt finalization before summarization.

For the curated release overview, see
[`documents/releases/v1.0.0.md`](documents/releases/v1.0.0.md).

[2.0.9]: https://github.com/evoelsewhere/evoflux/compare/v2.0.8...v2.0.9
[3.0.0]: https://github.com/evoelsewhere/evoflux/compare/v2.0.9...v3.0.0
[3.0.1]: https://github.com/evoelsewhere/evoflux/compare/v3.0.0...v3.0.1
[3.0.10]: https://github.com/evoelsewhere/evoflux/compare/v3.0.9...v3.0.10
[3.0.2]: https://github.com/evoelsewhere/evoflux/compare/v3.0.1...v3.0.2
[2.0.8]: https://github.com/evoelsewhere/evoflux/compare/v2.0.7...v2.0.8
[2.0.7]: https://github.com/evoelsewhere/evoflux/compare/v2.0.6...v2.0.7
[2.0.6]: https://github.com/evoelsewhere/evoflux/compare/v2.0.5...v2.0.6
[2.0.5]: https://github.com/evoelsewhere/evoflux/compare/v2.0.4...v2.0.5
[2.0.4]: https://github.com/evoelsewhere/evoflux/compare/v2.0.3...v2.0.4
[2.0.2]: https://github.com/evoelsewhere/evoflux/compare/v2.0.1...v2.0.2
[2.0.3]: https://github.com/evoelsewhere/evoflux/compare/v2.0.2...v2.0.3
[2.0.1]: https://github.com/evoelsewhere/evoflux/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/evoelsewhere/evoflux/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/evoelsewhere/evoflux/compare/v0.0.8...v1.0.0
