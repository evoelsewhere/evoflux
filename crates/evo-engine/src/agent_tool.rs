//! Subagents: the built-in `agent` and `message_agent` tools.
//!
//! `agent` hands a self-contained task to a child agent. The child starts with
//! only its brief (no copy of this conversation), works with the parent's
//! tools and model unless its agent type narrows them (see [`crate::agents`]),
//! optionally in its own Git worktree, and its final reply becomes the result.
//! Its steps never enter the parent's context.
//!
//! * **Foreground** (default): the tool waits for the child. While it runs, a
//!   cumulative snapshot of the child (status, turns, tool rows, the tail of
//!   its text, usage) goes out through `tool_execution_update` as
//!   `details.child`, and stays on the result so a reopened chat shows it.
//!   The child's usage is the result's `usage`.
//! * **Background** (`background: true`): the tool returns at once with the
//!   agent's id and the child keeps running past the end of the parent's run
//!   (until it finishes, is cancelled, or the session closes). When it
//!   finishes, its report is queued for the parent: into the running run
//!   (steering) or, when the parent is idle, for its next run, and a mesh
//!   wake request is put on the parent's session node so the host can start
//!   that run (`meta.wake`, see [`crate::mesh::LocalRouter::request_wake`]).
//!
//! A finished agent keeps its context: `message_agent` sends it another
//! message (foreground or background) and it continues where it left off.
//!
//! Every agent is also a node of this engine's session mesh
//! ([`crate::mesh`]) at `s_<session>/a_<agent>`: its state changes, tool rows,
//! text, usage and report go out as mesh events, and `cancel` reaches it.
//!
//! Children cannot delegate further (the harness refuses nested children and
//! hides these tools from them). At most [`MAX_RUNNING`] agents run at once
//! and [`MAX_KEPT`] are kept per engine; the oldest finished ones are closed.

use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, LazyLock, Mutex, OnceLock};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use evo_agent::agent_tool::AgentTool;
use evo_agent::error::AgentError;
use evo_agent::types::{AgentToolResult, TextContentOrImage, ToolExecutionMode, ToolResultPartial};
use evo_agent::{AgentEmitter, AgentEvent, AgentMessage};
use evo_ai::types::{AssistantMessageEvent, Schema, Tool, Usage};
use evo_harness::agent_harness::{AgentHarness, WeakAgentHarness};
use evo_harness::session::memory::{InMemorySessionStorage, SystemClock};
use evo_harness::session::session::DefaultIdGenerator;
use evo_harness::session::types::SessionMetadata;
use evo_harness::session::Session;
use serde::Deserialize;
use serde_json::{json, Value};
use tokio_util::sync::CancellationToken;

use crate::agents::{self, AgentType};
use crate::mesh::{self, Address, MeshUsage, NodeKind, NodeState, Origin, RunStatus, ToolRow};

/// Subagents running at once in one session.
pub const MAX_RUNNING: usize = 4;
/// Agents kept (running or able to continue) per engine.
pub const MAX_KEPT: usize = 16;
/// Bytes of a report the requester gets; the rest stays with the agent,
/// which `message_agent` can ask for.
const MAX_REPORT: usize = 16 * 1024;
/// A subagent run that takes longer is stopped.
const TIMEOUT: Duration = Duration::from_secs(30 * 60);
/// Progress updates at most this often (the final one always goes out).
const UPDATE_EVERY: Duration = Duration::from_millis(250);
/// Tool rows kept in the snapshot (the most recent).
const MAX_ROWS: usize = 50;
/// Bytes of the child's latest text kept in the snapshot.
const MAX_TEXT: usize = 4096;
/// Argument fields shown for a child's tool call (what the UI labels it by).
const ARG_FIELDS: &[&str] = &["command", "path", "file_path", "pattern", "query", "url", "description"];
/// Messages about background agents start with this, so hosts can show them
/// as events rather than as something the user typed.
pub const NOTE_TAG: &str = "<background-agent";

/// The parent harness, bound once it exists (tools are built before it).
pub type HarnessCell = Arc<OnceLock<WeakAgentHarness>>;

type Update = Arc<dyn Fn(ToolResultPartial) + Send + Sync>;

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

// ── Progress ────────────────────────────────────────────────────────────────

/// What the UI shows of a child.
struct Progress {
    agent_id: String,
    agent_type: String,
    description: String,
    model: String,
    background: bool,
    status: &'static str,
    turns: u32,
    tool_uses: u32,
    usage: Usage,
    started_at: u64,
    ended_at: Option<u64>,
    rows: VecDeque<Value>,
    text: String,
    worktree: Option<Value>,
    error: Option<String>,
}

impl Progress {
    fn snapshot(&self) -> Value {
        json!({
            "agentId": self.agent_id,
            "agentType": self.agent_type,
            "description": self.description,
            "model": self.model,
            "background": self.background,
            "status": self.status,
            "turns": self.turns,
            "toolUses": self.tool_uses,
            "usage": {
                "input": self.usage.input,
                "output": self.usage.output,
                "cacheRead": self.usage.cache_read,
                "cacheWrite": self.usage.cache_write,
                "totalTokens": self.usage.total_tokens,
                "cost": self.usage.cost.total,
            },
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "tools": self.rows,
            "text": self.text,
            "worktree": self.worktree,
            "error": self.error,
        })
    }

    /// What `event` changed, for a mesh activity event: the tool row it
    /// touched, or the text tail after a text delta.
    fn activity(&self, event: &AgentEvent) -> (Option<ToolRow>, Option<String>) {
        match event {
            AgentEvent::ToolExecutionStart { tool_call_id, .. } | AgentEvent::ToolExecutionEnd { tool_call_id, .. } => {
                let row = self.rows.iter().rev().find(|row| row["callId"] == *tool_call_id).map(|row| ToolRow {
                    call_id: tool_call_id.clone(),
                    name: row["name"].as_str().unwrap_or_default().to_string(),
                    args: row["args"].clone(),
                    phase: row["phase"].as_str().unwrap_or("running").to_string(),
                });
                (row, None)
            }
            AgentEvent::MessageUpdate { .. } | AgentEvent::MessageStart { .. } => (None, Some(self.text.clone())),
            _ => (None, None),
        }
    }

    fn observe(&mut self, event: &AgentEvent) {
        match event {
            AgentEvent::TurnEnd { .. } => self.turns += 1,
            AgentEvent::MessageStart { message: AgentMessage::Assistant(_), .. } => self.text.clear(),
            AgentEvent::MessageUpdate {
                assistant_message_event: AssistantMessageEvent::TextDelta { delta, .. },
                ..
            } => {
                self.text.push_str(delta);
                if self.text.len() > MAX_TEXT {
                    let mut cut = self.text.len() - MAX_TEXT;
                    while !self.text.is_char_boundary(cut) {
                        cut += 1;
                    }
                    self.text.drain(..cut);
                }
            }
            AgentEvent::MessageEnd { message: AgentMessage::Assistant(message), .. } => {
                self.usage.add(&message.usage);
            }
            AgentEvent::ToolExecutionStart { tool_call_id, tool_name, args } => {
                self.tool_uses += 1;
                let shown: serde_json::Map<String, Value> = ARG_FIELDS
                    .iter()
                    .filter_map(|key| {
                        let text = args.get(*key)?.as_str()?;
                        Some((key.to_string(), Value::String(text.chars().take(200).collect())))
                    })
                    .collect();
                self.rows.push_back(json!({
                    "callId": tool_call_id,
                    "name": tool_name,
                    "args": shown,
                    "phase": "running",
                }));
                while self.rows.len() > MAX_ROWS {
                    self.rows.pop_front();
                }
            }
            AgentEvent::ToolExecutionEnd { tool_call_id, is_error, .. } => {
                if let Some(row) = self.rows.iter_mut().rev().find(|row| row["callId"] == *tool_call_id) {
                    row["phase"] = json!(if *is_error { "error" } else { "done" });
                }
            }
            _ => {}
        }
    }
}

/// Feeds the child's events into its snapshot and, while a tool call waits
/// for it, into that call's updates.
struct ProgressEmitter {
    progress: Arc<Mutex<Progress>>,
    update: Arc<Mutex<Option<Update>>>,
    last: Mutex<Option<Instant>>,
    /// The agent's mesh node.
    address: Address,
}

impl ProgressEmitter {
    fn observe(&self, event: AgentEvent) {
        let router = mesh::router();
        router.event(&self.address, &event);
        let snapshot = {
            let mut progress = lock(&self.progress);
            progress.observe(&event);
            if matches!(event, AgentEvent::MessageEnd { message: AgentMessage::Assistant(_), .. }) {
                router.usage(&self.address, mesh::usage_of(&progress.usage));
            }
            let mut last = lock(&self.last);
            let due = last.is_none_or(|at| at.elapsed() >= UPDATE_EVERY)
                || matches!(event, AgentEvent::ToolExecutionStart { .. } | AgentEvent::ToolExecutionEnd { .. });
            if !due {
                return;
            }
            *last = Some(Instant::now());
            // Folded by the router even without subscribers, for later ones.
            let (tool, text) = progress.activity(&event);
            router.activity(&self.address, progress.turns, progress.tool_uses, tool, text);
            progress.snapshot()
        };
        let update = lock(&self.update).clone();
        if let Some(update) = update {
            update(partial(snapshot));
        }
    }
}

impl AgentEmitter for ProgressEmitter {
    fn emit(&self, event: AgentEvent) -> futures::future::BoxFuture<'static, ()> {
        self.observe(event);
        Box::pin(async {})
    }
    fn try_emit(&self, event: AgentEvent) {
        self.observe(event);
    }
}

/// An update carrying only the snapshot (no text output yet).
fn partial(snapshot: Value) -> AgentToolResult {
    AgentToolResult { content: Vec::new(), details: json!({ "child": snapshot }), ..Default::default() }
}

// ── Registry ────────────────────────────────────────────────────────────────

/// One subagent: running, or finished and able to continue.
pub struct Job {
    id: String,
    /// Its mesh node.
    address: Address,
    parent: WeakAgentHarness,
    /// The parent's session; limits and lookups are per session.
    session_id: String,
    /// The parent's tool call that started or last continued it.
    call_id: Mutex<String>,
    progress: Arc<Mutex<Progress>>,
    update: Arc<Mutex<Option<Update>>>,
    /// The child; `None` once closed (evicted, or its worktree was removed).
    child: Mutex<Option<ChildParts>>,
    /// The current run's cancel switch.
    cancel: Mutex<CancellationToken>,
    running: AtomicBool,
    background: AtomicBool,
    /// This run was started to answer an `ask` (mesh_tools.rs): its report
    /// goes to the asker, not to the parent as a background note.
    quiet: AtomicBool,
    worktree: Mutex<Option<crate::worktrees::Created>>,
    cwd: PathBuf,
    last_used: Mutex<Instant>,
}

#[derive(Clone)]
struct ChildParts {
    harness: AgentHarness,
    execution_scope: Arc<evo_agent::tool_execution_scope::ToolExecutionScope>,
}

#[derive(Default)]
pub struct Registry {
    jobs: Mutex<Vec<Arc<Job>>>,
}

static REGISTRY: LazyLock<Registry> = LazyLock::new(Registry::default);

/// This engine's subagents.
pub fn registry() -> &'static Registry {
    &REGISTRY
}

impl Registry {
    fn get(&self, id: &str) -> Option<Arc<Job>> {
        lock(&self.jobs).iter().find(|job| job.id == id).cloned()
    }

    /// Agents of the session `session_id` that are running now.
    fn running(&self, session_id: &str) -> usize {
        lock(&self.jobs)
            .iter()
            .filter(|job| job.running.load(Ordering::Acquire) && job.session_id == session_id)
            .count()
    }

    /// Add a job, closing the oldest finished ones beyond [`MAX_KEPT`].
    fn insert(&self, job: Arc<Job>) {
        let evicted: Vec<Arc<Job>> = {
            let mut jobs = lock(&self.jobs);
            jobs.push(job);
            let mut evicted = Vec::new();
            while jobs.len() > MAX_KEPT {
                let Some(oldest) = jobs
                    .iter()
                    .enumerate()
                    .filter(|(_, job)| !job.running.load(Ordering::Acquire))
                    .min_by_key(|(_, job)| *lock(&job.last_used))
                    .map(|(index, _)| index)
                else {
                    break;
                };
                evicted.push(jobs.remove(oldest));
            }
            evicted
        };
        for job in evicted {
            tokio::spawn(async move { job.close().await });
        }
    }

    /// Stop a running agent; false when it is not running.
    pub fn cancel(&self, id: &str) -> bool {
        match self.get(id) {
            Some(job) if job.running.load(Ordering::Acquire) => {
                lock(&job.cancel).cancel();
                true
            }
            _ => false,
        }
    }
}

impl Job {
    async fn close(&self) {
        mesh::router().transition(&self.address, NodeState::Closed, None, None);
        let child = lock(&self.child).take();
        if let Some(child) = child {
            let _ = child.harness.close().await;
        }
        let worktree = lock(&self.worktree).take();
        if let Some(created) = worktree {
            crate::child_agents::finish_worktree(created, self.cwd.clone()).await;
        }
    }
}

// ── Running ─────────────────────────────────────────────────────────────────

enum Outcome {
    Report(String),
    Failed(String),
}

/// One run of `job` on `brief`. `foreground` is the waiting tool call's signal;
/// `scope` ends with the parent's run (foreground) or session (background).
async fn run(job: Arc<Job>, brief: String, foreground: Option<CancellationToken>, scope: CancellationToken) -> Outcome {
    let Some(child) = lock(&job.child).clone() else {
        return Outcome::Failed("the agent was closed".into());
    };
    let cancel = CancellationToken::new();
    *lock(&job.cancel) = cancel.clone();
    {
        let mut progress = lock(&job.progress);
        progress.status = "running";
        progress.ended_at = None;
        progress.error = None;
    }
    let call_id = lock(&job.call_id).clone();
    let background = job.background.load(Ordering::Acquire);
    mesh::router().set_meta(&job.address, json!({ "callId": call_id, "background": background }));
    mesh::router().transition(&job.address, NodeState::Running, None, None);
    let lane = child.harness.lane("main");
    let prompt = lane.prompt_text(&brief, Vec::new());
    tokio::pin!(prompt);
    let foreground_abort = async {
        match &foreground {
            Some(signal) => signal.cancelled().await,
            None => std::future::pending::<()>().await,
        }
    };
    let outcome = tokio::select! {
        biased;
        _ = cancel.cancelled() => Err("cancelled".to_string()),
        _ = foreground_abort => Err("cancelled".to_string()),
        _ = scope.cancelled() => Err(if background { "the session closed" } else { "the parent run ended" }.to_string()),
        _ = tokio::time::sleep(TIMEOUT) => Err(format!("timed out after {} minutes", TIMEOUT.as_secs() / 60)),
        result = &mut prompt => result.map_err(|e| e.to_string()),
    };
    if outcome.is_err() {
        let _ = lane.abort().await;
        let _ = tokio::time::timeout(Duration::from_secs(2), &mut prompt).await;
    }
    let _ = tokio::time::timeout(Duration::from_secs(5), child.execution_scope.wait_idle()).await;
    match outcome {
        Ok(result) => {
            let outcome = crate::extensions_actions::run_outcome_json(result.outcome);
            let text = outcome.get("text").and_then(Value::as_str).unwrap_or("").trim().to_string();
            if outcome.get("status").and_then(Value::as_str) == Some("completed") {
                Outcome::Report(if text.is_empty() { "(the subagent returned no text)".into() } else { capped(text, &job.id) })
            } else {
                Outcome::Failed(format!("its run {}", outcome["status"].as_str().unwrap_or("failed")))
            }
        }
        Err(reason) => Outcome::Failed(reason),
    }
}

/// A report cut to [`MAX_REPORT`] bytes, saying how to get the rest.
fn capped(mut text: String, id: &str) -> String {
    if text.len() <= MAX_REPORT {
        return text;
    }
    let total = text.len();
    let mut cut = MAX_REPORT;
    while !text.is_char_boundary(cut) {
        cut -= 1;
    }
    text.truncate(cut);
    text.push_str(&format!(
        "\n\n[Report cut at {cut} of {total} bytes. Ask agent {id} with message_agent for the rest or a shorter summary.]"
    ));
    text
}

/// Record how a run ended and settle the worktree. Returns the final snapshot.
async fn settle(job: &Job, outcome: &Outcome, cancelled: bool) -> Value {
    // An unchanged worktree is removed; the agent cannot continue without it.
    let created = lock(&job.worktree).clone();
    let mut worktree_report = None;
    if let Some(created) = created {
        if crate::worktrees::Worktrees::changed(&created.worktree.path, Some(&created.base)) {
            worktree_report = Some(crate::child_agents::worktree_json(&created, Some(true)));
        } else {
            lock(&job.worktree).take();
            let child = lock(&job.child).take();
            if let Some(child) = child {
                let _ = child.harness.close().await;
            }
            worktree_report = Some(crate::child_agents::finish_worktree(created, job.cwd.clone()).await);
        }
    }
    let mut progress = lock(&job.progress);
    progress.status = match outcome {
        Outcome::Report(_) => "done",
        Outcome::Failed(_) if cancelled => "cancelled",
        Outcome::Failed(_) => "error",
    };
    progress.ended_at = Some(now_ms());
    progress.error = match outcome {
        Outcome::Failed(reason) => Some(reason.clone()),
        Outcome::Report(_) => None,
    };
    if let Some(report) = worktree_report {
        progress.worktree = Some(report);
    }
    *lock(&job.last_used) = Instant::now();
    job.running.store(false, Ordering::Release);
    let snapshot = progress.snapshot();
    let usage = mesh::usage_of(&progress.usage);
    drop(progress);
    announce(job, outcome, &snapshot, usage);
    snapshot
}

/// Tell the mesh how a run ended: the report, then the settled state.
fn announce(job: &Job, outcome: &Outcome, snapshot: &Value, usage: MeshUsage) {
    let router = mesh::router();
    let status = match snapshot["status"].as_str() {
        Some("done") => RunStatus::Done,
        Some("cancelled") => RunStatus::Cancelled,
        _ => RunStatus::Failed,
    };
    let worktree = snapshot.get("worktree").filter(|w| !w.is_null()).cloned();
    let resumable = lock(&job.child).is_some();
    router.set_meta(&job.address, json!({ "worktree": worktree, "resumable": resumable }));
    router.usage(&job.address, usage);
    router.report(&job.address, status, report_text(outcome, snapshot), usage, worktree);
    let reason = snapshot["error"].as_str().map(str::to_string);
    router.transition(&job.address, NodeState::Settled, Some(status), reason);
    // Questions it did not `reply` to get its report as their answer.
    crate::mesh_tools::run_ended(&job.address, &report_text(outcome, snapshot));
}

/// The report for the parent, with a kept worktree's place.
fn report_text(outcome: &Outcome, snapshot: &Value) -> String {
    let mut text = match outcome {
        Outcome::Report(text) => text.clone(),
        Outcome::Failed(reason) => format!("The subagent stopped: {reason}."),
    };
    if snapshot["worktree"]["kept"] == json!(true) {
        text.push_str(&format!(
            "\n\n[Its changes are in the worktree {} on branch {}.]",
            snapshot["worktree"]["path"].as_str().unwrap_or(""),
            snapshot["worktree"]["branch"].as_str().unwrap_or("")
        ));
    }
    text
}

/// A background run ended: queue its report for the parent — into the
/// running run, or for the next one with a wake request for the host.
async fn tell_parent(job: &Job, outcome: &Outcome, snapshot: &Value) {
    if job.quiet.swap(false, Ordering::AcqRel) {
        return;
    }
    let Some(parent) = job.parent.upgrade() else { return };
    let status = snapshot["status"].as_str().unwrap_or("done");
    let note = format!(
        "{NOTE_TAG} id=\"{}\" description=\"{}\" status=\"{status}\">\n{}\n</background-agent>",
        job.id,
        snapshot["description"].as_str().unwrap_or("").replace('"', "'"),
        report_text(outcome, snapshot)
    );
    let message = AgentMessage::from(evo_ai::types::UserMessage::new(note, now_ms() as i64));
    let lane = parent.lane("main");
    let queued = if parent.has_active_run() { lane.steer(message).await } else { lane.next_run(message).await };
    // Idle now (or its run ended meanwhile): it needs a run to read the report.
    if queued.is_ok() && !parent.has_active_run() {
        mesh::router().request_wake(&Address::session(&job.session_id), &job.address, None);
    }
}

fn result(text: String, snapshot: Value, usage: Option<Usage>) -> AgentToolResult {
    AgentToolResult {
        content: vec![TextContentOrImage::text(text)],
        details: json!({ "child": snapshot }),
        usage,
        ..Default::default()
    }
}

/// `after` minus `before`: one run's usage on a cumulative counter.
fn usage_since(after: &Usage, before: &Usage) -> Usage {
    let mut usage = after.clone();
    usage.input -= before.input;
    usage.output -= before.output;
    usage.cache_read -= before.cache_read;
    usage.cache_write -= before.cache_write;
    usage.total_tokens -= before.total_tokens;
    usage.cost.input -= before.cost.input;
    usage.cost.output -= before.cost.output;
    usage.cost.cache_read -= before.cost.cache_read;
    usage.cost.cache_write -= before.cost.cache_write;
    usage.cost.total -= before.cost.total;
    usage
}

/// Run `job` on `brief` for a tool call: wait for it (foreground) or let it
/// run on (background).
async fn drive(
    job: Arc<Job>,
    brief: String,
    background: bool,
    scope: CancellationToken,
    signal: CancellationToken,
    on_update: Update,
) -> Result<AgentToolResult, AgentError> {
    job.background.store(background, Ordering::Release);
    lock(&job.progress).background = background;
    if background {
        *lock(&job.update) = None;
        let snapshot = lock(&job.progress).snapshot();
        let worker = job.clone();
        tokio::spawn(async move {
            let outcome = run(worker.clone(), brief, None, scope).await;
            let cancelled = lock(&worker.cancel).is_cancelled();
            let snapshot = settle(&worker, &outcome, cancelled).await;
            tell_parent(&worker, &outcome, &snapshot).await;
        });
        return Ok(result(
            format!(
                "Started background agent {} ({}). It keeps working after this turn; its report will be \
                 delivered to you as a message when it finishes. Do not wait for it or poll it.",
                job.id,
                snapshot["description"].as_str().unwrap_or("")
            ),
            snapshot,
            None,
        ));
    }

    *lock(&job.update) = Some(on_update.clone());
    // The session waits on this agent until it reports: the agent asking the
    // session would never end (mesh_tools.rs refuses it).
    let _waits = mesh::router().add_wait(&Address::session(&job.session_id), &job.address);
    let before = lock(&job.progress).usage.clone();
    on_update(partial(lock(&job.progress).snapshot()));
    let outcome = run(job.clone(), brief, Some(signal.clone()), scope).await;
    let cancelled = signal.is_cancelled() || lock(&job.cancel).is_cancelled();
    let snapshot = settle(&job, &outcome, cancelled).await;
    *lock(&job.update) = None;
    on_update(partial(snapshot.clone()));
    // This run's usage only: earlier runs of a continued agent were counted then.
    let usage = usage_since(&lock(&job.progress).usage, &before);
    match outcome {
        Outcome::Report(_) => Ok(result(report_text(&outcome, &snapshot), snapshot, Some(usage))),
        Outcome::Failed(reason) => Err(AgentError::Tool(format!("subagent {} stopped: {reason}", job.id))),
    }
}

/// Put a mail message in front of the agent at `address` (mesh_tools.rs):
/// into its current run, or for its next one. A question (`ask`) to an idle
/// agent continues it in the background to answer.
pub(crate) async fn deliver(address: &Address, text: String, ask: bool) -> Result<&'static str, String> {
    let job = lock(&registry().jobs)
        .iter()
        .find(|job| job.address == *address)
        .cloned()
        .ok_or("that agent is gone")?;
    let child = lock(&job.child).clone().ok_or("that agent was closed and takes no messages")?;
    let lane = child.harness.lane("main");
    if job.running.load(Ordering::Acquire) {
        let message = AgentMessage::from(evo_ai::types::UserMessage::new(text, now_ms() as i64));
        lane.steer(message).await.map_err(|e| e.to_string())?;
        return Ok("delivered into its current run");
    }
    if !ask {
        let message = AgentMessage::from(evo_ai::types::UserMessage::new(text, now_ms() as i64));
        lane.next_run(message).await.map_err(|e| e.to_string())?;
        return Ok("queued: it reads it when it is continued");
    }
    let parent = job.parent.upgrade().ok_or("the session is gone")?;
    check_capacity(&job.session_id).map_err(|e| e.to_string())?;
    job.running.store(true, Ordering::Release);
    job.quiet.store(true, Ordering::Release);
    let scope = parent.session_scope_token();
    drive(job, text, true, scope, CancellationToken::new(), Arc::new(|_| {}))
        .await
        .map_err(|e| e.to_string())?;
    Ok("it was continued to answer")
}

fn parent_of(cell: &HarnessCell) -> Result<AgentHarness, AgentError> {
    cell.get()
        .and_then(WeakAgentHarness::upgrade)
        .ok_or_else(|| AgentError::Tool("the session is not ready for subagents".into()))
}

fn refuse_nested() -> Result<(), AgentError> {
    if evo_agent::tool_execution_scope::is_child_execution() {
        return Err(AgentError::Tool("subagents cannot start or message subagents".into()));
    }
    Ok(())
}

fn check_capacity(session_id: &str) -> Result<(), AgentError> {
    if registry().running(session_id) >= MAX_RUNNING {
        return Err(AgentError::Tool(format!(
            "at most {MAX_RUNNING} subagents run at once; wait for one to finish"
        )));
    }
    Ok(())
}

/// A model by id (`id` or `provider/id`, any case) among the harness's models.
fn find_model(models: &[evo_ai::Model], wanted: &str) -> Option<evo_ai::Model> {
    let wanted = wanted.trim();
    models
        .iter()
        .find(|m| {
            m.id.eq_ignore_ascii_case(wanted) || format!("{}/{}", m.provider, m.id).eq_ignore_ascii_case(wanted)
        })
        .cloned()
}

// ── The `agent` tool ────────────────────────────────────────────────────────

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Input {
    #[serde(default)]
    description: Option<String>,
    prompt: String,
    #[serde(default)]
    agent_type: Option<String>,
    #[serde(default)]
    model: Option<String>,
    #[serde(default)]
    isolation: Option<String>,
    #[serde(default)]
    background: bool,
}

pub struct SubagentTool {
    schema: Tool,
    harness: HarnessCell,
    cwd: PathBuf,
}

pub fn create_agent_tool(harness: HarnessCell, cwd: PathBuf) -> Arc<dyn AgentTool> {
    let types = agents::load(&cwd);
    Arc::new(SubagentTool { schema: schema(&types), harness, cwd })
}

fn schema(types: &[AgentType]) -> Tool {
    let listing: String = types.iter().map(|t| format!("\n- {}: {}", t.name, t.description)).collect();
    let names: Vec<&str> = types.iter().map(|t| t.name.as_str()).collect();
    Tool {
        name: "agent".into(),
        description: format!(
            "Hand a self-contained task to a subagent and get its final report back. The subagent starts \
             with ONLY your prompt (not this conversation), so the prompt must carry everything it needs: \
             the goal, what you already know or ruled out, the files or areas involved, and what the report \
             should contain. Its intermediate steps stay out of this conversation, which keeps your context \
             small: use it for wide searches, investigations across many files, or independent pieces of \
             work. Call it several times in one message to run independent tasks in parallel (at most \
             {MAX_RUNNING} at once). Do not delegate a quick lookup you can do with one or two tool calls. \
             Subagents cannot start subagents. Set isolation to \"worktree\" to have it work in its own Git \
             worktree; a worktree it changed is kept and its path and branch are reported. Set background \
             to true to let it run while you continue: the call returns its id at once and its report \
             arrives as a message when it finishes (do not wait for it or poll it). A finished agent keeps \
             its context: continue it with message_agent.\n\nAgent types:{listing}"
        ),
        parameters: Schema::new(json!({
            "type": "object",
            "properties": {
                "description": { "type": "string", "description": "A short (3-5 words) description of the task, shown to the user." },
                "prompt": { "type": "string", "description": "The complete brief for the subagent." },
                // No enum: agent files added later must work without a reload.
                "agentType": { "type": "string", "description": format!("Which kind of agent: {}. Default: general.", names.join(", ")) },
                "model": { "type": "string", "description": "Optional model id for the subagent; default: its type's model, else yours." },
                "isolation": { "type": "string", "enum": ["worktree"], "description": "Run in a separate Git worktree of this repository." },
                "background": { "type": "boolean", "description": "Run in the background and get its report later as a message." }
            },
            "required": ["description", "prompt"],
            "additionalProperties": false
        })),
        constrained_sampling: None,
    }
}

#[async_trait]
impl AgentTool for SubagentTool {
    fn schema(&self) -> &Tool {
        &self.schema
    }

    fn label(&self) -> &str {
        "agent"
    }

    fn execution_mode(&self) -> ToolExecutionMode {
        ToolExecutionMode::Parallel
    }

    async fn execute(
        &self,
        tool_call_id: &str,
        params: Value,
        signal: CancellationToken,
        on_update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let input: Input = serde_json::from_value(params)
            .map_err(|e| AgentError::Validation(format!("agent input invalid: {e}")))?;
        refuse_nested()?;
        let task = input.prompt.trim();
        if task.is_empty() || task.len() > 50_000 {
            return Err(AgentError::Validation("prompt must contain 1-50000 bytes".into()));
        }
        let description = input.description.as_deref().map(str::trim).filter(|d| !d.is_empty()).unwrap_or("Agent");
        let description: String = description.chars().take(200).collect();

        // Agent types are read per call, so a new `.evo/agents` file works at once.
        let types = agents::load(&self.cwd);
        let wanted = input.agent_type.as_deref().unwrap_or(agents::DEFAULT_TYPE);
        let agent = types.iter().find(|t| t.name == wanted).cloned().ok_or_else(|| {
            let names: Vec<_> = types.iter().map(|t| t.name.as_str()).collect();
            AgentError::Validation(format!("unknown agent type `{wanted}`; available: {}", names.join(", ")))
        })?;
        let isolated = match input.isolation.as_deref() {
            None => agent.worktree,
            Some("worktree") => true,
            Some("none") => false,
            Some(other) => return Err(AgentError::Validation(format!("unknown isolation `{other}`"))),
        };
        let parent = parent_of(&self.harness)?;
        let session_id = parent.session().storage().metadata().id.clone();
        check_capacity(&session_id)?;

        // An agent type's tool list narrows the parent's active tools.
        let requested = agent.tools.as_ref().map(|wanted| {
            let active: Vec<String> = parent
                .execution_context()
                .ok()
                .and_then(|context| context.get("tools").cloned())
                .and_then(|tools| serde_json::from_value(tools).ok())
                .unwrap_or_default();
            // Talking to other agents is part of every agent type.
            wanted
                .iter()
                .map(String::as_str)
                .chain(crate::mesh_tools::TOOL_NAMES)
                .filter(|name| active.iter().any(|a| a == name))
                .map(str::to_string)
                .collect::<Vec<_>>()
        });
        let model = match input.model.as_deref().or(agent.model.as_deref()) {
            Some(id) => Some(find_model(&parent.available_models(), id).ok_or_else(|| {
                AgentError::Validation(format!("model `{id}` is not available"))
            })?),
            None => None,
        };

        let worktree = if isolated {
            Some(crate::child_agents::create_worktree(&self.cwd).await.map_err(|e| {
                AgentError::Tool(format!("could not create a worktree: {e}"))
            })?)
        } else {
            None
        };
        let mut replacements = worktree
            .as_ref()
            .map(|created| crate::session::builtin_tools_in(&created.cwd))
            .unwrap_or_default();

        let id = parent.session().id_generator().next();
        let progress = Arc::new(Mutex::new(Progress {
            agent_id: id.clone(),
            agent_type: agent.name.clone(),
            description: description.clone(),
            model: model.as_ref().map(|m| m.id.clone()).unwrap_or_default(),
            background: input.background,
            status: "running",
            turns: 0,
            tool_uses: 0,
            usage: Usage::zero(),
            started_at: now_ms(),
            ended_at: None,
            rows: VecDeque::new(),
            text: String::new(),
            worktree: worktree.as_ref().map(|created| crate::child_agents::worktree_json(created, None)),
            error: None,
        }));
        let update: Arc<Mutex<Option<Update>>> = Arc::new(Mutex::new(None));
        let address = Address::session(&session_id).child(NodeKind::Agent, &id);
        let emitter = Arc::new(ProgressEmitter {
            progress: progress.clone(),
            update: update.clone(),
            last: Mutex::new(None),
            address: address.clone(),
        });
        let session = Session::new(
            Arc::new(InMemorySessionStorage::new(
                SessionMetadata {
                    id: id.clone(),
                    created_at: 0,
                    parent_session_id: Some(parent.session().storage().metadata().id.clone()),
                },
                Arc::new(SystemClock),
                Arc::new(DefaultIdGenerator::new()),
            )),
            None,
        );
        // Its own send_message / ask / reply / list_nodes, acting as its node.
        replacements.extend(
            crate::mesh_tools::create(self.harness.clone(), Some(address.clone()))
                .into_iter()
                .map(evo_harness::types::HarnessTool::new),
        );
        // A read-only type is held to it by a guard on every tool call.
        let guard = agent
            .read_only
            .then(|| Arc::new(crate::read_only::guard) as evo_harness::agent_harness::ChildToolGuard);
        let child = match parent
            .create_child_guarded(session, emitter, agent.max_turns(), requested, replacements, guard)
            .await
        {
            Ok(child) => child,
            Err(error) => {
                if let Some(created) = worktree {
                    crate::child_agents::finish_worktree(created, self.cwd.clone()).await;
                }
                return Err(AgentError::Tool(format!("could not start the subagent: {error}")));
            }
        };
        let lane = child.harness.lane("main");
        if let Some(model) = model {
            if let Err(error) = lane.set_model(model).await {
                let _ = child.harness.close().await;
                return Err(AgentError::Tool(format!("could not set the subagent's model: {error}")));
            }
        } else if let Ok(model) = lane.get_model().await {
            lock(&progress).model = model.id;
        }
        // The type's thinking level, as close as its model allows.
        if let (Some(level), Ok(model)) = (agent.thinking, lane.get_model().await) {
            if model.reasoning {
                if let Err(error) = lane.set_thinking_level(model.clamp_thinking_level(level)).await {
                    let _ = child.harness.close().await;
                    return Err(AgentError::Tool(format!("could not set the subagent's thinking level: {error}")));
                }
            }
        }
        // A background child outlives this run; a foreground one ends with it.
        let scope = if input.background { parent.session_scope_token() } else { child.scope.clone() };

        let place = match &worktree {
            Some(created) => format!(
                "\n\nYour working folder is an isolated Git worktree at {} on branch `{}`, cut from the current \
                 commit. Make your changes there and do not commit them: the requester reviews them.",
                created.cwd.display(),
                created.worktree.branch
            ),
            None => String::new(),
        };
        let brief = format!(
            "{}{place}\n\nYou are a subagent: you cannot delegate to other agents, and the requester sees only \
             your final reply, so end with a complete, concise report.\n\nTask:\n{task}",
            agent.prompt
        );

        let meta = {
            let progress = lock(&progress);
            json!({
                "agentType": agent.name,
                "model": progress.model,
                "background": input.background,
                "callId": tool_call_id,
                "worktree": progress.worktree,
                "resumable": true,
            })
        };
        let cancel_id = id.clone();
        mesh::router().spawn(
            address.clone(),
            &description,
            Origin::Agent,
            meta,
            Some(Arc::new(move || registry().cancel(&cancel_id))),
        );
        let job = Arc::new(Job {
            id,
            address,
            parent: parent.downgrade(),
            session_id,
            call_id: Mutex::new(tool_call_id.to_string()),
            progress,
            update,
            child: Mutex::new(Some(ChildParts {
                harness: child.harness.clone(),
                execution_scope: child.execution_scope.clone(),
            })),
            cancel: Mutex::new(CancellationToken::new()),
            running: AtomicBool::new(true),
            background: AtomicBool::new(input.background),
            quiet: AtomicBool::new(false),
            worktree: Mutex::new(worktree),
            cwd: self.cwd.clone(),
            last_used: Mutex::new(Instant::now()),
        });
        registry().insert(job.clone());
        drive(job, brief, input.background, scope, signal, on_update).await
    }
}

// ── The `message_agent` tool ────────────────────────────────────────────────

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct MessageInput {
    agent_id: String,
    message: String,
    #[serde(default)]
    background: bool,
}

pub struct MessageAgentTool {
    schema: Tool,
    harness: HarnessCell,
}

pub fn create_message_agent_tool(harness: HarnessCell) -> Arc<dyn AgentTool> {
    Arc::new(MessageAgentTool {
        harness,
        schema: Tool {
            name: "message_agent".into(),
            description: "Send a finished subagent another message; it continues with its own context (what it \
                          read and did before), which is cheaper than starting a new agent with the whole \
                          brief again. Use the id from the agent call's result. Set background to true to let \
                          it run while you continue; its reply then arrives as a message."
                .into(),
            parameters: Schema::new(json!({
                "type": "object",
                "properties": {
                    "agentId": { "type": "string", "description": "The subagent's id." },
                    "message": { "type": "string", "description": "What to tell or ask it." },
                    "background": { "type": "boolean", "description": "Run in the background." }
                },
                "required": ["agentId", "message"],
                "additionalProperties": false
            })),
            constrained_sampling: None,
        },
    })
}

#[async_trait]
impl AgentTool for MessageAgentTool {
    fn schema(&self) -> &Tool {
        &self.schema
    }

    fn label(&self) -> &str {
        "message_agent"
    }

    fn execution_mode(&self) -> ToolExecutionMode {
        ToolExecutionMode::Parallel
    }

    async fn execute(
        &self,
        tool_call_id: &str,
        params: Value,
        signal: CancellationToken,
        on_update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let input: MessageInput = serde_json::from_value(params)
            .map_err(|e| AgentError::Validation(format!("message_agent input invalid: {e}")))?;
        refuse_nested()?;
        let message = input.message.trim();
        if message.is_empty() || message.len() > 50_000 {
            return Err(AgentError::Validation("message must contain 1-50000 bytes".into()));
        }
        let parent = parent_of(&self.harness)?;
        let session_id = parent.session().storage().metadata().id.clone();
        let job = registry()
            .get(&input.agent_id)
            .filter(|job| job.session_id == session_id)
            .ok_or_else(|| AgentError::Validation(format!("no subagent `{}` in this session", input.agent_id)))?;
        if job.running.load(Ordering::Acquire) {
            return Err(AgentError::Tool(format!("subagent {} is still running", job.id)));
        }
        if lock(&job.child).is_none() {
            return Err(AgentError::Tool(format!(
                "subagent {} cannot continue (it was closed, or its unchanged worktree was removed); start a new one",
                job.id
            )));
        }
        check_capacity(&session_id)?;
        job.running.store(true, Ordering::Release);
        *lock(&job.call_id) = tool_call_id.to_string();
        // Background: on the session's scope; foreground: ends with this call.
        let scope = if input.background { parent.session_scope_token() } else { signal.child_token() };
        drive(job, message.to_string(), input.background, scope, signal, on_update).await
    }
}

#[cfg(test)]
mod tests;
