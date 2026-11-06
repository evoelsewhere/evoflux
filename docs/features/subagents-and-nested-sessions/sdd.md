# Subagents and nested sessions

| | |
| --- | --- |
| Status | Implemented (phases 1–4) |
| Area | engine, crate `evo-worktrees`, desktop |
| Format | Legacy — predates [the SDD template](../../templates/sdd.md); move to it on the next substantial edit |
| Updated | 2026-11-06 |
| ADD sections | [6.2 Sessions talking to sessions](../../architecture/README.md#62-sessions-talking-to-sessions) |
| ADRs | [0003](../../architecture/decisions/0003-engine-runs-as-a-child-process-per-chat.md) |

Status: all four phases are built: `crates/evo-engine/src/agents.rs`
(agent types), `crates/evo-engine/src/agent_tool.rs` (the `agent` tool, tests
in `agent_tool/tests.rs`), and the desktop's `components/ai-elements/agent-run.tsx`.
Phase 2 adds `background: true`, the `message_agent` tool, the RPC commands
`get_background_agents` / `ack_background_agents` / `cancel_background_agent`,
and the desktop's polling, wake-ups and event lines (`engine-store.ts`,
`chat-turn.tsx`). Phase 3 adds migration `0004_chat_parents.sql`
(`parent_chat_id`, `origin`), the desktop-provided external tools
`start_session` / `message_session` / `list_sessions` (`engine-store.ts`),
proposal cards (`components/ai-elements/session-proposal.tsx`), notes and
wake-ups to the parent, and sidebar nesting (`sidebar-chats.tsx`). Phase 4 moves the worktree manager
into its own crate (`crates/evo-worktrees`: create, list, changes, apply,
remove; the engine and the desktop shell share it), adds migration
`0005_chat_worktrees.sql` (a chat's `worktree_path`), `start_session`'s
`worktree` option, the shell commands in `src-tauri/src/worktrees.rs`, and
the review dialog (`components/ai-elements/worktree-review.tsx`) reached from
a subagent's kept worktree, a worktree session's toolbar chip, and Settings →
Sandbox. "Apply" puts the changes in the workspace uncommitted (no merge, no
commit) and removes the worktree; it changes nothing when the patch does not
apply cleanly.

(Since session mesh phase 3, notes go through the shell's mesh hub and reach
the parent in any window, or after its engine starts, and the hub — not
`engine-store.ts` — defines and answers `start_session`, `message_session`
and `list_sessions`; see [session mesh](../session-mesh-protocol/sdd.md). The limit below is
history.) Phase 3 limits: notes reach a parent held by this window (or started here to
receive them); a parent open in a separate chat window does not get them
yet. The desktop logic is covered by typecheck and a preview with sample
data, not by automated tests (the desktop has no test runner). Paths are relative to the repository root.

Since then the session mesh ([session mesh](../session-mesh-protocol/sdd.md), phase 2) replaced the
background-agent RPC commands and the polling described here with push
events and wake requests on the session node. Phase 2 originally differed from the design in one way: the engine has no event for "a
background agent finished", so the desktop polls `get_background_agents` (once
a second, only while one runs or waits to be delivered). Phase 1 differs from
the design below in two small ways: an agent type's
instructions open the child's first message (the harness has no getter for
the parent's system prompt to extend), and the `agent` tool runs its child
directly rather than through the plugin job runner (it shares the worktree
helpers and the recursion guard; the plugin API is unchanged).

Two features that look alike but are different things:

| | Subagent | Nested session |
| --- | --- | --- |
| What it is | A child agent **inside one engine**, run as a tool call of the parent | A **full chat** (own engine process, own transcript, own sidebar row) started by another chat |
| Context | Fresh: sees only the task it was given | Fresh, or a fork of the parent's conversation |
| Who sees the work | The parent gets one final report; the user sees the child's steps nested under the tool call | The user can open it, read it, type into it, like any chat |
| Lifetime | Bounded: ends with its report (or runs in the background until then) | Open-ended: lives on after the parent's turn, can be resumed |
| Back to the parent | The tool result (foreground) or a wake-up note (background) | A note each time the child finishes a turn; the parent may be woken |
| Cost of a mistake | A few model turns | A whole extra session that keeps running |

---

## 1. How Claude does it (the reference)

### 1.1 Subagents (Claude Code's `Agent` tool)

- **The tool.** The model calls `Agent` with a short `description` (3–5 words,
  shown in the UI), a `prompt` (the whole brief: the child knows nothing
  else), an optional `subagent_type`, and options: `model`, `isolation:
  "worktree"`, `run_in_background`.
- **Agent types** are Markdown files with YAML frontmatter:
  `.claude/agents/*.md` (project) and `~/.claude/agents/*.md` (user). The
  frontmatter gives `name`, `description` (when to use it — the parent model
  reads this list), `tools` (an allow-list) and `model`; the body is the
  child's system prompt. Built-in types exist (a general-purpose one, a
  read-only explorer, a planner).
- **Fresh context, one report.** The child starts with only its brief. Its
  intermediate tool calls never enter the parent's context; the parent gets
  the final message. This is the main point of subagents: wide searches and
  file dumps stay out of the parent's context window.
- **Parallel.** Several `Agent` calls in one assistant message run at once.
- **Background.** With `run_in_background` the tool returns at once; when the
  child finishes, a notification is injected into the parent as a new turn
  (the parent is woken if idle). The parent can send the finished child more
  messages and it resumes with its own context.
- **Worktree isolation.** The child works in a temporary Git worktree; an
  unchanged one is cleaned up, a changed one's path and branch come back.
- **No recursion** by default: a subagent cannot start subagents.
- **UI.** The tool call shows the agent's description, a live list of its
  tool calls, counts (tool uses, tokens) and elapsed time, then the report.

### 1.2 Nested sessions (Claude desktop's Code tab)

- **The tool.** The model calls `start_session` with a `title`, a brief, a
  `context` (`fresh`, or `fork` = a copy of this conversation), whether to use
  its own worktree, and optionally a model/effort. The result is a separate,
  full session the user can open, steer and stop.
- **Who decides.** An `initiation` field separates "the user asked for this"
  (starts now) from "the agent proposes it" (a card the user must click; it
  expires after a week). Agents cannot silently fan out sessions.
- **Sidebar.** Children are listed under their parent with a vertical guide
  line, each with a status dot (running, needs attention, unread). Long lists
  fold into a footer: "26 more nested sessions · 22 unread".
- **Back to the parent.** When a child ends a turn, the parent receives a
  note quoting the start of the child's latest report. If the parent is idle
  it is woken with an automated turn (marked as such, never mistaken for the
  user). After many automated wake-ups in a row without the user, notes wait
  for the user's next turn.
- **Talking to a child.** The parent sends follow-ups to the child session by
  id instead of starting a new one; it can list its linked sessions and their
  states.
- **Merging.** A child in its own worktree commits on its own branch; the
  parent merges only when the user says so.

---

## 2. What evo has today

### Engine

- **Child agents exist, but only plugins can start them.**
  `crates/evo-engine/src/child_agents.rs` runs plugin-owned children through
  the host action `child_agent` (`start | poll | cancel | dispose`), used by
  the optional `evo-subagents` plugin's `delegate_task` tool
  (`crates/evo-engine/embedded-docs/user-guide.md:410-431`). Limits: 16 jobs,
  `maxTurns` 1–32, `timeoutSeconds` 10–1800, task ≤ 20 KB.
- **Child construction** is `AgentHarness::create_child_with_tools`
  (`crates/evo-harness/src/agent_harness/child.rs`): a snapshot of the parent's
  model, prompt, resources, hooks and tools (narrow-only), its own in-memory
  session, recursion refused, `delegate_task` filtered out.
- **Worktree isolation** (added this week): `"isolation": "worktree"` on
  `start`, `crates/evo-engine/src/worktrees.rs`, location from Settings →
  Sandbox. Unchanged worktrees are removed, changed ones kept and reported.
- **Gaps:**
  - No built-in tool can reach the harness. Tools are built before the
    harness exists; the late-bound handle to copy is `harness_cell`
    (`crates/evo-engine/src/session.rs:421`, filled at `:1385`).
  - **Child events reach nobody.** The child's emitter keeps only text deltas
    for plugin polling (`child_agents.rs` `Job::observe`); the RPC stream has
    no child events and no `parentToolCallId`.
  - **A child dies with the run that started it** (`scope =
    active_run.children.child_token()`, `agent_harness.rs:3860`). Only side
    questions use the session-lifetime scope (`child.rs:216-221`) — the one a
    background subagent needs.
  - **Nothing wakes an idle parent.** `queue_message {deliverAs:
    steer|followUp|nextTurn}` queues; an idle harness keeps it for the next
    explicit run (`modes.rs:2121-2147`). `send_message(trigger_turn)` would
    run, but outside RPC's run slot, so no `agent_settled` reaches the UI.
  - **Child usage is not counted** (`run_outcome_json` has no usage).
  - **No agent definitions**: no `.evo/agents`, only a free-text `role`.
    Skills show the loader to mirror (`crates/evo-harness/src/skills.rs`,
    frontmatter in `frontmatter.rs`, `pub(crate)` today; resource dirs in
    `crates/evo-engine/src/resource_dirs.rs`).
- **Useful, unused today:** RPC already has an engine → client request/reply
  channel, **external tools**: the client registers tools with
  `configure_external_tools`; when the model calls one the engine emits
  `external_tool_request` and waits (≤ 60 s) for `external_tool_response`
  (`crates/evo-engine/src/rpc/external_tools.rs`, `client_requests.rs`). The
  desktop does not use it yet. It is exactly the shape of "start a session
  and return its id".

### Desktop

- **Transcript** (`apps/desktop/src/features/chat/transcript.ts`): turns of
  text, reasoning and tool parts; `tool_execution_update` replaces a tool
  part's `output` and `details` with each update (snapshots, not deltas).
  Rendering: `chat-turn.tsx` (`ProcessRows`, `ProcessGroup`),
  `components/ui/trace.tsx` (already draws an indented guide line inside
  `TraceCollapsibleContent`), `components/ai-elements/tool.tsx` (kind per tool
  name, body per kind).
- **Chats**: `chats` table (`crates/evo-store/src/migrations/0003…sql`) has
  no parent column; the transcript `sessions` table has `parent_session_id`
  (used by Fork). Migrations are numbered, checksummed, append-only
  (`crates/evo-store/src/lib.rs`).
- **Sidebar**: flat lists per workspace (`app-sidebar.tsx`,
  `sidebar-chats.tsx`); `SidebarMenuSub` (`components/ui/sidebar.tsx:639`)
  already provides the shadcn nested list with a guide line, unused.
- **Lifecycle**: one engine per chat; `launch()` can start a runtime without
  showing it, busy runtimes are never trimmed (`trimIdle`), other windows see
  `busyElsewhere`. There is no API to create and run a chat programmatically;
  `newChat`/`sendPrompt` assume the active chat.
- **Engine → UI requests**: only `ui_dialog_request` (approvals) is answered.

---

## 3. Design: subagents

### 3.1 Agent definitions

Markdown with YAML frontmatter, same rules and loader shape as skills:

- Project `.evo/agents/<name>.md`, user `~/.evo/agent/agents/<name>.md`,
  project first; settings key `agentDirs` like `skills`.
- Frontmatter: `name` (lowercase, hyphens), `description` (required; the
  parent reads it to choose), `tools` (allow-list, optional = parent's tools),
  `model` (`inherit` or a model id, resolved like `set_model`), `thinking`
  (`inherit` or a level, clamped to what the model supports; ignored for a
  model without reasoning), `maxTurns` (1–100, default 32), `access`
  (`read-only` or `full`, default `full`), `isolation` (`worktree` default for
  this type, optional).
- Body: put in front of the task in the child's first message.
- **`access: read-only` is enforced** (`crates/evo-engine/src/read_only.rs`):
  every tool call of the child goes through a `ChildToolGuard` (evo-harness)
  before it reaches an approval prompt, and again right before it runs (hooks
  may rewrite arguments). It passes reading tools and the mesh tools, refuses
  `write`/`edit` and any tool it does not know (connector tools included), and
  splits `bash`/`powershell` commands into simple commands that must each be on
  a read-only allow-list (`rg`, `git log/show/diff/status/blame`,
  `Get-ChildItem`, …) without their writing options (`find -delete`,
  `rg --pre`, `git -c`, `--output`, …). Redirection to a file, here-documents,
  command substitution in double quotes, PowerShell method calls, static .NET
  calls, property assignment and `&` are refused. Unknown commands are
  refused; the refusal tells the model to retry with a plainer command.
- Built-in types, each with a prompt that sets how to work and a fixed report
  format (the parent sees only the report):

  | Type | Tools | Access | Thinking | Turns | Report |
  |---|---|---|---|---|---|
  | `general` | parent's | full | inherit | 80 | Done / Changes / Checks / Not done |
  | `explore` | `read`, `bash`, `powershell` | read-only | low | 40 | Answer / Evidence (`path:line`) / Not found |
  | `plan` | `read`, `bash`, `powershell` | read-only | high | 40 | Goal / Approach / Changes / Steps / Risks / Verification / Open questions |

- A report longer than 16 KiB is cut; the cut says to ask the agent for the
  rest with `message_agent`.
- Loader beside `load_skills`; make `frontmatter::parse_frontmatter` public.
  The tool's description lists the available types with their descriptions.

### 3.2 The built-in `agent` tool

```jsonc
{
  "description": "Find auth call sites",   // 3–5 words, shown in the UI
  "prompt": "…the whole brief…",
  "agentType": "explore",                 // optional, default "general"
  "model": "…",                           // optional override
  "isolation": "worktree",                // optional
  "background": false                     // optional
}
```

- **Built in `build_tools`** with a clone of `harness_cell` (a
  `WeakAgentHarness`), like `HarnessActionHost` holds it; also on `/reload`.
- **One runner for plugins and the tool**: factor `run_child` and the job
  bookkeeping out of `child_agents.rs` so `delegate_task` (plugin) and `agent`
  (built-in) share limits, cancellation, worktrees and usage roll-up. Keep the
  plugin action API unchanged.
- **Per-type setup** after `create_child_with_tools`: narrow tools,
  `set_system_prompt` (parent prompt + agent body), `set_model`.
- **Foreground**: the tool awaits the child and returns its final text as the
  tool result. Parallel calls in one assistant message run concurrently
  already (the loop executes tool batches in parallel).
- **Progress**: the child's emitter turns child `AgentEvent`s into a compact,
  **cumulative** snapshot and calls the tool's `on_update` (throttled, ~4/s):

  ```jsonc
  "details": { "child": {
    "agentType": "explore", "description": "…", "status": "running",
    "turns": 3, "toolUses": 7, "usage": { "input": 0, "output": 0, "cost": 0 },
    "startedAt": 0,
    "tools": [ { "callId": "…", "name": "bash", "subject": "rg auth", "phase": "done" } ],
    "text": "…tail of the child's latest text…",
    "worktree": { "path": "…", "branch": "…", "kept": true }
  } }
  ```

  The last ~50 tool rows and ~4 KB of text, so updates stay small. No new RPC
  event is needed: `tool_execution_update` already carries `details`, and the
  desktop already replaces `details` per update. Because `details` is saved
  with the tool result, a reopened chat shows the finished child too.
- **Usage**: the child's total goes into `AgentToolResult.usage` (persisted on
  the tool result); the desktop adds tool-result usage to the turn's cost.
- **Limits**: recursion refused (already); at most 4 concurrent foreground
  children per run and 16 jobs per session (shared with plugins); `maxTurns`
  default 24; the Sandbox policy (environment, timeouts, denied patterns)
  applies to children automatically because it is process-wide.

### 3.3 Background subagents

- **Lifetime**: start the child on the session-lifetime scope (as
  `create_side_question` does), so it survives the end of the parent's run;
  cancelled on session close or switch.
- **Return value**: `{ "agentId": "…", "status": "running" }` immediately.
- **Waking the parent** when it finishes:
  - parent run active → `lane.follow_up(<agent-result>)`, picked up in the
    same run;
  - parent idle → the engine emits a new RPC event `agent_task_settled
    {agentId, description, status, report}`; the desktop decides to wake and
    sends a normal `prompt` with an automated-event message. This keeps RPC's
    single run slot and `agent_settled` intact (an engine-side
    `send_message(trigger_turn)` would bypass both).
- **Follow-ups**: keep a finished child's harness (in-memory session) for a
  while, keyed by `agentId`; a `message_agent {agentId, message}` tool resumes
  it with its own context. Evicted on session close or after N idle minutes.
- **UI**: a "Background agents" chip above the composer listing running ones;
  the wake-up turn renders as an event chip, not a user bubble.

### 3.4 Desktop rendering

- New tool kind `agent` in `tool.tsx` (`kinds`), label "Agent · {description}"
  with the shimmer while running; skip the "running without output" early
  return so the body shows from the first update.
- Body: a nested `<Trace>` of the child's tool rows, reusing the `Tool` row
  component (export `ProcessRows` from `chat-turn.tsx`), the latest text
  line, and a footer "7 tool uses · 12.3k tokens · 34s". When done: the
  report (Markdown), collapsed by default for long ones.
- Worktree kept → a badge with the branch and actions "Open in…" (existing
  Open in apps), "Show changes" (a diff panel), "Discard" (remove worktree).

---

## 4. Design: nested sessions

### 4.1 Data

Migration `0004_chat_parents.sql`:

```sql
ALTER TABLE chats ADD COLUMN parent_chat_id TEXT
    REFERENCES chats (id) ON DELETE SET NULL;
ALTER TABLE chats ADD COLUMN origin TEXT NOT NULL DEFAULT 'user'
    CHECK (origin IN ('user', 'agent'));
CREATE INDEX chats_by_parent ON chats (parent_chat_id, updated_at DESC);
```

- `Chat`, `NewChat`, `CHAT_COLUMNS`, `chat_row`, `create_chat` gain the fields;
  `DbChat`/`SessionSummary` in the UI too.
- Deleting a parent keeps its children (they move to the top level);
  archiving a parent archives nothing else.
- Transcript lineage (`sessions.parent_session_id`) is set too when the child
  is a fork of the parent's conversation (`context: "fork"`, via `fork_chat`).

### 4.2 Tools for the parent: desktop-provided external tools

The desktop registers three tools on each engine right after `ready`
(`configure_external_tools`), answers `external_tool_request` in
`engine-store.ts` `onMessage`, and replies with `external_tool_response`. No
engine change is needed for the mechanism.

| Tool | Does |
| --- | --- |
| `start_session {title, prompt, context: fresh\|fork, workspace?, worktree?, model?}` | Creates the child chat (parent link, workspace = parent's unless given), starts its engine in the background, sends the prompt, returns `{sessionId, title, status}` |
| `message_session {sessionId, message}` | Sends a follow-up to a child (queued if it is running) |
| `list_sessions {}` | The parent's children: id, title, status, unread, last report excerpt |

- **Approval.** By default `start_session` does not start anything: it returns
  `{status: "proposed", proposalId}` and the tool row renders a card "Start
  session: {title}" with Start / Dismiss. Settings → Sandbox gets "Let agents
  start sessions without asking" (off by default). This mirrors Claude's
  offer/own-initiative cards and keeps the 60 s request timeout irrelevant.
- **Depth.** Child sessions do not get `start_session` (one level), at most
  8 running children per parent; both configurable later.
- **Worktree.** `worktree: true` creates the child's worktree before its
  engine starts and uses it as the child's working folder. The desktop shell
  needs the worktree manager: move `worktrees.rs` into `evo-tools`
  (`evo_tools::worktrees`) and link `evo-tools` from the shell (no webview
  dependencies), or run it through an engine subcommand.

### 4.3 Running a chat in the background

New engine-store action (beside `newChat`/`forkChat`):

```ts
startChildChat(parentId, { title, prompt, workspaceId, cwd, origin: "agent" })
```

1. `db.createChat({ id, parentChatId, workspaceId, title, origin })`, apply it
   to the session store (and to other windows via `chat://updated`);
2. `launch(id, cwd, false)` without activating it;
3. on `ready`, `dispatch(id, {type: "prompt", text})` and
   `client.request(id, "prompt", {message})` — the per-chat variant of
   `sendPrompt`, which today assumes the active chat;
4. the runtime stays alive while busy (`trimIdle` already skips busy ones);
   idle children are trimmed like any chat and reopen from the database.

### 4.4 Telling the parent

In `recordFinishedTurn` (the turn-end hook), when the chat has a parent:

- Build a note: `{sessionId, title, status, report: first 400 chars}`.
- Parent busy → `queue_message {deliverAs: "followUp"}` to the parent.
- Parent idle → after a 2 s coalescing window, one automated `prompt` to the
  parent containing all pending notes, tagged so the transcript shows it as a
  "Nested sessions update" event chip.
- Guard rails: no automated wake while the user is typing in that chat; at
  most 5 automated wakes in a row without a user message, then notes wait for
  the user's next prompt; never wake an archived parent.
- Multi-window: the window holding the child runtime emits
  `nested://settled {parentId, note}`; the window holding the parent's
  runtime (or the main window, which attaches it) delivers it.

### 4.5 Sidebar

- Children are left out of the top-level lists (`app-sidebar.tsx`) and drawn
  under their parent's row in a `SidebarMenuSub` (the guide line).
- Show up to 3 children: running and unread first, then most recent. A
  footer row "26 more nested sessions · 22 unread" expands the rest.
- Child rows reuse `ChatItem`: title (shimmering while running), status dot
  (amber = waiting for approval, blue = unread, red = stopped).
- A collapsed parent shows a roll-up: spinner if any child runs, otherwise a
  dot if any child is unread.
- Chat header of a child: "Parent title › Child title", clicking the parent
  opens it. Chat menu: "Open parent", "Detach from parent".

---

## 5. Build plan

| Phase | Scope | Main files | Done when |
| --- | --- | --- | --- |
| 1. Foreground subagents | Agent definitions + loader; built-in `agent` tool sharing the child runner; streamed `details.child`; usage roll-up; desktop `agent` tool body | `evo-harness` skills/frontmatter, `evo-engine` `child_agents.rs`, new `agents.rs`, `session.rs`; desktop `tool.tsx`, `chat-turn.tsx`, `transcript.ts` | A model call runs an `explore` child, the UI shows its steps live and its report, cost includes the child, tests with the faux provider |
| 2. Background subagents | Session-lifetime children; `agent_task_settled` event; desktop wake; `message_agent`; background chip | `child_agents.rs`, `modes.rs`, `rpc/protocol.rs`; desktop `engine-store.ts` | A background child finishes while the parent is idle and the parent continues with its report |
| 3. Nested sessions | Migration 0004; `startChildChat`; external tools `start_session` / `message_session` / `list_sessions` with proposal cards; parent notes and wakes; sidebar nesting | `evo-store` chats + migration; desktop `engine-store.ts`, `session-store.ts`, `sidebar-chats.tsx`, `app-sidebar.tsx`, new proposal card | A chat proposes a session, the user starts it, it appears nested, and its finished turn reaches the parent |
| 4. Worktree review | Shared worktree manager for the shell; child sessions in worktrees; diff / discard / merge actions for kept worktrees (agents and sessions) | `evo-tools` (moved `worktrees.rs`), desktop shell commands, a diff panel | A kept worktree can be reviewed and merged or discarded from the UI |

Phases 1 and 3 are independent and can be built in parallel; 2 builds on 1,
4 on 1 and 3.

## 6. Decisions to make

1. **Tool name**: the built-in `agent` and the plugin's `delegate_task` would
   both exist. Keep both (plugins can wrap the runner), or have the built-in
   replace the plugin?
2. **Starting sessions**: proposals the user must click by default (as
   designed), or start immediately?
3. **Depth**: may a child session start its own sessions? (Designed: no.)
4. **Automated wakes**: wake an idle parent at all, or only queue notes until
   the user's next message?
5. **Built-in agent types**: is `general` / `explore` / `plan` the right first
   set?
