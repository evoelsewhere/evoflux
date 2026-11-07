# Session mesh protocol

| | |
| --- | --- |
| Status | Implemented (phases 1–4); phase 5 proposed |
| Area | crates `evo-mesh` `evo-protocol`, engine, desktop shell |
| Format | Legacy — predates [the SDD template](../../templates/sdd.md); move to it on the next substantial edit |
| Updated | 2026-11-06 |
| ADD sections | [6.2 Sessions talking to sessions](../../architecture/README.md#62-sessions-talking-to-sessions) |
| ADRs | [0003](../../architecture/decisions/0003-engine-runs-as-a-child-process-per-chat.md) |

Status: phases 1–4 built (see "as built" below; phase 4 within one engine); phase 5 proposed.
Builds on [subagents and nested sessions](../subagents-and-nested-sessions/sdd.md) (the features exist; this
document replaces the ad-hoc plumbing under them with one protocol). Paths
are relative to the repository root.

### Phase 1 as built

- `crates/evo-protocol/src/mesh.rs`: envelope, `Address`, `Node`, `Level`,
  `MeshEvent` (`node_state`, `node_report`, `node_activity`, `node_usage`,
  `node_event`), `MeshCommand` (`subscribe`, `list`, `get`, `cancel`), typed
  errors.
- `crates/evo-engine/src/mesh.rs`: the `LocalRouter` (one per engine). The
  `agent` tool, plugin children (`child_agents.rs`) and side questions
  register their nodes there with a cancel handle and report state, activity,
  usage and reports. Their own job tables stay (they hold the harness
  handles); the router is the shared registry and event source.
- RPC: `ready.mesh` advertises version 1; a `{"type":"mesh",…}` command line
  is answered with a `res` envelope (`corr` = its `id`), then the replay;
  events go out as `{"type":"mesh",…}` lines. The session's root node is
  `running` from an accepted prompt until `agent_settled`, then `idle`.
- Desktop: `src/engine/mesh.ts` (types and the fold into the agent view),
  `EngineClient.mesh()`, and `engine-store.ts` subscribes at `summary` on
  `ready` (and when it attaches to an engine that already runs) and renders
  subagents from `node_*` events.

### Phase 2 as built

- No polling. The RPC commands `get_background_agents`,
  `ack_background_agents` and `cancel_background_agent` are gone; the agent
  registry no longer keeps a wake flag.
- **Wake requests live on the session node.** When a background agent's
  report is queued for an idle parent, the engine adds the agent's address to
  the parent session node's `meta.wake` and announces the node
  (`LocalRouter::request_wake`). Any run of that session reads the queued
  reports, so the list clears when a run starts (`mesh::session_run`). No ack
  command is needed, and a window that reloads sees the pending list in the
  replay.
- **Activity snapshot on subscribe.** The router folds every node's activity
  (turns, tool uses, last 50 tool rows, text tail) even with no subscriber; a
  `summary` subscription replays one `node_activity` per node with `rows` set
  (the whole list, replacing the subscriber's). A reopened chat or reloaded
  window shows a running agent's steps at once.
- Desktop (`engine-store.ts`): on a session node's `node_state` (and on
  `agent_settled`) it waits 1 s for events to settle, then wakes an idle chat
  for the `meta.wake` reports it has not handled yet (`address@endedAt`), with
  the existing limit of 5 automated wakes in a row. Cancelling an agent sends
  mesh `cancel`. An idle chat whose subagents still run is no longer stopped
  by the idle-engine trim.

### Phase 3 as built

- **`crates/evo-mesh`**: the wire types moved here (`evo_protocol::mesh`
  re-exports them) so the shell can depend on the mesh without the engine
  crates; plus the `Hub` — pure logic that takes every engine stdout line
  and returns effects (`Send` a line to an engine, `MailWaiting`), with a
  `MailStore` trait. Mail ops: `mail` envelopes with op `message` and a
  `MailBody {text, deliver, title}`.
- **Engine**: every finished turn of a session emits a `node_report` about
  the session itself (status from the run's outcome, its final text; not for
  compactions). A `mail` envelope addressed to the session is queued like a
  steering message (running) or for the next run (idle); `deliver: wake`
  then adds a wake request (`meta.wake` + `meta.wakeTitles`), exactly like a
  background agent's report. The engine answers with `res` (`corr` = mail
  id) and drops a mail id it already took.
- **Shell** (`apps/desktop/src-tauri/src/mesh.rs`): the hub sees every
  engine's stdout. A nested session's `node_report` becomes a
  `<nested-session …>` note mailed to its parent with `wake`, stored in the
  new `mail` table (migration `0006_mail.sql`, `evo_store::mail`), written to
  the parent's engine if it is ready, and marked delivered when that engine
  answers. Otherwise the windows hear `mesh://mail-waiting`; the main window
  starts the parent's engine and the hub sends the mail on its `ready`.
  Unanswered mail is sent again after a restart (at least once). Reports the
  engine replays to a new subscriber are recognised by envelope id and not
  mailed twice.
- **Desktop**: the webview no longer builds or queues notes
  (`recordFinishedTurn`, `pendingNotes`, `flushNotes` are gone). A note wakes
  the parent through the same `meta.wake` path as background agents, with a
  `<nested-sessions-done>` prompt and a "Session finished a turn" chip.
  Restored transcripts no longer show an empty turn for a queued report.

Verified in the app: a child's turn reaches its parent in the same window,
from a separate chat window, and while the parent's engine is stopped (it is
started, then the note is delivered and the parent wakes).

**Session tools in the hub.** `start_session`, `message_session` and
`list_sessions` are defined by the hub (`session_tools()`, fetched by the
window through `mesh_session_tools` and registered on top-level chats) and
answered by it: the window ignores their `external_tool_request`s.

- `start_session` proposes (a `proposal_…` id in the tool result, as before)
  or, with Settings → Sandbox → start without asking (`mesh_configure`),
  starts at once. A proposal card's Start calls `mesh_start_session`.
  Starting creates the chat in Rust (`DbMailStore::create_session`: chat row,
  fork, worktree), announces it as `chat://updated`, and mails the child its
  brief with the new `deliver: prompt`. At most 8 children of a chat run at
  once; nested sessions get no session tools.
- **Prompt mail** waits until a window has *hosted* the receiving engine (set
  up its tools and called `mesh_hosted`), then goes out as an RPC `prompt`
  (idle) or `queue_message` steer (busy: read at the session's next step, not
  after its run; the hub tracks `agent_start` / `agent_settled`). A refused prompt goes out when the run ends. Accepted =
  delivered. The engine does not echo a run's first prompt, so the hub also
  emits `mesh://prompted` and the window showing the chat adds the turn.
- **Hosting.** When the hub needs an engine that is not set up — a session it
  just created, a chat with waiting mail, an engine that exited with mail
  pending — it emits `mesh://host {chat, cwd, restore}`. A window that holds
  the chat answers `mesh_hosted`; otherwise the main window starts the engine
  in the background, and `onReadyNested` calls `mesh_hosted` once the tools
  are set up. Windows still start, hold and trim engines.
- **Hosting an engine that died.** A window that holds a chat whose engine
  exited or failed to start (a crash) starts it again when the hub asks for
  a host, at most 3 times in 2 minutes per chat (an engine that dies on
  start is not restarted forever; its mail then waits until the chat is
  opened). Without this, `message_session` reported "sent" while the mail
  waited for good.
- **Mail left at startup.** No engine runs when the app starts, so nothing
  asks for a host: the main window reads the chats with undelivered mail
  (`mesh_pending_chats`, `evo_store::mail::chats_with_pending_mail`, archived
  chats excluded) and hosts each one.
- `list_sessions` reads the children from the database and their live state
  from the hub (`running`, `waiting` for an approval, `idle`).

Verified in the app: a proposal answered by the hub and started from its
card; the child's brief, its note and the parent's wake; `message_session`
to the child; `list_sessions`; and auto-start.

### Phase 4 as built (within one engine)

`crates/evo-engine/src/mesh_tools.rs`: the tools `send_message`, `ask`,
`reply`, `list_nodes` and `cancel_node`, for the session and for every
subagent. Each agent gets its own instances bound to its node (passed as the
child's tool replacements; agent types that narrow tools keep them), so a
call knows who calls; the session's instances refuse calls from other
children (plugin children).

- **Reach**: a node writes to its parent, its children and — with
  `mail.siblings`, which agents get — its siblings; never another tree.
  `to` takes `parent`, a node id, an agent id or a title.
- **Delivery**: a `<mail id from title kind>` user message. A running
  receiver gets it before its next model call (steer); an idle session gets
  it with its next run plus a wake request with reason `mail`
  (`meta.wakeReasons`; the desktop wakes it with `<mail-arrived>`, chips
  "Message/Question from …"); an idle agent gets it when continued.
- **ask / reply**: `ask` blocks until `reply {askId}`, the receiver's run
  ending (its final text answers), the timeout (default 600 s, max 1800 s)
  or cancellation. An `ask` to an idle agent continues it in the background
  to answer; that run's report goes to the asker, not to the parent.
- **Guards** (`LocalRouter`): the wait-for graph holds every open `ask` and
  every foreground `agent` call (the session waits on that agent); an `ask`
  that would close a cycle is refused (`would_deadlock`) — e.g. a foreground
  agent asking its session. At most `MAX_PAIR_MAIL` (20) messages per
  directed pair between two runs of the session.
- Not built: mail between nodes of different engines (sessions talk through
  notes and `message_session`), topics, budgets and depth limits beyond "no
  recursion".

Verified with the faux provider (`agent_tool/tests/peers.rs`: siblings
coordinate through ask/reply, a cyclic ask is refused, a message reaches the
parent) and in the app with a real model: two background agents, one asks
the other for a code word, tells the parent with `send_message`, and the idle
parent wakes once for the message and both reports.

Differences from the design below:

- Each subscriber has its own level; the router builds events up to the
  highest live one. `node_state`'s body carries the whole node record.
- Legacy engine events are not tagged with `from`: they all belong to the
  root, which the design allows. Hosted nodes' raw events are `node_event`
  at the `full` level (side questions do not send them yet).
- Side questions close as soon as they settle (they are one-shot).

Goal: one wire contract through which **sessions, nested sessions, subagents
and side questions** are started, observed, stopped and **talk to each other**
— whether they live in the same engine process or in different ones.

---

## 1. Why: five mechanisms for one idea

Today every "conversation that is not the one you are typing in" has its own
transport:

| Need | Today | Problem |
| --- | --- | --- |
| See a subagent's steps | Cumulative snapshot stuffed into `tool_execution_update.details.child` | Lossy (last 50 tools, 4 KB text), only reaches the direct parent's UI, not addressable |
| Know a background agent finished | Desktop polls `get_background_agents` once a second | Polling; no push event |
| Talk to a finished subagent | `message_agent` tool | Separate from sessions |
| Start / talk to a nested session | Desktop external tools `start_session` / `message_session` / `list_sessions` in `engine-store.ts` | Orchestration lives in the webview; breaks across windows |
| Tell a parent session a child finished | `recordFinishedTurn` → `queue_message` or automated `prompt` | Logic in the webview; notes lost if the parent is in another window |
| Plugin children | Host action `child_agent {start\|poll\|cancel\|dispose}` | Its own job table and polling |

None of them lets two **siblings** talk, none gives a child a way to **ask**
its parent something mid-task, and none survives a window or engine restart.

---

## 2. Model

### 2.1 Nodes

Every running conversation is a **node**:

| Kind | Lives in | Durable | User can open it | Example |
| --- | --- | --- | --- | --- |
| `session` | its own engine process | yes (chat row + transcript) | yes | a chat, a nested session |
| `agent` | inside its host session's engine | no (kept a while for follow-ups) | read-only, nested under the tool call | `agent` tool, `delegate_task` |
| `side` | inside its host session's engine | no | read-only | side questions |

```jsonc
{
  "id": "s_01JC…/a_01JD…",       // address, see 2.2
  "kind": "agent",
  "parent": "s_01JC…",           // lineage: who started it (may differ from host)
  "root": "s_01JA…",             // top of the lineage tree
  "depth": 1,
  "title": "Find auth call sites",
  "origin": "agent",             // user | agent  — who asked for it
  "state": "running",            // see 6
  "caps": ["mail.parent", "mail.siblings"],
  "budget": { "turns": 24, "costUsd": 0.5 },
  "usage": { "input": 0, "output": 0, "costUsd": 0 },
  "worktree": null
}
```

### 2.2 Address = location, parent = lineage

Two different things, deliberately kept apart:

- **Address** says *where the node runs* and therefore how to route to it.
  `s_<id>` is a session (one engine). `s_<id>/a_<id>` is an agent hosted in that
  engine; `s_<id>/a_<id>/a_<id>` if agents may nest. The hub routes on the first
  segment, the engine on the rest. No lookup table is needed to route.
- **Parent** says *who started it* and therefore who gets its reports and who
  may control it. A nested session has a top-level address (`s_B`, own engine)
  but `parent: s_A`.

Special addresses: `hub`, `client:<windowId>`, `topic:<name>` (phase 4).

---

## 3. Topology

```
 ┌──────────── desktop shell (Rust, Tauri) ─────────────┐
 │  Hub  (crate evo-mesh)                                │
 │  ├─ node registry (tree)      ├─ policy (caps, wake)  │
 │  ├─ router  s_* → engine      ├─ mailbox store (DB)   │
 │  └─ subscriptions (windows)   └─ proposals            │
 └────┬──────────────────┬──────────────────┬───────────┘
      │ stdio JSONL/CBOR │                  │ Tauri events
  engine s_A         engine s_B          windows (webviews)
  LocalRouter        LocalRouter
  ├─ s_A/a_1         (nested session,
  └─ s_A/a_2          parent = s_A)
```

- **Hub in the shell.** The shell already spawns every engine and relays its
  stdio (`apps/desktop/src-tauri/src/engine.rs`); it is the one place that sees
  all sessions and all windows. The hub is a transport-agnostic crate
  (`crates/evo-mesh`: registry, router, policy, a `MailStore` trait) embedded in
  the shell, so it can later run standalone for remote engines.
- **LocalRouter in the engine.** Owns the in-process nodes (agents, side
  questions). Mail between two agents of the same engine never leaves the
  process; everything else goes up to the hub. It replaces the separate job
  tables of `child_agents.rs`, `agent_tool.rs` and the background-agent list.
- **Windows are subscribers**, not orchestrators. Starting a nested session,
  delivering notes and waking parents move from `engine-store.ts` into the
  hub, which fixes the "parent open in another window" limit for free.

---

## 4. Envelope

One shape for everything on the mesh, over the existing `evo-protocol`
framing (JSONL by default, CBOR frames optional):

```jsonc
{
  "v": 1,
  "id": "m_01JE…",          // unique; idempotency key
  "kind": "cmd",            // cmd | res | evt | mail
  "op": "spawn",            // operation / event / mail type
  "from": "s_A",
  "to": "hub",
  "corr": null,             // res → its cmd; reply → its ask
  "seq": 1042,              // monotonic per sender; replay + ordering
  "ts": 1762400000000,
  "trace": { "root": "s_A", "cause": "m_01JD…", "hops": 1 },
  "body": { }
}
```

- `kind` splits the three planes (section 5): `cmd`/`res` = control,
  `evt` = observation, `mail` = conversation between nodes.
- `trace.cause` links every message to what caused it (a tool call, a mail),
  so loops and fan-out can be detected and the UI can draw causality.
- `trace.hops` is incremented on every relay; the hub drops at 16.

**Compatibility.** An engine that says `"mesh": 1` in `ready` speaks
envelopes. A message without an envelope is a legacy `RemoteEvent` /
`RemoteCommand` and is treated as `from`/`to` = the session's root node, so
current clients and engines keep working unchanged.

---

## 5. The three planes

### 5.1 Control (`cmd` → `res`)

| op | body | result |
| --- | --- | --- |
| `spawn` | `kind`, `parent`, `title`, `brief`, `context: fresh\|fork`, `agentType?`, `model?`, `worktree?`, `background?`, `initiation: user\|agent`, `budget?` | `{node}` or `{state: "proposed", proposalId}` |
| `resolve_proposal` | `proposalId`, `accept: bool` | `{node?}` |
| `cancel` | `node`, `cascade: true` | `{cancelled: [ids]}` |
| `close` | `node` (release a retained agent, stop a session engine) | — |
| `detach` | `node` (session leaves its parent) | — |
| `resume` | `node` (reopen a session's engine from the DB) | `{node}` |
| `list` | `scope: children\|subtree\|root`, `of`, `states?` | `{nodes: […]}` |
| `get` | `node` | `{node}` |
| `subscribe` | `node`, `scope: self\|subtree`, `level`, `since?` | `{seq}` |
| `unsubscribe` | `subscription` | — |

Errors are typed: `not_found`, `forbidden` (caps), `budget_exceeded`,
`depth_exceeded`, `too_many_children`, `would_deadlock`, `timeout`.

### 5.2 Observation (`evt`)

Subscribers choose a **level**, so a sidebar does not pay for token deltas:

| level | events |
| --- | --- |
| `state` | `node_state`, `node_report`, `proposal_*` |
| `summary` | + `node_activity` (tool rows: `callId`, `name`, `subject`, `phase`; text tail), `node_usage` |
| `full` | + every existing `RemoteEvent` (`message_update`, `tool_execution_*`, …) with `from` = that node |

Core events:

```jsonc
{ "op": "node_state",  "body": { "node": { "id": "s_A/a_1", "state": "settled", "status": "done", … }, "prev": "running" } }
{ "op": "node_report", "body": { "node": "s_A/a_1", "turn": 3, "status": "done",
                                  "text": "…report…", "usage": { … }, "worktree": { "path": "…", "branch": "…", "kept": true } } }
{ "op": "node_usage",  "body": { "node": "s_A/a_1", "self": { … }, "subtree": { … } } }
```

- The **parent is always subscribed** to its children at `state` level; that
  subscription is what used to be "notes" and polling.
- `subscribe {since: seq}` replays from a per-node ring buffer (engine side)
  and, for sessions, the transcript; a gap answers `resync` with a snapshot.
- `details.child` on the `agent` tool result stays, written once at the end,
  so a reopened chat still shows the finished child without the mesh.

### 5.3 Mail (`mail`)

How nodes talk. Three ops: `message`, `ask`, `reply`.

```jsonc
{ "kind": "mail", "op": "message", "from": "s_A/a_1", "to": "s_A/a_2",
  "body": { "content": [ { "type": "text", "text": "Schema is in db/0004.sql" } ],
            "deliver": "queue" } }
```

`deliver` decides what happens at the receiver:

| deliver | receiver running | receiver idle | maps to today |
| --- | --- | --- | --- |
| `interrupt` | injected before its next model call | starts a turn (wake guard) | `queue_message steer` |
| `queue` | after the current turn, same run | held until its next turn | `followUp` / `nextTurn` |
| `wake` | like `queue` | starts a turn (wake guard) | automated `prompt` |

**ask / reply.** `ask` is mail that expects one `reply` with `corr` = the
ask's id. The asking tool call blocks (node state `waiting`) until the reply
or `timeoutMs` (default 10 min). The receiver sees the question with its id
and answers with the `reply` tool; if the receiver is an agent whose run ends
without replying, its final text is the reply.

**Rendering into the model's context.** Mail never looks like the user:

```xml
<mail id="m_01JE…" from="s_A/a_1" title="Find auth call sites" origin="agent" kind="ask">
…content…
</mail>
```

The system prompt states that mail is information from another agent, not an
instruction from the user, and the transcript shows it as an event chip, not a
user bubble.

---

## 6. Lifecycle

```
 proposed ──accept──▶ starting ──▶ running ◀──▶ waiting (ask / approval)
     │                               │  ▲
  reject/expire                 turn end│  │ mail (interrupt|wake)
     ▼                               ▼  │
  dismissed                          idle ──────────────┐
                                     │                  │ (sessions only:
                       done | failed | cancelled        │  idle is normal,
                                     ▼                  │  they wait for input)
                                  settled ──close/evict──▶ closed
```

- **Agents**: `running` → `settled` when the run ends; kept (retained) for
  follow-up mail for N idle minutes, then `closed`.
- **Sessions**: alternate `running` ⇄ `idle` forever; `closed` only when
  archived or deleted. A `node_report` is emitted on every turn end.
- **Cancellation cascades** down the lineage tree by default. Deleting a parent
  session *detaches* its child sessions (they move to the top level) but
  cancels its agents.
- If an engine dies, the hub marks its session `failed {reason: "engine_exit"}`
  and its agents `failed`; pending mail to the session stays in the store.

---

## 7. Policy (enforced by the hub and LocalRouter, never by the model)

### 7.1 Capabilities — narrow-only inheritance

A child gets at most its parent's capabilities; `spawn` may narrow them.

| cap | default for agents | default for agent-started sessions |
| --- | --- | --- |
| `mail.parent`, `mail.children` | yes | yes |
| `mail.siblings` | yes | no |
| `mail.tree` (anyone under the same root) | no | no |
| `spawn.agent` | no (no recursion) | yes |
| `spawn.session` | no | no |
| `spawn.session.auto` (no proposal) | no | Settings → Sandbox |
| `topic:<name>` publish / subscribe | no | no |

Mail never crosses root trees without the user.

### 7.2 Limits and budgets

- `maxDepth` (default 2), `maxChildren` per node (8 sessions, 16 agents),
  `maxConcurrent` foreground agents per run (4).
- `budget {turns, tokens, costUsd, wallClockSec}`: a child's budget is at most
  its parent's remainder. Usage rolls up (`node_usage.subtree`); exceeding it
  settles the node with `failed {reason: "budget"}`.

### 7.3 Approval

`spawn {kind: "session", initiation: "agent"}` without `spawn.session.auto`
returns `proposed`; the hub stores the proposal (expires after 7 days) and
emits `proposal_created`; the UI shows the card. Same path as today's proposal
cards, now owned by the hub.

### 7.4 Wake guard and loop breaker

- Coalesce wakes for 2 s into one automated turn.
- At most 5 automated turns in a row on a node without a user message; after
  that, mail waits for the user.
- No wake while the user has a draft in that chat, or on an archived chat.
- **Ping-pong breaker**: more than 20 mails between the same two nodes with no
  user input pauses both (`waiting {reason: "loop"}`) and surfaces it.
- **Deadlock guard**: the hub keeps the wait-for graph of open `ask`s; an `ask`
  that would close a cycle is refused with `would_deadlock`.

---

## 8. Delivery and persistence

| | sessions | agents |
| --- | --- | --- |
| Mail guarantee | at-least-once, deduplicated by `id` | at-most-once (in memory) |
| Ordering | per (from, to) by `seq` | per (from, to) by `seq` |
| Survives engine restart | yes (DB) | no |
| Events replay | ring buffer + transcript | ring buffer while retained |

New migration in `crates/evo-store`:

```sql
CREATE TABLE mail (
    id          TEXT PRIMARY KEY,
    from_node   TEXT NOT NULL,
    to_node     TEXT NOT NULL,
    op          TEXT NOT NULL CHECK (op IN ('message', 'ask', 'reply')),
    corr        TEXT,
    deliver     TEXT NOT NULL,
    body        TEXT NOT NULL,           -- JSON
    state       TEXT NOT NULL DEFAULT 'pending'
                CHECK (state IN ('pending', 'delivered', 'failed', 'expired')),
    created_at  INTEGER NOT NULL,
    delivered_at INTEGER
);
CREATE INDEX mail_pending ON mail (to_node, state, created_at);

CREATE TABLE proposals (
    id TEXT PRIMARY KEY, parent_chat_id TEXT NOT NULL, spec TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'open', created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
);
```

Session nodes reuse `chats` (`parent_chat_id`, `origin` already exist).

---

## 9. Model-facing tools

A small, uniform set, each one mesh op underneath:

| Tool | Mesh op | Replaces |
| --- | --- | --- |
| `agent {description, prompt, agentType?, model?, isolation?, background?}` | `spawn kind=agent` | same name |
| `start_session {title, prompt, context, worktree?, model?}` | `spawn kind=session initiation=agent` | external tool |
| `send_message {to, message, deliver?}` | `mail message` | `message_agent`, `message_session` |
| `ask {to, question, timeoutSec?}` | `mail ask` (blocks) | — (new) |
| `reply {askId, answer}` | `mail reply` | — (new) |
| `list_nodes {scope?}` | `list` | `list_sessions`, `get_background_agents` |
| `cancel_node {node}` | `cancel` | `cancel_background_agent` |

Old names stay as aliases for one release. `to` accepts `parent`, a node id,
or a title the caller can see in `list_nodes`.

---

## 10. Example: two parallel agents, one asks the parent

```
s_A (parent)            engine A LocalRouter              s_A/a_1        s_A/a_2
  │ agent×2 (background)──▶ spawn a_1, a_2 ─────────────────▶ running      running
  │◀── node_state running ×2
  │ (turn ends, idle)
  │                                         a_1: send_message {to: a_2, "schema is in 0004"}
  │                         route locally ───────────────────────────────▶ mail(queue)
  │                                         a_2: ask {to: parent, "keep column or rename?"}
  │◀── mail ask (wake) ── hub wake guard: parent idle → automated turn
  │ reply {askId, "rename"} ──────────────────────────────────────────────▶ resumes
  │◀── node_report a_1 (done)  ◀── node_report a_2 (done)  → coalesced wake
```

---

## 11. Build plan

| Phase | Scope | Main files | Done when |
| --- | --- | --- | --- |
| 1. Envelope + addresses | `mesh` module in `evo-protocol` (envelope, node, ops, events); engine `LocalRouter` merging the job tables of `child_agents.rs`, `agent_tool.rs`, side questions; all engine events carry `from` | `crates/evo-protocol/src/mesh.rs`, `crates/evo-engine/src/child_agents.rs`, `agent_tool.rs`, `modes.rs` | Desktop renders a subagent from `summary` events; protocol round-trip tests |
| 2. Push lifecycle | `node_state` / `node_report` / `node_usage` from the engine; `get_background_agents` polling removed | `modes.rs`, `rpc/protocol.rs`, desktop `engine-store.ts` | A background agent finishing wakes the parent with no polling |
| 3. Hub | `crates/evo-mesh` (registry, router, policy, `MailStore`); embedded in the shell; nested-session spawn, notes, wakes and proposals moved out of the webview; `mail` + `proposals` migration; windows subscribe via Tauri events | `crates/evo-mesh`, `apps/desktop/src-tauri/src/engine.rs`, `crates/evo-store` | A child session in window 2 reports to its parent in window 1; mail to a closed session is delivered after reopen |
| 4. Peer messaging | `send_message` to siblings / tree, `ask` / `reply`, deadlock and loop guards, optional topics | `evo-mesh`, `evo-engine` tools | Two agents coordinate via `ask`/`reply`; a cyclic ask is refused |
| 5. Remote (later) | Hub over TCP for `--connect` and remote engines | `evo-protocol/client.rs`, `evo-mesh` | A remote engine joins the mesh |

Phases 1 → 2 → 3 → 4 in order; 4's in-engine part (agent ↔ agent) can start
right after 1.

---

## 12. Decisions to make

1. **Hub location**: embedded in the desktop shell (proposed), or a separate
   daemon that the shell and remote clients both connect to?
2. **Default peer scope**: parent and children only, or siblings too
   (proposed: siblings for agents, not for sessions)?
3. **Topics** (pub/sub channels for a team of agents) in phase 4, or later?
4. **Agent depth**: may agents start agents (`maxDepth` 2), or keep "no
   recursion"?
5. **`ask` without reply**: should an agent's final text count as the reply
   (proposed), or must it call `reply` explicitly?
