# Session mesh protocol — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | protocol, engine, desktop shell, crates `evo-mesh` `evo-protocol` |
| Created | 2026-11-06 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Subagents and nested sessions](../subagents-and-nested-sessions/spec.md) |

## 1. Summary

One wire contract through which **sessions, nested sessions, subagents and
side questions** are started, observed, stopped and **talk to each other** —
whether they live in the same engine process or in different ones. It
builds on [subagents and nested sessions](../subagents-and-nested-sessions/spec.md):
those features exist, and the mesh replaces the separate mechanisms under
them with one protocol.

Before the mesh, every conversation that was not the one being typed in had
its own transport: lossy snapshots, polling, webview-side orchestration and
a separate job table for plugin children. None of them let two siblings
talk, none gave a child a way to ask its parent something mid-task, and
none survived a window or engine restart. This feature is a technical
contract, so the message kinds, events and tool names that clients and the
model see are stated here; their full shapes are in the
[plan](plan.md#33-interfaces).

## 2. Scope

### 2.1 Goals

- One envelope and one addressing scheme for every conversation node.
- Push, not polling: clients learn about node state, activity, usage and
  reports as events, at the level of detail they ask for.
- A finished turn of a nested session reaches its parent whichever window
  shows the parent, and even when the parent's engine is stopped.
- Agents can message and ask their parent, children and siblings, with
  guards against deadlocks and loops.
- Session mail survives a window, engine or app restart.
- Later: a remote engine joins the mesh.

### 2.2 Non-goals

- Mail between root trees: mail never crosses root trees without the user.
- Topics (pub/sub channels) and agent recursion — not yet, see 6.2.
- The user-facing subagent and nested-session features themselves (the
  `agent` tool, worktrees, the nested-session UI) — see
  [subagents and nested sessions](../subagents-and-nested-sessions/spec.md).

## 3. User scenarios

### US-1 Watch subagents work (priority P1)

A person wants to see each subagent's steps live, also after reopening the
chat or reloading the window, so that they know what is happening.

Acceptance scenarios:

1. **Given** a running subagent, **when** the chat shows it, **then** its
   tool rows and text tail update as it works.
2. **Given** a running subagent, **when** the window reloads, **then** its
   steps so far show at once.

### US-2 A background agent's report reaches the idle parent (priority P1)

A person who started background agents wants the parent chat to pick up
their reports when they finish, without anything polling.

Acceptance scenarios:

1. **Given** an idle parent with a background agent, **when** the agent
   finishes, **then** the parent wakes once and reads the report.
2. **Given** pending wake requests, **when** the window reloads, **then**
   they are still pending and handled once.

### US-3 A nested session reports to its parent (priority P1)

A person with a nested session wants each of its finished turns to reach the
parent chat, so that the parent can follow up.

Acceptance scenarios:

1. **Given** the parent is in the same window, **when** the child finishes a
   turn, **then** the parent gets a note and wakes.
2. **Given** the parent is in another window, **when** the child finishes a
   turn, **then** the parent gets the note.
3. **Given** the parent's engine is stopped, **when** the child finishes a
   turn, **then** the parent's engine is started and the note delivered.

### US-4 The agent starts and steers a nested session (priority P2)

A person wants the agent to propose (or, if allowed, start) a nested session
with a brief, message it and list its children.

Acceptance scenarios:

1. **Given** auto-start is off, **when** the agent calls `start_session`,
   **then** a proposal card appears and **Start** creates the session with
   the brief.
2. **Given** auto-start is on, **when** the agent calls `start_session`,
   **then** the session starts at once.
3. **Given** a running child, **when** the agent calls `message_session`,
   **then** the child reads it at its next step.

### US-5 Agents coordinate (priority P2)

A person running several agents wants them to share findings and ask each
other questions, so that they do not duplicate work.

Acceptance scenarios:

1. **Given** two background agents, **when** one asks the other for a fact
   and tells the parent with `send_message`, **then** the idle parent wakes
   once for the message and both reports.
2. **Given** a foreground agent, **when** it asks the session that waits on
   it, **then** the ask is refused as a deadlock and says why.

### US-6 A remote engine joins (priority P3)

A person wants an engine running elsewhere to take part in the mesh.

Acceptance scenarios:

1. **Given** a remote engine, **when** it connects to the hub, **then** its
   nodes appear on the mesh.

### Edge cases

- An engine that dies on start is restarted at most 3 times in 2 minutes;
  its mail then waits until the chat is opened.
- The app starts with undelivered mail: the chats that have it are hosted.
- A report the engine replays to a new subscriber is not mailed twice.
- A prompt the receiving engine refuses goes out when its run ends.
- More than 8 running children of one chat: the next start is refused.
- Two nodes message each other in a loop: the pair is stopped after 20
  messages between two runs of the session.

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | Every running conversation — a session, a subagent, a side question — is a node with an address, a kind (`session`, `agent`, `side`), a parent, a root, a depth, a title, an origin and a state. | Given a session with a subagent, when a client lists nodes, then both appear with these fields. |
| FR-2 | A node's address says where it runs and routes without a lookup table (`s_<id>` a session engine, `s_<id>/a_<id>` an agent in it); its parent says who started it and so who gets its reports and may control it. A nested session has its own top-level address and its starter as parent. | Given a nested session started by `s_A`, when it is listed, then its address is top-level and its parent is `s_A`. |
| FR-3 | All mesh traffic uses one envelope (`v`, `id`, `kind`, `op`, `from`, `to`, `corr`, `seq`, `ts`, `trace`, `body`); `kind` is `cmd` / `res` (control), `evt` (observation) or `mail` (conversation between nodes). | Given any mesh message, when it is parsed, then it is an envelope of one of the four kinds; malformed and foreign messages are refused. |
| FR-4 | An engine that speaks the mesh says so (version 1) when it is ready. A message without an envelope is a legacy event or command of the session's root node, so existing clients and engines keep working. | Given a legacy client, when it talks to a mesh engine, then it works unchanged. |
| FR-5 | Control commands `subscribe`, `list`, `get` and `cancel` are answered with a `res` whose `corr` is the command's id. Errors are typed: `not_found`, `forbidden`, `budget_exceeded`, `depth_exceeded`, `too_many_children`, `would_deadlock`, `timeout`. | Given a `subscribe` command, when the engine answers, then the `res` carries its id in `corr` before the replay. |
| FR-6 | Cancelling a node cancels its children first and reports every node it stopped. | Given an agent with a child, when the agent is cancelled, then both stop and the result lists both. |
| FR-7 | Subscribers choose a level — `state`, `summary` or `full` — and each gets events up to its own level. | Given a `state` subscriber and a `summary` subscriber, when an agent works, then only the second gets activity events. |
| FR-8 | Nodes emit `node_state` (the whole node record), `node_report`, `node_activity`, `node_usage` and, at `full`, `node_event` (a hosted node's raw engine events). | Given a subagent run, when it starts, works and ends, then subscribers see state, activity, usage and a report in order, and a closed node leaves. |
| FR-9 | A session's root node is `running` from an accepted prompt until the run settles, then `idle`. | Given a prompt, when it is accepted and the run settles, then the root node goes `running` then `idle`. |
| FR-10 | Every node's activity (turns, tool uses, last 50 tool rows, text tail) is kept even with no subscriber; a new `summary` subscriber gets one activity snapshot per node with the whole row list. | Given a running agent, when a client subscribes late, then it gets one snapshot of the agent's rows. |
| FR-11 | The desktop shows subagents from mesh events, subscribing at `summary` when an engine is ready and when it attaches to an engine that already runs. | Manual check: a subagent's rows appear in the chat. |
| FR-12 | Background agent reports are pushed, never polled. When a report is queued for an idle parent, the parent session node carries a wake request; any run of that session reads the queued reports and clears the requests, with no acknowledgement. A reloaded window sees pending requests in the replay. | Given an idle parent, when its background agent finishes, then the parent node carries a wake request that clears on its next run. |
| FR-13 | The desktop wakes an idle chat for each wake request it has not handled yet, once events have settled, with at most 5 automated wakes in a row. | Given two reports for an idle chat, when they arrive together, then the chat wakes once. |
| FR-14 | An idle chat whose subagents still run is not stopped by the idle-engine trim; cancelling an agent from the desktop goes through the mesh. | Given an idle chat with a running background agent, when idle engines are trimmed, then its engine keeps running. |
| FR-15 | Every finished turn of a session (not a compaction) emits a `node_report` about the session itself, with the run's status and final text. | Given a session turn, when it ends, then a `node_report` for the session carries its final text. |
| FR-16 | Mail addressed to a session is queued as steering (session running) or for the next run (idle); `deliver: wake` also adds a wake request. The engine answers with `res` (`corr` = mail id) and drops a mail id it already took. | Given a `wake` mail to an idle session, when the engine takes it, then it answers `res`, adds a wake request, and ignores a resend of the same id. |
| FR-17 | A nested session's finished turn reaches its parent as a note that wakes it, whichever window shows the parent and even when the parent's engine is stopped (it is started first). The note is stored until the parent's engine answers, sent again after a restart if unanswered, and not created twice for a replayed report. | Given the parent's engine is stopped, when the child finishes a turn, then the parent's engine starts, gets the note and wakes. |
| FR-18 | `start_session`, `message_session` and `list_sessions` are owned by the hub and offered on top-level chats only; nested sessions get no session tools. | Given a nested session, when its tools are listed, then the session tools are absent. |
| FR-19 | `start_session` returns a proposal (id `proposal_…`) that a card's **Start** turns into a session, or starts at once when "start without asking" is on. Starting creates the chat (row, fork, worktree), announces it, and sends the child its brief as a prompt. | Given auto-start off, when the agent calls `start_session`, then the result holds a proposal id and no chat exists until **Start**. |
| FR-20 | At most 8 children of a chat run at once. | Given 8 running children, when a 9th is started, then it is refused. |
| FR-21 | Prompt mail waits until a window has hosted the receiving engine, then goes out as a prompt (idle) or a steer read at the session's next step (busy). A refused prompt goes out when the run ends. Accepted means delivered. The window showing the chat adds the prompted turn. | Given a busy child, when `message_session` sends to it, then the child reads it at its next step. |
| FR-22 | When the hub needs an engine that is not set up (a new session, a chat with waiting mail, an engine that exited with mail pending) it asks for a host: a window holding the chat answers, otherwise the main window starts the engine in the background. | Given mail for a closed child, when it is sent, then the child's engine is started and the mail delivered. |
| FR-23 | A window holding a chat whose engine exited or failed to start starts it again when the hub asks for a host, at most 3 times in 2 minutes per chat; after that the mail waits until the chat is opened. | Given an engine that dies on start, when the hub keeps asking, then it is restarted at most 3 times in 2 minutes. |
| FR-24 | At app start the main window hosts every chat with undelivered mail (archived chats excluded). | Given undelivered mail for a chat at quit, when the app starts, then the mail is delivered. |
| FR-25 | `list_sessions` lists the chat's children with their live state: `running`, `waiting` (for an approval) or `idle`. | Given one running and one idle child, when the agent lists sessions, then both show with their state. |
| FR-26 | The session and every subagent get `send_message`, `ask`, `reply`, `list_nodes` and `cancel_node`, bound to their own node so a call knows who calls; agent types that narrow tools keep them; the session's tools refuse calls from other children (plugin children). | Given a subagent, when it calls `send_message`, then the mail's `from` is the subagent. |
| FR-27 | A node can write to its parent, its children and — with the siblings capability, which agents get — its siblings; never to another tree. `to` takes `parent`, a node id, an agent id or a title. | Given two sibling agents, when one sends to the other by title, then the mail arrives; a node in another tree is refused. |
| FR-28 | Mail reaches the model as a `<mail id from title kind>` message, shown in the transcript as an event chip ("Message/Question from …"), not as a user bubble. A running receiver gets it before its next model call; an idle session gets it with its next run plus a wake request with reason `mail`; an idle agent gets it when continued. | Given an idle parent, when an agent sends it a message, then the parent wakes and the transcript shows a "Message from …" chip. |
| FR-29 | `ask` blocks until `reply {askId}`, the receiver's run ending (its final text answers), the timeout (default 600 s, max 1800 s) or cancellation. An `ask` to an idle agent continues it in the background to answer; that run's report goes to the asker, not to the parent. | Given a sibling ask, when the receiver replies, then the asker resumes with the answer; `reply` checks the asker. |
| FR-30 | Open `ask`s and foreground `agent` calls form a wait-for graph; an `ask` that would close a cycle is refused with `would_deadlock` and says why. | Given a foreground agent, when it asks the session waiting on it, then the ask is refused with `would_deadlock`. |
| FR-31 | At most 20 messages per directed pair of nodes between two runs of the session. | Given a pair at 20 messages, when one sends a 21st, then it is refused. |
| FR-32 | Mail (`send_message`, `ask`, `reply`) also works between nodes of different engines. | Given an agent in session A and nested session B, when the agent sends B a message, then B receives it. |
| FR-33 | A remote engine joins the mesh over TCP. | Given a remote engine, when it connects, then its nodes are listed and routable. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Session mail is delivered at least once, deduplicated by id, and survives engine and app restarts; agent mail is at most once, in memory. | Given unanswered session mail, when the app restarts, then it is sent again and taken once. |
| NFR-2 | Reach, guards, limits and approval are enforced by the hub and the engine's router, never by the model. | Review: every guard is in the hub or the router; no tool description is the only guard. |
| NFR-3 | Observation costs follow the subscriber level: `summary` events are built only while a live subscriber wants them, so a sidebar does not pay for token deltas. | Given no `summary` subscriber, when an agent works, then no activity events are emitted. |

## 5. Success criteria

- SC-1 A nested session's turn reaches its parent in the same window, from a
  separate chat window, and while the parent's engine is stopped.
- SC-2 Two background agents coordinate through a question and an answer,
  and the idle parent wakes once for the message and both reports.
- SC-3 A reopened chat or reloaded window shows a running agent's steps at
  once.
- SC-4 Nothing in the app polls for background-agent state.
- SC-5 A remote engine joins the mesh.

## 6. Clarifications

### 6.1 Open

None.

### 6.2 Resolved

- 2026-11-06 — Q: Where does the hub live — embedded in the desktop shell,
  or a separate daemon that the shell and remote clients both connect to?
  → A: embedded in the desktop shell, as a transport-agnostic crate that can
  later run standalone (now in FR-17, FR-33; plan 3.1).
- 2026-11-06 — Q: Default peer scope — parent and children only, or
  siblings too? → A: siblings for agents, not for sessions (now in FR-27).
- 2026-11-06 — Q: Does an agent's final text count as the reply to an
  `ask` it did not answer, or must it call `reply`? → A: the final text
  counts (now in FR-29).
- 2026-11-07 — Q: Should the mesh offer topics (pub/sub channels for a team of
  agents)? → A: Not yet; peer messaging ships without them; specify them
  when a team of agents needs a shared channel (section 2.2).
- 2026-11-07 — Q: May agents start agents (`maxDepth` 2), or does "no recursion"
  stay? → A: "No recursion" stays, as built; depth limits and budgets
  beyond it are not built (section 2.2).

## 7. History

- 2026-11-06 — Phases 1–4 implemented (phase 4 within one engine); phase 5
  (remote engines) proposed. Documented in the legacy single-file format.
- 2026-11-07 — Moved to the spec / plan / tasks format.
- 2026-11-07 — Open clarifications answered by the owner (accepted as proposed).
