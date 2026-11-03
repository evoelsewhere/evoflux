//! One Work lead turn: the path of `AgentTeam.handle_user_message`,
//! `TeamMember._run_activation` / `_handle_messages`, `Agent.run`
//! (app/agent/agent_loop/core.py), `stream_and_assemble` (streaming.py), the
//! tool executor (tool_executor.py), `StreamPublisherHook` and the
//! `SQLiteCheckpointer`, with the SSE events in Python's order.
//!
//! Not ported (KNOWN_DIFFERENCES): hooks (title, memory, summarization,
//! prefix snapshot, telemetry), modes and delegation, MCP, skills, permission
//! prompts, checkpoints, queued messages, provider fallback and the delayed
//! rate-limit re-activation.

use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Instant;

use evoflux_area_providers::retry::{stream_with_retry, RetryItem, Target};
use evoflux_area_providers::{
    provider_for, ChatRequest, Message, ProviderError, ProviderEvent, ToolCall, ToolSpec, Usage,
};
use evoflux_area_tools::{read_only_tools, Tool, ToolCtx};
use futures_util::StreamExt;
use serde_json::{json, Map, Value};
use tokio_util::sync::CancellationToken;

use crate::agent::{turn_settings, wire_model, LeadAgent};
use crate::store::{self, MessageRow};
use crate::usage::{self, TurnUsage};
use crate::ChatState;

/// The usage fields `StreamPublisherHook` compares to skip a repeated block.
type UsageKey = (i64, i64, i64, Option<i64>, Option<i64>);

/// `MAX_AGENT_ITERATIONS`.
const MAX_ITERATIONS: usize = 5000;
/// `max_empty_after_tool_continuations`.
const MAX_EMPTY_AFTER_TOOL: usize = 3;
/// Largest tool-call arguments text echoed in `tool_start` and stored for later
/// turns (Python has no cap; KNOWN_DIFFERENCES).
const MAX_ECHOED_ARGS_BYTES: usize = 1 << 20;

/// The arguments text to publish and persist: as is up to the cap, else a
/// valid JSON marker so a later request to the provider stays well-formed.
fn echoed_args(args: &str) -> std::borrow::Cow<'_, str> {
    if args.len() <= MAX_ECHOED_ARGS_BYTES {
        return std::borrow::Cow::Borrowed(args);
    }
    std::borrow::Cow::Owned(json!({"truncated": true, "original_bytes": args.len()}).to_string())
}

/// The built-in tools of the Python lead that this server does not run. A
/// call to one ends the turn; any other unknown name gets Python's
/// not-found result and the loop goes on.
pub(crate) const PYTHON_ONLY_TOOLS: [&str; 35] = [
    "todo_manage",
    "schedule_task",
    "note",
    "ask_user",
    "browser_use",
    "computer_app",
    "document_preview",
    "edit",
    "get_goal",
    "image_search",
    "memory_search",
    "motion_progress",
    "motion_review",
    "patch",
    "preview",
    "process",
    "python",
    "rm",
    "shell",
    "show_widget",
    "ui_block",
    "update_goal",
    "visual_artifact",
    "visualize_read_me",
    "web_fetch",
    "web_search",
    "write",
    "team_message",
    "team_handoff",
    "team_state",
    "sleep",
    "team_manage",
    "team_delegate",
    "team_reject",
    "team_worktree",
];

/// What the request carried for this turn.
pub(crate) struct TurnInput {
    /// Stored (hex) and API (dashed) session ids.
    pub sid_hex: String,
    pub sid: String,
    pub content: String,
    pub lead: LeadAgent,
    /// `Some(value)` when the form named the field (an empty value clears it).
    pub model: Option<Option<String>>,
    pub thinking_level: Option<Option<String>>,
    pub workspace: Option<String>,
    pub cancel: CancellationToken,
}

/// Why a turn stopped early.
enum Failure {
    Provider(ProviderError),
    /// `ToolNotFoundError` for a Python tool this server does not run.
    ToolNotPorted(String),
    /// `AgentLoopError` after repeated empty replies.
    EmptyLoop,
    /// No model on the session or the agent.
    NoModel,
}

struct Turn {
    state: Arc<ChatState>,
    input: TurnInput,
    started: Instant,
    usage: Arc<Mutex<TurnUsage>>,
    /// The first user message, until its title request starts (`TitleGenerationHook`).
    title_pending: Option<String>,
    settings: Option<evoflux_core::config::Settings>,
    tools: Vec<Arc<dyn Tool>>,
}

/// `duration_ms` as Python rounds it: `round(seconds * 1000, 3)`.
fn ms_since(start: Instant) -> f64 {
    (start.elapsed().as_secs_f64() * 1_000_000.0).round() / 1000.0
}

fn status(agent: &str, status: &str, metadata: Value) -> Value {
    json!({"type": "agent_status", "agent": agent, "status": status, "metadata": metadata})
}

/// History rows as the provider schema (`_deserialize_messages`).
fn to_message(row: &MessageRow) -> Option<Message> {
    match row.role.as_str() {
        "user" => Some(Message::User {
            content: row.content.clone(),
            parts: None,
        }),
        "assistant" => Some(Message::Assistant {
            content: row.content.clone(),
            reasoning_content: row.reasoning_content.clone(),
            tool_calls: row
                .tool_calls
                .as_ref()
                .and_then(|calls| serde_json::from_value::<Vec<ToolCall>>(calls.clone()).ok())
                .filter(|calls| !calls.is_empty()),
        }),
        "tool" => Some(Message::Tool {
            content: row.content.clone(),
            tool_call_id: row.tool_call_id.clone().unwrap_or_default(),
            name: row.name.clone(),
            parts: None,
        }),
        _ => None,
    }
}

/// `_merge_consecutive_user_messages`.
fn merge_user_messages(messages: Vec<Message>) -> Vec<Message> {
    let mut merged: Vec<Message> = Vec::with_capacity(messages.len());
    for message in messages {
        if let (
            Message::User {
                content: Some(next),
                parts: None,
            },
            Some(Message::User {
                content: prev,
                parts: None,
            }),
        ) = (&message, merged.last_mut())
        {
            let joined = format!("{}\n\n{}", prev.as_deref().unwrap_or_default(), next);
            *prev = Some(joined.trim().to_owned());
            continue;
        }
        merged.push(message);
    }
    merged
}

/// The system prompt: the agent file's prompt text. Python composes a much
/// larger prompt from hooks and skills (KNOWN_DIFFERENCES).
fn system_prompt(lead: &LeadAgent) -> String {
    if lead.prompt.is_empty() {
        format!("You are {}, the user's assistant in EvoFlux.", lead.name)
    } else {
        lead.prompt.clone()
    }
}

/// The `tool_calls` column / message shape (`ToolCall.model_dump()`).
fn tool_calls_json(calls: &[(String, String, String)]) -> Value {
    Value::Array(
        calls
            .iter()
            .map(|(id, name, args)| {
                json!({
                    "id": id,
                    "type": "function",
                    "function": {"name": name, "arguments": echoed_args(args), "thought": null, "thought_signature": null},
                })
            })
            .collect(),
    )
}

/// Releases the session when the turn task ends, including by a panic, so the
/// session does not answer 409 forever and its stream readers end.
struct TurnGuard {
    state: Arc<ChatState>,
    sid: String,
}

impl Drop for TurnGuard {
    fn drop(&mut self) {
        if std::thread::panicking() {
            self.state.store.mark_done(&self.sid);
        }
        self.state.finish_turn(&self.sid);
    }
}

pub(crate) async fn run(state: Arc<ChatState>, input: TurnInput) {
    let started = Instant::now();
    let _guard = TurnGuard {
        state: state.clone(),
        sid: input.sid.clone(),
    };
    let mut turn = Turn {
        state,
        input,
        started,
        usage: Arc::new(Mutex::new(TurnUsage::default())),
        title_pending: None,
        settings: None,
        tools: read_only_tools(),
    };
    turn.go().await;
}

impl Turn {
    fn push(&self, event: &str, data: Value) {
        self.state.store.push(&self.input.sid, event, &data);
    }

    fn usage(&self) -> MutexGuard<'_, TurnUsage> {
        self.usage.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// Start the title request once (`TitleGenerationHook._spawn_pending`).
    fn spawn_title(&mut self, model: &str) {
        let (Some(text), Some(settings)) = (self.title_pending.take(), self.settings.clone())
        else {
            return;
        };
        let job = crate::title::TitleJob {
            sid: self.input.sid.clone(),
            sid_hex: self.input.sid_hex.clone(),
            agent: self.input.lead.name.clone(),
            model: model.to_owned(),
            user_text: text,
        };
        tokio::spawn(crate::title::generate_and_save(
            self.state.clone(),
            settings,
            self.usage.clone(),
            job,
        ));
    }

    fn agent(&self) -> &str {
        &self.input.lead.name
    }

    async fn go(&mut self) {
        self.persist_user_message().await;
        self.state.store.init_turn(&self.input.sid, true);
        self.push("agent_status", status(self.agent(), "working", json!({})));
        let outcome = self.agent_loop().await;
        match outcome {
            Ok(()) => self.push("agent_status", status(self.agent(), "idle", json!({}))),
            Err(failure) => self.fail(failure),
        }
        self.finish().await;
    }

    /// The user-message transaction of `handle_user_message`.
    async fn persist_user_message(&self) {
        let Some(db) = self.state.db.clone() else {
            return;
        };
        let sid = self.input.sid_hex.clone();
        let workspace = self.input.workspace.clone();
        let model = self.input.model.clone();
        let thinking = self.input.thinking_level.clone();
        let agent_model = self.input.lead.model.clone();
        let content = self.input.content.clone();
        let now = store::now_db();
        let id = store::uuid7_hex();
        let result = db
            .write(move |tx| {
                store::touch_session_for_turn(
                    tx,
                    &sid,
                    workspace.as_deref(),
                    model.as_ref().map(|m| m.as_deref()),
                    thinking.as_ref().map(|t| t.as_deref()),
                    &now,
                )?;
                let row = store::get_session(tx, &sid)?;
                let effective = row
                    .as_ref()
                    .and_then(|r| r.model.clone())
                    .or_else(|| agent_model.clone());
                let mut extra = Map::new();
                extra.insert("model".into(), json!(effective));
                if let Some(level) = row.and_then(|r| r.thinking_level) {
                    extra.insert("thinking_level".into(), json!(level));
                }
                store::insert_message(
                    tx,
                    &MessageRow {
                        id: id.clone(),
                        session_id: sid.clone(),
                        role: "user".into(),
                        content: Some(content.clone()),
                        extra: Some(Value::Object(extra)),
                        created_at: now.clone(),
                        ..MessageRow::default()
                    },
                )
            })
            .await;
        if let Err(error) = result {
            tracing::warn!(%error, "team_save_user_message_failed");
        }
    }

    async fn agent_loop(&mut self) -> Result<(), Failure> {
        let (mut history, session) = self.load().await;
        // `TitleGenerationHook.before_agent`: only a session's first turn.
        if !history.iter().any(|r| r.role == "assistant") {
            self.title_pending = history
                .iter()
                .rev()
                .filter(|r| r.role == "user")
                .find_map(|r| r.content.clone().filter(|c| !c.is_empty()))
                .filter(|c| !c.starts_with("[Scheduled Task:"));
        }
        let runtime_model = history
            .iter()
            .rev()
            .filter(|r| r.role == "user")
            .find_map(|r| {
                r.extra
                    .as_ref()?
                    .get("model")?
                    .as_str()
                    .filter(|m| !m.is_empty())
                    .map(str::to_owned)
            })
            .or_else(|| session.as_ref().and_then(|s| s.model.clone()))
            .or_else(|| self.input.lead.model.clone());
        let thinking_level = session
            .as_ref()
            .and_then(|s| s.thinking_level.clone())
            .or_else(|| self.input.lead.thinking_level.clone());
        let workspace_root = match session.as_ref().and_then(|s| s.workspace.clone()) {
            Some(workspace) => std::path::PathBuf::from(workspace),
            None => self.state.settings.workspace_dir.join(&self.input.sid),
        };
        self.push(
            "agent_status",
            status(self.agent(), "working", json!({"phase": "model_calling"})),
        );
        let model = runtime_model.ok_or(Failure::NoModel)?;
        let settings = turn_settings(&self.state.settings).await;
        let provider = provider_for(&settings, &model).map_err(Failure::Provider)?;
        self.settings = Some(settings);
        let target = Target {
            provider,
            label: model.clone(),
        };
        let specs: Vec<ToolSpec> = self
            .tools
            .iter()
            .filter_map(|t| serde_json::from_value(t.spec()).ok())
            .collect();
        let options = match &thinking_level {
            Some(level) => json!({"thinking_level": level}),
            None => Value::Null,
        };
        let ctx = ToolCtx {
            workspace_root,
            session_id: self.input.sid.clone(),
            denied_patterns: evoflux_area_tools::load_denied_patterns(
                self.state.settings.config_dir.clone(),
            )
            .await,
        };
        let mut empty_after_tool = 0;
        let mut last_assistant: Option<(String, Value)> = None;
        for _ in 0..MAX_ITERATIONS {
            if self.input.cancel.is_cancelled() {
                break;
            }
            let mut messages = vec![Message::System {
                content: Some(system_prompt(&self.input.lead)),
            }];
            messages.extend(history.iter().filter_map(to_message));
            let req = ChatRequest {
                model: model.clone(),
                messages: merge_user_messages(messages),
                tools: specs.clone(),
                options: options.clone(),
            };
            let call = self.stream_call(&target, req, &model).await?;
            let has_payload = !call.content.trim().is_empty()
                || !call.reasoning.trim().is_empty()
                || !call.tool_calls.is_empty();
            let previous_was_tool = history.last().is_some_and(|r| r.role == "tool");
            if !has_payload && previous_was_tool && !call.interrupted {
                empty_after_tool += 1;
                if empty_after_tool < MAX_EMPTY_AFTER_TOOL {
                    continue;
                }
                return Err(Failure::EmptyLoop);
            } else if has_payload {
                empty_after_tool = 0;
            }

            let mut extra = Map::new();
            if let Some(u) = &call.usage {
                extra.insert("usage".into(), usage::usage_to_dict(u));
            }
            extra.insert("duration_ms".into(), json!(ms_since(self.started)));
            extra.insert("model".into(), json!(model));
            if let Some(snapshot) = call.turn_usage_before {
                extra.insert("turn_usage".into(), snapshot);
            }
            let row = MessageRow {
                id: store::uuid7_hex(),
                session_id: self.input.sid_hex.clone(),
                role: "assistant".into(),
                content: (!call.content.is_empty()).then(|| call.content.clone()),
                reasoning_content: (!call.reasoning.is_empty()).then(|| call.reasoning.clone()),
                tool_calls: (!call.tool_calls.is_empty())
                    .then(|| tool_calls_json(&call.tool_calls)),
                extra: Some(Value::Object(extra.clone())),
                created_at: store::now_db(),
                ..MessageRow::default()
            };
            if has_payload {
                self.save(vec![row.clone()]).await;
                self.state
                    .store
                    .commit_agent_content(&self.input.sid, self.agent());
                last_assistant = Some((row.id.clone(), Value::Object(extra)));
            }
            history.push(row);
            if call.interrupted || call.tool_calls.is_empty() {
                break;
            }

            let mut tool_rows = Vec::new();
            let mut not_ported: Option<String> = None;
            for (id, name, args) in &call.tool_calls {
                if self.input.cancel.is_cancelled() {
                    break;
                }
                let started = Instant::now();
                self.push(
                    "tool_start",
                    json!({"type": "tool_start", "agent": self.agent(), "tool_call_id": id, "name": name, "arguments": echoed_args(args), "metadata": {}}),
                );
                let result = match self.tools.iter().find(|t| t.name() == name) {
                    Some(tool) => {
                        let parsed = serde_json::from_str::<Value>(args).unwrap_or(json!({}));
                        tool.call(parsed, &ctx).await.content
                    }
                    None => {
                        if not_ported.is_none() && PYTHON_ONLY_TOOLS.contains(&name.as_str()) {
                            not_ported = Some(name.clone());
                        }
                        format!("Error: Tool '{name}' not found.")
                    }
                };
                let duration = ms_since(started);
                self.push(
                    "tool_end",
                    json!({"type": "tool_end", "agent": self.agent(), "tool_call_id": id, "name": name,
                           "result": (!result.is_empty()).then_some(&result), "metadata": {"duration_ms": duration}}),
                );
                let row = MessageRow {
                    id: store::uuid7_hex(),
                    session_id: self.input.sid_hex.clone(),
                    role: "tool".into(),
                    content: Some(result),
                    tool_call_id: Some(id.clone()),
                    name: Some(name.clone()),
                    extra: Some(json!({"duration_ms": duration})),
                    created_at: store::now_db(),
                    ..MessageRow::default()
                };
                tool_rows.push(row);
            }
            self.save(tool_rows.clone()).await;
            history.extend(tool_rows);
            if let Some(name) = not_ported {
                return Err(Failure::ToolNotPorted(name));
            }
        }
        // `after_agent`: the final turn total goes on the last reply.
        let final_usage = self.usage().snapshot();
        if let (Some((id, mut extra)), Some(snapshot)) = (last_assistant, final_usage) {
            if let Value::Object(map) = &mut extra {
                map.insert("turn_usage".into(), snapshot);
            }
            if let Some(db) = self.state.db.clone() {
                if let Err(error) = db
                    .write(move |tx| store::update_message_extra(tx, &id, &extra))
                    .await
                {
                    tracing::warn!(%error, "checkpointer_sync_failed");
                }
            }
        }
        Ok(())
    }

    async fn load(&self) -> (Vec<MessageRow>, Option<store::SessionRow>) {
        let Some(db) = self.state.db.clone() else {
            return (Vec::new(), None);
        };
        let sid = self.input.sid_hex.clone();
        match db
            .read(move |conn| {
                Ok((
                    store::llm_rows(conn, &sid)?,
                    store::get_session(conn, &sid)?,
                ))
            })
            .await
        {
            Ok(loaded) => loaded,
            Err(error) => {
                tracing::warn!(%error, "load_llm_messages_failed");
                (Vec::new(), None)
            }
        }
    }

    async fn save(&self, rows: Vec<MessageRow>) {
        let Some(db) = self.state.db.clone() else {
            return;
        };
        if rows.is_empty() {
            return;
        }
        let result = db
            .write(move |tx| {
                for row in &rows {
                    store::insert_message(tx, row)?;
                }
                Ok(())
            })
            .await;
        if let Err(error) = result {
            tracing::error!(%error, "checkpointer_sync_failed");
        }
    }

    /// One model call: the events of `stream_and_assemble` and the publisher hook.
    async fn stream_call(
        &mut self,
        target: &Target,
        req: ChatRequest,
        model: &str,
    ) -> Result<Call, Failure> {
        let mut stream = stream_with_retry(target.clone(), None, req);
        let mut call = Call::default();
        let wire = wire_model(model).to_owned();
        let mut pending_usage_events: Vec<Value> = Vec::new();
        let mut last_usage_key: Option<UsageKey> = None;
        loop {
            let item = tokio::select! {
                () = self.input.cancel.cancelled() => {
                    call.interrupted = true;
                    break;
                }
                item = stream.next() => item,
            };
            let Some(item) = item else { break };
            if matches!(item, Ok(RetryItem::Event(_))) {
                self.spawn_title(model);
            }
            match item.map_err(Failure::Provider)? {
                RetryItem::Restart => {
                    call.content.clear();
                    call.reasoning.clear();
                    call.tool_calls.clear();
                }
                RetryItem::RateLimit {
                    retry_after,
                    attempt,
                    max_attempts,
                } => self.push(
                    "rate_limit",
                    json!({"type": "rate_limit", "retry_after": retry_after, "attempt": attempt, "max_attempts": max_attempts, "metadata": {}}),
                ),
                RetryItem::Retry {
                    model,
                    attempt,
                    max_attempts,
                    delay_seconds,
                    error_type,
                    status_code,
                    retry_after,
                } => self.push(
                    "provider_status",
                    json!({"type": "provider_status", "agent": self.agent(), "status": "retrying", "model": model,
                           "primary": null, "fallback": null, "attempt": attempt, "max_attempts": max_attempts,
                           "delay_seconds": delay_seconds, "error_type": error_type, "status_code": status_code,
                           "retry_after": retry_after, "metadata": {}}),
                ),
                RetryItem::Exhausted {
                    model,
                    max_attempts,
                    error_type,
                    status_code,
                } => self.push(
                    "provider_status",
                    json!({"type": "provider_status", "agent": self.agent(), "status": "exhausted", "model": model,
                           "primary": null, "fallback": null, "attempt": null, "max_attempts": max_attempts,
                           "delay_seconds": null, "error_type": error_type, "status_code": status_code,
                           "retry_after": null, "metadata": {}}),
                ),
                RetryItem::Fallback { primary, fallback } => self.push(
                    "provider_status",
                    json!({"type": "provider_status", "agent": self.agent(), "status": "fallback", "model": null,
                           "primary": primary, "fallback": fallback, "attempt": null, "max_attempts": null,
                           "delay_seconds": null, "error_type": null, "status_code": null,
                           "retry_after": null, "metadata": {}}),
                ),
                RetryItem::Event(ProviderEvent::TextDelta(text)) => {
                    if !text.is_empty() {
                        call.content.push_str(&text);
                        self.push(
                            "message",
                            json!({"type": "message", "agent": self.agent(), "text": text, "metadata": {"model": wire}}),
                        );
                    }
                }
                RetryItem::Event(ProviderEvent::ReasoningDelta(text)) => {
                    if !text.is_empty() {
                        call.reasoning.push_str(&text);
                        self.push(
                            "thinking",
                            json!({"type": "thinking", "agent": self.agent(), "text": text, "metadata": {"model": wire}}),
                        );
                    }
                }
                RetryItem::Event(ProviderEvent::Usage(u)) => {
                    let key = (
                        u.prompt_tokens,
                        u.completion_tokens,
                        u.total_tokens,
                        u.cached_tokens,
                        u.cache_write_tokens,
                    );
                    if last_usage_key != Some(key) {
                        last_usage_key = Some(key);
                        pending_usage_events.push(usage::call_usage_event(&u, self.agent(), &wire));
                    }
                    call.usage = Some(usage::fold(call.usage.take(), &u));
                }
                RetryItem::Event(ProviderEvent::ToolCall {
                    id,
                    name,
                    arguments,
                }) => {
                    let args = serde_json::to_string(&arguments).unwrap_or_else(|_| "{}".into());
                    call.tool_calls.push((id, name, args));
                }
                RetryItem::Event(ProviderEvent::Done { .. }) => {}
            }
        }
        // Tool calls are announced when their first delta streams in Python,
        // which is before the call's usage block.
        let mut announced: Vec<(&str, &str)> = Vec::new();
        for (id, name, _) in &call.tool_calls {
            if name.is_empty() || announced.contains(&(name.as_str(), id.as_str())) {
                continue;
            }
            announced.push((name, id));
            self.push(
                "tool_call",
                json!({"type": "tool_call", "agent": self.agent(), "tool_call_id": id, "name": name, "metadata": {}}),
            );
        }
        for event in pending_usage_events {
            self.push("usage", event);
        }
        // `after_model` fallback for a stream that produced no chunk.
        self.spawn_title(model);
        call.turn_usage_before = self.usage().snapshot();
        if let Some(u) = &call.usage {
            let recorded = self.usage().record(u, "main", model);
            if let Some(snapshot) = recorded {
                self.push("usage", usage::turn_total_event(&snapshot, self.agent()));
            }
        }
        Ok(call)
    }

    /// The `except` branches of `_run_activation` and the lead's `_on_turn_error`.
    fn fail(&self, failure: Failure) {
        let agent = self.agent().to_owned();
        let (message, exception) = match failure {
            // Python schedules a delayed re-activation and ends the turn idle.
            Failure::Provider(ProviderError::RateLimited) => {
                self.push("agent_status", status(&agent, "idle", json!({})));
                return;
            }
            Failure::Provider(
                e @ (ProviderError::Authentication { .. } | ProviderError::Unconfigured(_)),
            ) => {
                let message = e.to_string();
                self.push(
                    "agent_not_configured",
                    json!({"type": "agent_not_configured", "agent": agent, "message": message,
                           "action": {"type": "open_settings", "tab": "providers"}}),
                );
                self.push("agent_status", status(&agent, "error", json!({"message": message})));
                return;
            }
            Failure::Provider(e) => (e.to_string(), e.kind().to_owned()),
            Failure::ToolNotPorted(name) => {
                (format!("Tool '{name}' not found."), "ToolNotFoundError".to_owned())
            }
            Failure::EmptyLoop => (
                format!(
                    "Agent produced {MAX_EMPTY_AFTER_TOOL} consecutive empty responses after tool calls \
                     — stopping to avoid a silent loop. Reassign remaining work or retry."
                ),
                "AgentLoopError".to_owned(),
            ),
            Failure::NoModel => (
                format!("No model is configured for agent '{agent}'."),
                "UnconfiguredProviderError".to_owned(),
            ),
        };
        self.push(
            "error",
            json!({"type": "error", "message": format!("Lead agent '{agent}' failed: {message}"),
                   "metadata": {"agent": agent, "exception": exception}}),
        );
        self.push(
            "agent_status",
            status(&agent, "error", json!({"message": message})),
        );
    }

    /// `_try_emit_done`: notification, turn changes, `done`.
    async fn finish(&self) {
        let sid = self.input.sid.clone();
        let row = match self.state.db.clone() {
            Some(db) => {
                let hex = self.input.sid_hex.clone();
                db.read(move |conn| store::get_session(conn, &hex))
                    .await
                    .ok()
                    .flatten()
            }
            None => None,
        };
        let title = row.as_ref().and_then(|r| r.title.clone());
        let mode = row.as_ref().map(|r| r.mode.clone());
        let workspace = row.as_ref().and_then(|r| r.workspace.clone());
        let workspace_name = match (&mode, &workspace) {
            (Some(m), Some(w)) if m == "coding" => std::path::Path::new(w)
                .file_name()
                .map(|n| n.to_string_lossy().into_owned()),
            _ => None,
        };
        let notification_title = match workspace_name {
            Some(name) => format!("Session completed - {name}"),
            None => "Session completed".to_owned(),
        };
        let body = match title.as_deref().map(str::trim) {
            Some(t) if !t.is_empty() => t.to_owned(),
            _ => format!("Session {}", sid.chars().take(8).collect::<String>()),
        };
        self.push(
            "desktop_notification",
            json!({"type": "desktop_notification", "kind": "assistant_done", "session_id": sid,
                   "title": notification_title, "body": body,
                   "metadata": {"session_id": sid, "title": title, "mode": mode, "workspace": workspace}}),
        );
        self.push(
            "turn_changes",
            json!({"type": "turn_changes", "session_id": sid, "additions": 0, "deletions": 0, "files": [], "metadata": {}}),
        );
        self.push("done", json!({"type": "done", "metadata": {}}));
        self.state.store.mark_done(&sid);
        self.state.finish_turn(&sid);
    }
}

/// What one model call produced.
#[derive(Default)]
struct Call {
    content: String,
    reasoning: String,
    /// `(id, name, arguments JSON text)`.
    tool_calls: Vec<(String, String, String)>,
    usage: Option<Usage>,
    /// The turn total before this call was recorded (Python stamps the reply
    /// before `after_model` adds the call).
    turn_usage_before: Option<Value>,
    interrupted: bool,
}

#[cfg(test)]
mod more_tests;

#[cfg(test)]
#[allow(
    clippy::unwrap_used,
    clippy::indexing_slicing,
    clippy::disallowed_methods
)]
mod tests {
    use super::*;

    #[test]
    fn rows_become_provider_messages() {
        let tool_calls = tool_calls_json(&[("c1".into(), "date".into(), "{}".into())]);
        let rows = [
            MessageRow {
                role: "user".into(),
                content: Some("hi".into()),
                ..MessageRow::default()
            },
            MessageRow {
                role: "assistant".into(),
                tool_calls: Some(tool_calls),
                ..MessageRow::default()
            },
            MessageRow {
                role: "tool".into(),
                content: Some("r".into()),
                tool_call_id: Some("c1".into()),
                name: Some("date".into()),
                ..MessageRow::default()
            },
            MessageRow {
                role: "system".into(),
                ..MessageRow::default()
            },
        ];
        let messages: Vec<Message> = rows.iter().filter_map(to_message).collect();
        assert_eq!(
            serde_json::to_value(&messages).unwrap(),
            json!([
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": null, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": "date", "arguments": "{}"}}]},
                {"role": "tool", "content": "r", "tool_call_id": "c1", "name": "date"}
            ])
        );
        let empty = MessageRow {
            role: "assistant".into(),
            tool_calls: Some(json!([])),
            ..MessageRow::default()
        };
        assert!(matches!(
            to_message(&empty),
            Some(Message::Assistant {
                tool_calls: None,
                ..
            })
        ));
    }

    #[test]
    fn adjacent_user_messages_merge() {
        let user = |t: &str| Message::User {
            content: Some(t.into()),
            parts: None,
        };
        let merged = merge_user_messages(vec![
            Message::System {
                content: Some("s".into()),
            },
            user(" a"),
            user("b "),
            Message::Assistant {
                content: Some("x".into()),
                reasoning_content: None,
                tool_calls: None,
            },
            user("c"),
        ]);
        assert_eq!(
            serde_json::to_value(&merged).unwrap(),
            json!([
                {"role": "system", "content": "s"},
                {"role": "user", "content": "a\n\nb"},
                {"role": "assistant", "content": "x"},
                {"role": "user", "content": "c"}
            ])
        );
    }

    #[test]
    fn system_prompt_falls_back_to_a_name_line() {
        let mut lead = LeadAgent {
            name: "evoflux".into(),
            model: None,
            thinking_level: None,
            prompt: String::new(),
        };
        assert_eq!(
            system_prompt(&lead),
            "You are evoflux, the user's assistant in EvoFlux."
        );
        lead.prompt = "Be brief.".into();
        assert_eq!(system_prompt(&lead), "Be brief.");
    }

    #[test]
    fn tool_call_column_matches_model_dump() {
        assert_eq!(
            crate::pyjson::dumps(&tool_calls_json(&[(
                "c".into(),
                "date".into(),
                "{}".into()
            )])),
            r#"[{"id": "c", "type": "function", "function": {"name": "date", "arguments": "{}", "thought": null, "thought_signature": null}}]"#
        );
    }

    #[test]
    fn oversized_tool_arguments_are_replaced_by_a_json_marker() {
        let small = "x".repeat(MAX_ECHOED_ARGS_BYTES);
        assert_eq!(echoed_args(&small), small);
        let big = "x".repeat(MAX_ECHOED_ARGS_BYTES + 1);
        let echoed = echoed_args(&big).into_owned();
        assert_eq!(echoed, r#"{"truncated":true,"original_bytes":1048577}"#);
        let column = tool_calls_json(&[("c".into(), "date".into(), big)]);
        assert_eq!(column[0]["function"]["arguments"], json!(echoed));
    }

    #[tokio::test]
    #[allow(clippy::panic)]
    async fn a_panicking_turn_still_releases_the_session() {
        let dir = std::env::temp_dir();
        let settings = evoflux_core::config::Settings::from_vars(
            &std::collections::HashMap::new(),
            Some(&dir),
            &dir,
        )
        .unwrap();
        let state = Arc::new(ChatState {
            workspaces: crate::workspace::Allowed::current(&settings),
            settings: Arc::new(settings),
            db: None,
            http: evoflux_net::build_client().unwrap(),
            store: Arc::new(crate::stream_store::StreamStore::default()),
            active: Mutex::new(std::collections::HashMap::new()),
        });
        assert!(state.begin_turn("s"));
        state.store.init_turn("s", false);
        let task_state = state.clone();
        let task = tokio::spawn(async move {
            let _guard = TurnGuard {
                state: task_state,
                sid: "s".into(),
            };
            panic!("boom");
        });
        assert!(task.await.unwrap_err().is_panic());
        assert!(state.begin_turn("s"));
        assert!(!state.store.is_running("s"));
    }

    #[tokio::test]
    async fn a_finished_turn_releases_the_session() {
        let dir = std::env::temp_dir();
        let settings = evoflux_core::config::Settings::from_vars(
            &std::collections::HashMap::new(),
            Some(&dir),
            &dir,
        )
        .unwrap();
        let state = Arc::new(ChatState {
            workspaces: crate::workspace::Allowed::current(&settings),
            settings: Arc::new(settings),
            db: None,
            http: evoflux_net::build_client().unwrap(),
            store: Arc::new(crate::stream_store::StreamStore::default()),
            active: Mutex::new(std::collections::HashMap::new()),
        });
        assert!(state.begin_turn("s"));
        state.store.init_turn("s", false);
        let cancel = state.cancel_token("s");
        cancel.cancel();
        let input = TurnInput {
            sid_hex: "s".into(),
            sid: "s".into(),
            content: "hi".into(),
            lead: LeadAgent {
                name: "lead".into(),
                model: None,
                thinking_level: None,
                prompt: String::new(),
            },
            model: None,
            thinking_level: None,
            workspace: None,
            cancel,
        };
        run(state.clone(), input).await;
        assert!(state.begin_turn("s"));
    }

    #[test]
    fn python_only_tools_exclude_the_ported_ones() {
        for tool in read_only_tools() {
            assert!(!PYTHON_ONLY_TOOLS.contains(&tool.name()));
        }
    }

    #[test]
    fn durations_round_to_microseconds() {
        let d = ms_since(Instant::now());
        assert!((0.0..1000.0).contains(&d));
        assert_eq!((d * 1000.0).fract(), 0.0);
    }
}
