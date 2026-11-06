//! Hooks for this session (`evo-hooks`): which ones apply, and the points
//! where the engine runs them.
//!
//! * `SessionStart` — when the engine starts; its context goes with the first
//!   prompt.
//! * `UserPromptSubmit` — before a prompt runs: a hook can block it, or add
//!   context (sent with the prompt in a `<hook-context>` block).
//! * `PreToolUse` — before a tool runs (`before_tool_call`): block it (the
//!   reason becomes the tool's error), ask the person first (the same
//!   approval prompt extensions use), allow it, or rewrite its input.
//! * `PostToolUse` / `PostToolUseFailure` — after it ran (`after_tool_call`):
//!   feedback and context are added to the tool's result.
//! * `Stop` — when a run ends; `SessionEnd` — when the engine shuts down.
//!
//! Hooks come from `hooks` in `~/.evo/agent/settings.json` and, when the
//! project is trusted, `.evo/settings.json`. `disableAllHooks: true` (user
//! settings) turns them all off. The tool-call hooks are installed when the
//! session starts with hooks for those events; the others follow the
//! settings as they are now (RPC `reload_resources`).

use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock, RwLock};
use std::time::Duration;

use evo_hooks::{Hooks, Outcome, RunRecord};
use serde_json::{json, Value};

/// Runs kept for Customize → Hooks.
const RECENT: usize = 100;

struct Runtime {
    cwd: PathBuf,
    trusted: bool,
    session_id: Mutex<String>,
    hooks: RwLock<Hooks>,
    recent: Mutex<VecDeque<RunRecord>>,
    /// `SessionStart` context waiting for the first prompt.
    pending_context: Mutex<Vec<String>>,
}

static RUNTIME: OnceLock<Arc<Runtime>> = OnceLock::new();

/// The session's folder, once [`init`] ran.
pub fn cwd() -> Option<PathBuf> {
    RUNTIME.get().map(|rt| rt.cwd.clone())
}

/// Whether the session's folder is trusted (its project files are read).
pub fn trusted() -> bool {
    RUNTIME.get().is_some_and(|rt| rt.trusted)
}

fn user_settings() -> Option<PathBuf> {
    crate::config::settings_path().ok()
}

fn project_settings(cwd: &Path, trusted: bool) -> Option<PathBuf> {
    trusted.then(|| crate::resource_dirs::project_config_file(cwd, "settings.json"))
}

fn load(cwd: &Path, trusted: bool) -> Hooks {
    let mut hooks = load_settings(cwd, trusted);
    // Enabled plugins' hooks/hooks.json (and inline hooks).
    for (plugin, events) in crate::plugins::hooks() {
        hooks.add_events(&events, &format!("plugin:{plugin}"), &format!("plugin {plugin}"));
    }
    hooks
}

fn load_settings(cwd: &Path, trusted: bool) -> Hooks {
    Hooks::load(
        user_settings().as_deref(),
        project_settings(cwd, trusted).as_deref(),
    )
}

/// Load this session's hooks (once per engine process).
pub fn init(cwd: &Path, trusted: bool) {
    let _ = RUNTIME.set(Arc::new(Runtime {
        cwd: cwd.to_path_buf(),
        trusted,
        session_id: Mutex::new(String::new()),
        hooks: RwLock::new(load(cwd, trusted)),
        recent: Mutex::new(VecDeque::new()),
        pending_context: Mutex::new(Vec::new()),
    }));
}

pub fn set_session_id(id: &str) {
    if let Some(rt) = RUNTIME.get() {
        *rt.session_id.lock().unwrap() = id.to_string();
    }
}

/// Read the settings again.
pub fn reload() {
    if let Some(rt) = RUNTIME.get() {
        *rt.hooks.write().unwrap() = load(&rt.cwd, rt.trusted);
    }
}

/// Whether any hook is configured for `event` (and hooks are on).
pub fn has(event: &str) -> bool {
    RUNTIME.get().is_some_and(|rt| {
        let hooks = rt.hooks.read().unwrap();
        !hooks.disabled && hooks.entries.iter().any(|e| e.event == event)
    })
}

/// Run `event`'s hooks with `input`; records the runs.
pub async fn run(event: &str, target: Option<&str>, mut input: Value) -> Outcome {
    let Some(rt) = RUNTIME.get().cloned() else {
        return Outcome::default();
    };
    let hooks = rt.hooks.read().unwrap().clone();
    if let Some(object) = input.as_object_mut() {
        object.insert("session_id".into(), json!(*rt.session_id.lock().unwrap()));
    }
    let outcome = evo_hooks::run_event(&hooks, event, target, input, &rt.cwd).await;
    if !outcome.records.is_empty() {
        let mut recent = rt.recent.lock().unwrap();
        for record in &outcome.records {
            if recent.len() >= RECENT {
                recent.pop_front();
            }
            recent.push_back(record.clone());
        }
    }
    for message in &outcome.messages {
        tracing::info!(event, "hook: {message}");
    }
    outcome
}

/// Everything for Customize → Hooks: the hooks, problems, and recent runs.
pub fn describe() -> Value {
    let Some(rt) = RUNTIME.get() else {
        return json!({ "entries": [], "disabled": false, "problems": [], "recent": [], "events": evo_hooks::EVENTS });
    };
    let hooks = rt.hooks.read().unwrap();
    let recent: Vec<RunRecord> = rt.recent.lock().unwrap().iter().rev().cloned().collect();
    json!({
        "entries": hooks.entries,
        "disabled": hooks.disabled,
        "problems": hooks.problems,
        "recent": recent,
        "events": evo_hooks::EVENTS,
        "userSettings": user_settings(),
        "projectSettings": project_settings(&rt.cwd, rt.trusted),
    })
}

/// Turn every hook off (or back on) in user settings.
pub fn set_disabled(disabled: bool) -> Result<(), String> {
    crate::settings::update_settings_value(|settings| {
        if disabled {
            settings.insert("disableAllHooks".into(), json!(true));
        } else {
            settings.remove("disableAllHooks");
        }
    })?;
    reload();
    Ok(())
}

// ── Session start / prompt / stop / end ─────────────────────────────────────

/// `SessionStart`: context is kept for the first prompt.
pub async fn session_start(source: &str) {
    if !has("SessionStart") {
        return;
    }
    let outcome = run("SessionStart", None, json!({ "source": source })).await;
    if let Some(rt) = RUNTIME.get() {
        rt.pending_context.lock().unwrap().extend(outcome.context);
    }
}

/// `UserPromptSubmit` for `text`: `Err(reason)` when a hook blocks it,
/// otherwise the context to send along (with any `SessionStart` context).
pub async fn prompt_submit(text: &str) -> Result<Vec<String>, String> {
    let mut context: Vec<String> = RUNTIME
        .get()
        .map(|rt| std::mem::take(&mut *rt.pending_context.lock().unwrap()))
        .unwrap_or_default();
    if has("UserPromptSubmit") {
        let outcome = run("UserPromptSubmit", None, json!({ "prompt": text })).await;
        if let Some(reason) = outcome.block.or(outcome.stop) {
            return Err(reason);
        }
        context.extend(outcome.context);
    }
    Ok(context)
}

/// The block the context rides in, after the prompt.
pub fn context_block(context: &[String]) -> Option<String> {
    (!context.is_empty())
        .then(|| format!("<hook-context>\n{}\n</hook-context>", context.join("\n\n")))
}

/// `Stop`, after a run (in the background).
pub fn stop(outcome: &str) {
    if !has("Stop") {
        return;
    }
    let outcome = outcome.to_string();
    tokio::spawn(async move {
        run(
            "Stop",
            None,
            json!({ "outcome": outcome, "stop_hook_active": false }),
        )
        .await;
    });
}

/// `SessionEnd`, with a short budget (the engine is closing).
pub async fn session_end(reason: &str) {
    if !has("SessionEnd") {
        return;
    }
    let _ = tokio::time::timeout(
        Duration::from_millis(1500),
        run("SessionEnd", None, json!({ "reason": reason })),
    )
    .await;
}

// ── Tool calls ──────────────────────────────────────────────────────────────

/// Ask the person to allow a call (the approval prompt in the chat input).
async fn confirm(
    ui_dialog: &evo_extensions::UiDialogMailbox,
    tool_call_id: &str,
    tool: &str,
    reason: &str,
    signal: &tokio_util::sync::CancellationToken,
) -> bool {
    let request_id = format!("hook:{tool_call_id}");
    let opened = ui_dialog.handle(json!({
        "op": "open",
        "requestId": request_id,
        "toolCallId": tool_call_id,
        "ui": {
            "kind": "confirm",
            "title": format!("Allow {tool}?"),
            "description": reason,
            "options": [{ "title": "Allow" }, { "title": "Deny" }],
        },
    }));
    if opened.is_err() {
        // No one to ask (headless): a hook asking means no.
        return false;
    }
    loop {
        if signal.is_cancelled() {
            let _ = ui_dialog.cancel(&request_id);
            return false;
        }
        match ui_dialog.poll(&request_id) {
            Ok(state) => match state.get("status").and_then(Value::as_str) {
                Some("answered") => {
                    let answer = state.get("answer").cloned().unwrap_or(Value::Null);
                    let index = answer.get("index").and_then(Value::as_u64);
                    let value = answer.get("value").and_then(Value::as_str).unwrap_or("");
                    return index == Some(0) || value.eq_ignore_ascii_case("allow");
                }
                Some("cancelled") => return false,
                _ => {}
            },
            Err(_) => return false,
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
}

/// `PreToolUse` in front of the engine's other approval hook (`previous`).
/// Installed only when the session starts with `PreToolUse` hooks.
pub fn before_tool_call(
    previous: Option<evo_agent::BeforeToolCall>,
    ui_dialog: evo_extensions::UiDialogMailbox,
) -> Option<evo_agent::BeforeToolCall> {
    if !has("PreToolUse") {
        return previous;
    }
    Some(Arc::new(
        move |ctx: evo_agent::BeforeToolCallContext<'_>, signal| {
            let tool = ctx.tool_call.name.clone();
            let id = ctx.tool_call.id.clone();
            let args = ctx.args.clone();
            let earlier = previous.as_ref().map(|hook| hook(ctx, signal.clone()));
            let ui_dialog = ui_dialog.clone();
            Box::pin(async move {
                let input = json!({ "tool_name": tool, "tool_input": args, "tool_use_id": id });
                let outcome = run("PreToolUse", Some(&tool), input).await;
                let block = |reason: String| {
                    Some(evo_agent::BeforeToolCallResult {
                        block: true,
                        reason: Some(reason),
                        terminate: false,
                        args: None,
                    })
                };
                if let Some(reason) = outcome.block.or(outcome.stop) {
                    return block(format!("Blocked by a hook: {reason}"));
                }
                if let Some(reason) = outcome.ask.filter(|_| !outcome.allow) {
                    if !confirm(&ui_dialog, &id, &tool, &reason, &signal).await {
                        return block("The user declined this tool call.".into());
                    }
                }
                if let Some(earlier) = earlier {
                    if let Some(result) = earlier.await {
                        if result.block {
                            return Some(result);
                        }
                    }
                }
                outcome
                    .updated_input
                    .map(|input| evo_agent::BeforeToolCallResult {
                        block: false,
                        reason: None,
                        terminate: false,
                        args: Some(input),
                    })
            })
        },
    ))
}

fn result_text(result: &evo_agent::types::AgentToolResult) -> String {
    result
        .content
        .iter()
        .filter_map(|part| match part {
            evo_agent::types::TextContentOrImage::Text(text) => Some(text.text.as_str()),
            _ => None,
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// `PostToolUse` / `PostToolUseFailure`: a hook's feedback (`decision:
/// "block"` + reason) and context are added to the tool's result, and its
/// messages ride in the result's details for the app.
pub fn after_tool_call() -> Option<evo_agent::AfterToolCall> {
    if !has("PostToolUse") && !has("PostToolUseFailure") {
        return None;
    }
    Some(Arc::new(
        move |ctx: evo_agent::AfterToolCallContext<'_>, _signal| {
            let event = if ctx.is_error {
                "PostToolUseFailure"
            } else {
                "PostToolUse"
            };
            let tool = ctx.tool_call.name.clone();
            let input = json!({
                "tool_name": tool,
                "tool_input": ctx.args,
                "tool_use_id": ctx.tool_call.id,
                "tool_response": result_text(ctx.result),
                "is_error": ctx.is_error,
            });
            let content = ctx.result.content.clone();
            let details = ctx.result.details.clone();
            Box::pin(async move {
                let outcome = run(event, Some(&tool), input).await;
                let mut notes = Vec::new();
                if let Some(reason) = outcome.block {
                    notes.push(format!("Hook feedback: {reason}"));
                }
                notes.extend(outcome.context.iter().map(|c| format!("Hook context: {c}")));
                if notes.is_empty() && outcome.messages.is_empty() {
                    return None;
                }
                let mut content = content;
                if !notes.is_empty() {
                    content.push(evo_agent::types::TextContentOrImage::text(notes.join("\n")));
                }
                let mut details = if details.is_object() {
                    details
                } else {
                    json!({})
                };
                details["hooks"] =
                    json!({ "event": event, "messages": outcome.messages, "notes": notes });
                Some(evo_agent::types::AfterToolCallResult {
                    content: Some(content),
                    details: Some(details),
                    ..Default::default()
                })
            })
        },
    ))
}
