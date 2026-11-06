//! Session mesh wire types, version 1 (`docs/features/session-mesh-protocol/sdd.md`).
//!
//! One envelope for everything said between conversations — sessions, nested
//! sessions, subagents, side questions — and their clients. On the existing
//! JSONL/CBOR stream an envelope is one object tagged `"type":"mesh"`, so a
//! peer that does not speak the mesh skips it like any unknown event:
//!
//! ```json
//! {"type":"mesh","v":1,"id":"m_1","kind":"evt","op":"node_state","from":"s_A/a_1",
//!  "to":"*","seq":7,"ts":1762400000000,"trace":{"hops":0},"body":{…}}
//! ```
//!
//! - [`Kind`] splits the planes: `cmd`/`res` (control), `evt` (observation),
//!   `mail` (conversation between nodes; later phases).
//! - [`Address`] is where a node runs (`s_<session>` / `s_<session>/a_<agent>`);
//!   [`Node::parent`] is who started it. The two are deliberately separate.
//! - [`MeshEvent`] is the typed view of `evt` envelopes, [`MeshCommand`] of
//!   `cmd` envelopes; [`Envelope`] carries either as `op` + `body`.

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Protocol version carried in every envelope (`v`).
pub const VERSION: u32 = 1;
/// The `type` tag of an envelope on the RPC stream.
pub const WIRE_TYPE: &str = "mesh";
/// The `to` of an event meant for every subscriber.
pub const BROADCAST: &str = "*";
/// The `to` of a command meant for whoever routes (engine or hub).
pub const ROUTER: &str = "hub";
/// Relays after which an envelope is dropped (loop guard).
pub const MAX_HOPS: u32 = 16;

// ── Addresses ───────────────────────────────────────────────────────────────

/// What kind of conversation a node is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NodeKind {
    /// A full chat with its own engine and transcript.
    Session,
    /// A subagent hosted inside a session's engine.
    Agent,
    /// A side question hosted inside a session's engine.
    Side,
}

impl NodeKind {
    /// The address segment prefix of this kind.
    pub const fn prefix(self) -> &'static str {
        match self {
            NodeKind::Session => "s_",
            NodeKind::Agent => "a_",
            NodeKind::Side => "q_",
        }
    }

    fn from_segment(segment: &str) -> Option<Self> {
        [NodeKind::Session, NodeKind::Agent, NodeKind::Side]
            .into_iter()
            .find(|kind| segment.len() > 2 && segment.starts_with(kind.prefix()))
    }
}

/// Where a node runs: `s_<id>` for a session, `s_<id>/a_<id>` for a node
/// hosted in that session's engine (deeper paths if hosted nodes nest).
/// The first segment routes to an engine, the rest inside it.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct Address(String);

/// Characters an id segment may not contain (they would break the path).
fn clean_id(id: &str) -> String {
    id.chars()
        .map(|c| if c == '/' || c.is_whitespace() || c.is_control() { '_' } else { c })
        .collect()
}

impl Address {
    /// The address of the session `id`.
    pub fn session(id: &str) -> Self {
        Address(format!("{}{}", NodeKind::Session.prefix(), clean_id(id)))
    }

    /// The address of a node of `kind` with `id`, hosted by this one.
    pub fn child(&self, kind: NodeKind, id: &str) -> Self {
        Address(format!("{}/{}{}", self.0, kind.prefix(), clean_id(id)))
    }

    /// Parse and validate an address.
    pub fn parse(text: &str) -> Result<Self, String> {
        let mut segments = text.split('/');
        match segments.next().and_then(NodeKind::from_segment) {
            Some(NodeKind::Session) => {}
            _ => return Err(format!("address `{text}` must start with a session segment `s_<id>`")),
        }
        for segment in segments {
            match NodeKind::from_segment(segment) {
                Some(NodeKind::Agent | NodeKind::Side) => {}
                _ => return Err(format!("address `{text}` has an invalid segment `{segment}`")),
            }
        }
        Ok(Address(text.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// The session segment: which engine hosts this node.
    pub fn session_segment(&self) -> &str {
        self.0.split('/').next().unwrap_or(&self.0)
    }

    /// The session id inside the session segment.
    pub fn session_id(&self) -> &str {
        &self.session_segment()[NodeKind::Session.prefix().len()..]
    }

    /// The kind of the node, from its last segment.
    pub fn kind(&self) -> NodeKind {
        self.0
            .rsplit('/')
            .next()
            .and_then(NodeKind::from_segment)
            .unwrap_or(NodeKind::Session)
    }

    /// The node hosting this one (`None` for a session).
    pub fn host(&self) -> Option<Address> {
        self.0.rsplit_once('/').map(|(host, _)| Address(host.to_string()))
    }

    /// Whether this node runs in the engine of `session`.
    pub fn is_hosted_by(&self, session: &Address) -> bool {
        self.session_segment() == session.session_segment()
    }
}

impl std::fmt::Display for Address {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl TryFrom<String> for Address {
    type Error = String;
    fn try_from(value: String) -> Result<Self, Self::Error> {
        Address::parse(&value)
    }
}

impl From<Address> for String {
    fn from(value: Address) -> Self {
        value.0
    }
}

// ── Nodes ───────────────────────────────────────────────────────────────────

/// A node's lifecycle state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NodeState {
    /// Waiting for the user to accept it.
    Proposed,
    Starting,
    Running,
    /// Blocked on someone else (an approval, an answer).
    Waiting,
    /// A session between turns.
    Idle,
    /// A run ended (see [`Node::status`]); an agent may still be continued.
    Settled,
    /// Gone: it can no longer be continued or addressed.
    Closed,
}

/// How a settled node's last run ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RunStatus {
    Done,
    Failed,
    Cancelled,
}

/// Who asked for a node.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Origin {
    #[default]
    User,
    Agent,
    Plugin,
}

/// Token and cost totals, in the shape clients already use for messages.
#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MeshUsage {
    #[serde(default)]
    pub input: u64,
    #[serde(default)]
    pub output: u64,
    #[serde(default)]
    pub cache_read: u64,
    #[serde(default)]
    pub cache_write: u64,
    #[serde(default)]
    pub total_tokens: u64,
    #[serde(default)]
    pub cost: f64,
}

impl MeshUsage {
    pub fn add(&mut self, other: &MeshUsage) {
        self.input += other.input;
        self.output += other.output;
        self.cache_read += other.cache_read;
        self.cache_write += other.cache_write;
        self.total_tokens += other.total_tokens;
        self.cost += other.cost;
    }
}

/// A node record: what `list` returns and `node_state` carries.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Node {
    pub id: Address,
    pub kind: NodeKind,
    /// Who started it (lineage); `None` for a top-level session.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent: Option<Address>,
    /// Top of the lineage tree.
    pub root: Address,
    pub depth: u32,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub origin: Origin,
    pub state: NodeState,
    /// How the last run ended, once settled.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub status: Option<RunStatus>,
    /// Why it failed or was cancelled.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    /// Capabilities granted to it (`mail.parent`, `spawn.agent`, …).
    #[serde(default)]
    pub caps: Vec<String>,
    #[serde(default)]
    pub usage: MeshUsage,
    #[serde(default)]
    pub started_at: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ended_at: Option<u64>,
    /// Kind-specific facts: `agentType`, `model`, `background`, `callId`
    /// (the tool call that started it), `worktree`, …
    #[serde(default)]
    pub meta: Value,
}

impl Node {
    /// A new running node of `kind` at `id`, started by `parent`.
    pub fn new(id: Address, parent: Option<&Node>, title: impl Into<String>, origin: Origin) -> Self {
        Node {
            kind: id.kind(),
            root: parent.map_or_else(|| id.clone(), |p| p.root.clone()),
            depth: parent.map_or(0, |p| p.depth + 1),
            parent: parent.map(|p| p.id.clone()),
            id,
            title: title.into(),
            origin,
            state: NodeState::Running,
            status: None,
            reason: None,
            caps: Vec::new(),
            usage: MeshUsage::default(),
            started_at: 0,
            ended_at: None,
            meta: Value::Object(Default::default()),
        }
    }
}

// ── Observation ─────────────────────────────────────────────────────────────

/// How much a subscriber wants to see. Ordered: each level includes the ones
/// before it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Level {
    /// Nothing (not subscribed).
    #[default]
    None,
    /// Lifecycle: `node_state`, `node_report`.
    State,
    /// + `node_activity`, `node_usage`.
    Summary,
    /// + every engine event of hosted nodes (`node_event`).
    Full,
}

/// One tool call of a node, as a row the UI can label.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolRow {
    pub call_id: String,
    pub name: String,
    /// The few argument fields worth showing (`command`, `path`, …).
    #[serde(default)]
    pub args: Value,
    /// `running` | `done` | `error`.
    pub phase: String,
}

/// The typed view of an `evt` envelope (`op` + `body`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "op", content = "body", rename_all = "snake_case")]
pub enum MeshEvent {
    /// A node appeared or changed state. Carries the whole record.
    NodeState {
        node: Node,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        prev: Option<NodeState>,
    },
    /// A node finished a run (an agent's report, a session's turn).
    NodeReport {
        node: Address,
        status: RunStatus,
        #[serde(default)]
        text: String,
        #[serde(default)]
        usage: MeshUsage,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        worktree: Option<Value>,
    },
    /// What a running node is doing: the tool row that changed and/or the
    /// tail of its latest text (replaces the previous tail). On `subscribe`
    /// the router sends one per node with `rows` set: the whole list of
    /// recent rows, replacing what the subscriber had.
    NodeActivity {
        node: Address,
        turns: u32,
        #[serde(rename = "toolUses")]
        tool_uses: u32,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        tool: Option<ToolRow>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        text: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        rows: Option<Vec<ToolRow>>,
    },
    /// A node's usage so far, and with everything it started.
    NodeUsage {
        node: Address,
        #[serde(rename = "self")]
        own: MeshUsage,
        subtree: MeshUsage,
    },
    /// One engine event of a hosted node, in the legacy RPC event shape.
    NodeEvent { node: Address, event: Value },
}

impl MeshEvent {
    /// The least subscription level that receives this event.
    pub fn level(&self) -> Level {
        match self {
            MeshEvent::NodeState { .. } | MeshEvent::NodeReport { .. } => Level::State,
            MeshEvent::NodeActivity { .. } | MeshEvent::NodeUsage { .. } => Level::Summary,
            MeshEvent::NodeEvent { .. } => Level::Full,
        }
    }

    /// The node the event is about.
    pub fn node(&self) -> &Address {
        match self {
            MeshEvent::NodeState { node, .. } => &node.id,
            MeshEvent::NodeReport { node, .. }
            | MeshEvent::NodeActivity { node, .. }
            | MeshEvent::NodeUsage { node, .. }
            | MeshEvent::NodeEvent { node, .. } => node,
        }
    }
}

// ── Control ─────────────────────────────────────────────────────────────────

/// Which nodes `list` returns.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ListScope {
    /// Every node this router knows.
    #[default]
    All,
    /// The direct children (by lineage) of `of`.
    Children,
    /// Everything below `of` (by lineage).
    Subtree,
}

/// The typed view of a `cmd` envelope (`op` + `body`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "op", content = "body", rename_all = "snake_case")]
pub enum MeshCommand {
    /// Receive events up to `level`; with `since`, first replay the retained
    /// events after that sequence number.
    Subscribe {
        level: Level,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        since: Option<u64>,
    },
    List {
        #[serde(default)]
        scope: ListScope,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        of: Option<Address>,
    },
    Get { node: Address },
    /// Stop a node's run; with `cascade` (default) also what it started.
    Cancel {
        node: Address,
        #[serde(default = "yes")]
        cascade: bool,
    },
}

fn yes() -> bool {
    true
}

/// Typed failure of a command, in a `res` body as `{"error":{code,message}}`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorCode {
    BadRequest,
    NotFound,
    Forbidden,
    BudgetExceeded,
    DepthExceeded,
    TooManyChildren,
    WouldDeadlock,
    Timeout,
    Unsupported,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MeshError {
    pub code: ErrorCode,
    pub message: String,
}

impl MeshError {
    pub fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        MeshError { code, message: message.into() }
    }
}

// ── Mail ────────────────────────────────────────────────────────────────────

/// What a `mail` message does at the receiver (see the design's table).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Deliver {
    /// Into the receiver's current run before its next model call; an idle
    /// receiver is woken.
    Interrupt,
    /// After the receiver's current turn, or held for its next turn.
    #[default]
    Queue,
    /// Like `queue`, and an idle receiver is woken (subject to the host's
    /// wake guard).
    Wake,
    /// A prompt from another session (`message_session`, a started session's
    /// brief): it starts the receiver's next turn, or follows its current one.
    /// The hub delivers it as an RPC `prompt` / `queue_message`, not as a
    /// `mail` envelope.
    Prompt,
}

/// The body of a `mail` envelope with op `message`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MailBody {
    /// What the receiver's model reads, as a user-role message.
    pub text: String,
    #[serde(default)]
    pub deliver: Deliver,
    /// The sender's title, for the receiver's host (wake labels).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
}

// ── Envelope ────────────────────────────────────────────────────────────────

/// Which plane an envelope belongs to.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    Cmd,
    Res,
    Evt,
    Mail,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum WireTag {
    Mesh,
}

/// Causality: what started the chain this envelope is part of.
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct Trace {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub root: Option<String>,
    /// The envelope (or tool call) that caused this one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cause: Option<String>,
    #[serde(default)]
    pub hops: u32,
}

/// One message on the mesh.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Envelope {
    #[serde(rename = "type")]
    tag: WireTag,
    pub v: u32,
    /// Unique; the idempotency key.
    pub id: String,
    pub kind: Kind,
    pub op: String,
    /// A node address, `client:<id>`, or [`ROUTER`].
    pub from: String,
    /// A node address, [`ROUTER`], or [`BROADCAST`].
    pub to: String,
    /// `res` → the `cmd` it answers; `reply` → the `ask`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub corr: Option<String>,
    /// Monotonic per sender: ordering and replay.
    #[serde(default)]
    pub seq: u64,
    #[serde(default)]
    pub ts: u64,
    #[serde(default)]
    pub trace: Trace,
    #[serde(default)]
    pub body: Value,
}

/// Split a `{"op":…,"body":…}` value into its parts.
fn op_body(value: Value) -> (String, Value) {
    let mut value = value;
    let op = value.get("op").and_then(Value::as_str).unwrap_or_default().to_string();
    let body = value.get_mut("body").map(Value::take).unwrap_or(Value::Null);
    (op, body)
}

impl Envelope {
    fn new(kind: Kind, id: String, op: String, from: String, to: String, body: Value) -> Self {
        Envelope {
            tag: WireTag::Mesh,
            v: VERSION,
            id,
            kind,
            op,
            from,
            to,
            corr: None,
            seq: 0,
            ts: 0,
            trace: Trace::default(),
            body,
        }
    }

    /// An event about `event.node()`, sent to every subscriber.
    pub fn event(id: String, seq: u64, ts: u64, event: &MeshEvent) -> Self {
        let from = event.node().to_string();
        let (op, body) = op_body(serde_json::to_value(event).unwrap_or(Value::Null));
        let mut envelope = Envelope::new(Kind::Evt, id, op, from, BROADCAST.into(), body);
        envelope.seq = seq;
        envelope.ts = ts;
        envelope
    }

    /// A command from `from` to the router.
    pub fn command(id: String, from: impl Into<String>, command: &MeshCommand) -> Self {
        let (op, body) = op_body(serde_json::to_value(command).unwrap_or(Value::Null));
        Envelope::new(Kind::Cmd, id, op, from.into(), ROUTER.into(), body)
    }

    /// The answer to `command`: `Ok(body)` or a typed error.
    pub fn response(id: String, command: &Envelope, result: Result<Value, MeshError>) -> Self {
        let body = match result {
            Ok(body) => body,
            Err(error) => serde_json::json!({ "error": error }),
        };
        let mut envelope = Envelope::new(
            Kind::Res,
            id,
            command.op.clone(),
            command.to.clone(),
            command.from.clone(),
            body,
        );
        envelope.corr = Some(command.id.clone());
        envelope.trace = Trace { root: command.trace.root.clone(), cause: Some(command.id.clone()), hops: 0 };
        envelope
    }

    /// The typed event, for an `evt` envelope.
    pub fn as_event(&self) -> Option<MeshEvent> {
        (self.kind == Kind::Evt).then_some(())?;
        serde_json::from_value(serde_json::json!({ "op": self.op, "body": self.body })).ok()
    }

    /// The typed command, for a `cmd` envelope; a malformed one is an error.
    pub fn as_command(&self) -> Result<MeshCommand, MeshError> {
        if self.kind != Kind::Cmd {
            return Err(MeshError::new(ErrorCode::BadRequest, "not a command"));
        }
        if self.v != VERSION {
            return Err(MeshError::new(ErrorCode::Unsupported, format!("mesh version {} is not supported", self.v)));
        }
        serde_json::from_value(serde_json::json!({ "op": self.op, "body": self.body }))
            .map_err(|error| MeshError::new(ErrorCode::BadRequest, format!("invalid `{}` command: {error}", self.op)))
    }

    /// A `mail` message from `from` to `to`.
    pub fn mail(id: String, from: impl Into<String>, to: impl Into<String>, body: &MailBody) -> Self {
        let body = serde_json::to_value(body).unwrap_or(Value::Null);
        Envelope::new(Kind::Mail, id, "message".into(), from.into(), to.into(), body)
    }

    /// The typed body of a `mail` message.
    pub fn as_mail(&self) -> Result<MailBody, MeshError> {
        if self.kind != Kind::Mail || self.op != "message" {
            return Err(MeshError::new(ErrorCode::BadRequest, format!("not a mail message (`{}`)", self.op)));
        }
        if self.v != VERSION {
            return Err(MeshError::new(ErrorCode::Unsupported, format!("mesh version {} is not supported", self.v)));
        }
        serde_json::from_value(self.body.clone())
            .map_err(|error| MeshError::new(ErrorCode::BadRequest, format!("invalid mail: {error}")))
    }

    /// Whether a wire object is a mesh envelope (by its `type` tag).
    pub fn is_envelope(value: &Value) -> bool {
        value.get("type").and_then(Value::as_str) == Some(WIRE_TYPE)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn agent_node() -> Node {
        let session = Node::new(Address::session("S1"), None, "chat", Origin::User);
        let mut agent = Node::new(Address::session("S1").child(NodeKind::Agent, "A1"), Some(&session), "Find auth", Origin::Agent);
        agent.meta = json!({ "callId": "call-1", "agentType": "explore" });
        agent
    }

    #[test]
    fn addresses_route_by_session_and_keep_lineage_apart() {
        let session = Address::session("abc");
        let agent = session.child(NodeKind::Agent, "x/y z");
        assert_eq!(agent.as_str(), "s_abc/a_x_y_z");
        assert_eq!(agent.session_segment(), "s_abc");
        assert_eq!(agent.session_id(), "abc");
        assert_eq!(agent.kind(), NodeKind::Agent);
        assert_eq!(agent.host(), Some(session.clone()));
        assert!(agent.is_hosted_by(&session));
        assert!(!agent.is_hosted_by(&Address::session("other")));
        assert_eq!(session.kind(), NodeKind::Session);
        assert_eq!(session.host(), None);
        let side = session.child(NodeKind::Side, "q");
        assert_eq!(side.kind(), NodeKind::Side);

        for bad in ["", "a_1", "s_", "s_1/s_2", "s_1/x_2", "s_1/a_"] {
            assert!(Address::parse(bad).is_err(), "{bad} should be rejected");
        }
        assert!(serde_json::from_value::<Address>(json!("a_1/s_2")).is_err());
        assert_eq!(serde_json::from_value::<Address>(json!("s_1/a_2/q_3")).unwrap().kind(), NodeKind::Side);
    }

    #[test]
    fn child_nodes_inherit_root_and_depth() {
        let agent = agent_node();
        assert_eq!(agent.root, Address::session("S1"));
        assert_eq!(agent.parent, Some(Address::session("S1")));
        assert_eq!(agent.depth, 1);
        assert_eq!(agent.kind, NodeKind::Agent);
    }

    #[test]
    fn event_envelopes_round_trip_on_the_wire() {
        let events = vec![
            MeshEvent::NodeState { node: agent_node(), prev: Some(NodeState::Starting) },
            MeshEvent::NodeReport {
                node: agent_node().id,
                status: RunStatus::Done,
                text: "report 🐈".into(),
                usage: MeshUsage { input: 3, output: 4, total_tokens: 7, cost: 0.5, ..Default::default() },
                worktree: Some(json!({ "kept": true })),
            },
            MeshEvent::NodeActivity {
                node: agent_node().id,
                turns: 2,
                tool_uses: 5,
                tool: Some(ToolRow { call_id: "c".into(), name: "bash".into(), args: json!({"command":"rg"}), phase: "running".into() }),
                text: None,
                rows: None,
            },
            MeshEvent::NodeActivity {
                node: agent_node().id,
                turns: 1,
                tool_uses: 1,
                tool: None,
                text: Some("tail".into()),
                rows: Some(vec![ToolRow { call_id: "c".into(), name: "read".into(), args: json!({}), phase: "done".into() }]),
            },
            MeshEvent::NodeUsage { node: agent_node().id, own: MeshUsage::default(), subtree: MeshUsage::default() },
            MeshEvent::NodeEvent { node: agent_node().id, event: json!({ "type": "turn_start" }) },
        ];
        for (seq, event) in events.into_iter().enumerate() {
            let envelope = Envelope::event(format!("m_{seq}"), seq as u64, 42, &event);
            let wire = serde_json::to_value(&envelope).unwrap();
            assert_eq!(wire["type"], "mesh");
            assert_eq!(wire["v"], 1);
            assert_eq!(wire["kind"], "evt");
            assert_eq!(wire["from"], "s_S1/a_A1");
            assert_eq!(wire["to"], "*");
            assert!(Envelope::is_envelope(&wire));
            let back: Envelope = serde_json::from_value(wire).unwrap();
            assert_eq!(back, envelope);
            assert_eq!(back.as_event(), Some(event));
        }
    }

    #[test]
    fn wire_names_are_stable() {
        let event = MeshEvent::NodeUsage { node: agent_node().id, own: MeshUsage::default(), subtree: MeshUsage::default() };
        let wire = serde_json::to_value(Envelope::event("m".into(), 1, 2, &event)).unwrap();
        assert_eq!(wire["op"], "node_usage");
        assert!(wire["body"].get("self").is_some());
        assert!(wire["body"]["self"].get("cacheRead").is_some());
        let state = serde_json::to_value(Envelope::event("m".into(), 1, 2, &MeshEvent::NodeState { node: agent_node(), prev: None })).unwrap();
        assert_eq!(state["body"]["node"]["id"], "s_S1/a_A1");
        assert_eq!(state["body"]["node"]["state"], "running");
        assert_eq!(state["body"]["node"]["meta"]["callId"], "call-1");
        assert!(state["body"]["node"].get("startedAt").is_some());
    }

    #[test]
    fn levels_are_ordered_and_assigned() {
        assert!(Level::None < Level::State && Level::State < Level::Summary && Level::Summary < Level::Full);
        let id = agent_node().id;
        assert_eq!(MeshEvent::NodeState { node: agent_node(), prev: None }.level(), Level::State);
        assert_eq!(
            MeshEvent::NodeActivity { node: id.clone(), turns: 0, tool_uses: 0, tool: None, text: None, rows: None }.level(),
            Level::Summary
        );
        assert_eq!(MeshEvent::NodeEvent { node: id, event: Value::Null }.level(), Level::Full);
    }

    #[test]
    fn commands_parse_and_answer_with_correlation() {
        let raw = json!({
            "type": "mesh", "v": 1, "id": "w1-7", "kind": "cmd", "op": "subscribe",
            "from": "client:w1", "to": "hub", "body": { "level": "summary", "since": 3 }
        });
        let envelope: Envelope = serde_json::from_value(raw).unwrap();
        assert_eq!(envelope.as_command().unwrap(), MeshCommand::Subscribe { level: Level::Summary, since: Some(3) });

        let cancel: Envelope = serde_json::from_value(json!({
            "type": "mesh", "v": 1, "id": "c", "kind": "cmd", "op": "cancel", "from": "client:w1", "to": "hub",
            "body": { "node": "s_S1/a_A1" }
        }))
        .unwrap();
        assert_eq!(cancel.as_command().unwrap(), MeshCommand::Cancel { node: agent_node().id, cascade: true });

        let list = Envelope::command("l".into(), "client:w1", &MeshCommand::List { scope: ListScope::Children, of: Some(Address::session("S1")) });
        let wire = serde_json::to_value(&list).unwrap();
        assert_eq!(wire["op"], "list");
        assert_eq!(wire["body"]["scope"], "children");
        assert_eq!(serde_json::from_value::<Envelope>(wire).unwrap().as_command().unwrap(), list.as_command().unwrap());

        let ok = Envelope::response("r1".into(), &envelope, Ok(json!({ "seq": 9 })));
        assert_eq!(ok.kind, Kind::Res);
        assert_eq!(ok.corr.as_deref(), Some("w1-7"));
        assert_eq!(ok.to, "client:w1");
        assert_eq!(ok.from, "hub");
        let failed = Envelope::response("r2".into(), &envelope, Err(MeshError::new(ErrorCode::NotFound, "no node")));
        assert_eq!(serde_json::to_value(&failed).unwrap()["body"]["error"]["code"], "not_found");
    }

    #[test]
    fn mail_round_trips_and_answers_with_correlation() {
        let body = MailBody { text: "note 🐈".into(), deliver: Deliver::Wake, title: Some("Child".into()) };
        let mail = Envelope::mail("mail-1".into(), "s_child", "s_parent", &body);
        let wire = serde_json::to_value(&mail).unwrap();
        assert_eq!((wire["kind"].as_str(), wire["op"].as_str()), (Some("mail"), Some("message")));
        assert_eq!(wire["body"]["deliver"], "wake");
        let back: Envelope = serde_json::from_value(wire).unwrap();
        assert_eq!(back.as_mail().unwrap(), body);
        // `deliver` defaults to queue.
        let mut plain = back.clone();
        plain.body = json!({ "text": "x" });
        assert_eq!(plain.as_mail().unwrap().deliver, Deliver::Queue);
        let ack = Envelope::response("r".into(), &back, Ok(json!({ "queued": "next_turn" })));
        assert_eq!((ack.corr.as_deref(), ack.to.as_str(), ack.from.as_str()), (Some("mail-1"), "s_child", "s_parent"));
        assert!(Envelope::command("c".into(), "x", &MeshCommand::Get { node: Address::session("S") }).as_mail().is_err());
    }

    #[test]
    fn malformed_and_foreign_messages_are_refused() {
        // A legacy event is not an envelope.
        let legacy = json!({ "type": "turn_start" });
        assert!(!Envelope::is_envelope(&legacy));
        assert!(serde_json::from_value::<Envelope>(legacy).is_err());

        let mut bad = Envelope::command("x".into(), "client:w", &MeshCommand::Get { node: Address::session("S") });
        bad.body = json!({ "node": "not-an-address" });
        assert_eq!(bad.as_command().unwrap_err().code, ErrorCode::BadRequest);
        bad.op = "teleport".into();
        assert_eq!(bad.as_command().unwrap_err().code, ErrorCode::BadRequest);
        let mut future = Envelope::command("y".into(), "client:w", &MeshCommand::Get { node: Address::session("S") });
        future.v = 2;
        assert_eq!(future.as_command().unwrap_err().code, ErrorCode::Unsupported);
        let event = Envelope::event("e".into(), 0, 0, &MeshEvent::NodeEvent { node: Address::session("S"), event: Value::Null });
        assert!(event.as_command().is_err());
        assert!(Envelope::command("z".into(), "c", &MeshCommand::Get { node: Address::session("S") }).as_event().is_none());
    }
}
