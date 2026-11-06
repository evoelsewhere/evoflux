//! The hub: sessions talking to sessions (`docs/features/session-mesh-protocol/sdd.md`).
//!
//! Each session runs in its own engine; whoever relays those engines' stdout
//! (the desktop shell) feeds every line to [`Hub::on_line`] and carries out the
//! [`Effect`]s it returns. The hub keeps no engine handles and does no IO
//! itself (the [`MailStore`] does the storage), so it is the same in the shell
//! and in tests.
//!
//! What it does:
//!
//! - **Session tools.** It answers a session's `start_session`,
//!   `message_session` and `list_sessions` calls ([`session_tools`] defines
//!   them; the host registers them as external tools). Starting creates the
//!   child chat through the store and sends it its brief; messaging sends a
//!   prompt; listing reads the children and their live state.
//! - **Reports to the parent.** When a session finishes a turn its engine
//!   emits a `node_report` about its own node. If another session started it,
//!   the hub turns the report into a `<nested-session …>` note for the parent,
//!   delivered with `wake`.
//! - **Durable delivery.** Mail is stored before it is sent and marked
//!   delivered only when the receiving engine accepts it. Notes go out once the
//!   receiving engine is `ready`; prompts once a window has *hosted* it (set
//!   up its tools, [`Hub::on_hosted`]), as a `prompt` when it is idle or a
//!   `queue_message` follow-up while it runs. Mail for a chat with no engine
//!   asks the host to start one ([`Effect::Host`]). Delivery is at least once;
//!   engines drop duplicate notes by id.

use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::wire::{Address, Deliver, Envelope, MailBody, MeshEvent, RunStatus};

/// Characters of a session's reply quoted in its note to the parent.
pub const REPORT_CHARS: usize = 400;
/// Report envelope ids remembered per chat (replays repeat recent ones).
const SEEN_REPORTS: usize = 256;
/// Nested sessions of one chat that may run at once.
pub const MAX_RUNNING_CHILDREN: usize = 8;

/// One message between sessions, as stored.
#[derive(Debug, Clone, PartialEq)]
pub struct Mail {
    pub id: String,
    /// The sending chat (session) id.
    pub from_chat: String,
    /// The receiving chat (session) id.
    pub to_chat: String,
    pub body: MailBody,
    pub created_at: i64,
}

impl Mail {
    /// The envelope that carries a note to the receiver's engine.
    pub fn envelope(&self) -> Envelope {
        Envelope::mail(
            self.id.clone(),
            Address::session(&self.from_chat).to_string(),
            Address::session(&self.to_chat).to_string(),
            &self.body,
        )
    }
}

/// A session to start (the `start_session` arguments).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SessionSpec {
    pub title: String,
    /// Its brief: the first prompt it gets.
    pub prompt: String,
    /// `fork`: a copy of the parent's conversation; otherwise fresh.
    #[serde(default)]
    pub fork: bool,
    /// Work in its own Git worktree.
    #[serde(default)]
    pub worktree: bool,
}

/// A chat the store created for a [`SessionSpec`].
#[derive(Debug, Clone, PartialEq)]
pub struct CreatedSession {
    pub id: String,
    pub title: String,
    /// Where its engine should work (a worktree's subfolder); `None`: the chat's folder.
    pub cwd: Option<String>,
}

/// A nested session as `list_sessions` shows it.
#[derive(Debug, Clone, PartialEq)]
pub struct ChildInfo {
    pub id: String,
    pub title: String,
    pub unread: bool,
    pub preview: Option<String>,
}

/// Where the hub keeps mail and reads (and creates) chats.
pub trait MailStore: Send + Sync {
    /// The chat that started `chat`, if any.
    fn parent_of(&self, chat: &str) -> Option<String>;
    /// `chat`'s title, for notes.
    fn title_of(&self, chat: &str) -> Option<String>;
    fn insert(&self, mail: &Mail) -> Result<(), String>;
    /// Undelivered mail for `chat`, oldest first.
    fn pending(&self, chat: &str) -> Vec<Mail>;
    fn mark_delivered(&self, id: &str);
    /// The sessions `parent` started (not archived).
    fn children_of(&self, parent: &str) -> Vec<ChildInfo>;
    /// Create a nested session of `parent` (its chat row, worktree, fork).
    fn create_session(&self, parent: &str, spec: &SessionSpec) -> Result<CreatedSession, String>;
}

/// What the host must do after a line.
#[derive(Debug, Clone, PartialEq)]
pub enum Effect {
    /// Write `line` to `chat`'s engine.
    Send { chat: String, line: Value },
    /// `chat` has mail but no engine set up to take it: a window should start
    /// (or set up) its engine, in `cwd` if given, restoring its transcript
    /// when `restore`, then call [`Hub::on_hosted`].
    Host { chat: String, cwd: Option<String>, restore: bool },
    /// A turn of `chat` is about to start with `text` (comes right before
    /// the `Send` of the prompt). The engine does not echo a run's prompt,
    /// so the window showing the chat adds the turn, as for a typed prompt.
    Prompted { chat: String, text: String },
}

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

/// The note a nested session's turn leaves for its parent.
pub fn session_note(chat: &str, title: &str, status: RunStatus, text: &str) -> String {
    let status = match status {
        RunStatus::Done => "done",
        RunStatus::Failed => "error",
        RunStatus::Cancelled => "cancelled",
    };
    let mut report: String = text.trim().chars().take(REPORT_CHARS).collect();
    if report.is_empty() {
        report = "(no reply text)".into();
    }
    format!(
        "<nested-session id=\"{chat}\" title=\"{}\" status=\"{status}\">\n{report}\n</nested-session>",
        title.replace('"', "'")
    )
}

/// The session tools' definitions, for a host to register on a top-level
/// chat's engine as external tools (nested sessions get none: one level).
pub fn session_tools() -> Value {
    json!([
        {
            "name": "start_session",
            "description": "Start a separate, full chat session for a task of its own that should run on its own and that the user may want to open, follow or steer apart from this conversation (not for a quick lookup or a piece of this task: use the agent tool for that). It runs in the background in this workspace; you get a note each time it finishes a turn. By default this only proposes the session and the user decides whether to start it. The prompt is its whole brief: with context \"fresh\" (default) it knows nothing else; \"fork\" gives it a copy of this conversation.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": { "type": "string", "description": "A short title (under 60 characters) naming the task." },
                    "prompt": { "type": "string", "description": "The brief: the task, the files or area, what done looks like." },
                    "context": { "type": "string", "enum": ["fresh", "fork"], "description": "fresh (default) or fork (a copy of this conversation)." },
                    "worktree": { "type": "boolean", "description": "Work in its own Git worktree of this repository, so its edits stay apart until the user applies them." }
                },
                "required": ["title", "prompt"],
                "additionalProperties": false
            }
        },
        {
            "name": "message_session",
            "description": "Send a message to a session started from this chat: a running session reads it at its next step (steering), an idle one starts a turn with it. Use this instead of starting a new session for the same task.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sessionId": { "type": "string", "description": "The session's id (from start_session or list_sessions)." },
                    "message": { "type": "string", "description": "What to tell or ask it." }
                },
                "required": ["sessionId", "message"],
                "additionalProperties": false
            }
        },
        {
            "name": "list_sessions",
            "description": "List the sessions started from this chat: id, title, status (running, waiting for the user, idle), unread, and the start of its latest reply.",
            "inputSchema": { "type": "object", "properties": {}, "additionalProperties": false }
        }
    ])
}

const SESSION_TOOLS: [&str; 3] = ["start_session", "message_session", "list_sessions"];

/// Whether the hub answers calls of the tool `name`.
pub fn is_session_tool(name: &str) -> bool {
    SESSION_TOOLS.contains(&name)
}

/// What the hub knows about one chat's engine.
#[derive(Default)]
struct Engine {
    /// Said `ready` and has not exited.
    ready: bool,
    /// A window set it up (tools) and asked for prompts.
    hosted: bool,
    /// A run is active (from `agent_start`, or a prompt we sent, to `agent_settled`).
    busy: bool,
    /// Open approval requests.
    waiting: HashSet<String>,
}

pub struct Hub<S: MailStore> {
    store: S,
    engines: Mutex<HashMap<String, Engine>>,
    /// Mail sent and not answered yet: id → receiving chat.
    in_flight: Mutex<HashMap<String, String>>,
    /// Report envelopes already turned into mail, per chat. An engine replays
    /// its retained state events to every new subscriber (a window opening
    /// the chat), so the same report passes by again; its id is unique.
    seen_reports: Mutex<HashMap<String, VecDeque<String>>>,
    /// `start_session` starts at once instead of proposing (Settings → Sandbox).
    auto_start: AtomicBool,
    epoch: i64,
    ids: AtomicU64,
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

/// An external tool's answer as the engine expects it.
fn tool_result(text: impl Into<String>, structured: Option<Value>, is_error: bool) -> Value {
    let mut result = json!({ "content": [{ "type": "text", "text": text.into() }] });
    if let Some(structured) = structured {
        result["structuredContent"] = structured;
    }
    if is_error {
        result["isError"] = json!(true);
    }
    result
}

impl<S: MailStore> Hub<S> {
    pub fn new(store: S) -> Self {
        Hub {
            store,
            engines: Mutex::new(HashMap::new()),
            in_flight: Mutex::new(HashMap::new()),
            seen_reports: Mutex::new(HashMap::new()),
            auto_start: AtomicBool::new(false),
            epoch: now_ms(),
            ids: AtomicU64::new(0),
        }
    }

    pub fn store(&self) -> &S {
        &self.store
    }

    /// Whether `start_session` starts sessions at once (true) or proposes them.
    pub fn set_auto_start(&self, on: bool) {
        self.auto_start.store(on, Ordering::Release);
    }

    fn next_id(&self, prefix: &str) -> String {
        format!("{prefix}_{}_{}", self.epoch, self.ids.fetch_add(1, Ordering::Relaxed) + 1)
    }

    fn with_engine<T>(&self, chat: &str, f: impl FnOnce(&mut Engine) -> T) -> T {
        f(lock(&self.engines).entry(chat.to_string()).or_default())
    }

    /// Whether `chat`'s engine is ready for notes.
    pub fn is_ready(&self, chat: &str) -> bool {
        self.with_engine(chat, |e| e.ready)
    }

    /// Whether `chat` is running a turn.
    pub fn is_busy(&self, chat: &str) -> bool {
        self.with_engine(chat, |e| e.busy)
    }

    /// `chat`'s engine is starting (again): nothing is ready or in flight there.
    pub fn on_start(&self, chat: &str) {
        lock(&self.engines).remove(chat);
        lock(&self.in_flight).retain(|_, to| to != chat);
    }

    /// `chat`'s engine is gone: its unanswered mail stays pending. If any is,
    /// the host is asked to start the engine again.
    pub fn on_exit(&self, chat: &str) -> Vec<Effect> {
        self.on_start(chat);
        if self.store.pending(chat).is_empty() {
            Vec::new()
        } else {
            vec![Effect::Host { chat: chat.into(), cwd: None, restore: true }]
        }
    }

    /// A window set `chat`'s engine up (its tools) and takes prompts now.
    pub fn on_hosted(&self, chat: &str) -> Vec<Effect> {
        self.with_engine(chat, |e| {
            e.ready = true;
            e.hosted = true;
        });
        self.flush(chat)
    }

    /// One stdout line of `chat`'s engine.
    pub fn on_line(&self, chat: &str, line: &Value) -> Vec<Effect> {
        match line.get("type").and_then(Value::as_str) {
            Some("ready") => {
                self.with_engine(chat, |e| e.ready = true);
                self.flush(chat)
            }
            Some("agent_start") => {
                self.with_engine(chat, |e| e.busy = true);
                Vec::new()
            }
            Some("agent_settled") => {
                self.with_engine(chat, |e| e.busy = false);
                // Prompts that waited for the run to end.
                self.flush(chat)
            }
            Some("ui_dialog_request") => {
                if let Some(id) = line.get("requestId").and_then(Value::as_str) {
                    self.with_engine(chat, |e| e.waiting.insert(id.to_string()));
                }
                Vec::new()
            }
            Some("ui_dialog_closed") => {
                if let Some(id) = line.get("requestId").and_then(Value::as_str) {
                    self.with_engine(chat, |e| e.waiting.remove(id));
                }
                Vec::new()
            }
            Some("response") => {
                self.on_response(chat, line);
                Vec::new()
            }
            Some("external_tool_request") => self.on_tool_call(chat, line),
            Some(crate::wire::WIRE_TYPE) => self.on_envelope(chat, line),
            _ => Vec::new(),
        }
    }

    // ── Notes ────────────────────────────────────────────────────────────

    fn on_envelope(&self, chat: &str, line: &Value) -> Vec<Effect> {
        // Cheap header checks first: activity events are frequent.
        let kind = line.get("kind").and_then(Value::as_str);
        let op = line.get("op").and_then(Value::as_str);
        match (kind, op) {
            (Some("evt"), Some("node_report")) => {}
            (Some("res"), _) => {
                // A note's answer: `res` with `corr` = the mail id.
                if let Some(corr) = line.get("corr").and_then(Value::as_str) {
                    let failed = line.get("body").and_then(|b| b.get("error")).is_some();
                    self.answered(corr, !failed);
                }
                return Vec::new();
            }
            _ => return Vec::new(),
        }
        // A report about the session itself (not one of its agents).
        if line.get("from").and_then(Value::as_str) != Some(Address::session(chat).as_str()) {
            return Vec::new();
        }
        let Ok(envelope) = serde_json::from_value::<Envelope>(line.clone()) else { return Vec::new() };
        let Some(MeshEvent::NodeReport { status, text, .. }) = envelope.as_event() else { return Vec::new() };
        {
            let mut seen = lock(&self.seen_reports);
            let seen = seen.entry(chat.to_string()).or_default();
            if seen.contains(&envelope.id) {
                return Vec::new();
            }
            seen.push_back(envelope.id.clone());
            while seen.len() > SEEN_REPORTS {
                seen.pop_front();
            }
        }
        let Some(parent) = self.store.parent_of(chat) else { return Vec::new() };
        let title = self.store.title_of(chat).unwrap_or_default();
        self.post(chat, &parent, MailBody {
            text: session_note(chat, &title, status, &text),
            deliver: Deliver::Wake,
            title: Some(title),
        })
    }

    /// An RPC response; if it answers a prompt we sent, the prompt is delivered.
    fn on_response(&self, chat: &str, line: &Value) {
        let Some(id) = line.get("id").and_then(Value::as_str) else { return };
        let accepted = line.get("success").and_then(Value::as_bool).unwrap_or(false);
        if lock(&self.in_flight).contains_key(id) && !accepted {
            // Refused (a run started meanwhile): it goes out when that run ends.
            self.with_engine(chat, |e| e.busy = e.busy || line_says_busy(line));
        }
        self.answered(id, accepted);
    }

    /// The receiving engine answered mail `id`: delivered, or still pending.
    fn answered(&self, id: &str, delivered: bool) {
        if lock(&self.in_flight).remove(id).is_some() && delivered {
            self.store.mark_delivered(id);
        }
    }

    // ── Mail ─────────────────────────────────────────────────────────────

    /// Store mail from `from` to `to` and send it if `to` can take it.
    pub fn post(&self, from: &str, to: &str, body: MailBody) -> Vec<Effect> {
        let mail = Mail { id: self.next_id("mail"), from_chat: from.into(), to_chat: to.into(), body, created_at: now_ms() };
        if let Err(error) = self.store.insert(&mail) {
            // Not stored: still try to deliver it now rather than lose it.
            eprintln!("[evo-mesh] could not store mail {}: {error}", mail.id);
        }
        match self.deliverable(&mail) {
            Some(true) => self.send(&mail),
            Some(false) => Vec::new(),
            None => vec![Effect::Host { chat: to.into(), cwd: None, restore: true }],
        }
    }

    /// Can `mail` go out now? `Some(true)` yes, `Some(false)` later (its
    /// engine will flush it), `None` its engine needs a host.
    fn deliverable(&self, mail: &Mail) -> Option<bool> {
        self.with_engine(&mail.to_chat, |e| match mail.body.deliver {
            Deliver::Prompt if e.hosted => Some(true),
            Deliver::Prompt => None,
            _ if e.ready => Some(true),
            _ => None,
        })
    }

    fn send(&self, mail: &Mail) -> Vec<Effect> {
        lock(&self.in_flight).insert(mail.id.clone(), mail.to_chat.clone());
        let mut effects = Vec::new();
        let line = match mail.body.deliver {
            Deliver::Prompt => {
                // A running engine reads it at its next step (steering); an
                // idle one starts a turn (and is busy from now on).
                let busy = self.with_engine(&mail.to_chat, |e| std::mem::replace(&mut e.busy, true));
                if busy {
                    json!({ "type": "queue_message", "id": mail.id, "message": mail.body.text, "deliverAs": "steer" })
                } else {
                    effects.push(Effect::Prompted { chat: mail.to_chat.clone(), text: mail.body.text.clone() });
                    json!({ "type": "prompt", "id": mail.id, "message": mail.body.text })
                }
            }
            _ => serde_json::to_value(mail.envelope()).unwrap_or(Value::Null),
        };
        effects.push(Effect::Send { chat: mail.to_chat.clone(), line });
        effects
    }

    /// Send `chat`'s pending mail that can go now and is not already on its way.
    fn flush(&self, chat: &str) -> Vec<Effect> {
        let pending = self.store.pending(chat);
        let fresh: Vec<Mail> = {
            let in_flight = lock(&self.in_flight);
            pending.into_iter().filter(|mail| !in_flight.contains_key(&mail.id)).collect()
        };
        fresh
            .iter()
            .filter(|mail| self.deliverable(mail) == Some(true))
            .flat_map(|mail| self.send(mail))
            .collect()
    }

    // ── Session tools ────────────────────────────────────────────────────

    /// Start a nested session of `parent` now: create it, send its brief,
    /// and have a window host its engine.
    pub fn start_session(&self, parent: &str, spec: &SessionSpec) -> Result<(CreatedSession, Vec<Effect>), String> {
        let created = self.store.create_session(parent, spec)?;
        let mut effects = self.post(parent, &created.id, MailBody {
            text: spec.prompt.clone(),
            deliver: Deliver::Prompt,
            title: None,
        });
        // A new chat has no engine yet: host it where its worktree says.
        for effect in effects.iter_mut() {
            if let Effect::Host { chat, cwd, restore } = effect {
                if *chat == created.id {
                    *cwd = created.cwd.clone();
                    *restore = spec.fork;
                }
            }
        }
        Ok((created, effects))
    }

    fn children_running(&self, parent: &str) -> usize {
        self.store.children_of(parent).iter().filter(|child| self.is_busy(&child.id)).count()
    }

    fn on_tool_call(&self, chat: &str, line: &Value) -> Vec<Effect> {
        let Some(name) = line.get("toolName").and_then(Value::as_str).filter(|n| is_session_tool(n)) else {
            return Vec::new();
        };
        let Some(request_id) = line.get("requestId").and_then(Value::as_str) else { return Vec::new() };
        let args = line.get("arguments").cloned().unwrap_or(Value::Null);
        let (result, mut effects) = match name {
            "start_session" => self.call_start(chat, &args),
            "message_session" => self.call_message(chat, &args),
            _ => (self.call_list(chat), Vec::new()),
        };
        let answer = json!({
            "type": "external_tool_response",
            "id": self.next_id("hub"),
            "requestId": request_id,
            "result": result,
        });
        effects.insert(0, Effect::Send { chat: chat.into(), line: answer });
        effects
    }

    fn call_start(&self, chat: &str, args: &Value) -> (Value, Vec<Effect>) {
        let text = |key: &str| args.get(key).and_then(Value::as_str).unwrap_or_default().to_string();
        let title: String = text("title").split_whitespace().collect::<Vec<_>>().join(" ").chars().take(120).collect();
        let prompt = text("prompt").trim().to_string();
        let fork = args.get("context").and_then(Value::as_str) == Some("fork");
        let worktree = args.get("worktree").and_then(Value::as_bool).unwrap_or(false);
        if title.is_empty() || prompt.is_empty() {
            return (tool_result("start_session needs a title and a prompt.", None, true), Vec::new());
        }
        if self.store.parent_of(chat).is_some() {
            return (tool_result("Nested sessions cannot start sessions of their own.", None, true), Vec::new());
        }
        let running = self.children_running(chat);
        if running >= MAX_RUNNING_CHILDREN {
            let text = format!("{running} sessions from this chat are already running; wait for one to finish.");
            return (tool_result(text, None, true), Vec::new());
        }
        let context = if fork { "fork" } else { "fresh" };
        if !self.auto_start.load(Ordering::Acquire) {
            let proposal = json!({
                "status": "proposed", "proposalId": self.next_id("proposal"),
                "title": title, "prompt": prompt, "context": context, "worktree": worktree,
            });
            let text = format!(
                "Proposed a session \"{title}\". The user decides whether to start it; if they do, you will get a note each time it finishes a turn. Do not wait for it."
            );
            return (tool_result(text, Some(proposal), false), Vec::new());
        }
        let spec = SessionSpec { title: title.clone(), prompt: prompt.clone(), fork, worktree };
        match self.start_session(chat, &spec) {
            Ok((created, effects)) => {
                let started = json!({
                    "status": "started", "sessionId": created.id, "title": created.title,
                    "prompt": prompt, "context": context, "worktree": worktree,
                });
                let text = format!(
                    "Started session {} (\"{}\"). It runs on its own; you will get a note each time it finishes a turn. Use message_session to follow up.",
                    created.id, created.title
                );
                (tool_result(text, Some(started), false), effects)
            }
            Err(error) => (tool_result(format!("The session could not be started: {error}"), None, true), Vec::new()),
        }
    }

    fn call_message(&self, chat: &str, args: &Value) -> (Value, Vec<Effect>) {
        let target = args.get("sessionId").and_then(Value::as_str).unwrap_or_default();
        let message = args.get("message").and_then(Value::as_str).unwrap_or_default().trim();
        if target.is_empty() || self.store.parent_of(target).as_deref() != Some(chat) {
            return (tool_result(format!("No session {target} was started from this chat."), None, true), Vec::new());
        }
        if message.is_empty() {
            return (tool_result("message_session needs a message.", None, true), Vec::new());
        }
        let title = self.store.title_of(target).unwrap_or_default();
        let effects = self.post(chat, target, MailBody { text: message.into(), deliver: Deliver::Prompt, title: None });
        (tool_result(format!("Sent to \"{title}\". You will get a note when it finishes its turn."), None, false), effects)
    }

    fn call_list(&self, chat: &str) -> Value {
        let sessions: Vec<Value> = self
            .store
            .children_of(chat)
            .into_iter()
            .map(|child| {
                let status = self.with_engine(&child.id, |e| {
                    if !e.waiting.is_empty() {
                        "waiting"
                    } else if e.busy {
                        "running"
                    } else {
                        "idle"
                    }
                });
                json!({
                    "sessionId": child.id, "title": child.title, "status": status,
                    "unread": child.unread, "lastReply": child.preview,
                })
            })
            .collect();
        let structured = json!({ "sessions": sessions });
        tool_result(structured.to_string(), Some(structured), false)
    }
}

/// Whether a refused prompt was refused because a run is active.
fn line_says_busy(line: &Value) -> bool {
    line.get("error").and_then(Value::as_str).is_some_and(|e| e.contains("active") || e.contains("running"))
}

/// A [`MailStore`] in memory (tests, and hosts without a database).
#[derive(Default)]
pub struct MemoryStore {
    pub parents: Mutex<HashMap<String, String>>,
    pub titles: Mutex<HashMap<String, String>>,
    mail: Mutex<Vec<(Mail, bool)>>,
    created: AtomicU64,
}

impl MemoryStore {
    pub fn with_parent(self, child: &str, parent: &str, title: &str) -> Self {
        lock(&self.parents).insert(child.into(), parent.into());
        lock(&self.titles).insert(child.into(), title.into());
        self
    }

    /// Every stored mail and whether it was delivered.
    pub fn all(&self) -> Vec<(Mail, bool)> {
        lock(&self.mail).clone()
    }
}

impl MailStore for MemoryStore {
    fn parent_of(&self, chat: &str) -> Option<String> {
        lock(&self.parents).get(chat).cloned()
    }
    fn title_of(&self, chat: &str) -> Option<String> {
        lock(&self.titles).get(chat).cloned()
    }
    fn insert(&self, mail: &Mail) -> Result<(), String> {
        lock(&self.mail).push((mail.clone(), false));
        Ok(())
    }
    fn pending(&self, chat: &str) -> Vec<Mail> {
        lock(&self.mail).iter().filter(|(m, done)| !done && m.to_chat == chat).map(|(m, _)| m.clone()).collect()
    }
    fn mark_delivered(&self, id: &str) {
        for (mail, done) in lock(&self.mail).iter_mut() {
            if mail.id == id {
                *done = true;
            }
        }
    }
    fn children_of(&self, parent: &str) -> Vec<ChildInfo> {
        let parents = lock(&self.parents);
        let titles = lock(&self.titles);
        let mut children: Vec<ChildInfo> = parents
            .iter()
            .filter(|(_, p)| p.as_str() == parent)
            .map(|(child, _)| ChildInfo {
                id: child.clone(),
                title: titles.get(child).cloned().unwrap_or_default(),
                unread: false,
                preview: None,
            })
            .collect();
        children.sort_by(|a, b| a.id.cmp(&b.id));
        children
    }
    fn create_session(&self, parent: &str, spec: &SessionSpec) -> Result<CreatedSession, String> {
        let id = format!("new-{}", self.created.fetch_add(1, Ordering::Relaxed) + 1);
        lock(&self.parents).insert(id.clone(), parent.into());
        lock(&self.titles).insert(id.clone(), spec.title.clone());
        let cwd = spec.worktree.then(|| format!("/worktrees/{id}"));
        Ok(CreatedSession { id, title: spec.title.clone(), cwd })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wire::{MeshUsage, NodeKind};
    use serde_json::json;

    fn hub() -> Hub<MemoryStore> {
        Hub::new(MemoryStore::default().with_parent("child", "parent", "Fix \"the\" tests"))
    }

    static NEXT: AtomicU64 = AtomicU64::new(0);

    /// A fresh report envelope (each with its own id, as an engine sends them).
    fn report(chat: &str, from: Address, status: RunStatus, text: &str) -> Value {
        let event = MeshEvent::NodeReport { node: from, status, text: text.into(), usage: MeshUsage::default(), worktree: None };
        let id = format!("m_{chat}_{}", NEXT.fetch_add(1, Ordering::Relaxed));
        serde_json::to_value(Envelope::event(id, 1, 0, &event)).unwrap()
    }

    fn ack(mail_line: &Value, error: bool) -> Value {
        let envelope: Envelope = serde_json::from_value(mail_line.clone()).unwrap();
        let body = if error { Err(crate::wire::MeshError::new(crate::wire::ErrorCode::BadRequest, "no")) } else { Ok(json!({})) };
        serde_json::to_value(Envelope::response("r".into(), &envelope, body)).unwrap()
    }

    fn sent(effects: &[Effect]) -> Vec<(String, Value)> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::Send { chat, line } => Some((chat.clone(), line.clone())),
                _ => None,
            })
            .collect()
    }

    fn hosts(effects: &[Effect]) -> Vec<(String, Option<String>, bool)> {
        effects
            .iter()
            .filter_map(|e| match e {
                Effect::Host { chat, cwd, restore } => Some((chat.clone(), cwd.clone(), *restore)),
                _ => None,
            })
            .collect()
    }

    fn call(tool: &str, args: Value) -> Value {
        json!({ "type": "external_tool_request", "requestId": format!("req-{tool}"), "toolName": tool, "arguments": args })
    }

    fn accepted(id: &Value) -> Value {
        json!({ "type": "response", "id": id, "command": "prompt", "success": true, "data": { "accepted": true } })
    }

    #[test]
    fn a_nested_sessions_turn_reaches_its_running_parent_as_a_wake_note() {
        let hub = hub();
        assert!(hub.on_line("parent", &json!({"type":"ready"})).is_empty());
        let effects = hub.on_line("child", &report("child", Address::session("child"), RunStatus::Done, "All green."));
        let sent = sent(&effects);
        assert_eq!(sent.len(), 1);
        let (to, line) = &sent[0];
        assert_eq!(to, "parent");
        let envelope: Envelope = serde_json::from_value(line.clone()).unwrap();
        assert_eq!((envelope.from.as_str(), envelope.to.as_str()), ("s_child", "s_parent"));
        let body = envelope.as_mail().unwrap();
        assert_eq!(body.deliver, Deliver::Wake);
        assert_eq!(body.title.as_deref(), Some("Fix \"the\" tests"));
        assert_eq!(
            body.text,
            "<nested-session id=\"child\" title=\"Fix 'the' tests\" status=\"done\">\nAll green.\n</nested-session>"
        );
        assert!(!hub.store().all()[0].1, "not delivered before the engine answers");
        hub.on_line("parent", &ack(line, false));
        assert!(hub.store().all()[0].1);
        // Nothing left to send when the parent restarts.
        assert!(hub.on_exit("parent").is_empty());
        assert!(hub.on_line("parent", &json!({"type":"ready"})).is_empty());
    }

    #[test]
    fn mail_for_a_closed_session_asks_for_a_host_and_waits() {
        let hub = hub();
        let effects = hub.on_line("child", &report("child", Address::session("child"), RunStatus::Failed, ""));
        assert_eq!(hosts(&effects), vec![("parent".to_string(), None, true)]);
        // Another turn while it is closed: both wait, in order.
        hub.on_line("child", &report("child", Address::session("child"), RunStatus::Done, "second"));
        let sent = sent(&hub.on_line("parent", &json!({"type":"ready"})));
        assert_eq!(sent.len(), 2);
        let first: Envelope = serde_json::from_value(sent[0].1.clone()).unwrap();
        assert!(first.as_mail().unwrap().text.contains("status=\"error\">\n(no reply text)"));
        // A second `ready` does not send what is already on its way.
        assert!(hub.on_line("parent", &json!({"type":"ready"})).is_empty());
        for (_, line) in &sent {
            hub.on_line("parent", &ack(line, false));
        }
        assert!(hub.store().all().iter().all(|(_, done)| *done));
    }

    #[test]
    fn unanswered_or_refused_mail_is_sent_again_after_a_restart() {
        let hub = hub();
        hub.on_line("parent", &json!({"type":"ready"}));
        let first = sent(&hub.on_line("child", &report("child", Address::session("child"), RunStatus::Done, "a")));
        // The engine dies before answering: the host is asked to start it again.
        assert_eq!(hosts(&hub.on_exit("parent")), vec![("parent".to_string(), None, true)]);
        let again = sent(&hub.on_line("parent", &json!({"type":"ready"})));
        assert_eq!(again.len(), 1);
        assert_eq!(again[0].1["id"], first[0].1["id"], "same id: the engine drops duplicates");
        // A refusal leaves it pending too.
        hub.on_line("parent", &ack(&again[0].1, true));
        assert!(!hub.store().all()[0].1);
        hub.on_start("parent");
        assert_eq!(sent(&hub.on_line("parent", &json!({"type":"ready"}))).len(), 1);
    }

    #[test]
    fn only_a_sessions_own_report_with_a_parent_makes_mail() {
        let hub = hub();
        hub.on_line("parent", &json!({"type":"ready"}));
        let agent = Address::session("child").child(NodeKind::Agent, "a1");
        assert!(hub.on_line("child", &report("child", agent, RunStatus::Done, "x")).is_empty());
        assert!(hub.on_line("parent", &report("parent", Address::session("parent"), RunStatus::Done, "x")).is_empty());
        assert!(hub.on_line("other", &report("other", Address::session("child"), RunStatus::Done, "x")).is_empty());
        assert!(hub.on_line("child", &json!({"type":"agent_settled"})).is_empty());
        assert!(hub.on_line("child", &json!("garbage")).is_empty());
        assert!(hub.store().all().is_empty());
    }

    #[test]
    fn a_replayed_report_makes_no_second_mail() {
        let hub = hub();
        hub.on_line("parent", &json!({"type":"ready"}));
        let line = report("child", Address::session("child"), RunStatus::Done, "once");
        assert_eq!(sent(&hub.on_line("child", &line)).len(), 1);
        assert!(hub.on_line("child", &line).is_empty());
        hub.on_start("child");
        assert!(hub.on_line("child", &line).is_empty());
        assert_eq!(hub.store().all().len(), 1);
        let next = report("child", Address::session("child"), RunStatus::Done, "twice");
        assert_eq!(sent(&hub.on_line("child", &next)).len(), 1);
    }

    #[test]
    fn start_session_proposes_unless_auto_start_is_on() {
        let hub = Hub::new(MemoryStore::default());
        let effects = hub.on_line("p", &call("start_session", json!({"title":"  Fix   CI ", "prompt":"Make it green", "worktree": true})));
        let answers = sent(&effects);
        assert_eq!(answers.len(), 1, "only the answer: nothing started");
        let (to, answer) = &answers[0];
        assert_eq!(to, "p");
        assert_eq!((answer["type"].as_str(), answer["requestId"].as_str()), (Some("external_tool_response"), Some("req-start_session")));
        let proposal = &answer["result"]["structuredContent"];
        assert_eq!((proposal["status"].as_str(), proposal["title"].as_str()), (Some("proposed"), Some("Fix CI")));
        assert_eq!((proposal["context"].as_str(), proposal["worktree"].as_bool()), (Some("fresh"), Some(true)));
        assert!(proposal["proposalId"].as_str().unwrap().starts_with("proposal_"));
        assert!(hub.store().children_of("p").is_empty());

        hub.set_auto_start(true);
        let effects = hub.on_line("p", &call("start_session", json!({"title":"Fix CI", "prompt":"Make it green", "context":"fork"})));
        let answer = &sent(&effects)[0].1;
        let started = &answer["result"]["structuredContent"];
        assert_eq!((started["status"].as_str(), started["sessionId"].as_str()), (Some("started"), Some("new-1")));
        // The new chat's engine is hosted (a fork restores its copied transcript).
        assert_eq!(hosts(&effects), vec![("new-1".to_string(), None, true)]);
        assert_eq!(hub.store().parent_of("new-1").as_deref(), Some("p"));
    }

    #[test]
    fn a_started_session_gets_its_brief_once_a_window_hosts_it() {
        let hub = Hub::new(MemoryStore::default());
        let (created, effects) = hub
            .start_session("p", &SessionSpec { title: "T".into(), prompt: "Do it".into(), fork: false, worktree: true })
            .unwrap();
        assert_eq!(hosts(&effects), vec![(created.id.clone(), Some(format!("/worktrees/{}", created.id)), false)]);
        // Ready is not enough: its tools are not set up yet.
        assert!(sent(&hub.on_line(&created.id, &json!({"type":"ready"}))).is_empty());
        let hosted = hub.on_hosted(&created.id);
        // The window showing it adds the turn first: the engine does not echo it.
        assert_eq!(hosted[0], Effect::Prompted { chat: created.id.clone(), text: "Do it".into() });
        let sent_now = sent(&hosted);
        assert_eq!(sent_now.len(), 1);
        let prompt = &sent_now[0].1;
        assert_eq!((prompt["type"].as_str(), prompt["message"].as_str()), (Some("prompt"), Some("Do it")));
        assert!(hub.is_busy(&created.id));
        hub.on_line(&created.id, &accepted(&prompt["id"]));
        assert!(hub.store().all()[0].1, "accepted: delivered");
    }

    #[test]
    fn message_session_prompts_an_idle_child_and_steers_a_busy_one() {
        let hub = hub();
        hub.on_hosted("child");
        // Only the chat that started it may message it.
        let refused = sent(&hub.on_line("stranger", &call("message_session", json!({"sessionId":"child","message":"hi"}))));
        assert_eq!(refused[0].1["result"]["isError"], true);
        let effects = hub.on_line("parent", &call("message_session", json!({"sessionId":"child","message":"and the docs?"})));
        let sent_now = sent(&effects);
        assert_eq!(sent_now[0].1["result"]["content"][0]["text"], "Sent to \"Fix \"the\" tests\". You will get a note when it finishes its turn.");
        assert_eq!((sent_now[1].0.as_str(), sent_now[1].1["type"].as_str()), ("child", Some("prompt")));
        // While that turn runs, the next one steers it (read at its next step).
        hub.on_line("child", &json!({"type":"agent_start"}));
        let next = sent(&hub.on_line("parent", &call("message_session", json!({"sessionId":"child","message":"also tests"}))));
        assert_eq!((next[1].1["type"].as_str(), next[1].1["deliverAs"].as_str()), (Some("queue_message"), Some("steer")));
    }

    #[test]
    fn a_refused_prompt_goes_out_when_the_run_ends() {
        let hub = hub();
        hub.on_hosted("child");
        let first = sent(&hub.on_line("parent", &call("message_session", json!({"sessionId":"child","message":"one"}))));
        // The engine refused: a run had just started.
        hub.on_line("child", &json!({"type":"response","id": first[1].1["id"], "success": false, "error": "a run is already active"}));
        assert!(!hub.store().all()[0].1);
        let retried = sent(&hub.on_line("child", &json!({"type":"agent_settled"})));
        assert_eq!(retried.len(), 1);
        assert_eq!((retried[0].1["type"].as_str(), retried[0].1["id"].clone()), (Some("prompt"), first[1].1["id"].clone()));
    }

    #[test]
    fn a_message_to_a_closed_child_hosts_it_first() {
        let hub = hub();
        let effects = hub.on_line("parent", &call("message_session", json!({"sessionId":"child","message":"wake up"})));
        assert_eq!(hosts(&effects), vec![("child".to_string(), None, true)]);
        assert_eq!(sent(&hub.on_hosted("child"))[0].1["message"], "wake up");
    }

    #[test]
    fn list_sessions_shows_live_state_and_nested_sessions_cannot_start_more() {
        let hub = hub();
        let list = |hub: &Hub<MemoryStore>| sent(&hub.on_line("parent", &call("list_sessions", json!({}))))[0].1["result"]["structuredContent"]["sessions"][0]["status"].clone();
        assert_eq!(list(&hub), "idle");
        hub.on_line("child", &json!({"type":"agent_start"}));
        assert_eq!(list(&hub), "running");
        hub.on_line("child", &json!({"type":"ui_dialog_request","requestId":"q"}));
        assert_eq!(list(&hub), "waiting");
        hub.on_line("child", &json!({"type":"ui_dialog_closed","requestId":"q"}));
        hub.on_line("child", &json!({"type":"agent_settled"}));
        assert_eq!(list(&hub), "idle");
        // One level deep.
        hub.set_auto_start(true);
        let answer = sent(&hub.on_line("child", &call("start_session", json!({"title":"x","prompt":"y"}))));
        assert_eq!(answer[0].1["result"]["isError"], true);
        // Other tools are not the hub's.
        assert!(hub.on_line("parent", &call("browser_open", json!({}))).is_empty());
    }

    #[test]
    fn running_children_are_capped() {
        let store = MemoryStore::default();
        for i in 0..MAX_RUNNING_CHILDREN {
            lock(&store.parents).insert(format!("c{i}"), "p".into());
        }
        let hub = Hub::new(store);
        hub.set_auto_start(true);
        for i in 0..MAX_RUNNING_CHILDREN {
            hub.on_line(&format!("c{i}"), &json!({"type":"agent_start"}));
        }
        let answer = sent(&hub.on_line("p", &call("start_session", json!({"title":"x","prompt":"y"}))));
        assert!(answer[0].1["result"]["content"][0]["text"].as_str().unwrap().contains("already running"));
    }

    #[test]
    fn long_reports_are_cut_and_titles_quoted() {
        let note = session_note("c", "a \"b\"", RunStatus::Cancelled, &"é".repeat(REPORT_CHARS + 50));
        assert!(note.starts_with("<nested-session id=\"c\" title=\"a 'b'\" status=\"cancelled\">\n"));
        assert_eq!(note.matches('é').count(), REPORT_CHARS);
        assert_eq!(session_tools().as_array().unwrap().len(), 3);
        assert!(is_session_tool("list_sessions") && !is_session_tool("agent"));
    }
}
