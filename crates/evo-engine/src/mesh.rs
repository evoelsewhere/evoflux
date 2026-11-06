//! This engine's side of the session mesh (`docs/features/session-mesh-protocol/sdd.md`).
//!
//! The [`LocalRouter`] is the one registry of the conversations this engine
//! hosts: its session, the subagents of the `agent` tool
//! ([`crate::agent_tool`]), plugin children ([`crate::child_agents`]) and side
//! questions ([`crate::side_questions`]). Each of those keeps its own run
//! state, but registers here under a mesh [`Address`] with a cancel handle and
//! reports its lifecycle, activity and usage here. The router turns that into
//! [`MeshEvent`]s for subscribers (the RPC client) and answers mesh commands
//! (`subscribe`, `list`, `get`, `cancel`).
//!
//! Events are only built for levels someone subscribed to, so an engine
//! without mesh clients pays (almost) nothing. State-level events are always
//! kept in a small ring so a client that subscribes late can replay them.

use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicU64, AtomicU8, Ordering};
use std::sync::{Arc, LazyLock, Mutex};

use evo_agent::AgentEvent;
use serde_json::{json, Value};
use tokio::sync::broadcast;

pub use evo_protocol::mesh::{
    Address, Deliver, Envelope, ErrorCode, Level, ListScope, MailBody, MeshCommand, MeshError, MeshEvent, MeshUsage,
    Node, NodeKind, NodeState, Origin, RunStatus, ToolRow,
};

/// A model call's usage in mesh terms.
pub fn usage_of(usage: &evo_ai::types::Usage) -> MeshUsage {
    MeshUsage {
        input: usage.input.max(0) as u64,
        output: usage.output.max(0) as u64,
        cache_read: usage.cache_read.max(0) as u64,
        cache_write: usage.cache_write.max(0) as u64,
        total_tokens: usage.total_tokens.max(0) as u64,
        cost: usage.cost.total,
    }
}

/// Mail one node may send another between two runs of the session.
pub const MAX_PAIR_MAIL: u32 = 20;

/// A recorded wait; dropping it ends the wait.
pub struct WaitGuard<'a> {
    router: &'a LocalRouter,
    id: u64,
}

impl Drop for WaitGuard<'_> {
    fn drop(&mut self) {
        lock(&self.router.waits).retain(|(id, _, _)| *id != self.id);
    }
}

/// Envelopes kept for replay (`subscribe {since}`).
const RING: usize = 512;
/// Envelopes buffered per live subscriber before it lags.
const CHANNEL: usize = 1024;

/// Stops a node's run; false when there was nothing to stop.
pub type CancelFn = Arc<dyn Fn() -> bool + Send + Sync>;

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|e| e.into_inner())
}

fn level_code(level: Level) -> u8 {
    match level {
        Level::None => 0,
        Level::State => 1,
        Level::Summary => 2,
        Level::Full => 3,
    }
}

fn level_of(code: u8) -> Level {
    match code {
        1 => Level::State,
        2 => Level::Summary,
        3 => Level::Full,
        _ => Level::None,
    }
}

struct Entry {
    node: Node,
    cancel: Option<CancelFn>,
    /// The latest activity, replayed to new subscribers as one snapshot.
    activity: Option<Activity>,
}

/// What a node is doing, folded from its activity reports.
#[derive(Default, Clone)]
struct Activity {
    turns: u32,
    tool_uses: u32,
    rows: VecDeque<ToolRow>,
    text: String,
}

/// Tool rows kept per node for the snapshot.
const MAX_ROWS: usize = 50;

#[derive(Default)]
struct Inner {
    /// Insertion order: parents before their children.
    nodes: Vec<Entry>,
    root: Option<Address>,
    seq: u64,
    ring: VecDeque<(Level, Envelope)>,
}

impl Inner {
    fn find(&self, id: &Address) -> Option<usize> {
        self.nodes.iter().position(|entry| entry.node.id == *id)
    }

    /// `id` and everything started (by lineage) below it, parents first.
    fn subtree(&self, id: &Address) -> Vec<Address> {
        let mut out = vec![id.clone()];
        let mut index = 0;
        while index < out.len() {
            let current = out[index].clone();
            out.extend(
                self.nodes
                    .iter()
                    .filter(|entry| entry.node.parent.as_ref() == Some(&current))
                    .map(|entry| entry.node.id.clone()),
            );
            index += 1;
        }
        out
    }

    fn subtree_usage(&self, id: &Address) -> MeshUsage {
        let mut total = MeshUsage::default();
        for member in self.subtree(id) {
            if let Some(index) = self.find(&member) {
                total.add(&self.nodes[index].node.usage);
            }
        }
        total
    }
}

/// The registry and event source of the nodes this engine hosts.
pub struct LocalRouter {
    inner: Mutex<Inner>,
    tx: broadcast::Sender<(Level, Envelope)>,
    /// The highest level any subscriber asked for.
    level: AtomicU8,
    /// Each subscriber's level, by subscriber id.
    subscribers: Mutex<HashMap<u64, Level>>,
    /// Who waits on whom (`ask`s, a parent's foreground agent call): the
    /// wait-for graph that refuses an `ask` closing a cycle.
    waits: Mutex<Vec<(u64, Address, Address)>>,
    /// Mail per directed pair since the session's last run started (loop breaker).
    pair_mail: Mutex<HashMap<(Address, Address), u32>>,
    /// Makes envelope ids unique across engine restarts in one hub.
    epoch: u64,
    ids: AtomicU64,
}

impl Default for LocalRouter {
    fn default() -> Self {
        LocalRouter {
            inner: Mutex::new(Inner::default()),
            tx: broadcast::channel(CHANNEL).0,
            level: AtomicU8::new(0),
            subscribers: Mutex::new(HashMap::new()),
            waits: Mutex::new(Vec::new()),
            pair_mail: Mutex::new(HashMap::new()),
            epoch: now_ms(),
            ids: AtomicU64::new(0),
        }
    }
}

/// One consumer of mesh events (an RPC client). Its level filters what it
/// receives; the router builds events up to the highest level of any live
/// subscriber. Dropping it unsubscribes.
pub struct Subscriber<'a> {
    router: &'a LocalRouter,
    id: u64,
    level: Arc<AtomicU8>,
}

impl Subscriber<'_> {
    pub fn level(&self) -> Level {
        level_of(self.level.load(Ordering::Acquire))
    }

    /// A handle to this subscriber's level, for the task that writes its events.
    pub fn level_handle(&self) -> Arc<AtomicU8> {
        self.level.clone()
    }

    /// Whether an event of `level` goes to this subscriber.
    pub fn wants(level: &AtomicU8, event: Level) -> bool {
        event != Level::None && event <= level_of(level.load(Ordering::Acquire))
    }
}

impl Drop for Subscriber<'_> {
    fn drop(&mut self) {
        lock(&self.router.subscribers).remove(&self.id);
        self.router.recompute();
    }
}

static ROUTER: LazyLock<LocalRouter> = LazyLock::new(LocalRouter::default);

/// This engine's router.
pub fn router() -> &'static LocalRouter {
    &ROUTER
}

impl LocalRouter {
    // ── Subscribers ────────────────────────────────────────────────────────

    pub fn level(&self) -> Level {
        level_of(self.level.load(Ordering::Acquire))
    }

    /// Whether events of `level` are wanted by anyone (skip building them otherwise).
    pub fn wants(&self, level: Level) -> bool {
        level != Level::None && level <= self.level()
    }

    /// A live feed of `(level, envelope)`; filter by the level you subscribed to.
    pub fn feed(&self) -> broadcast::Receiver<(Level, Envelope)> {
        self.tx.subscribe()
    }

    /// A new subscriber, at level `none` until it subscribes.
    pub fn subscriber(&self) -> Subscriber<'_> {
        let id = self.ids.fetch_add(1, Ordering::Relaxed) + 1;
        lock(&self.subscribers).insert(id, Level::None);
        Subscriber { router: self, id, level: Arc::new(AtomicU8::new(0)) }
    }

    fn recompute(&self) {
        let max = lock(&self.subscribers).values().copied().max().unwrap_or(Level::None);
        self.level.store(level_code(max), Ordering::Release);
    }

    /// Set `subscriber`'s level and return the retained envelopes after
    /// `since` (all retained ones when `None`) that the level includes.
    pub fn subscribe(&self, subscriber: &Subscriber<'_>, level: Level, since: Option<u64>) -> (u64, Vec<Envelope>) {
        subscriber.level.store(level_code(level), Ordering::Release);
        lock(&self.subscribers).insert(subscriber.id, level);
        self.recompute();
        let inner = lock(&self.inner);
        let mut replay: Vec<Envelope> = inner
            .ring
            .iter()
            .filter(|(at, envelope)| *at <= level && since.is_none_or(|since| envelope.seq > since))
            .map(|(_, envelope)| envelope.clone())
            .collect();
        // Activity is not retained event by event: a summary subscriber gets
        // one snapshot per node instead (the rows replace what it had).
        if level >= Level::Summary {
            for entry in &inner.nodes {
                let Some(activity) = &entry.activity else { continue };
                let event = MeshEvent::NodeActivity {
                    node: entry.node.id.clone(),
                    turns: activity.turns,
                    tool_uses: activity.tool_uses,
                    tool: None,
                    text: Some(activity.text.clone()),
                    rows: Some(activity.rows.iter().cloned().collect()),
                };
                replay.push(Envelope::event(self.next_id(), inner.seq, now_ms(), &event));
            }
        }
        (inner.seq, replay)
    }

    pub fn next_id(&self) -> String {
        format!("m_{}_{}", self.epoch, self.ids.fetch_add(1, Ordering::Relaxed) + 1)
    }

    fn publish(&self, inner: &mut Inner, event: MeshEvent) {
        let level = event.level();
        // State events are always retained for late subscribers; the rest
        // only exist while someone wants them.
        if level > Level::State && !self.wants(level) {
            return;
        }
        inner.seq += 1;
        let envelope = Envelope::event(self.next_id(), inner.seq, now_ms(), &event);
        if level <= Level::State {
            inner.ring.push_back((level, envelope.clone()));
            while inner.ring.len() > RING {
                inner.ring.pop_front();
            }
        }
        if self.wants(level) {
            let _ = self.tx.send((level, envelope));
        }
    }

    // ── Registry ───────────────────────────────────────────────────────────

    /// Register this engine's session as the root node (idle). A different
    /// session replaces the previous root, which is closed.
    pub fn set_root(&self, session_id: &str, title: &str) -> Address {
        let id = Address::session(session_id);
        let mut inner = lock(&self.inner);
        if inner.root.as_ref() == Some(&id) {
            return id;
        }
        if let Some(old) = inner.root.take() {
            if let Some(index) = inner.find(&old) {
                let mut entry = inner.nodes.remove(index);
                let prev = entry.node.state;
                entry.node.state = NodeState::Closed;
                entry.node.ended_at = Some(now_ms());
                self.publish(&mut inner, MeshEvent::NodeState { node: entry.node, prev: Some(prev) });
            }
        }
        let mut node = Node::new(id.clone(), None, title, Origin::User);
        node.state = NodeState::Idle;
        node.started_at = now_ms();
        node.caps = vec!["spawn.agent".into(), "mail.children".into()];
        inner.root = Some(id.clone());
        inner.nodes.insert(0, Entry { node: node.clone(), cancel: None, activity: None });
        self.publish(&mut inner, MeshEvent::NodeState { node, prev: None });
        id
    }

    pub fn root(&self) -> Option<Address> {
        lock(&self.inner).root.clone()
    }

    /// A new node hosted here, started by the node at its address's host
    /// (its parent by lineage). `title`, `origin` and `meta` describe it.
    pub fn spawn(&self, id: Address, title: &str, origin: Origin, meta: Value, cancel: Option<CancelFn>) -> Node {
        let mut inner = lock(&self.inner);
        let parent = id.host().and_then(|host| inner.find(&host).map(|index| inner.nodes[index].node.clone()));
        // A host this router does not know (e.g. a session that is not the
        // root) still gives the node its lineage.
        let parent = parent.or_else(|| id.host().map(|host| Node::new(host, None, "", Origin::User)));
        let mut node = Node::new(id, parent.as_ref(), title, origin);
        node.started_at = now_ms();
        node.meta = if meta.is_object() { meta } else { json!({}) };
        // Agents may write to their parent and their siblings (mesh_tools.rs).
        node.caps = match node.kind {
            NodeKind::Agent => vec!["mail.parent".into(), "mail.siblings".into()],
            _ => vec!["mail.parent".into()],
        };
        match inner.find(&node.id) {
            Some(index) => inner.nodes[index] = Entry { node: node.clone(), cancel, activity: None },
            None => inner.nodes.push(Entry { node: node.clone(), cancel, activity: None }),
        }
        self.publish(&mut inner, MeshEvent::NodeState { node: node.clone(), prev: None });
        node
    }

    /// Change a node's state. Unchanged state and status emit nothing.
    /// `Closed` removes the node after announcing it.
    pub fn transition(&self, id: &Address, state: NodeState, status: Option<RunStatus>, reason: Option<String>) {
        let mut inner = lock(&self.inner);
        let Some(index) = inner.find(id) else { return };
        let node = &mut inner.nodes[index].node;
        let prev = node.state;
        if prev == state && node.status == status && node.reason == reason {
            return;
        }
        node.state = state;
        match state {
            NodeState::Settled | NodeState::Closed => {
                if state == NodeState::Settled || node.status.is_none() {
                    node.status = status.or(node.status);
                    node.reason = reason.or(node.reason.take());
                }
                node.ended_at.get_or_insert_with(now_ms);
            }
            _ => {
                node.status = None;
                node.reason = None;
                node.ended_at = None;
            }
        }
        let snapshot = node.clone();
        if state == NodeState::Closed {
            inner.nodes.remove(index);
        }
        self.publish(&mut inner, MeshEvent::NodeState { node: snapshot, prev: Some(prev) });
    }

    /// Change a node's record without announcing it (the next state change carries it).
    pub fn update(&self, id: &Address, change: impl FnOnce(&mut Node)) {
        let mut inner = lock(&self.inner);
        if let Some(index) = inner.find(id) {
            change(&mut inner.nodes[index].node);
        }
    }

    /// Merge `fields` into a node's `meta`.
    pub fn set_meta(&self, id: &Address, fields: Value) {
        self.update(id, |node| {
            if let (Some(meta), Some(fields)) = (node.meta.as_object_mut(), fields.as_object()) {
                for (key, value) in fields {
                    meta.insert(key.clone(), value.clone());
                }
            }
        });
    }

    /// What a running node is doing. Always folded into the node's snapshot
    /// (for later subscribers); sent at the summary level.
    pub fn activity(&self, id: &Address, turns: u32, tool_uses: u32, tool: Option<ToolRow>, text: Option<String>) {
        let mut inner = lock(&self.inner);
        let Some(index) = inner.find(id) else { return };
        let activity = inner.nodes[index].activity.get_or_insert_with(Activity::default);
        activity.turns = turns;
        activity.tool_uses = tool_uses;
        if let Some(text) = &text {
            activity.text.clone_from(text);
        }
        if let Some(row) = &tool {
            match activity.rows.iter_mut().find(|r| r.call_id == row.call_id) {
                Some(existing) => *existing = row.clone(),
                None => {
                    activity.rows.push_back(row.clone());
                    while activity.rows.len() > MAX_ROWS {
                        activity.rows.pop_front();
                    }
                }
            }
        }
        self.publish(&mut inner, MeshEvent::NodeActivity { node: id.clone(), turns, tool_uses, tool, text, rows: None });
    }

    // ── Waiting and loops ──────────────────────────────────────────────────

    /// Whether `from` waiting on `to` would close a cycle of waits (or wait
    /// on itself): `to` already waits, directly or not, on `from`.
    pub fn would_deadlock(&self, from: &Address, to: &Address) -> bool {
        if from == to {
            return true;
        }
        let waits = lock(&self.waits);
        let mut seen = vec![to.clone()];
        let mut index = 0;
        while index < seen.len() {
            let current = seen[index].clone();
            for (_, waiter, target) in waits.iter() {
                if *waiter == current && !seen.contains(target) {
                    if target == from {
                        return true;
                    }
                    seen.push(target.clone());
                }
            }
            index += 1;
        }
        false
    }

    /// Record that `from` waits on `to` until the guard drops; refused with
    /// `would_deadlock` when that closes a cycle.
    pub fn try_wait(&self, from: &Address, to: &Address) -> Result<WaitGuard<'_>, MeshError> {
        if self.would_deadlock(from, to) {
            return Err(MeshError::new(
                ErrorCode::WouldDeadlock,
                format!("{to} is (indirectly) waiting on {from}: waiting on it would never end"),
            ));
        }
        Ok(self.add_wait(from, to))
    }

    /// Record that `from` waits on `to` (no check: a foreground agent call).
    pub fn add_wait(&self, from: &Address, to: &Address) -> WaitGuard<'_> {
        let id = self.ids.fetch_add(1, Ordering::Relaxed) + 1;
        lock(&self.waits).push((id, from.clone(), to.clone()));
        WaitGuard { router: self, id }
    }

    /// Count one mail from `from` to `to`; refused past [`MAX_PAIR_MAIL`]
    /// since the session's last run started (two nodes talking in a loop).
    pub fn count_mail(&self, from: &Address, to: &Address) -> Result<(), MeshError> {
        let mut counts = lock(&self.pair_mail);
        let count = counts.entry((from.clone(), to.clone())).or_insert(0);
        if *count >= MAX_PAIR_MAIL {
            return Err(MeshError::new(
                ErrorCode::Forbidden,
                format!("{from} already sent {MAX_PAIR_MAIL} messages to {to}; stop and report what you have"),
            ));
        }
        *count += 1;
        Ok(())
    }

    // ── Wake requests ──────────────────────────────────────────────────────

    /// `from` queued a message for the idle session `session`'s next turn:
    /// the session needs a run to read it. Recorded on the session node as
    /// `meta.wake` (the nodes waiting to be read) and announced, so the host
    /// can start that run. The list clears when the session's next run
    /// starts ([`session_run`]). A sender this router does not host (another
    /// session) leaves its `title` in `meta.wakeTitles` for the host's label.
    pub fn request_wake(&self, session: &Address, from: &Address, title: Option<&str>) {
        self.request_wake_for(session, from, title, "report");
    }

    /// [`request_wake`](Self::request_wake) with why: `report` (a finished
    /// agent or session), `mail` (a message or question from a node). The
    /// reason goes to `meta.wakeReasons`, so the host can say what woke it.
    pub fn request_wake_for(&self, session: &Address, from: &Address, title: Option<&str>, reason: &str) {
        let mut inner = lock(&self.inner);
        let index = match inner.find(session) {
            Some(index) => index,
            None => {
                // A session this engine hosts but has not registered (no RPC
                // client yet): track it without making it the root.
                let mut node = Node::new(session.clone(), None, "", Origin::User);
                node.state = NodeState::Idle;
                node.started_at = now_ms();
                inner.nodes.insert(0, Entry { node, cancel: None, activity: None });
                0
            }
        };
        let node = &mut inner.nodes[index].node;
        if !node.meta.is_object() {
            node.meta = json!({});
        }
        if let Some(title) = title {
            let titles = node.meta.as_object_mut().expect("object").entry("wakeTitles").or_insert_with(|| json!({}));
            if let Some(titles) = titles.as_object_mut() {
                titles.insert(from.to_string(), json!(title));
            }
        }
        let reasons = node.meta.as_object_mut().expect("object").entry("wakeReasons").or_insert_with(|| json!({}));
        // A report outranks a message from the same node (the host labels the wake by it).
        let changed = match reasons.as_object_mut() {
            Some(reasons) => {
                let before = reasons.get(from.as_str()).and_then(Value::as_str).map(str::to_string);
                let keep = before.as_deref() == Some("report") && reason != "report";
                if !keep {
                    reasons.insert(from.to_string(), json!(reason));
                }
                !keep && before.as_deref() != Some(reason)
            }
            None => false,
        };
        let wake = node.meta.as_object_mut().expect("object").entry("wake").or_insert_with(|| json!([]));
        let Some(list) = wake.as_array_mut() else { return };
        if list.iter().any(|item| item == from.as_str()) {
            if changed {
                let snapshot = node.clone();
                self.publish(&mut inner, MeshEvent::NodeState { prev: Some(snapshot.state), node: snapshot });
            }
            return;
        }
        list.push(json!(from.as_str()));
        let snapshot = node.clone();
        self.publish(&mut inner, MeshEvent::NodeState { prev: Some(snapshot.state), node: snapshot });
    }

    /// The nodes whose messages wait for `session`'s next turn.
    pub fn pending_wake(&self, session: &Address) -> Vec<String> {
        self.get(session)
            .and_then(|node| serde_json::from_value(node.meta["wake"].clone()).ok())
            .unwrap_or_default()
    }

    /// A node's cumulative usage. Announces it and the new subtree totals of
    /// every node above it (summary level).
    pub fn usage(&self, id: &Address, usage: MeshUsage) {
        let mut inner = lock(&self.inner);
        let Some(index) = inner.find(id) else { return };
        inner.nodes[index].node.usage = usage;
        if !self.wants(Level::Summary) {
            return;
        }
        let mut current = Some(id.clone());
        while let Some(at) = current {
            let Some(index) = inner.find(&at) else { break };
            let own = inner.nodes[index].node.usage;
            let parent = inner.nodes[index].node.parent.clone();
            let subtree = inner.subtree_usage(&at);
            self.publish(&mut inner, MeshEvent::NodeUsage { node: at, own, subtree });
            current = parent;
        }
    }

    /// A node finished a run with `text` (state level).
    pub fn report(&self, id: &Address, status: RunStatus, text: String, usage: MeshUsage, worktree: Option<Value>) {
        let mut inner = lock(&self.inner);
        if inner.find(id).is_none() {
            return;
        }
        self.publish(&mut inner, MeshEvent::NodeReport { node: id.clone(), status, text, usage, worktree });
    }

    /// One engine event of a hosted node (full level only).
    pub fn event(&self, id: &Address, event: &AgentEvent) {
        if !self.wants(Level::Full) {
            return;
        }
        let projected = crate::rpc::events::project(event);
        let mut inner = lock(&self.inner);
        if inner.find(id).is_none() {
            return;
        }
        self.publish(&mut inner, MeshEvent::NodeEvent { node: id.clone(), event: projected });
    }

    pub fn get(&self, id: &Address) -> Option<Node> {
        let inner = lock(&self.inner);
        inner.find(id).map(|index| inner.nodes[index].node.clone())
    }

    pub fn list(&self, scope: ListScope, of: Option<&Address>) -> Result<Vec<Node>, MeshError> {
        let inner = lock(&self.inner);
        let of = match (scope, of) {
            (ListScope::All, _) => return Ok(inner.nodes.iter().map(|entry| entry.node.clone()).collect()),
            (_, Some(of)) => of.clone(),
            (_, None) => inner
                .root
                .clone()
                .ok_or_else(|| MeshError::new(ErrorCode::BadRequest, "`of` is required"))?,
        };
        let members: Vec<Address> = match scope {
            ListScope::Children => inner
                .nodes
                .iter()
                .filter(|entry| entry.node.parent.as_ref() == Some(&of))
                .map(|entry| entry.node.id.clone())
                .collect(),
            _ => inner.subtree(&of).into_iter().skip(1).collect(),
        };
        Ok(members
            .iter()
            .filter_map(|id| inner.find(id).map(|index| inner.nodes[index].node.clone()))
            .collect())
    }

    /// Stop `id`'s run (and, with `cascade`, everything it started). Returns
    /// the nodes that were actually stopped.
    pub fn cancel(&self, id: &Address, cascade: bool) -> Result<Vec<Address>, MeshError> {
        let targets: Vec<(Address, CancelFn)> = {
            let inner = lock(&self.inner);
            if inner.find(id).is_none() {
                return Err(MeshError::new(ErrorCode::NotFound, format!("no node `{id}` here")));
            }
            let members = if cascade { inner.subtree(id) } else { vec![id.clone()] };
            // Children first, so a parent does not wait on a child that is stopping.
            members
                .into_iter()
                .rev()
                .filter_map(|member| {
                    let index = inner.find(&member)?;
                    inner.nodes[index].cancel.clone().map(|cancel| (member, cancel))
                })
                .collect()
        };
        // Outside the lock: a cancel handle may report back synchronously.
        Ok(targets.into_iter().filter(|(_, cancel)| cancel()).map(|(member, _)| member).collect())
    }

    /// Answer a `cmd` envelope. Also returns the envelopes to replay before
    /// any new event (for `subscribe`).
    pub fn handle(&self, envelope: &Envelope, subscriber: &Subscriber<'_>) -> (Envelope, Vec<Envelope>) {
        let mut replay = Vec::new();
        let result = envelope.as_command().and_then(|command| match command {
            MeshCommand::Subscribe { level, since } => {
                let (seq, retained) = self.subscribe(subscriber, level, since);
                replay = retained;
                Ok(json!({ "level": level, "seq": seq, "root": self.root() }))
            }
            MeshCommand::List { scope, of } => {
                self.list(scope, of.as_ref()).map(|nodes| json!({ "nodes": nodes }))
            }
            MeshCommand::Get { node } => self
                .get(&node)
                .map(|node| json!({ "node": node }))
                .ok_or_else(|| MeshError::new(ErrorCode::NotFound, format!("no node `{node}` here"))),
            MeshCommand::Cancel { node, cascade } => {
                self.cancel(&node, cascade).map(|cancelled| json!({ "cancelled": cancelled }))
            }
        });
        (Envelope::response(self.next_id(), envelope, result), replay)
    }
}

/// The session's own run slot: running once a prompt is accepted, idle once
/// it settles. A different session id (after `new` or a switch) becomes the
/// root first.
///
/// A starting run reads every queued message, so it clears the session's
/// pending wake requests (announced with the state change).
///
/// A finished run passes `report` (how it ended, its final text): the
/// session's `node_report`, which the hub turns into a note for the session
/// that started this one.
pub fn session_run(session_id: &str, running: bool, report: Option<(RunStatus, String)>) {
    let root = router().set_root(session_id, "");
    let state = if running { NodeState::Running } else { NodeState::Idle };
    if running {
        router().set_meta(&root, json!({ "wake": [], "wakeTitles": {}, "wakeReasons": {} }));
        // A new run of the session: nodes may talk again.
        lock(&router().pair_mail).clear();
    }
    if let Some((status, text)) = &report {
        router().report(&root, *status, text.clone(), MeshUsage::default(), None);
    }
    if !running {
        // Questions to the session that its run did not answer get its final text.
        let text = report.map(|(_, text)| text).unwrap_or_default();
        crate::mesh_tools::run_ended(&root, &text);
    }
    router().transition(&root, state, None, None);
}

/// Mail ids this engine already took (the hub delivers at least once).
static SEEN_MAIL: LazyLock<Mutex<VecDeque<String>>> = LazyLock::new(Default::default);
const SEEN_MAIL_KEPT: usize = 512;

/// Take a `mail` message for this session: into its running run, or queued
/// for its next one (and a wake request when the mail asks for one). Answers
/// with a `res` envelope whose `corr` is the mail's id, so the sender can mark
/// it delivered.
pub async fn receive_mail(harness: &evo_harness::agent_harness::AgentHarness, envelope: &Envelope) -> Envelope {
    let result = take_mail(harness, envelope).await;
    Envelope::response(router().next_id(), envelope, result)
}

async fn take_mail(harness: &evo_harness::agent_harness::AgentHarness, envelope: &Envelope) -> Result<Value, MeshError> {
    let body = envelope.as_mail()?;
    let session = Address::session(&harness.session().storage().metadata().id);
    if envelope.to != session.as_str() {
        return Err(MeshError::new(ErrorCode::NotFound, format!("this engine runs {session}, not {}", envelope.to)));
    }
    let from = Address::parse(&envelope.from).map_err(|e| MeshError::new(ErrorCode::BadRequest, e))?;
    if lock(&SEEN_MAIL).contains(&envelope.id) {
        return Ok(json!({ "duplicate": true }));
    }
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0);
    let message = evo_agent::AgentMessage::from(evo_ai::types::UserMessage::new(body.text.clone(), now));
    let lane = harness.lane("main");
    let running = harness.has_active_run();
    let (queued, result) = match (running, body.deliver) {
        (true, Deliver::Queue | Deliver::Prompt) => ("follow_up", lane.follow_up(message).await),
        (true, _) => ("steer", lane.steer(message).await),
        (false, _) => ("next_turn", lane.next_run(message).await),
    };
    result.map_err(|error| MeshError::new(ErrorCode::Unsupported, format!("could not queue the mail: {error}")))?;
    {
        let mut seen = lock(&SEEN_MAIL);
        seen.push_back(envelope.id.clone());
        while seen.len() > SEEN_MAIL_KEPT {
            seen.pop_front();
        }
    }
    // Idle now (or its run ended meanwhile): it needs a run to read the mail.
    let wake = body.deliver != Deliver::Queue && !harness.has_active_run();
    if wake {
        router().request_wake(&session, &from, body.title.as_deref());
    }
    Ok(json!({ "queued": queued, "wake": wake }))
}

/// The ready-header capability block for the mesh.
pub fn capabilities() -> Value {
    json!({
        "version": evo_protocol::mesh::VERSION,
        "wireType": evo_protocol::mesh::WIRE_TYPE,
        "levels": ["state", "summary", "full"],
        "commands": ["subscribe", "list", "get", "cancel"],
        // `mail` envelopes (op `message`) to this session; answered by `res`.
        "mail": ["message"],
        "events": ["node_state", "node_report", "node_activity", "node_usage", "node_event"],
        "kinds": ["session", "agent", "side"],
        // A session node's `meta.wake` lists nodes whose messages wait for its
        // next run; it clears when that run starts.
        "wake": "sessionMeta",
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicBool;

    fn drain(rx: &mut broadcast::Receiver<(Level, Envelope)>) -> Vec<MeshEvent> {
        let mut out = Vec::new();
        while let Ok((_, envelope)) = rx.try_recv() {
            out.push(envelope.as_event().expect("event"));
        }
        out
    }

    fn agent(router: &LocalRouter, root: &Address, id: &str, cancel: Option<CancelFn>) -> Address {
        let address = root.child(NodeKind::Agent, id);
        router.spawn(address.clone(), id, Origin::Agent, json!({ "callId": format!("call-{id}") }), cancel);
        address
    }

    #[test]
    fn lifecycle_reaches_subscribers_in_order_and_closed_nodes_leave() {
        let router = LocalRouter::default();
        let mut rx = router.feed();
        let sub = router.subscriber();
        router.subscribe(&sub, Level::State, None);
        let root = router.set_root("S", "chat");
        let a = agent(&router, &root, "1", None);
        router.transition(&a, NodeState::Running, None, None); // unchanged: silent
        router.report(&a, RunStatus::Done, "found it".into(), MeshUsage::default(), None);
        router.transition(&a, NodeState::Settled, Some(RunStatus::Done), None);
        router.transition(&a, NodeState::Closed, None, None);

        let events = drain(&mut rx);
        let kinds: Vec<_> = events
            .iter()
            .map(|event| match event {
                MeshEvent::NodeState { node, .. } => format!("{}:{:?}", node.id, node.state),
                MeshEvent::NodeReport { node, .. } => format!("{node}:report"),
                other => format!("{other:?}"),
            })
            .collect();
        assert_eq!(
            kinds,
            ["s_S:Idle", "s_S/a_1:Running", "s_S/a_1:report", "s_S/a_1:Settled", "s_S/a_1:Closed"]
        );
        let MeshEvent::NodeState { node, prev } = &events[1] else { panic!() };
        assert_eq!(node.parent, Some(root.clone()));
        assert_eq!(node.depth, 1);
        assert_eq!(node.meta["callId"], "call-1");
        assert_eq!(*prev, None);
        let MeshEvent::NodeState { node, prev } = &events[4] else { panic!() };
        assert_eq!(node.status, Some(RunStatus::Done));
        assert_eq!(*prev, Some(NodeState::Settled));
        assert!(router.get(&a).is_none());
        assert_eq!(router.list(ListScope::All, None).unwrap().len(), 1);
    }

    #[test]
    fn summary_events_exist_only_while_wanted() {
        let router = LocalRouter::default();
        let mut rx = router.feed();
        let root = router.set_root("S", "chat");
        let a = agent(&router, &root, "1", None);
        router.activity(&a, 1, 1, None, Some("hello".into()));
        router.usage(&a, MeshUsage { input: 5, ..Default::default() });
        assert!(drain(&mut rx).is_empty(), "nobody subscribed: nothing is sent");
        // ...but state events were retained and replay on subscribe, followed
        // by the activity snapshot.
        let sub = router.subscriber();
        let (seq, replay) = router.subscribe(&sub, Level::Summary, None);
        assert_eq!(seq, 2);
        let ops: Vec<_> = replay.iter().map(|e| e.op.as_str()).collect();
        assert_eq!(ops, ["node_state", "node_state", "node_activity"]);
        let (_, after) = router.subscribe(&sub, Level::Summary, Some(1));
        let ops: Vec<_> = after.iter().map(|e| (e.op.as_str(), e.from.as_str())).collect();
        assert_eq!(ops, [("node_state", "s_S/a_1"), ("node_activity", "s_S/a_1")]);

        router.activity(&a, 2, 3, None, None);
        router.usage(&a, MeshUsage { input: 7, cost: 0.25, ..Default::default() });
        let events = drain(&mut rx);
        assert!(matches!(&events[0], MeshEvent::NodeActivity { turns: 2, tool_uses: 3, .. }));
        // The node's usage, then the root's subtree total.
        let MeshEvent::NodeUsage { node, own, subtree } = &events[1] else { panic!() };
        assert_eq!((node.as_str(), own.input, subtree.input), ("s_S/a_1", 7, 7));
        let MeshEvent::NodeUsage { node, own, subtree } = &events[2] else { panic!() };
        assert_eq!((node.as_str(), own.input, subtree.input), ("s_S", 0, 7));
        assert_eq!(subtree.cost, 0.25);
    }

    #[test]
    fn cancel_cascades_children_first_and_reports_what_stopped() {
        let router = LocalRouter::default();
        let root = router.set_root("S", "chat");
        let order = Arc::new(Mutex::new(Vec::new()));
        let handle = |name: &'static str, stops: bool| -> CancelFn {
            let order = order.clone();
            Arc::new(move || {
                order.lock().unwrap().push(name);
                stops
            })
        };
        let a = agent(&router, &root, "1", Some(handle("a1", true)));
        let nested = a.child(NodeKind::Agent, "2");
        router.spawn(nested.clone(), "nested", Origin::Agent, json!({}), Some(handle("a2", true)));
        let idle = agent(&router, &root, "3", Some(handle("a3", false)));

        assert_eq!(router.get(&nested).unwrap().parent, Some(a.clone()));
        assert_eq!(router.list(ListScope::Children, Some(&root)).unwrap().len(), 2);
        assert_eq!(router.list(ListScope::Subtree, None).unwrap().len(), 3);

        let stopped = router.cancel(&root, true).unwrap();
        assert_eq!(stopped, vec![nested.clone(), a.clone()]);
        assert_eq!(*order.lock().unwrap(), vec!["a2", "a3", "a1"]);
        assert_eq!(router.cancel(&a, false).unwrap(), vec![a.clone()]);
        assert!(router.cancel(&idle, false).unwrap().is_empty());
        assert_eq!(
            router.cancel(&root.child(NodeKind::Agent, "nope"), true).unwrap_err().code,
            ErrorCode::NotFound
        );
    }

    #[test]
    fn commands_answer_through_envelopes() {
        let router = LocalRouter::default();
        let root = router.set_root("S", "chat");
        let stopped = Arc::new(AtomicBool::new(false));
        let flag = stopped.clone();
        let a = agent(
            &router,
            &root,
            "1",
            Some(Arc::new(move || {
                flag.store(true, Ordering::SeqCst);
                true
            })),
        );
        let command = |c: MeshCommand| Envelope::command("c-1".into(), "client:w", &c);
        let sub = router.subscriber();

        let (res, replay) = router.handle(&command(MeshCommand::Subscribe { level: Level::State, since: None }), &sub);
        assert_eq!(res.corr.as_deref(), Some("c-1"));
        assert_eq!(res.body["root"], "s_S");
        assert_eq!(replay.len(), 2);
        assert_eq!(router.level(), Level::State);

        let (res, _) = router.handle(&command(MeshCommand::List { scope: ListScope::Children, of: None }), &sub);
        assert_eq!(res.body["nodes"][0]["id"], "s_S/a_1");
        let (res, _) = router.handle(&command(MeshCommand::Get { node: a.clone() }), &sub);
        assert_eq!(res.body["node"]["kind"], "agent");
        let (res, _) = router.handle(&command(MeshCommand::Cancel { node: a.clone(), cascade: true }), &sub);
        assert_eq!(res.body["cancelled"][0], "s_S/a_1");
        assert!(stopped.load(Ordering::SeqCst));

        let (res, _) = router.handle(&command(MeshCommand::Get { node: root.child(NodeKind::Side, "x") }), &sub);
        assert_eq!(res.body["error"]["code"], "not_found");
        let mut bad = command(MeshCommand::Get { node: a });
        bad.op = "teleport".into();
        let (res, _) = router.handle(&bad, &sub);
        assert_eq!(res.body["error"]["code"], "bad_request");
    }

    #[test]
    fn late_summary_subscribers_get_one_activity_snapshot_per_node() {
        let router = LocalRouter::default();
        let root = router.set_root("S", "chat");
        let a = agent(&router, &root, "1", None);
        let row = |id: &str, phase: &str| ToolRow { call_id: id.into(), name: "bash".into(), args: json!({}), phase: phase.into() };
        // Nobody subscribed: still folded.
        router.activity(&a, 1, 1, Some(row("c1", "running")), None);
        router.activity(&a, 1, 2, Some(row("c2", "running")), Some("thinking".into()));
        router.activity(&a, 2, 2, Some(row("c1", "done")), None);

        let sub = router.subscriber();
        let (_, replay) = router.subscribe(&sub, Level::Summary, None);
        let snapshot = replay
            .iter()
            .filter_map(Envelope::as_event)
            .find_map(|event| match event {
                MeshEvent::NodeActivity { node, turns, tool_uses, text, rows: Some(rows), .. } if node == a => {
                    Some((turns, tool_uses, text, rows))
                }
                _ => None,
            })
            .expect("a snapshot");
        assert_eq!((snapshot.0, snapshot.1, snapshot.2.as_deref()), (2, 2, Some("thinking")));
        let phases: Vec<_> = snapshot.3.iter().map(|r| (r.call_id.as_str(), r.phase.as_str())).collect();
        assert_eq!(phases, [("c1", "done"), ("c2", "running")]);

        // A state-level subscriber gets no activity.
        let other = router.subscriber();
        let (_, replay) = router.subscribe(&other, Level::State, None);
        assert!(replay.iter().all(|e| e.op != "node_activity"));
    }

    #[test]
    fn wake_requests_live_on_the_session_until_its_next_run() {
        let router = LocalRouter::default();
        let mut rx = router.feed();
        let sub = router.subscriber();
        router.subscribe(&sub, Level::State, None);
        let root = router.set_root("S", "chat");
        let a = agent(&router, &root, "1", None);
        let b = agent(&router, &root, "2", None);
        drain(&mut rx);

        router.request_wake(&root, &a, None);
        router.request_wake(&root, &a, None); // once per node
        router.request_wake(&root, &b, Some("B"));
        assert_eq!(router.pending_wake(&root), [a.to_string(), b.to_string()]);
        let events = drain(&mut rx);
        assert_eq!(events.len(), 2);
        let MeshEvent::NodeState { node, prev } = &events[1] else { panic!() };
        assert_eq!((node.id.clone(), node.state, *prev), (root.clone(), NodeState::Idle, Some(NodeState::Idle)));
        assert_eq!(node.meta["wake"], json!([a.as_str(), b.as_str()]));

        // A message, then a report from the same node: the upgrade is
        // announced; a later message does not downgrade it.
        let c = agent(&router, &root, "3", None);
        drain(&mut rx);
        router.request_wake_for(&root, &c, None, "mail");
        assert_eq!(drain(&mut rx).len(), 1);
        router.request_wake_for(&root, &c, None, "report");
        let MeshEvent::NodeState { node, .. } = drain(&mut rx).pop().expect("announced") else { panic!() };
        assert_eq!(node.meta["wakeReasons"][c.as_str()], "report");
        router.request_wake_for(&root, &c, None, "mail");
        assert!(drain(&mut rx).is_empty());
        assert_eq!(router.get(&root).unwrap().meta["wakeReasons"][c.as_str()], "report");

        // A session the router has not seen is tracked, not made the root.
        let other = Address::session("T");
        router.request_wake(&other, &a, None);
        assert_eq!(router.pending_wake(&other), [a.to_string()]);
        assert_eq!(router.root(), Some(root.clone()));
    }

    #[test]
    fn a_wait_that_closes_a_cycle_is_refused() {
        let router = LocalRouter::default();
        let root = Address::session("S");
        let a = root.child(NodeKind::Agent, "a");
        let b = root.child(NodeKind::Agent, "b");
        let c = root.child(NodeKind::Agent, "c");
        // The session waits on a (a foreground agent call); a asks b; b asks c.
        let _fg = router.add_wait(&root, &a);
        let _ab = router.try_wait(&a, &b).unwrap();
        let bc = router.try_wait(&b, &c).unwrap();
        // c asking a, or a asking the session, would never end.
        assert_eq!(router.try_wait(&c, &a).err().unwrap().code, ErrorCode::WouldDeadlock);
        assert_eq!(router.try_wait(&a, &root).err().unwrap().code, ErrorCode::WouldDeadlock);
        assert!(router.would_deadlock(&a, &a));
        // So would c asking the session (it waits on c through a and b); an
        // agent outside the chain may ask it. Once b's ask ends, c may ask a.
        assert!(router.would_deadlock(&c, &root));
        assert!(!router.would_deadlock(&root.child(NodeKind::Agent, "d"), &root));
        drop(bc);
        assert!(router.try_wait(&c, &a).is_ok());
    }

    #[test]
    fn a_pair_talking_in_a_loop_is_stopped() {
        let router = LocalRouter::default();
        let (a, b) = (Address::session("S").child(NodeKind::Agent, "a"), Address::session("S").child(NodeKind::Agent, "b"));
        for _ in 0..MAX_PAIR_MAIL {
            router.count_mail(&a, &b).unwrap();
        }
        assert_eq!(router.count_mail(&a, &b).unwrap_err().code, ErrorCode::Forbidden);
        assert!(router.count_mail(&b, &a).is_ok(), "per direction");
    }

    #[test]
    fn a_new_session_replaces_the_root() {
        let router = LocalRouter::default();
        let mut rx = router.feed();
        let sub = router.subscriber();
        router.subscribe(&sub, Level::State, None);
        router.set_root("S1", "one");
        router.set_root("S1", "one again"); // same session: no-op
        router.set_root("S2", "two");
        let events = drain(&mut rx);
        assert_eq!(events.len(), 3);
        let MeshEvent::NodeState { node, .. } = &events[1] else { panic!() };
        assert_eq!((node.id.as_str(), node.state), ("s_S1", NodeState::Closed));
        assert_eq!(router.root(), Some(Address::session("S2")));
        assert_eq!(router.list(ListScope::All, None).unwrap().len(), 1);
    }
}
