# evo Rust Extension Authoring Best Practices

This document is the model-readable specification for creating Rust `cdylib` extensions for evo.
Extensions are native Rust dynamic libraries that register tools, event handlers, resource
discovery, Providers and renderers through a stable C ABI (`evo-plugin-sdk`); the host (the
`evo` CLI) is responsible for loading and lifecycle. For the default structure of a complete
Agent project, see the `agent` topic of `docs`; this guide focuses on the ABI and lifecycle of
the extension itself.

## 1. Extension Model Overview

| Item | Native Rust extension |
| --- | --- |
| Install | `evo install crate-name` (prebuilt protocol); `--build` / `--path` (from source) |
| Entry point | `evo_plugin_register` C ABI symbol |
| Development feedback | `evo dev` watch + hot reload; `evo dev-local` isolated debugging |
| Static resources | `resources_discover`, or ship them with the project in `.evo` |
| Runtime environment | Native dynamic library on the local machine, current user's privileges |
| Use cases | Local tools, system integration, performance-sensitive or pure-Rust projects |

Use `evo extension update [name]` to update extensions: with no name it updates all
project-linked extensions and global registry/prebuilt extensions; with a name it updates only
the matching ones. Updates keep the original Cargo build backend or explicit GitHub source;
development extensions installed globally via `--path` are not updated.
The old command `evo package update [name]` is still supported; the project link management
commands remain `evo package link`, `evo package list` and `evo package unlink` and have not
been renamed.

Extensions should follow capability detection: only call capabilities the host explicitly
provides, and check whether the corresponding registration slot in `PluginApi` is `Some`. When a
capability is missing, return a clear error and degrade gracefully; do not panic, use null
pointers, or rely on `undefined` semantics.

### Choose the Reuse Layer First

When writing a Rust `cdylib` plugin that `evo` loads directly, use `evo-plugin-sdk` for the ABI
entry point and tool/event registration. Do not link `evo-extensions`, `evo-cli` or
harness-private modules into the plugin; they belong to the host side.

If the plugin project also needs the session, workspace, RPC, event replay and run-state logic
shared by Web/ACP/remote adapters, it can reuse [`evo-extcore`](https://crates.io/crates/evo-extcore) from crates.io:

```toml
[dependencies]
evo-plugin-sdk = "0.8"
evo-extcore = "0.1" # add only when you need native RPC / session / workspace services
```

`evo-extcore` is an ordinary Rust library; it is not a `cdylib` plugin entry point and does not
replace `evo-plugin-sdk`. It provides adapters with reusable modules such as `service::Service`,
`host::HostSession`, event subscription, session/workspace operations and
`durable::DurableCoordinator`; at runtime it needs a compatible `evo --mode rpc` executable. It
does not start a server on its own, manage credentials or provide an HTTP/ACP frontend, and it
does not create a second transcript. Projects that need it can initialize the shared service
like this:

```rust
use evo_extcore::service::{self, BackendConfig, Service};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let core = Service::new(BackendConfig::default())?;
    let projects = service::list_projects(&core).await;
    assert!(projects["projects"].is_array());
    core.shutdown().await;
    Ok(())
}
```

If you only need to add a single tool to `evo`, keep `evo-plugin-sdk` as the only dependency and
start from `examples/plugin-stub`; add `evo-extcore` only when you genuinely need a protocol
adapter or the shared native RPC service. Note that its versioning policy is independent of the
plugin ABI: the plugin SDK follows the host ABI, while for `evo-extcore` you pick a compatible
patch version within its own `0.1` minor line.

## 2. Recommended Structure

```text
my-evo-extension/
├── Cargo.toml
├── README.md
├── src/
│   ├── lib.rs
│   ├── tool.rs
│   └── error.rs
└── tests/
    └── behavior.rs
```

### Cargo.toml

```toml
[package]
name = "my-evo-extension"
version = "0.1.0"
edition = "2021"
license = "MIT"
repository = "https://github.com/example/my-evo-extension"

[lib]
crate-type = ["cdylib", "rlib"]

[dependencies]
evo-plugin-sdk = "0.8"
serde_json = "1"
```

`cdylib` is the artifact the host loads; also keep `rlib` so that Rust integration tests are
easy to write. At the extension boundary, depend only on `evo-plugin-sdk`; do not depend on
`evo-cli`, `evo-extensions` or harness-internal modules, otherwise the plugin becomes coupled to
the host implementation.

## 3. ABI Entry Point

The host only loads the unified C ABI symbol `evo_plugin_register`. Extensions use
`export_plugin!`, register capabilities through a single `PluginApi`, and call `api.declare` to
declare priority/platforms. Before registration the SDK checks `abi_version` and `struct_size`;
optional trailing slots that an older host lacks are filled with `None`, so the plugin can
degrade accordingly. If the version is incompatible or required fields are incomplete, it
returns a nonzero status and the host reports a load failure.

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

The `declare` JSON supports `priority` (a number; higher runs first) and `platforms` (a string
array, e.g. `["linux","windows","macos"]`); when dispatching to event handlers, the host skips
those whose platforms do not match.

### Capability Detection

Every registration slot is an `Option`. Before registering, check whether the vtable slot is
`Some`, and return a clear error when it is missing; do not use null pointers or panics to
signal lack of support. The host returns a structured error for unknown runtime action IDs and
does not dispatch them. Runtime actions use the SDK's `RuntimeActionId` definitions (including
`GetCliFlag` and `UiDialog`); do not assume numeric ranges yourself.

### Independent Subtasks

`GetExecutionContext` (23) returns the current model identity, thinking, active tools, cwd and
session ID; it does not include credentials, auth headers or endpoints. `ChildAgent` (24)
dispatches on `op`:

- `start`: `task` (required, at most 20,000 bytes), `role`, `maxTurns` (1-32, default 8),
  `timeoutSeconds` (10-1800, default 300), and `tools`, an optional subset of the parent's active tools.
  Returns immediately with `childId`, an independent `sessionId` and `status: running`.
- `poll`: pass `childId`; consume the `deltas` array and get the `running/done/failed` status.
  After `done`, also check `result.status`, `result.text` and `result.turnLimited`.
- `cancel`: sets the cancellation signal; `dispose`: cancels and releases the handle. Every task
  in a terminal state must be disposed.

The subtask inherits the effective provider private binding, the system prompt/resources, the
project cwd and the permission hooks; it does not reload the default configuration and does not
enter the parent transcript. Permission approvals and user questions go through the parent UI;
when there is no interactive consumer, they are not allowed by default. `delegate_task` is
removed from the child's tool registry. Plugin tools still belong to the parent host, and
`__evo.sessionId` is still the parent extension's state space; it must not be used as a child ID.
Handles are isolated per plugin owner; they are cleaned up when the parent ends or is cancelled,
on session switch, on shutdown, or on plugin reload. Each host keeps at most 16 tasks; text
deltas and final reports share a 4 MiB budget and at most 8192 deltas.
This is not an OS security sandbox; read-only tasks should narrow the tool scope and use
permission rules.

Call synchronous runtime actions from a worker thread to avoid deadlocking yourself in a
single-threaded Tokio executor. ChildAgent must also be bound to this tool call's
`__evo.runtimeHandle` / `runtimeKey`: use the opaque handle as the action's user_data and pass
`__evoRuntimeKey` in the parameters; do not cache them across calls or output them to the model.
Registration-level-only, invalidated and child-originated calls are rejected (including through
aliased tools), and the tool subset cannot be bypassed via the root host. After cancellation, a
valid parent capability only allows poll/cancel/dispose to reclaim existing tasks and does not
allow start; a queued start also inherits the original call's cancellation.
Synchronous tool callbacks are bound automatically by the host. Background tools, providers and
approval drivers keep the DLL and parameters alive themselves; anything that outlasts the
two-second foreground cleanup grace period still occupies an active slot until it actually exits.
The host runtime binding holds the parent harness weakly; rolling back a candidate reload does
not leave behind a dereferenceable stale bridge pointer.
When an older host does not support a new action, tell the user clearly to upgrade; do not
silently fall back to a subprocess that might switch models.
For the full protocol and real DLL tests, see `docs/extensions/subagents.md` in the repository.

### Appending Context During a Run

The `{"customType": "...", "data": {...}}` form of `AppendEntry` only stores extension data; by
default it does not enter the model context. The `{"message": <AgentMessage>}` form appends a
session message but does not trigger a new model response. During a run, messages first go into
a persistent queue; they are written to history and displayed only after all tool results of the
current turn have been committed, and only the next model request can read them.

The returned `entryId` is a stable reserved ID; querying that entry while it is still queued may
return nothing. A tool can wait for `AppendEntry` to return; it does not wait for the tool or the
whole run to finish. Cancellation and session resume do not discard queued messages that have
already been accepted.

### SendMessage Delivery Options

`SendMessage` accepts the existing `{"message": <AgentMessage>}` / `{"text": "..."}` forms, and
also Evo's custom message shape: `customType`, `content`, `display`, `details`.
`content` can be a string or an array of text/image blocks; a missing or null value is
normalized to an empty array.

Options can go in an `options` object or at the top level of the parameters; do not mix the two
forms:

```json
{
  "message": {"customType": "goal-state", "content": "Goal state updated", "display": true},
  "options": {"triggerTurn": false}
}
```

| Option | Behavior |
| --- | --- |
| `triggerTurn` omitted | When idle, only appends context; during a run, goes into the steering queue by default |
| `triggerTurn: true` | When idle, starts a model run; during a run, queued according to `deliverAs` |
| `triggerTurn: false` | Only updates context; during a run, committed after the current tool batch ends; does not proactively request a model reply |
| `deliverAs: "steer"` | Default mode; injected after the current tool batch ends |
| `deliverAs: "followUp"` | Injected after the current task completes, then processing continues |
| `deliverAs: "nextTurn"` | Held until the next explicitly started run and added before the new input; takes precedence over `triggerTurn` |

The return value distinguishes `status: "appended"`, `status: "queued"` and the existing run
result statuses. Appended and queued messages return a stable `entryId`; querying the entry
before a queued message is committed may return nothing.
`deliverAs` in a queued result indicates the delivery mode; silent context updates return
`queue: "context"`. Steering/follow-up messages do not re-enter a tool that is executing, and
`nextTurn` is not consumed early by automatic run resumption.

Default idle sends now match Evo and no longer automatically request the model. Callers that
relied on the default send producing an immediate reply should pass `triggerTurn: true`
explicitly.

### Tool Prompt Snippets and Guidelines (Consistent with Evo)

The tool schema determines whether the model can call a tool; the system prompt only selectively
shows snippets. The two are independent. Register the tool first, then register explicit
metadata through the optional `api.register_tool_prompt`:

```rust
if let Some(register_prompt) = api.register_tool_prompt {
    let status = register_prompt(
        evo_plugin_sdk::StbStringRef::from_str("my_tool"),
        evo_plugin_sdk::StbStringRef::from_str(
            r#"{"promptSnippet":"Short summary of the tool","promptGuidelines":["A specific usage rule for this tool"]}"#,
        ),
    );
    if status != 0 { return status; }
}
```

- Metadata can only be set for tools the current plugin has already registered. Return values:
  `0` success, `1` unknown tool, `2` the metadata is not a valid object or a field has the wrong
  type, `-1` not in the registration phase; the host copies the argument strings immediately.
- `promptSnippet` is optional; it appears in the prompt's tool list only if it is non-empty after
  trimming and the tool is enabled. Tools without a snippet remain fully usable through their
  schema; the description is not automatically used as the snippet.
- `promptGuidelines` is optional; guidelines are collected only from enabled tools, trimmed,
  stripped of blank entries, and deduplicated against other tools and the core guidelines in
  enabled-tool order. Guidelines do not require a snippet; the host no longer hardcodes
  guidelines for external todo tools.
- Metadata takes part in first-wins merging and reload together with the tool definition. When an
  extension tool with the same name replaces a built-in tool, it does not inherit the built-in
  snippet; after a tool is unloaded or disabled, its snippet and guidelines do not linger. An
  empty object clears the metadata.
- The registrar is only appended to the end of the ABI vtable; it does not change
  `StableToolSchema` or the ABI version. Old plugins still load; when the slot is `None` on an
  older host, skip metadata registration, but do not skip tool registration because of it.
- A custom `SYSTEM.md` / `--system-prompt` still replaces the default prompt; the automatic
  contributions above apply only to the default prompt.

## 4. Tool Lifecycle: execute → poll → cancel → destroy

A tool exports four `extern "C"` functions, which the host drives according to a fixed protocol:

- `execute` parses the JSON passed in by the host (an owned `StbString`; release it with
  `free_with`) and creates an independent handle for each call (`Box::into_raw`).
- `poll` must be non-blocking; return `Pending` if not finished, and `Done` or `Err` when
  finished. `partial_cb` is called synchronously within poll, and the host forwards partials in
  real time while waiting for a terminal state. The host backs off briefly on Pending, and after
  cancellation it waits for the driver to finish without busy-looping; a late success does not
  override the cancellation.
- `cancel` only sets a thread-safe cancellation flag; it must be idempotent and must not release
  the handle.
- `destroy` is called exactly once by the host at the end and releases the handle (a no-op on a
  null pointer).

Ownership protocol:

- `StbString`s produced by the host (execute's params, event payloads) are released by the plugin
  through the host's `free_string`.
- `StbString`s produced by the plugin (done results, partial progress, the out of
  resources_discover) are released by the host through the `plugin_free_string` that the plugin
  provided at registration.
- No `extern "C"` boundary may unwind; catch panics inside the plugin and convert them into
  error results.

A complete, runnable ABI template is in `examples/plugin-stub/src/lib.rs`. When creating a new
tool, copy the lifecycle skeleton first, then replace the parameter schema and domain logic; do
not redesign the ownership protocol.

### Host Context Injected into Tool Parameters

**Before** handing the parameters to the plugin, the host adds a reserved key `__evo`
(`evo_plugin_sdk::HOST_CONTEXT_KEY`) to this call's JSON parameters:

```json
{ "action": "add", "text": "…",
  "__evo": { "cwd": "D:\\Projects\\evo-harness",
             "sessionId": "01adb026-7230-708b-855b-91eab6b056b8" } }
```

- **The model can neither see nor write it.** Injection happens after the model's arguments are
  parsed and before `execute`; it does not appear in `ToolExecutionStart`/`Update` events or in
  the session log. If the model happens to pass a key with the same name, the host's value
  overrides it.
- **Either field may be missing.** There is no `cwd` when the working directory cannot be
  determined; ephemeral sessions, and older hosts that predate this injection, have no
  `sessionId`; the whole key may also be absent.
- **Therefore the tool's parameter type must tolerate unknown top-level fields.** Reading values
  through `serde_json::Value` satisfies this naturally; a parameter struct defined with
  `#[serde(deny_unknown_fields)]` will fail outright.
- Built-in tools do not go through this path; they get `ExecutionToolContext` directly from the
  harness.

Plugins that need "one state per session" should key on `sessionId` (`evo-todo` stores
`.evo/todos/<sessionId>.json`, one file per session). When it is unavailable, fall back to
project-level state and **say so in the reply**; do not invent a shared pseudo-session, which is
exactly the problem this key exists to solve.

## 5. Event Handlers, Resource Discovery and Providers

### Event Handlers

Subscribe by `EventTag` (36 kinds) through `api.register_event_handler`:

- **Session lifecycle**: `SessionStart`, `SessionBeforeSwitch`, `SessionBeforeFork`,
  `SessionBeforeCompact`, `SessionCompact`, `SessionShutdown`, etc.
- **Agent loop**: `BeforeAgentStart`, `AgentStart`, `AgentEnd`, `AgentSettled`,
  `TurnStart`, `TurnEnd`, `MessageStart`/`MessageUpdate`/`MessageEnd`,
  `ToolExecutionStart`/`Update`/`End`, `ToolCall`, `ToolResult`, `UserBash`, `Input`.
- **evo-specific / UI**: `BeforeTuiStart` (before TUI initialization), `UiPromptStart`/`UiPromptEnd`.

Handlers receive a `StablePluginEvent` and must not free the strings in the event (the host frees
them all after the fan-out). Return `0` for success; return `EVENT_HANDLER_ABORT` to veto.

### Lifecycle Veto

`BeforeTuiStart` is an evo-specific hook with veto semantics: the first handler that returns
`EVENT_HANDLER_ABORT` aborts startup, and the CLI exits with exit code `3` (used for cases like
"an external connection must be established before entering the TUI").
A veto from `SessionStart`/`SessionShutdown` is only advisory. Dispatch has a timeout, so slow
handlers cannot block the main flow indefinitely.

### Resource Discovery

`api.register_resources_discover` registers a handler; on `startup`/`reload` the host fans out
to all registered handlers and merges the returned `{skillPaths, promptPaths, themePaths}`.
An error from a single handler does not abort the fan-out. `out` is a plugin-owned `StbString`,
which the host reclaims through the `plugin_free_string` the plugin provided at registration.

### Rewriting the System Prompt at Runtime

`api.register_before_agent_start` registers a system prompt transformer, corresponding to evo's
`before_agent_start` handler returning `systemPrompt` (which becomes that run's
`forceSystemPrompt`). This is the only supported entry point for a plugin to change the system
prompt **at runtime**:

```rust
// event_json carries prompt / imageCount / sessionId / host, plus the **current** systemPrompt.
extern "C" fn on_before_agent_start(
    event_json: StbStringRef,
    out: *mut StbString,
    user_data: *mut c_void,
) -> i32 {
    evo_plugin_sdk::guard_or(1, || {
        let env: serde_json::Value =
            serde_json::from_str(unsafe { event_json.as_str() }).unwrap_or_default();
        let current = env["systemPrompt"].as_str().unwrap_or("");
        // The return value **replaces** rather than appends: to append, read the current value and concatenate (evo requires the same).
        let next = format!("{current}\n\nIn this repository, prefer `just test` over `cargo test`.");
        unsafe { *out = StbString::from_string(json!({ "systemPrompt": next }).to_string()); }
        0
    })
}
```

Key semantics (aligned with evo):

- **Replace, not append.** The returned text becomes the prompt. To append, you must read
  `systemPrompt` from `eventJson` yourself and concatenate; the host does not preserve the
  original for you.
- **Chained in registration order.** Each handler receives the result returned by the previous
  handler.
- **A single handler failure is not fatal.** On a nonzero return or a panic, the prompt keeps the
  previous handler's result and the fan-out continues (the host logs and skips it).
- **Affects only that run.** The host re-derives the prompt from session state every turn; the
  plugin's result is not persisted.
- **Evaluated once per user prompt.** A single prompt may trigger multiple provider calls (the
  tool loop); the transformer runs only before the first one and its result is cached, to avoid
  drift in the middle of a run.
- **Returning an empty object/empty string = no change.** A plugin that only wants to observe
  without changing anything can return nothing; explicitly returning an empty string means "clear
  the prompt" and is applied.

Like other out-param handlers, `out` is owned by the plugin and reclaimed by the host via
`plugin_free_string`. This slot was newly added at the end of the struct and may be `None`:
plugins targeting older hosts should check before registering (see §3 Capability Detection),
and the host skips this path entirely when no plugin has registered one.

### Providers and Renderers

For the catalog, authentication, execution binding and acceptance requirements of inference
providers, see "Provider Integration Specification" at the end of this document.

`api.register_provider` injects a custom LLM Provider (`provider_id`/`base_url`/
`api_style` + `request_fn`). `register_message_renderer`/`register_markdown_transformer`/
`register_entry_renderer` register message rendering capabilities. Any of these slots may be
`None` and must be checked before use.

`api.register_streaming_provider` injects a **streaming** Provider. Registration likewise supplies
the provider ID, endpoint, API style and string-release callback; the streaming request fn
additionally receives a per-chunk callback `emit`, `emit_user_data`, an optional control plane
`control`, and `completion`, which is always `None` on the current host.
While the request is still in progress, the plugin calls `emit` to push deltas to the host:

```json
{"type":"text_delta","contentIndex":0,"delta":"hello "}
{"type":"thinking_delta","contentIndex":1,"delta":"weighing"}
{"type":"toolcall_delta","contentIndex":2,"delta":"{\"path\""}
```

The host immediately maps them to `AssistantMessageEvent` (`TextDelta`/`ThinkingDelta`/
`ToolCallDelta`, etc.), so the TUI starts rendering while the model is still generating instead
of waiting for the whole response. Available `type` values: `start`, `text_start`/`text_delta`/`text_end`,
`thinking_start`/`thinking_delta`/`thinking_end`,
`toolcall_start`/`toolcall_delta`/`toolcall_end`, `usage`; unknown `type` values are ignored
(forward compatibility).

`toolcall_end` may carry an optional `recorded` field, indicating that this tool call **has
already been executed remotely** (for example, a remote agent ran the tool itself and streams the
call back together with its result). The host treats `recorded` as a completed tool result and
**never executes the call locally again**; neither approval hooks nor the tool's `execute` are
triggered. The shape of `recorded` matches what the Cursor replay worker emits:
`{"version":1,"isError":false,"result":{"content":[{"type":"text","text":"..."}],"details":{},"terminate":true}}`.
`result.content` allows only `text` and `image` blocks; `result.details` and `result.terminate`
may be omitted. `terminate: true` ends the current batch of tool calls just like a live tool
result. Incomplete records such as `{"version":1}` (written before a crash), records whose
version is not `1`, and records with `null` fields, unknown top-level fields or an invalid shape
are all returned by the host as error tool results, and are likewise not executed. Include
`recorded` only when the call really has already happened; calls without this field behave
exactly as before.

**Check host capabilities first.** Older hosts that do not recognize `recorded` ignore the field
and execute the call locally; the fact that the C ABI is unchanged does not prevent this. The
`capabilities` object at the top level of the request envelope describes what the host supports:
`capabilities.recordedToolCalls` is the highest `recorded` version the host can decode;
advertising `n` means it can decode every version from `1` to `n`. A plugin may send `recorded`
only when this value is `>= 1` (and not less than the `version` it sends). If the key is absent,
the host is an older one: the plugin must not send `recorded` and should end the turn with an
error, rather than handing an already-executed call to the host as an ordinary call.

For providers written with the SDK bridge (`export_provider!`, `provider::drive`,
`provider::drive_with_context`), the bridge performs this check: when the host has not advertised
`recordedToolCalls >= 1`, a final message that contains `recorded` calls and would otherwise be
executable becomes an `Error` terminal state (with the text
`host does not support recorded tool calls`, no content, and usage preserved). During the bridge
call, the factory can read this request's `capabilities` with `provider::host_capabilities()`
(`null` on older hosts) and pass them to the provider it constructs. The value is available only
on the request thread; other threads (including tasks the provider itself spawns under
`drive_with_context`) read `null`, so read and store it in the factory.
The bridge's own check reads the request directly and is not affected. The bridge puts
`recorded` into both the `toolcall_end` block and `out`.

**`recorded` and the final `out`.** The host executes the calls in `out`, so before the terminal
state it checks, against `out`, every call that carried `recorded` on its `toolcall_end`: it finds
the same call in `out` by `id` and requires `name` and `arguments` to be identical (compared as
JSON values: object key order does not matter, but `1` and `1.0` differ). When that call has no
`recorded` key in `out`, the host fills in the record from the stream (an explicit `null` record
is filled in as well; it is still an error result and is not executed); if both records are
identical, nothing changes. Any of the following ends the turn with an `Error` terminal state and
executes no calls locally: the `id` is missing from `out`, the same `id` appears more than once,
`name` or `arguments` differ, the records differ, or a `toolcall_end` that carries `recorded` has
no `id`. The error text is fixed and does not include the call `id`, so that it is not treated as
a retryable transient error. Including `recorded` only in `out` is equally valid. When the plugin
returns nonzero, `out` is empty or unparseable, or the request is cancelled, the terminal state is
already `Error`/`Aborted` and no calls are executed. Including the same `recorded` in both
`toolcall_end` and `out` is recommended.

Conventions:

- **`out` is still the final message.** Callbacks only deliver deltas; the complete
  `AssistantMessage` that the plugin writes to `out` when it returns is the payload of the
  terminal `Done`/`Error`. The host inserts a `Start` before the terminal state, so the event
  stream is valid even if the plugin did not emit a single chunk.
- **Callback ownership is the same as for tool partials.** Each chunk is a plugin-allocated
  `StbString`, which the host reclaims with the `plugin_free_string` the plugin provided at
  registration; `emit`/`emit_user_data` are valid only for the duration of this request, and the
  plugin must not store them.

This slot is likewise appended at the end of the struct and may be `None`: when targeting older
hosts, degrade to `register_provider` (one-shot) rather than refusing to load. When the same
`provider_id` is registered first as one-shot and then as streaming, the streaming registration
replaces that record in place (streaming is a superset of one-shot). You can copy a complete,
runnable skeleton from `on_provider_stream_request` in `examples/plugin-stub/src/lib.rs`.

#### Cancellation: Same Method, the Plugin Decides

Long generations need to be interruptible. **There is no separate "cancellable" registration**:
`register_streaming_provider` has only one method and one signature, and the request fn always
receives a `control` argument (a synchronous control plane provided by the host). Whether to
poll it is up to the plugin.

```rust
// Between SSE frames (a real provider usually blocks on a socket read here):
if (control.is_cancelled)(control.user_data, ProviderChunkKind::Content as u32) != 0 {
    return 1; // the caller has gone away; stop generating
}
```

- `is_cancelled(user_data, chunk_kind)`: non-blocking poll. Pass `Content` (0) for "model
  output", or `Structural` (1) for closing frames such as `start`/`*_end`/`usage`.
  After cancellation the host accepts structural frames and rejects content frames; closing
  frames that arrive after the terminal state has been emitted are dropped.
  The cancellation terminal state preserves already-forwarded content, the model identifier and
  usage. The plugin holds a DLL reference until the request returns, and a success result
  written to `out` afterwards does not override the cancellation terminal state.
- `wait_cancelled_ms(user_data, timeout_ms)`: the blocking version, for loops that cannot poll;
  it returns immediately if already cancelled instead of sleeping for the full timeout.

The host's cancellation signal comes from `options.signal` (the same `CancellationToken` used by
built-in providers, cancelled by the agent loop when the user interrupts). Once cancellation
happens, the host latches the control plane, stops forwarding content deltas, **immediately**
emits an `Error { reason: Aborted }` terminal state and ends the event stream, rather than
waiting for a full generation that nobody wants anymore. `emit` returning nonzero for a content
frame is the same signal, and the plugin can exit on it.

Polling `control` is **optional**; both approaches are valid:

- **No polling** (fire-and-forget): the plugin pushes out its entire output as usual. On
  cancellation the host still stops forwarding content frames and ends the turn immediately; the
  plugin merely spends the extra tokens it has produced.
- **Polling**: the plugin exits at the earliest check point, saving the rest of the generation.

`control` may be `null` (for hosts that do not support the control plane); in that case treat it
as "not cancellable" and do not refuse to load.

The `completion` argument is **always `None` on the current host**: this host does not allow a
plugin to keep calling back after the request fn returns (that would let the callback pointer
outlive the call). The plugin must finish up and write `out` within the request fn; the argument
is kept in the ABI so that future hosts can extend it without changing the signature again.

The plugin only needs to degrade step by step, streaming → one-shot:

```rust
if let Some(register) = api.register_streaming_provider { /* streaming, optionally poll control */ }
else { /* register_provider, one-shot */ }
```

You can copy one skeleton each from `on_provider_stream_request` (no polling) and
`on_cancellable_provider_stream_request` (polling) in `examples/plugin-stub/src/lib.rs`.

## 6. Best Practices for Rust Tool Design

1. Write domain logic as ordinary Rust functions; FFI functions are only responsible for conversion, lifecycle and error mapping.
2. Write `rlib` unit tests for ordinary logic; write at least one host smoke test for ABI registration, loading and unloading.
3. Use the same field names in the schema and the implementation, and reject unknown fields; set limits on paths, URLs, commands, counts and output size.
4. `poll` must not run long blocking work. Put time-consuming work in a thread/task with the state held in the handle; the cancellation flag must be able to make the task finish within bounded time.
5. Use explicit synchronization for global mutable state; avoid storing session or tool call state in an unprotected `static mut`.
6. Runtime actions, providers, renderers, event handlers and resources handlers are all optional capabilities; check the vtable slot before registering.
7. Return nonzero when plugin registration fails; when a single tool execution fails, return a structured error rather than making the whole host exit.
8. The README documents the tool schema, permission boundaries, persisted files, network access, supported platforms and how to uninstall.

## 7. Developing with evo dev

Run in the extension crate directory:

```bash
evo dev
```

evo identifies the current `cdylib` through Cargo metadata, places a versioned copy in the
workspace's `.evo/extensions/.dev/` after the first build, starts the normal TUI, and watches
`src/`, `build.rs`, the package/workspace `Cargo.toml` and `Cargo.lock`. When source files
change, it rebuilds automatically and goes through the existing reload flow; if the build fails,
the currently loaded version is kept.

A workspace with multiple extensions must select the package explicitly:

```bash
evo dev --package evo-todo
evo dev -P evo-webfetch
```

Other modes:

```bash
evo dev --release
evo dev --no-watch
evo dev-local
evo dev --package evo-todo -- --model gateway/model
```

Use `evo dev-local` (equivalent to `evo dev --local-only`) when debugging a single extension. It
loads only the currently built extension, the skills/prompts in the current project directory,
and the skills/prompts discovered by that extension; it does not scan global extensions,
installed Evo packages or other project resources, so same-named or unrelated commands do not
interfere with debugging. Built-in commands (including `/reload`) remain available. Without a
Cargo cdylib, it degrades gracefully to skills-only mode.

Running `/reload` in the TUI forces Cargo build to run again and then loads the newly staged
artifact. On Windows a loaded DLL cannot be overwritten in place, so do not manually copy the
Cargo target DLL to a fixed filename; the versioned staging of `evo dev` performs the switch
safely and cleans up after the session exits and the loader releases the DLL.

## 8. Resource and Configuration Conventions

Project-level resources go in `.evo/`. Precedence for resources with the same name: definitions
within the project take precedence over `.evo`, project over global, and packages last:

```text
.evo/
├── SYSTEM.md
├── APPEND_SYSTEM.md
├── settings.json
├── skills/
├── prompts/
├── themes/
└── extensions/
```

Dynamic `resources_discover` is suited to deciding paths based on the runtime environment; for
fixed resources, prefer a manifest or the conventional directories, so that the installer, the
welcome page and `/context` can discover them before any extension code runs.

### Custom Load Paths

A project-level `.evo/settings.json` can declare additional resource paths; no other
compatibility fallback is needed. Paths are relative to the project root, and configured paths
are ordered before the conventional directories:

```json
{
  "skillDirs": ["./team-skills"],
  "promptDirs": ["./prompts/shared"],
  "extensionDirs": ["./target/debug"],
  "packages": ["./packages/review-tools"]
}
```

`skills`, `prompts` and `extensions` can also be used as shorthand for the three path arrays,
respectively. The global `~/.evo/agent/settings.json` supports the same `skillDirs`,
`promptDirs` and `extensionDirs`, where relative paths are relative to the global agent
directory. Project configuration takes precedence over global configuration; `.evo` resources
and settings are ordered before `.evo`.

A single run can append paths explicitly:

```bash
evo --skill ./extra-skills
evo --prompt-template ./extra-prompts
evo --extension ./target/debug/my_extension.dll
evo --extensions-dir ./target/debug
```

`--skill`, `--prompt-template`, `--extension` and `--extensions-dir` can all be repeated.
Additional Rust extension directories can also be configured through `EVO_EXTENSIONS_DIR`;
entries are separated by semicolons on Windows and by colons on Linux/macOS. The command line and
environment variables are suited to local development, CI and troubleshooting; for configuration
shared by a team, use the project's `.evo/settings.json`.

## 9. Release Checklist

- `cargo fmt --check`, `cargo clippy --all-targets` and `cargo test` pass.
- `crate-type` includes `cdylib`, and `evo_plugin_register` is exported with
  `export_plugin!`.
- The crate depends on a compatible published version of `evo-plugin-sdk` and does not link
  host-private crates.
- `evo dev --no-watch` can build, load and register the expected tools.
- The clean install path `evo install <crate> --build --force` succeeds.
- Linux/macOS/Windows builds are verified by CI, and the README states the support matrix.

## 10. Model Execution Rules

When the model receives a task to "create an evo Rust plugin or extension tool":

1. First call `docs` to look up `authoring` (extension development) or `debugging` (debugging).
2. Read the current repository's existing manifest, SDK version and the conventions of neighboring extensions; do not guess APIs.
3. Prefer copying the minimal skeleton from `examples/plugin-stub`.
4. Implement the domain logic and boundary tests first, then wire up the loader/ABI.
5. Use `evo dev --no-watch` and `evo install <crate> --build --force` for a real smoke test.
6. Do not claim that unverified Evo capabilities are fully compatible; document degraded behavior explicitly.

## Provider Integration Specification

The unified production package is `evo-providers`; a single install entry point includes
DeepSeek, OpenRouter, llama.cpp and Proxy. Prefer adding new vendors as modules inside this
package; only the root module exports `export_plugin!`, once, and all modules share the
registration bridge. Provider IDs, catalogs and credentials remain independent. Only
single-provider teaching examples use `export_provider!`.

Full specification: [Provider Integration Specification](https://github.com/evoelsewhere/evo-harness/blob/feature-stream-porider/docs/extensions/provider-integration.md). When creating an inference extension, prefer copying
the official provider package example at [evo-providers](https://github.com/evoelsewhere/evo-package/tree/feature-1014/packages/evo-providers); use `plugin-stub` for general-purpose tool extensions. The current integration conventions are as follows.

### Approach and Catalog

When you only change the endpoint, models and key of an already-supported protocol, prefer
`models.json`; when you need an installable catalog, an authentication strategy or vendor logic,
use a standalone package. New vendors are not added as default dependencies of the CLI.
Providers handle inference and auth handles credentials and login flows; the two are registered
independently.

Declare providers through the `providers` array of `declare`, giving `id`, `models` (an array of
complete `evo_ai::Model` values), the optional `apiKeyEnv`, and `requiresAuth` (default `true`).
Construct models with `Model::new` and serialize them; the shorthand objects of models.json
cannot be used. The provider ID, each model's `provider`, and the ID actually registered must
match; the model ID is the name sent to the server. Anonymous services must set
`requiresAuth: false` explicitly, and the protocol client must also allow anonymous access;
changing only the catalog declaration is not enough.

A catalog takes effect only after the same plugin successfully registers the corresponding
provider; on a name conflict, the first implementation and its catalog are kept.
Registration and catalog discovery do not require credentials; the host loads extensions and
merges models.json overrides before selecting a model.
`--list-models` can display the catalog without credentials; `--no-extensions` disables both the
implementations and the declarations.

### Factory and Private Execution Binding

Within the unified package, reuse `crate::registration::register_provider!`; single-provider
teaching packages can use `evo_plugin_sdk::export_provider!`, which requires explicitly enabling
the SDK's `provider` feature (off by default). A module provides
`fn(&Model, &SimpleStreamOptions) -> Arc<dyn Provider>`. OpenAI-compatible integrations can reuse
`evo_plugin_sdk::provider::completions(model, options, anonymous)` instead of copying the SSE
parser. This helper returns a `Result`; propagate client configuration errors through
`ContextFactory`, or use `context.completions(model, options, anonymous)` to reuse the client.
The host-private `ProviderFactory` selects between extension and built-in protocols uniformly;
it is not an interface that plugins need to implement.
At runtime, depend on `evo-ai` and on `evo-plugin-sdk` with the `provider` feature enabled, not
on `evo-cli`; the host loader can be used as a test dependency.

The descriptions returned by the public catalog, by the current model, and by
`Provider::models()` after configuration carry no request headers.
The host-private `ExecutionBinding` stores the actual endpoint, the model's request headers and
the default authentication, and restores them by provider / API / model ID before execution;
modifying the public description cannot redirect the bound credentials.
`base_url` remains public for display, and options passed explicitly with each request still
take effect under the existing rules.
Plugins must use the model / options passed in with the request, and must not switch to a
hardcoded endpoint or to a key from the process environment variables.

### Authentication and Reload

Default credentials are resolved by the host per provider ID: the selected provider's
`--api-key` → a valid key / OAuth in `auth.json` → `models.json` → the declared `apiKeyEnv` →
explicitly allowed anonymous access.
The protocol name does not determine authentication, and `OPENAI_API_KEY` is not inherited;
blank values, unresolved references and expired tokens that cannot be refreshed do not count as
usable. The catalog must not contain credentials; request parameters, tokens and private request
headers must not appear in logs, ordinary events or error text.
OAuth vendor flows are integrated separately through `register_oauth_provider`; the host is
responsible for the generic commands and storage.

When a matching OAuth extension is loaded and the stored entry contains a refresh token, the host
can select the provider for an expired login, and before each request it automatically refreshes
tokens that have expired or expire within 60 seconds, saving the new token before using it; if
the refresh fails, the old token is not sent.
`auth check` only checks for unexpired local credentials; it does not contact the server or
refresh tokens, so it may report missing credentials even though requests could still refresh
automatically. Its exit codes are 0 for ready, 1 for missing credentials, and 2 for a
configuration error.
`/provider <id>` and selecting from the list switch the current session immediately and save the
default model; if authentication is missing or the switch fails, the original session and
defaults are kept. `/model` selects a specific model; `/provider remove` deletes the
configuration; to uninstall a package, use `evo package unlink`. API-key logout does not clear
environment variables or models.json.

A `/reload` that involves a provider package rebinds the runtime, credentials, endpoints and
public catalog; if the current package has disappeared or cannot be re-resolved, it returns an
error and keeps the old session. Sessions that use only built-in providers still use the
existing resource reload logic, which does not promise to re-resolve all provider configuration;
a full reload is not yet an atomic generation switch.

### Streaming and Acceptance

Deltas must be emitted during generation, the final `out` still provides the complete message,
and the host produces exactly one Done / Error. Cancellation must stop the request promptly and
keep partial output; calling `emit` after the synchronous request fn has returned is forbidden.
Use the bridge library to handle ABI string release, cancellation and the runtime lifecycle;
hand-written ABI code must follow the protocol described above.

Acceptance testing must include loading a real dynamic library, a gated test in which the local
SSE server continues sending only after the first content delta has arrived, UTF-8 split across
chunks, usage, a single terminal state, cancellation before the response has finished, and
HTTP 401; auth isolation, endpoint / request header overrides, the absence of auth headers in
the public catalog, commands and reload must also be verified. Tools and OAuth declare only the
capabilities whose verification has been completed.
Real API tests are ignored by default; when run explicitly, they inject the key from the
environment and limit timeouts, retries and usage.
The official unified package lives in the separate [evo-package project](https://github.com/evoelsewhere/evo-package/tree/feature-1014/packages/evo-providers);
it keeps the `deepseek` ID, declares `DEEPSEEK_API_KEY`, and supports tool continuation turns
through `requiresReasoningContent`.

Run the official package's offline verification in the evo-package repository:

```sh
cd /path/to/evo-package
cargo build -p evo-providers
cargo test -p evo-providers --test streaming
cargo test -p evo-providers --test host
```

When running the CLI integration tests in the evo-harness repository, set
`EVO_TEST_PROVIDER_LIBRARY` and `EVO_TEST_PROVIDER_PACKAGE`, then run:

```sh
cargo test -p evo-cli --test provider_packages
```

A new package must also build and test its own dynamic library; it cannot claim the integration
is complete merely because the host tests pass.
