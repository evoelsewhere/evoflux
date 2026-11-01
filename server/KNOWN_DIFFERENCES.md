# Known differences between the Rust server and Python

Each entry is a place where the Rust port cannot or deliberately does not match
Python. Entries need owner approval.


## providers (AR1, `server/crates/area-providers`)

- **No models.dev catalog.** Thinking fields, budgets and service tiers follow Python's path for a model the catalog has no row for: fallback levels per dialect, budgets from the ceilings alone, and `service_tier` forwarded as is. For a model the catalog does describe, Python may clamp levels, size budgets from the model's output limit or apply a catalog tier patch.
- **Providers in scope.** `router9`, `xiaomi`, `cliproxy`, `mistral`, `cohere`, `groq`, `cerebras`, `together`, `deepinfra`, `sambanova`, `perplexity` and `vercel`. Other registry IDs are `ProviderError::NotPorted`. Unknown IDs get Python's "Unsupported provider" message without a catalog or plugin lookup.
- **Settings are a snapshot.** Python reads `os.environ` at call time, so keys saved in Settings → Providers apply without a restart. Rust reads the `Settings` it is given. Like Python, a `.env` file only sets the fields `app/core/config.py` declares; other provider variables (`MISTRAL_API_KEY`, `GROQ_BASE_URL`, ...) come from the process environment alone.
- **Event shape.** The assembled tool call carries parsed JSON arguments (an empty string becomes `{}`) where Python keeps the string. `Done.finish_reason` is `""` when the provider sent none. Python's `cache_probe` diagnostics are not ported.
- **Size caps.** Python buffers without limit. Rust ends a stream with `ProviderError::TooLarge` (not retried) when one SSE line passes 16 MiB, one tool call's arguments pass 16 MiB, the arguments of all tool calls in one response pass 32 MiB, or a response has more than 128 distinct tool calls, and keeps only the first 64 KiB of an error body (after gzip decoding), decoded as lossy UTF-8 instead of by the response charset.

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
