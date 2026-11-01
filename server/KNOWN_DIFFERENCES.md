# Known differences between the Rust server and Python

Each entry is a place where the Rust port cannot or deliberately does not match
Python. Entries need owner approval.


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

- **Check, then open.** `validate_path` resolves a path and the tool opens it
  afterwards, and `grep` checks `permits_link` before it opens a file. Another
  process that keeps swapping a folder between a real folder and a link to
  outside the workspace can win that race (reproduced on Windows with a junction
  swap: `read d/secret.txt` returned the outside file after a few tries). Python
  validates and then opens in the same way, so this matches Python; no handle-based
  recheck without a new dependency.
- **Hard links.** A hard link inside the workspace to a file outside it, or to
  `.env`, reads as an ordinary file; only symlinks and reparse points are judged.
- **Metadata of link targets.** `ls` shows the size of a file behind a link that
  leads outside, and `glob` lists such files; their contents are not read.

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
- **Deny patterns.** Rust applies the built-in defaults (`**/.env`, `**/.env.*`).
  A user's own `sandbox.yaml` `denied_patterns` are not read, so a pattern the user
  added is not enforced by these tools until `ToolCtx` can carry them.
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
- **Same as Python, on purpose.** The session `workspace` comes from the request
  form (a user choice) and is created if missing, only after the lead and
  running-turn checks; Python creates it before them. Neither Python nor the Rust
  gateway checks `Origin` or `Host` on state-changing requests (Python only adds
  `CORSMiddleware` with `CORS_ORIGINS = ["*"]`), so a page the user opens in a
  browser can post to `/api/team/chat` with any workspace. The step limit per
  turn is Python's `MAX_AGENT_ITERATIONS` (5000).
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
