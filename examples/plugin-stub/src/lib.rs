//! `plugin-stub` — the example evo plugin, and the template to copy.
//!
//! A complete Rust `cdylib` built only on `evo-plugin-sdk`. It registers one of
//! each common capability through the unified `evo_plugin_register` entrypoint:
//!
//! | Registration                 | What it does                                          |
//! | ---------------------------- | ----------------------------------------------------- |
//! | tool `echo`                  | returns `echo: <text>` via execute → poll → destroy   |
//! | `echo` prompt metadata       | a prompt snippet and one usage rule                   |
//! | `MessageEnd` event handler   | counts assistant messages                             |
//! | `resources_discover` handler | advertises `plugin-stub-discovered/SKILL.md`          |
//! | `before_agent_start`         | appends a marker to the system prompt                 |
//! | provider `stub-provider`     | one-shot: answers `from-stub-provider`                |
//! | `stub-streaming-provider`    | streams thinking then text deltas                     |
//! | `stub-cancel-provider`       | streams slowly and stops when the run is cancelled    |
//! | markdown `stub-uppercase`    | uppercases rendered markdown                          |
//!
//! Every callback also bumps a process-global counter that the cdylib exports
//! as `plugin_stub_*` symbols, so a host-side smoke test can observe that the
//! real library ran (see `crates/evo-extensions/tests/plugin_stub_smoke.rs`).
//!
//! Ownership rules (see the SDK docs): strings the plugin produces are freed by
//! the host through the `free_string` passed at registration; strings the host
//! produces are freed by the plugin through the host's deallocator; nothing may
//! unwind across an `extern "C"` boundary. The SDK macros used below
//! (`execute_handler!`, `event_handler!`, `string_handler!`) take care of all
//! three, so the bodies here only deal with ordinary Rust strings.

// `export_plugin!` expands to a safe `pub extern "C" fn` taking the host's
// `*const PluginApi`; the ABI requires that signature, and the SDK validates
// the pointer before use.
#![allow(clippy::not_unsafe_ptr_arg_deref)]

use std::ffi::c_void;
use std::io::Write;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

use evo_plugin_sdk::callbacks::{free_string, Output};
use evo_plugin_sdk::{
    EventTag, PluginApi, ProviderChunkKind, ProviderStreamCompletionFn, ProviderStreamControl,
    ProviderStreamEmitFn, StableToolSchema, StbString, StbStringRef, StepHandle, StepResult,
    ToolPartialCb, EVENT_HANDLER_CONTINUE,
};
use serde_json::{json, Value};

/// The skill path the discovery handler advertises (relative to the cwd).
const DISCOVERED_SKILL: &str = "plugin-stub-discovered/SKILL.md";
/// The text the prompt transformer appends to the system prompt.
const PROMPT_MARKER: &str = "[plugin-stub says: the example plugin is loaded]";
const ONE_SHOT_PROVIDER: &str = "stub-provider";
const STREAMING_PROVIDER: &str = "stub-streaming-provider";
const CANCEL_PROVIDER: &str = "stub-cancel-provider";
const PROVIDER_BASE_URL: &str = "https://stub.example";
const PROVIDER_API_STYLE: &str = "faux";
/// How many deltas `stub-cancel-provider` produces when nobody cancels it.
const CANCEL_DELTA_BUDGET: usize = 200;

// Observation counters, read by the host smoke test through the exports below.
static MESSAGE_END_HITS: AtomicUsize = AtomicUsize::new(0);
static DISCOVER_HITS: AtomicUsize = AtomicUsize::new(0);
static PROMPT_TRANSFORM_HITS: AtomicUsize = AtomicUsize::new(0);
static PROVIDER_REQUEST_HITS: AtomicUsize = AtomicUsize::new(0);
static STREAM_EMIT_HITS: AtomicUsize = AtomicUsize::new(0);
static MARKDOWN_TRANSFORM_HITS: AtomicUsize = AtomicUsize::new(0);
static CANCEL_EMITS_BEFORE_STOP: AtomicUsize = AtomicUsize::new(0);
static CANCEL_OBSERVED: AtomicUsize = AtomicUsize::new(0);

// ---------------------------------------------------------------------------
// Entrypoint
// ---------------------------------------------------------------------------

// Emits `evo_plugin_register`. The SDK checks the ABI version and struct size
// before calling `register`, and turns a panic into a status code.
evo_plugin_sdk::export_plugin!(|api| match register(api) {
    Ok(()) => 0,
    Err(status) => status,
});

/// Turn a nonzero registrar status into an early return.
fn check(status: i32) -> Result<(), i32> {
    if status == 0 {
        Ok(())
    } else {
        Err(status)
    }
}

fn register(api: &PluginApi) -> Result<(), i32> {
    record_registration();

    // The echo tool is this plugin's reason to exist, so a host without the
    // tool slot is a load failure. Every other slot is optional: skip it on a
    // host that predates it rather than refusing to load.
    let register_tool = api.register_tool.ok_or(-1)?;
    let schema = StableToolSchema {
        name: StbString::from_string("echo".into()),
        description: StbString::from_string(
            "Echoes back the supplied text, prefixed with `echo: `.".into(),
        ),
        parameters: StbString::from_string(
            json!({
                "type": "object",
                "properties": {
                    "text": { "type": "string", "description": "The text to echo back" }
                },
                "required": ["text"]
            })
            .to_string(),
        ),
    };
    // The host copies the schema strings and frees them with `free_string`.
    check(register_tool(
        &schema,
        echo_execute,
        echo_poll,
        echo_cancel,
        echo_destroy,
        free_string,
    ))?;

    // Prompt metadata: the snippet listed in the system prompt's tool list and
    // a usage rule. Independent of the schema; must follow the tool.
    if let Some(register_prompt) = api.register_tool_prompt {
        check(register_prompt(
            StbStringRef::from_str("echo"),
            StbStringRef::from_str(
                r#"{"promptSnippet":"Echo the supplied text","promptGuidelines":["Use echo only when an echo is requested"]}"#,
            ),
        ))?;
    }

    // A fire-and-forget observer of every completed message.
    if let Some(register_event_handler) = api.register_event_handler {
        check(register_event_handler(
            EventTag::MessageEnd,
            on_message_end,
            std::ptr::null_mut(),
        ))?;
    }

    // Extra resources discovered at startup/reload.
    if let Some(register_discover) = api.register_resources_discover {
        check(register_discover(
            on_resources_discover,
            free_string,
            std::ptr::null_mut(),
        ))?;
    }

    // Runtime system-prompt transform (evo's `before_agent_start`).
    if let Some(register_prompt_transform) = api.register_before_agent_start {
        check(register_prompt_transform(
            on_before_agent_start,
            free_string,
            std::ptr::null_mut(),
        ))?;
    }

    // A one-shot provider: the whole message comes back from one call.
    if let Some(register_provider) = api.register_provider {
        check(register_provider(
            StbStringRef::from_str(ONE_SHOT_PROVIDER),
            StbStringRef::from_str(PROVIDER_BASE_URL),
            StbStringRef::from_str(PROVIDER_API_STYLE),
            on_provider_request,
            free_string,
            std::ptr::null_mut(),
        ))?;
    }

    // Two streaming providers registered through the same slot: one ignores
    // the cancellation control surface, the other polls it.
    if let Some(register_streaming) = api.register_streaming_provider {
        check(register_streaming(
            StbStringRef::from_str(STREAMING_PROVIDER),
            StbStringRef::from_str(PROVIDER_BASE_URL),
            StbStringRef::from_str(PROVIDER_API_STYLE),
            on_provider_stream_request,
            free_string,
            std::ptr::null_mut(),
        ))?;
        check(register_streaming(
            StbStringRef::from_str(CANCEL_PROVIDER),
            StbStringRef::from_str(PROVIDER_BASE_URL),
            StbStringRef::from_str(PROVIDER_API_STYLE),
            on_cancellable_provider_stream_request,
            free_string,
            std::ptr::null_mut(),
        ))?;
    }

    // A markdown transformer used when the TUI renders assistant text.
    if let Some(register_markdown) = api.register_markdown_transformer {
        check(register_markdown(
            StbStringRef::from_str("stub-uppercase"),
            on_markdown_transform,
            free_string,
            std::ptr::null_mut(),
        ))?;
    }

    Ok(())
}

/// Test hook: when `EVO_PLUGIN_STUB_REGISTRATION_LOG` names a file, append one
/// `register <source digest>` line per registration. The CLI's resource tests
/// use it to prove which build registered, and that rejected startups never
/// ran plugin code. The digest is stamped at build time by those tests.
fn record_registration() {
    let Some(path) = std::env::var_os("EVO_PLUGIN_STUB_REGISTRATION_LOG") else {
        return;
    };
    let digest = option_env!("EVO_RESOURCE_FIXTURE_SOURCE_SHA256").unwrap_or("unstamped");
    if let Ok(mut log) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        let _ = log.write_all(format!("register {digest}\n").as_bytes());
    }
}

// ---------------------------------------------------------------------------
// Tool `echo`: execute → poll → cancel → destroy
// ---------------------------------------------------------------------------

/// Per-call state behind the opaque `StepHandle`.
struct EchoCall {
    text: String,
    /// Set by `cancel` (any thread); observed by `poll`.
    cancelled: AtomicBool,
    /// Whether the first poll already reported progress.
    started: AtomicBool,
}

evo_plugin_sdk::execute_handler! {
    /// Parse the arguments and allocate this call's handle. `params` is the
    /// host's JSON, reclaimed when it goes out of scope. Read fields from a
    /// `Value`: the host also injects a reserved `__evo` key.
    fn echo_execute(_tool_call_id, params) {
        let params: Value = serde_json::from_str(&params.as_str_lossy()).unwrap_or(Value::Null);
        let text = params
            .get("text")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        let call = EchoCall {
            text,
            cancelled: AtomicBool::new(false),
            started: AtomicBool::new(false),
        };
        Box::into_raw(Box::new(call)) as StepHandle
    }
}

/// Non-blocking: the first poll reports progress, the second finishes. A real
/// tool would check a worker's state here instead.
extern "C" fn echo_poll(
    handle: StepHandle,
    _partial_cb: Option<ToolPartialCb>,
    _user_data: *mut c_void,
) -> StepResult {
    evo_plugin_sdk::guard(|| {
        if handle.is_null() {
            return error_step("echo: missing call handle");
        }
        // SAFETY: the host passes the handle from `echo_execute` and only
        // destroys it after the last poll.
        let call = unsafe { &*(handle as *const EchoCall) };
        if call.cancelled.load(Ordering::SeqCst) {
            return error_step("echo cancelled");
        }
        if !call.started.swap(true, Ordering::SeqCst) {
            return StepResult::pending(tool_result("echoing..."));
        }
        StepResult::done(tool_result(&format!("echo: {}", call.text)))
    })
    .unwrap_or_else(|_| error_step("echo poll panicked"))
}

/// Only sets the flag: idempotent, thread-safe, never frees.
extern "C" fn echo_cancel(handle: StepHandle) {
    if !handle.is_null() {
        // SAFETY: the handle stays live until `echo_destroy`.
        let call = unsafe { &*(handle as *const EchoCall) };
        call.cancelled.store(true, Ordering::SeqCst);
    }
}

/// Called exactly once by the host; frees the handle.
extern "C" fn echo_destroy(handle: StepHandle) {
    if !handle.is_null() {
        // SAFETY: the handle came from `Box::into_raw` in `echo_execute`.
        drop(unsafe { Box::from_raw(handle as *mut EchoCall) });
    }
}

/// A plugin-owned JSON `AgentToolResult` with one text block.
fn tool_result(text: &str) -> StbString {
    StbString::from_string(json!({ "content": [{ "type": "text", "text": text }] }).to_string())
}

fn error_step(message: &str) -> StepResult {
    StepResult::err(StbString::from_string(message.to_owned()))
}

// ---------------------------------------------------------------------------
// Event handler, resource discovery, prompt transform, markdown transform
// ---------------------------------------------------------------------------

evo_plugin_sdk::event_handler! {
    /// Event buffers are borrowed for the call: read them, never free them.
    fn on_message_end(_event, _user_data) {
        MESSAGE_END_HITS.fetch_add(1, Ordering::SeqCst);
        EVENT_HANDLER_CONTINUE
    }
}

evo_plugin_sdk::string_handler! {
    /// Return `{skillPaths, promptPaths, themePaths}`; every field is optional.
    fn on_resources_discover((_cwd, _reason), out, _user_data) {
        DISCOVER_HITS.fetch_add(1, Ordering::SeqCst);
        let found = json!({ "skillPaths": [DISCOVERED_SKILL] });
        i32::from(!out.write(found.to_string()))
    }
}

evo_plugin_sdk::string_handler! {
    /// The returned prompt *replaces* the current one, so append explicitly.
    fn on_before_agent_start(event_json, out, _user_data) {
        PROMPT_TRANSFORM_HITS.fetch_add(1, Ordering::SeqCst);
        let event: Value = serde_json::from_str(event_json).unwrap_or(Value::Null);
        let current = event
            .get("systemPrompt")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let next = if current.is_empty() {
            PROMPT_MARKER.to_owned()
        } else {
            format!("{current}\n\n{PROMPT_MARKER}")
        };
        i32::from(!out.write(json!({ "systemPrompt": next }).to_string()))
    }
}

evo_plugin_sdk::string_handler! {
    /// `{"markdown": "..."}` in, `{"markdown": "..."}` out.
    fn on_markdown_transform(input, out, _user_data) {
        MARKDOWN_TRANSFORM_HITS.fetch_add(1, Ordering::SeqCst);
        let input: Value = serde_json::from_str(input).unwrap_or(Value::Null);
        let Some(markdown) = input.get("markdown").and_then(Value::as_str) else {
            return 1;
        };
        i32::from(!out.write(json!({ "markdown": markdown.to_uppercase() }).to_string()))
    }
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

evo_plugin_sdk::string_handler! {
    /// One-shot provider: `request` is the borrowed `{model, context, options,
    /// capabilities}` envelope; `out` receives the final `AssistantMessage`.
    fn on_provider_request(request, out, _user_data) {
        PROVIDER_REQUEST_HITS.fetch_add(1, Ordering::SeqCst);
        let request: Value = serde_json::from_str(request).unwrap_or(Value::Null);
        let content = json!([{ "type": "text", "text": "from-stub-provider" }]);
        i32::from(!out.write(assistant_message(ONE_SHOT_PROVIDER, &request, content)))
    }
}

/// Streaming provider that does not poll for cancellation: it pushes its
/// deltas through `emit` while "generating", then returns the final message.
/// The host still stops forwarding and ends the turn if the run is cancelled.
#[allow(clippy::too_many_arguments)]
extern "C" fn on_provider_stream_request(
    req_json: StbStringRef,
    emit: Option<ProviderStreamEmitFn>,
    emit_user_data: *mut c_void,
    _control: *const ProviderStreamControl,
    _completion: Option<ProviderStreamCompletionFn>,
    _completion_user_data: *mut c_void,
    out: *mut StbString,
    _user_data: *mut c_void,
) -> i32 {
    evo_plugin_sdk::guard_or(1, || {
        let request = parse_request(req_json);
        // `emit` is None only on a host that cannot take chunks; the final
        // message below is then the whole answer.
        if let Some(emit) = emit {
            for chunk in [
                json!({ "type": "start" }),
                json!({ "type": "thinking_start", "contentIndex": 0 }),
                json!({ "type": "thinking_delta", "contentIndex": 0, "delta": "weighing" }),
                json!({ "type": "thinking_delta", "contentIndex": 0, "delta": " options" }),
                json!({ "type": "thinking_end", "contentIndex": 0 }),
                json!({ "type": "text_start", "contentIndex": 1 }),
                json!({ "type": "text_delta", "contentIndex": 1, "delta": "from-stub" }),
                json!({ "type": "text_delta", "contentIndex": 1, "delta": "-stream" }),
                json!({ "type": "text_end", "contentIndex": 1 }),
            ] {
                send_chunk(emit, emit_user_data, chunk);
            }
        }
        // The deltas only drive rendering; `out` is still the full message.
        let content = json!([
            { "type": "thinking", "thinking": "weighing options" },
            { "type": "text", "text": "from-stub-stream" }
        ]);
        let message = assistant_message(STREAMING_PROVIDER, &request, content);
        // SAFETY: the host passes an exclusive output slot valid for this call.
        let mut out = unsafe { Output::from_raw(out) };
        i32::from(!out.write(message))
    })
}

/// Streaming provider that polls the control surface between deltas, the way a
/// real provider waits on its socket, and stops as soon as the run is cancelled.
#[allow(clippy::too_many_arguments)]
extern "C" fn on_cancellable_provider_stream_request(
    req_json: StbStringRef,
    emit: Option<ProviderStreamEmitFn>,
    emit_user_data: *mut c_void,
    control: *const ProviderStreamControl,
    _completion: Option<ProviderStreamCompletionFn>,
    _completion_user_data: *mut c_void,
    out: *mut StbString,
    _user_data: *mut c_void,
) -> i32 {
    evo_plugin_sdk::guard_or(1, || {
        let request = parse_request(req_json);
        // SAFETY: `control` is null or valid for the duration of this call. A
        // null control means the host cannot cancel: just run to completion.
        let control = unsafe { control.as_ref() }.copied();
        let mut text = String::new();
        if let Some(emit) = emit {
            send_chunk(emit, emit_user_data, json!({ "type": "start" }));
            send_chunk(
                emit,
                emit_user_data,
                json!({ "type": "text_start", "contentIndex": 0 }),
            );
            for i in 0..CANCEL_DELTA_BUDGET {
                // Blocks up to 10 ms but returns at once when cancelled.
                if let Some(control) = control {
                    if (control.wait_cancelled_ms)(control.user_data, 10) != 0 {
                        CANCEL_OBSERVED.store(1, Ordering::SeqCst);
                        return 1; // The caller is gone: stop generating.
                    }
                }
                let delta = format!("tick {i} ");
                let chunk = json!({ "type": "text_delta", "contentIndex": 0, "delta": delta });
                if send_chunk(emit, emit_user_data, chunk) != 0 {
                    // A rejected content chunk means the run was cancelled (or
                    // the host refused the chunk): stop either way.
                    if control.is_some_and(|control| {
                        (control.is_cancelled)(control.user_data, ProviderChunkKind::Content as u32)
                            != 0
                    }) {
                        CANCEL_OBSERVED.store(1, Ordering::SeqCst);
                    }
                    return 1;
                }
                CANCEL_EMITS_BEFORE_STOP.fetch_add(1, Ordering::SeqCst);
                text.push_str(&delta);
            }
            send_chunk(
                emit,
                emit_user_data,
                json!({ "type": "text_end", "contentIndex": 0 }),
            );
        }
        let content = json!([{ "type": "text", "text": text }]);
        let message = assistant_message(CANCEL_PROVIDER, &request, content);
        // SAFETY: the host passes an exclusive output slot valid for this call.
        let mut out = unsafe { Output::from_raw(out) };
        i32::from(!out.write(message))
    })
}

/// Hand one chunk to the host. Ownership passes with it: the host frees the
/// string through the `free_string` registered with the provider.
fn send_chunk(emit: ProviderStreamEmitFn, user_data: *mut c_void, chunk: Value) -> i32 {
    STREAM_EMIT_HITS.fetch_add(1, Ordering::SeqCst);
    emit(StbString::from_string(chunk.to_string()), user_data)
}

/// Copy the borrowed request envelope into a `Value`.
fn parse_request(req_json: StbStringRef) -> Value {
    // SAFETY: the host keeps the borrowed envelope live for the whole call.
    serde_json::from_str(unsafe { req_json.as_str() }).unwrap_or(Value::Null)
}

/// A complete `AssistantMessage` JSON for the requested model.
fn assistant_message(provider: &str, request: &Value, content: Value) -> String {
    let model = &request["model"];
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |elapsed| elapsed.as_millis() as i64);
    json!({
        "role": "assistant",
        "content": content,
        "api": model.get("api").cloned().unwrap_or_else(|| json!(PROVIDER_API_STYLE)),
        "provider": provider,
        "model": model.get("id").and_then(Value::as_str).unwrap_or_default(),
        "usage": {
            "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0,
            "cost": { "input": 0.0, "output": 0.0, "cacheRead": 0.0, "cacheWrite": 0.0, "total": 0.0 }
        },
        "stopReason": "stop",
        "timestamp": timestamp,
    })
    .to_string()
}

// ---------------------------------------------------------------------------
// Test observation exports
// ---------------------------------------------------------------------------

/// Export `extern "C" fn() -> usize` readers for the counters above.
macro_rules! export_counters {
    ($($symbol:ident => $counter:ident),* $(,)?) => {
        $(
            #[no_mangle]
            pub extern "C" fn $symbol() -> usize {
                $counter.load(Ordering::SeqCst)
            }
        )*
    };
}

export_counters! {
    plugin_stub_message_end_hits => MESSAGE_END_HITS,
    plugin_stub_discover_hits => DISCOVER_HITS,
    plugin_stub_prompt_transform_hits => PROMPT_TRANSFORM_HITS,
    plugin_stub_provider_request_hits => PROVIDER_REQUEST_HITS,
    plugin_stub_stream_emit_hits => STREAM_EMIT_HITS,
    plugin_stub_markdown_transform_hits => MARKDOWN_TRANSFORM_HITS,
    plugin_stub_cancel_emits_before_stop => CANCEL_EMITS_BEFORE_STOP,
    plugin_stub_cancel_observed => CANCEL_OBSERVED,
}

/// Reset the `stub-cancel-provider` counters before a cancellation scenario.
#[no_mangle]
pub extern "C" fn plugin_stub_reset_cancel_counters() {
    CANCEL_EMITS_BEFORE_STOP.store(0, Ordering::SeqCst);
    CANCEL_OBSERVED.store(0, Ordering::SeqCst);
}
