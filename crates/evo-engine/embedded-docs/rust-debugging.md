# evo Rust Extension and Agent Debugging Guide

This document covers two main topics: **how to write Rust `cdylib` extensions** (the unified C ABI, tool lifecycle,
event handlers, resource discovery, providers/renderers), and **how to debug agents and extensions** (event log,
dev host, system prompt inspection, locating common failures). For the default layout of a complete Agent project, see the `agent` topic in `docs`.

## 1. Rust Extension Quick Start

The minimal working extension is a Rust `cdylib` crate that depends only on `evo-plugin-sdk`:

```bash
cargo new my-evo-extension
cd my-evo-extension
# In Cargo.toml, set crate-type to ["cdylib", "rlib"]
```

```toml
[package]
name = "my-evo-extension"
version = "0.1.0"
edition = "2021"
license = "MIT"

[lib]
crate-type = ["cdylib", "rlib"]

[dependencies]
evo-plugin-sdk = "0.8"
serde_json = "1"
```

**Extension boundary rule**: a `cdylib` depends only on `evo-plugin-sdk`. Never link `evo-cli`,
`evo-extensions`, or harness-internal crates: plugins are loaded dynamically by the host; the host links the plugin,
and the plugin must not link back to the host. `rlib` is kept so that Rust unit tests can be written in the same crate.

The repository's bundled `examples/plugin-stub` is a complete, runnable template containing three capabilities (an echo tool, an event
handler, and resource discovery), and is the preferred source to copy the skeleton from.

## 2. Unified ABI Entry Point

The host loads only the unified C ABI symbol `evo_plugin_register`. Extensions use `export_plugin!`,
register capabilities through a single `PluginApi`, and call `api.declare` to declare priority/platforms.
The SDK checks `abi_version` and `struct_size` before registration; if incompatible, it returns a non-zero status and the host reports a load failure.

```rust
evo_plugin_sdk::export_plugin!(|api| {
    if let Some(declare) = api.declare {
        let status = declare(evo_plugin_sdk::StbStringRef::from_str(
            r#"{"priority":60,"platforms":["linux"]}"#,
        ));
        if status != 0 {
            return status;
        }
    }
    let Some(register_tool) = api.register_tool else {
        return -1;
    };
    // Build the StableToolSchema and the execute/poll/cancel/destroy function table,
    // then call register_tool. See examples/plugin-stub for a complete implementation.
    let _ = register_tool;
    0
});
```

The `declare` JSON supports `priority` (a number; higher runs earlier) and `platforms` (an array of strings,
such as `["linux","windows","macos"]`); when dispatching event handlers, the host skips those whose platforms do not match.

### Capability Detection

Every registration slot is an `Option`. Before registering, check whether the vtable slot is `Some`; if it is missing, return a
clear error and degrade gracefully. Do not panic, dereference a null pointer, or rely on `undefined` semantics. For an unknown
runtime action ID, the host returns a structured error and does not dispatch it.

## 3. Tool Lifecycle: execute -> poll -> cancel -> destroy

Each tool exports four `extern "C"` functions, which the host drives according to a fixed protocol:

- `execute(tool_call_id, params, free_params) -> StepHandle`: parses the JSON passed in by the host
  (an owned `StbString`, freed with `free_with(free_params)`) and creates a handle specific to this call
  (usually `Box::into_raw(Box::new(State))`).
- `poll(handle, partial_cb, user_data) -> StepResult`: **must be non-blocking**. If not finished, return
  `StepResult::pending(progress)`; when finished, return `StepResult::done(result)`;
  on failure, return `StepResult::err(message)`. `partial_cb` is called synchronously within poll.
- `cancel(handle)`: sets a thread-safe cancellation flag. **Must be idempotent and must not free the handle**.
- `destroy(handle)`: called exactly once by the host at the end; frees the handle with `Box::from_raw`. Must be a no-op for a null pointer.

Key points of the ownership protocol:

- A `StbString` produced by the host (execute's params, event payloads) is freed by the **plugin** through the
  host-provided `free_string`.
- A `StbString` produced by the plugin (done results, partial progress, resources_discover's out)
  is freed by the **host** through the `plugin_free_string` the plugin provided at registration.
- No `extern "C"` boundary may unwind: the plugin uses `catch_unwind` internally and converts panics into
  structured error results.

```rust
extern "C" fn my_execute(
    _tool_call_id: StbStringRef,
    params: StbString,
    free_params: Option<FreeStringFn>,
) -> StepHandle {
    let text = params.to_string_lossy();
    params.free_with(free_params);
    let state = Box::new(MyState { input: text, done: false });
    Box::into_raw(state) as StepHandle
}

extern "C" fn my_poll(
    handle: StepHandle,
    _partial_cb: Option<ToolPartialCb>,
    _user_data: *mut c_void,
) -> StepResult {
    let state = unsafe { &mut *(handle as *mut MyState) };
    if !state.done {
        state.done = true;
        return StepResult::pending(StbString::empty());
    }
    StepResult::done(StbString::from_string(
        r#"{"content":[{"type":"text","text":"ok"}]}"#.to_string(),
    ))
}

extern "C" fn my_cancel(_handle: StepHandle) {}

extern "C" fn my_destroy(handle: StepHandle) {
    if !handle.is_null() {
        unsafe { drop(Box::from_raw(handle as *mut MyState)) };
    }
}
```

See `examples/plugin-stub/src/lib.rs` for the complete template. When creating a new tool, copy the lifecycle skeleton and
replace only the parameter schema and domain logic; do not redesign the ownership protocol.

## 4. Event Handlers, Resource Discovery, and Providers

### Event Handlers (36 Event Categories)

Subscribe by `EventTag` via `api.register_event_handler`. Events fall into three broad groups:

- **Session lifecycle**: `SessionStart`, `SessionBeforeSwitch`, `SessionBeforeFork`,
  `SessionBeforeCompact`, `SessionCompact`, `SessionShutdown`, etc.
- **Agent loop**: `BeforeAgentStart`, `AgentStart`, `AgentEnd`, `AgentSettled`,
  `TurnStart`, `TurnEnd`, `MessageStart`/`MessageUpdate`/`MessageEnd`,
  `ToolExecutionStart`/`Update`/`End`, `ToolCall`, `ToolResult`, `UserBash`, `Input`.
- **evo-specific / UI**: `BeforeTuiStart` (before TUI initialization), `UiPromptStart`/`UiPromptEnd`
  (when an interactive prompt blocks the agent).

Handlers receive a `StablePluginEvent` and **must not free** the strings in the event (the host frees them all after the
fan-out). Return `0` for success; return `EVENT_HANDLER_ABORT` to veto.

### Lifecycle Veto (P1)

`BeforeTuiStart` is an evo-specific hook with veto semantics: the first handler that returns
`EVENT_HANDLER_ABORT` **aborts startup**, and the CLI exits with exit code `3` and prints the reason
(for scenarios such as "an external connection must be established before entering the TUI"). A veto from `SessionStart` / `SessionShutdown`
is only advisory: headless mode prints a warning, and it is ignored at shutdown. Event dispatch has a timeout,
so a slow handler cannot block the main flow indefinitely.

### Resource Discovery

`api.register_resources_discover` registers a handler. On `startup` / `reload`, the host
fans out to all registered handlers and merges the returned `{skillPaths, promptPaths, themePaths}`.
An error from a single handler does not abort the fan-out. `out` is a plugin-owned `StbString`, which the host reclaims through the
`plugin_free_string` the plugin provided at registration.

### Providers and Renderers

`api.register_provider` injects a custom LLM provider (`provider_id` / `base_url` /
`api_style` + `request_fn`). `register_message_renderer` /
`register_markdown_transformer` / `register_entry_renderer` register message rendering capabilities;
the host accepts a `{text, lines}` component envelope. Any of these slots may be `None` and must be checked before use.

## 5. Developing with `evo dev`

Run in the extension crate directory:

```bash
evo dev
```

evo identifies the current `cdylib` via Cargo metadata, places a versioned copy in the workspace's
`.evo/extensions/.dev/` after the first build, starts the normal TUI, and watches `src/`, `build.rs`, the package/workspace
`Cargo.toml`, and `Cargo.lock`. Source changes trigger an automatic rebuild and hot reload; if a build fails, the currently loaded
version is kept. In the TUI, `/reload` forces a rebuild and then reloads.

A multi-extension workspace must explicitly select a package:

```bash
evo dev --package evo-todo
evo dev -P evo-webfetch
evo dev --release
evo dev --no-watch
evo dev --package evo-todo -- --model gateway/model
```

To debug a single extension, use `evo dev-local` (equivalent to `evo dev --local-only`): it loads only the currently built
extension and the skills/prompts that extension discovers, without scanning global extensions, installed Evo packages, or other project resources,
to avoid interference from commands with the same name. Without a cdylib, it degrades gracefully to skills-only mode. On Windows, a loaded
DLL cannot be overwritten in place, so do not manually copy the Cargo target DLL; versioned staging switches over safely.

## 6. Agent Debugging: Event Log

### Enabling the Event Log

```bash
export EVO_EVENT_LOG=1
evo            # any run records extension event handler invocations
```

By default, the log is written to `~/.evo/logs/events.jsonl` (when `EVO_CODING_AGENT_DIR` is set, it is written under `logs/` in that
directory's parent; `EVO_EVENT_LOG_PATH` overrides it explicitly). When disabled, there are zero disk writes and zero overhead.

To view the log location and follow it live:

```bash
evo events path        # print the event log path
evo events tail        # print existing content and keep following (Ctrl+C to stop)
```

Each JSON line contains `ts_ms` (Unix milliseconds), `event` (such as `BeforeTuiStart` /
`MessageEnd`), `plugin` (the extension's display name), `result` (`Continue` / `Error` / `Abort` /
`Timeout` / `Panic` / `JoinFailed`), `duration_ms`, and an optional `detail`. Use it to answer questions such as
"why didn't my extension run?".

### Request, Context, and Frame Writer Diagnostics

When investigating "model requests are slow", "context building takes a long time", or "streaming progress writes are blocking", you can temporarily enable
stderr diagnostics. Both switches are enabled only when the value is set and is not the string `0`; they do not write logs to the session
file and do not change the normal persistence format:

```bash
EVO_AGENT_DIAGNOSTICS=1 EVO_FRAME_DIAGNOSTICS=1 evo -p "reproduce the issue" 2>evo-diagnostics.log
```

PowerShell:

```powershell
$env:EVO_AGENT_DIAGNOSTICS="1"
$env:EVO_FRAME_DIAGNOSTICS="1"
evo -p "reproduce the issue" 2> evo-diagnostics.log
```

- `EVO_AGENT_DIAGNOSTICS` outputs nanosecond timings for context building, assistant request conversion/stream setup, tool execution, and
  session entry/record/batch append; each model request line starts with
  `EVO_AGENT_DIAGNOSTICS`, and each tool line starts with `EVO_TOOL_DIAGNOSTICS`.
- `EVO_FRAME_DIAGNOSTICS` applies only to the assistant frame writer of persisted sessions, and outputs an `EVO_FRAME_DIAGNOSTICS`
  summary during cleanup at the end of the run. Focus on `batch_records`,
  `append_records_calls`, `flush_requests`, `writer_failures`, and the various flush barriers.
- By default, the frame writer aggregates at most 32 records, or waits about 50 ms, before writing; a flush is forced when committing an assistant entry
  and before/after cleaning up a stream/run. The `*_ns` values in the diagnostics are cumulative times and must not be taken directly as single
  wall-clock latencies or throughput benchmarks.

These diagnostics are only for reproduction and localization, and may contain metadata such as tool names, call IDs, and session size; do not
commit full stderr containing sensitive provider responses directly to the repository. When the switches are not enabled, these
diagnostic lines are not output.

### System Prompt and Resource Inspection

```bash
evo --debug-system-prompt   # print each section of the final resolved system prompt to stderr
evo --list-models           # list available models (optionally with a fuzzy search term)
evo --verbose               # show startup warnings (such as ignored flags)
```

`--debug-system-prompt` shows skills, prompts, package resources, and counts; it is the direct path for investigating
"why a resource does not appear on the welcome screen".

### Credential and Provider Debugging

```bash
evo auth check                          # report any available auth source (no network access)
evo auth check --provider gateway --json
```

When an API call errors, keep the diagnostic text returned by the provider, and first check the endpoint, auth headers, and model ID.

### Session Export

```bash
evo --export session.jsonl      # export a JSONL session to HTML for easier review
```

## 7. Remote Mode Debugging

```bash
evo --server --port 9899        # headless server; prints a token at startup
evo --connect 127.0.0.1:9899 --token <token>   # remote TUI client
```

The client is pure input/display, with no local providers, tools, extensions, or session files; all agent
work happens on the server. Debugging tips:

- Server logs (`--verbose`) show startup warnings; the event log (`EVO_EVENT_LOG=1`) is enabled in the server
  process; follow it with `evo events tail` on the same machine.
- The client can use `/state` (current model/thinking/tools), `/model <id>`, `/thinking <level>`, and
  `/tools` to inspect session state.
- In remote mode, `/tree`, `/fork`, `/switch`, `/export`, `/name`, and `/reload` are unavailable
  (they depend on the local harness) and produce an explicit "not supported" message.

### Key Diagnostics (Phone / Remote Terminal)

Phone clients, IMEs, and SSH gateways each encode "Enter" differently. When something goes wrong, first look at the **raw key events
that reach the TUI**; do not guess. Setting `EVO_DEBUG_KEYS` appends all key events (including the Enter decision result)
to a log:

```powershell
# Windows: in the session the phone SSHed into
$env:EVO_DEBUG_KEYS=1; evo
```

```bash
# Unix / Termux
EVO_DEBUG_KEYS=1 evo
```

By default it writes to `<temp dir>/evo-keys.log` (`%TEMP%\evo-keys.log` on Windows); you can also specify a file with
`EVO_DEBUG_KEYS=<path>`. Format:

```text
2026-09-24T12:00:01.234Z --- evo TUI key trace start pid=4321 TERM=xterm-256color raw_mode=true ---
2026-09-24T12:00:01.235Z code=Char('h') mods=NONE kind=Press
2026-09-24T12:00:01.236Z code=Enter mods=NONE kind=Press
2026-09-24T12:00:01.236Z enter-decision -> newline (paste burst) gap_ms=1 more_queued=false
```

Use these clues to diagnose:

| Log | Meaning | Resolution |
| --- | --- | --- |
| `code=Char('j') mods=CONTROL` (or `Char('\n')`) | The client sent Enter as **LF (0x0A)**. In raw mode, crossterm treats LF as Ctrl+J, and Ctrl+J is bound to "insert newline" (matching evo's `tui.input.newLine`) | **Fixed**: `Editor::handle_key` now treats unmodified `Char('\n')`/`Char('\r')` as submit, while `Ctrl+J` (`Char('j') + CONTROL`) still inserts a newline |
| `code=Enter mods=NONE` + `enter-decision -> newline (paste burst)` | A normal CR was received, but the client sent "text + Enter" as a single batch, and the paste heuristic (20ms burst window) misjudged it as a paste | **Fixed**: the paste heuristic is kept only on Windows (`cfg!(windows)`). On Unix, bracketed paste handles real pastes via `Event::Paste`, and a plain Enter submits directly |
| `code=Enter mods=NONE` + `enter-decision -> submit` | The input path is fine; the problem is not in the key layer | Check the session/network layer |
| No `code=` lines at all | Keys never reached the TUI | The client is not connected, the window is not focused, or `EVO_SKIP_STDIN` is set |

## 8. Locating Common Failures

| Symptom | What to check |
| --- | --- |
| Extension not loaded | `cdylib` crate-type? Platform matches? Use `--extensions-dir` to point to the build output directory; make sure `--no-extensions` is not accidentally enabled |
| Tool not registered | ABI version negotiation failed? vtable slot is `None` (not implemented by the host)? Registration returned non-zero? |
| Event handler not firing | `EVO_EVENT_LOG=1` + `evo events tail` to check for `Abort`/`Panic`/`Timeout` |
| Startup aborted | An extension returned `EVENT_HANDLER_ABORT` from `BeforeTuiStart`; exit code 3 |
| `poll` hangs | `poll` must be non-blocking; move long-running work to a thread, keep state in the handle, and have the cancellation flag end it within a time limit |
| Hot reload fails on Windows | A loaded DLL cannot be overwritten; use `evo dev`'s versioned staging, do not copy manually |
| Resource missing from the system prompt | Use `--debug-system-prompt` to view the final assembled result; confirm the skill path is discovered |
| Enter becomes a newline on a phone/remote terminal | Use `EVO_DEBUG_KEYS=1` to inspect keys: `Char('j') mods=CONTROL` = the client sent LF (now treated as submit by `Editor`); `Enter` + `paste burst` = the paste heuristic misjudged it (now restricted to the Windows platform) |
| Pasted content is not the system clipboard (but the TUI's own text) | When a remote/phone client maps paste to `Ctrl+V`, `read_clipboard_text` reads the **server's** clipboard, which may have had TUI text written to it by drag-select copying (copy-on-select) (such as the welcome text `Skills (…): …`). This fallback is now restricted to Windows; on Unix, real pastes go through bracketed paste `Event::Paste`, and `Ctrl+V` falls back to the editor's kill-ring yank |
| panic / segfault across the ABI | `extern "C"` boundaries must not unwind; `StbString` ownership must follow the host-side and plugin-side rules |
| ABI version mismatch | The host log reports a mismatch and skips loading; check the `evo-plugin-sdk` version |

## 9. Testing and Release

- Write domain logic as ordinary Rust functions, and have the FFI layer do only conversion/lifecycle/error mapping; write
  `rlib` unit tests for the ordinary logic.
- At least one host smoke test verifies ABI registration, loading, and unloading (see the test pattern in `plugin-stub`:
  the host reads a hit counter exported by the plugin to assert behavior).
- `cargo fmt --check`, `cargo clippy --all-targets`, and `cargo test` pass.
- `evo dev --no-watch` builds, loads, and registers the expected tools.
- The clean install path via `evo install <crate> --force` passes (Linux/macOS/Windows verified by CI).
- The README documents the tool schema, permission boundaries, persisted files, network access, supported platforms, and how to uninstall.
