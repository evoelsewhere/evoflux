//! Peer messaging between the conversations this engine hosts (session mesh
//! phase 4, `docs/features/session-mesh-protocol/sdd.md`): the `send_message`,
//! `ask`, `reply`, `list_nodes` and `cancel_node` tools.
//!
//! The session has one instance of each (bound to the session's node); every
//! subagent gets its own, bound to its node (`agent_tool.rs` passes them as
//! the child's tool replacements), so a call knows who is calling. The
//! session's instances refuse calls from any other child (plugin children).
//!
//! - **Who may talk to whom.** A node reaches its parent, its children and,
//!   with the `mail.siblings` capability, its siblings — never another tree.
//! - **Delivery.** Mail is a user-role `<mail …>` message. A running receiver
//!   gets it before its next model call; an idle session gets it with its next
//!   run and a wake request (`meta.wakeReasons` = `mail`); an idle agent gets
//!   it when it is continued — except for an `ask`, which continues it at once.
//! - **ask / reply.** `ask` blocks the caller until the receiver calls
//!   `reply` with the ask's id, its run ends (its final text is the answer),
//!   or the timeout. The router's wait-for graph refuses an ask that would
//!   close a cycle (including asking the session that waits on you in a
//!   foreground `agent` call), and a pair of nodes may exchange at most
//!   [`crate::mesh::MAX_PAIR_MAIL`] messages per session run.

use std::sync::{Arc, LazyLock, Mutex};
use std::time::Duration;

use async_trait::async_trait;
use evo_agent::agent_tool::AgentTool;
use evo_agent::error::AgentError;
use evo_agent::types::{AgentToolResult, TextContentOrImage, ToolExecutionMode, ToolResultPartial};
use evo_agent::AgentMessage;
use evo_ai::types::{Schema, Tool};
use evo_harness::agent_harness::{AgentHarness, WeakAgentHarness};
use serde_json::{json, Value};
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use crate::mesh::{self, Address, ListScope, Node, NodeKind, NodeState};

/// The session's harness, bound once it exists.
pub type HarnessCell = Arc<std::sync::OnceLock<WeakAgentHarness>>;

/// Names of the tools, for agent types that narrow the tool list.
pub const TOOL_NAMES: [&str; 5] = ["send_message", "ask", "reply", "list_nodes", "cancel_node"];
const DEFAULT_ASK_SECS: u64 = 600;
const MAX_ASK_SECS: u64 = 1800;
const MAX_TEXT: usize = 20_000;

fn now_ms() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

fn text_result(text: impl Into<String>, details: Value) -> AgentToolResult {
    AgentToolResult { content: vec![TextContentOrImage::text(text.into())], details, ..Default::default() }
}

// ── Pending asks ─────────────────────────────────────────────────────────────

struct PendingAsk {
    id: String,
    from: Address,
    to: Address,
    answer: oneshot::Sender<String>,
}

static ASKS: LazyLock<Mutex<Vec<PendingAsk>>> = LazyLock::new(Default::default);

/// `node`'s run ended: questions to it that it did not answer get `text`
/// (its final reply) as their answer.
pub fn run_ended(node: &Address, text: &str) {
    let answered: Vec<PendingAsk> = {
        let mut asks = lock(&ASKS);
        let (done, open): (Vec<_>, Vec<_>) = asks.drain(..).partition(|ask| ask.to == *node);
        *asks = open;
        done
    };
    for ask in answered {
        let answer = if text.trim().is_empty() {
            "(it finished without answering)".to_string()
        } else {
            format!("(it did not call reply; its final message)\n{}", text.trim())
        };
        let _ = ask.answer.send(answer);
    }
}

/// Open questions to `node`, oldest first (`list_nodes` shows them).
fn asks_to(node: &Address) -> Vec<Value> {
    lock(&ASKS)
        .iter()
        .filter(|ask| ask.to == *node)
        .map(|ask| json!({ "askId": ask.id, "from": ask.from }))
        .collect()
}

// ── Context ──────────────────────────────────────────────────────────────────

struct Ctx {
    harness: HarnessCell,
    /// The node these instances act for; `None`: the session itself.
    me: Option<Address>,
}

impl Ctx {
    fn session(&self) -> Result<AgentHarness, AgentError> {
        self.harness
            .get()
            .and_then(WeakAgentHarness::upgrade)
            .ok_or_else(|| AgentError::Tool("the session is not ready".into()))
    }

    fn session_address(&self) -> Result<Address, AgentError> {
        Ok(Address::session(&self.session()?.session().storage().metadata().id))
    }

    /// Who is calling.
    fn caller(&self) -> Result<Address, AgentError> {
        match &self.me {
            Some(me) => Ok(me.clone()),
            None if evo_agent::tool_execution_scope::is_child_execution() => {
                Err(AgentError::Tool("this tool is not available to this kind of child agent".into()))
            }
            None => self.session_address(),
        }
    }
}

/// The node record of `address`, or a stand-in for a session the router
/// does not know (an engine with no RPC client: tests, headless).
fn node_of(address: &Address) -> Node {
    mesh::router().get(address).unwrap_or_else(|| {
        let mut node = Node::new(address.clone(), None, "", mesh::Origin::User);
        node.state = NodeState::Idle;
        node.caps = vec!["mail.children".into()];
        node
    })
}

fn title_of(node: &Node) -> String {
    match node.kind {
        NodeKind::Session => "the session".into(),
        _ if node.title.is_empty() => node.id.to_string(),
        _ => node.title.clone(),
    }
}

/// The nodes `me` may address: parent, children, and siblings (capability).
fn reachable(me: &Node) -> Vec<Node> {
    let router = mesh::router();
    let mut out = Vec::new();
    if let Some(parent) = &me.parent {
        out.push(node_of(parent));
        if me.caps.iter().any(|cap| cap == "mail.siblings") {
            let siblings = router.list(ListScope::Children, Some(parent)).unwrap_or_default();
            out.extend(siblings.into_iter().filter(|n| n.id != me.id && n.kind == NodeKind::Agent));
        }
    }
    let children = router.list(ListScope::Children, Some(&me.id)).unwrap_or_default();
    out.extend(children.into_iter().filter(|n| n.kind == NodeKind::Agent));
    out
}

/// `to` as given by a model: `parent`, an address, an agent id, or a title.
fn resolve(me: &Node, to: &str) -> Result<Node, AgentError> {
    let to = to.trim();
    let candidates = reachable(me);
    let found = if to.eq_ignore_ascii_case("parent") {
        me.parent.as_ref().and_then(|p| candidates.iter().find(|n| n.id == *p))
    } else {
        candidates.iter().find(|n| {
            n.id.as_str() == to
                || n.id.as_str().ends_with(&format!("/a_{to}"))
                || (!n.title.is_empty() && n.title.eq_ignore_ascii_case(to))
        })
    };
    found.cloned().ok_or_else(|| {
        let names: Vec<String> = candidates.iter().map(|n| format!("{} ({})", n.id, title_of(n))).collect();
        AgentError::Validation(format!(
            "`{to}` is not a node you can reach; you can reach: {}",
            if names.is_empty() { "nobody".to_string() } else { names.join(", ") }
        ))
    })
}

/// The `<mail …>` message the receiver's model reads.
fn render(id: &str, from: &Node, ask: bool, text: &str) -> String {
    let kind = if ask { "ask" } else { "message" };
    let mut body = format!(
        "<mail id=\"{id}\" from=\"{}\" title=\"{}\" kind=\"{kind}\">\n{}\n",
        from.id,
        title_of(from).replace('"', "'"),
        text.trim()
    );
    if ask {
        body.push_str(&format!(
            "(A question for you: answer it with the reply tool, askId \"{id}\". The asker waits for your answer.)\n"
        ));
    }
    body.push_str("</mail>");
    body
}

/// Put `text` in front of `to`'s model. Returns how it was delivered.
async fn deliver(ctx: &Ctx, from: &Node, to: &Node, text: String, ask: bool) -> Result<&'static str, AgentError> {
    match to.kind {
        NodeKind::Session => {
            let session = ctx.session()?;
            if to.id != ctx.session_address()? {
                return Err(AgentError::Tool(format!("{} runs in another engine", to.id)));
            }
            let message = AgentMessage::from(evo_ai::types::UserMessage::new(text, now_ms()));
            let lane = session.lane("main");
            if session.has_active_run() {
                lane.steer(message).await.map_err(|e| AgentError::Tool(e.to_string()))?;
                Ok("delivered into its current turn")
            } else {
                lane.next_run(message).await.map_err(|e| AgentError::Tool(e.to_string()))?;
                mesh::router().request_wake_for(&to.id, &from.id, Some(&title_of(from)), "mail");
                Ok("queued for its next turn; it is being woken")
            }
        }
        NodeKind::Agent => crate::agent_tool::deliver(&to.id, text, ask)
            .await
            .map_err(AgentError::Tool),
        NodeKind::Side => Err(AgentError::Tool("side questions take no messages".into())),
    }
}

// ── Tools ────────────────────────────────────────────────────────────────────

fn schema(name: &str, description: &str, parameters: Value) -> Tool {
    Tool { name: name.into(), description: description.into(), parameters: Schema::new(parameters), constrained_sampling: None }
}

/// The five tools for the session (`me: None`) or for the agent at `me`.
pub fn create(harness: HarnessCell, me: Option<Address>) -> Vec<Arc<dyn AgentTool>> {
    let ctx = Arc::new(Ctx { harness, me });
    vec![
        Arc::new(SendMessage { ctx: ctx.clone(), schema: schema(
            "send_message",
            "Send a message to another agent of this session: your parent (`to`: \"parent\"), an agent you started, or — for a subagent — another subagent of the same parent. It does not wait for an answer (use ask for that). A running receiver reads it before its next step; an idle session is woken to read it; an idle agent reads it when it is continued. Find who you can reach with list_nodes.",
            json!({
                "type": "object",
                "properties": {
                    "to": { "type": "string", "description": "\"parent\", or a node's id, agent id or title (from list_nodes)." },
                    "message": { "type": "string", "description": "What to tell it." }
                },
                "required": ["to", "message"],
                "additionalProperties": false
            }),
        ) }),
        Arc::new(Ask { ctx: ctx.clone(), schema: schema(
            "ask",
            "Ask another agent of this session a question and wait for its answer (it answers with the reply tool; an agent that ends its run without replying answers with its final message). Use it when you cannot go on without the answer; otherwise use send_message. An idle agent is continued to answer. Asking someone who is waiting on you is refused (it would never end), e.g. a subagent asking the session that waits for its report: put the question in your report instead.",
            json!({
                "type": "object",
                "properties": {
                    "to": { "type": "string", "description": "\"parent\", or a node's id, agent id or title (from list_nodes)." },
                    "question": { "type": "string", "description": "The question, with what the receiver needs to answer it." },
                    "timeoutSeconds": { "type": "integer", "minimum": 10, "maximum": MAX_ASK_SECS, "description": "How long to wait (default 600)." }
                },
                "required": ["to", "question"],
                "additionalProperties": false
            }),
        ) }),
        Arc::new(Reply { ctx: ctx.clone(), schema: schema(
            "reply",
            "Answer a question another agent asked you (a <mail kind=\"ask\"> message): it is waiting for this answer.",
            json!({
                "type": "object",
                "properties": {
                    "askId": { "type": "string", "description": "The question's id (the mail's id)." },
                    "answer": { "type": "string", "description": "Your answer." }
                },
                "required": ["askId", "answer"],
                "additionalProperties": false
            }),
        ) }),
        Arc::new(ListNodes { ctx: ctx.clone(), schema: schema(
            "list_nodes",
            "List the agents you can talk to (your parent, the agents you started, your sibling subagents) with their id, title, kind and state (running, settled, …), and the questions waiting for your reply.",
            json!({ "type": "object", "properties": {}, "additionalProperties": false }),
        ) }),
        Arc::new(CancelNode { ctx, schema: schema(
            "cancel_node",
            "Stop an agent you started (and anything it started). Its run ends as cancelled.",
            json!({
                "type": "object",
                "properties": { "node": { "type": "string", "description": "The agent's id, node id or title." } },
                "required": ["node"],
                "additionalProperties": false
            }),
        ) }),
    ]
}

fn string_arg(params: &Value, key: &str) -> Result<String, AgentError> {
    let value = params.get(key).and_then(Value::as_str).map(str::trim).unwrap_or_default();
    if value.is_empty() || value.len() > MAX_TEXT {
        return Err(AgentError::Validation(format!("`{key}` must contain 1-{MAX_TEXT} bytes")));
    }
    Ok(value.to_string())
}

macro_rules! tool_basics {
    ($name:literal) => {
        fn schema(&self) -> &Tool {
            &self.schema
        }
        fn label(&self) -> &str {
            $name
        }
        fn execution_mode(&self) -> ToolExecutionMode {
            ToolExecutionMode::Parallel
        }
    };
}

struct SendMessage {
    ctx: Arc<Ctx>,
    schema: Tool,
}

#[async_trait]
impl AgentTool for SendMessage {
    tool_basics!("send_message");

    async fn execute(
        &self,
        _call: &str,
        params: Value,
        _signal: CancellationToken,
        _update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let me = node_of(&self.ctx.caller()?);
        let to = resolve(&me, &string_arg(&params, "to")?)?;
        let message = string_arg(&params, "message")?;
        mesh::router().count_mail(&me.id, &to.id).map_err(|e| AgentError::Tool(e.message))?;
        let id = mesh::router().next_id();
        let how = deliver(&self.ctx, &me, &to, render(&id, &me, false, &message), false).await?;
        Ok(text_result(
            format!("Sent to {} ({how}).", title_of(&to)),
            json!({ "mail": { "id": id, "from": me.id, "to": to.id, "delivery": how } }),
        ))
    }
}

struct Ask {
    ctx: Arc<Ctx>,
    schema: Tool,
}

#[async_trait]
impl AgentTool for Ask {
    tool_basics!("ask");

    async fn execute(
        &self,
        _call: &str,
        params: Value,
        signal: CancellationToken,
        _update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let me = node_of(&self.ctx.caller()?);
        let to = resolve(&me, &string_arg(&params, "to")?)?;
        let question = string_arg(&params, "question")?;
        let secs = params.get("timeoutSeconds").and_then(Value::as_u64).unwrap_or(DEFAULT_ASK_SECS).clamp(10, MAX_ASK_SECS);
        let router = mesh::router();
        // Waiting on someone who waits on us would never end.
        let _wait = router.try_wait(&me.id, &to.id).map_err(|e| AgentError::Tool(e.message))?;
        router.count_mail(&me.id, &to.id).map_err(|e| AgentError::Tool(e.message))?;
        let id = router.next_id();
        let (answer_tx, answer_rx) = oneshot::channel();
        lock(&ASKS).push(PendingAsk { id: id.clone(), from: me.id.clone(), to: to.id.clone(), answer: answer_tx });
        let forget = |id: &str| lock(&ASKS).retain(|ask| ask.id != id);
        if let Err(error) = deliver(&self.ctx, &me, &to, render(&id, &me, true, &question), true).await {
            forget(&id);
            return Err(error);
        }
        let outcome = tokio::select! {
            answer = answer_rx => answer.map_err(|_| "the question was dropped".to_string()),
            _ = tokio::time::sleep(Duration::from_secs(secs)) => Err(format!("no answer within {secs} seconds")),
            _ = signal.cancelled() => Err("cancelled".to_string()),
        };
        forget(&id);
        let answer = outcome.map_err(|reason| AgentError::Tool(format!("{} did not answer: {reason}", title_of(&to))))?;
        Ok(text_result(
            format!("{} answered:\n{answer}", title_of(&to)),
            json!({ "ask": { "id": id, "from": me.id, "to": to.id } }),
        ))
    }
}

struct Reply {
    ctx: Arc<Ctx>,
    schema: Tool,
}

#[async_trait]
impl AgentTool for Reply {
    tool_basics!("reply");

    async fn execute(
        &self,
        _call: &str,
        params: Value,
        _signal: CancellationToken,
        _update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let me = self.ctx.caller()?;
        let id = string_arg(&params, "askId")?;
        let answer = string_arg(&params, "answer")?;
        let ask = {
            let mut asks = lock(&ASKS);
            let Some(index) = asks.iter().position(|ask| ask.id == id) else {
                return Err(AgentError::Validation(format!(
                    "no open question `{id}` (it was answered, timed out or never asked)"
                )));
            };
            if asks[index].to != me {
                return Err(AgentError::Validation(format!("question `{id}` was not asked to you")));
            }
            asks.remove(index)
        };
        let to = ask.from.clone();
        let _ = ask.answer.send(answer);
        Ok(text_result(format!("Answered {to}."), json!({ "reply": { "askId": id, "to": to } })))
    }
}

struct ListNodes {
    ctx: Arc<Ctx>,
    schema: Tool,
}

#[async_trait]
impl AgentTool for ListNodes {
    tool_basics!("list_nodes");

    async fn execute(
        &self,
        _call: &str,
        _params: Value,
        _signal: CancellationToken,
        _update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let me = node_of(&self.ctx.caller()?);
        let nodes: Vec<Value> = reachable(&me)
            .into_iter()
            .map(|node| {
                let relation = if Some(&node.id) == me.parent.as_ref() {
                    "parent"
                } else if node.parent.as_ref() == Some(&me.id) {
                    "child"
                } else {
                    "sibling"
                };
                json!({
                    "id": node.id, "title": title_of(&node), "kind": node.kind, "relation": relation,
                    "state": node.state, "status": node.status, "agentType": node.meta.get("agentType"),
                })
            })
            .collect();
        let listing = json!({ "you": me.id, "nodes": nodes, "questionsForYou": asks_to(&me.id) });
        Ok(text_result(listing.to_string(), listing))
    }
}

struct CancelNode {
    ctx: Arc<Ctx>,
    schema: Tool,
}

#[async_trait]
impl AgentTool for CancelNode {
    tool_basics!("cancel_node");

    async fn execute(
        &self,
        _call: &str,
        params: Value,
        _signal: CancellationToken,
        _update: Arc<dyn Fn(ToolResultPartial) + Send + Sync>,
    ) -> Result<AgentToolResult, AgentError> {
        let me = node_of(&self.ctx.caller()?);
        let target = resolve(&me, &string_arg(&params, "node")?)?;
        if target.parent.as_ref() != Some(&me.id) {
            return Err(AgentError::Validation(format!("{} was not started by you", title_of(&target))));
        }
        let cancelled = mesh::router().cancel(&target.id, true).map_err(|e| AgentError::Tool(e.message))?;
        let text = if cancelled.is_empty() {
            format!("{} was not running.", title_of(&target))
        } else {
            format!("Stopped {}.", title_of(&target))
        };
        Ok(text_result(text, json!({ "cancelled": cancelled })))
    }
}
