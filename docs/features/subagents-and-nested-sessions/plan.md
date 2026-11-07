# Subagents and nested sessions — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [6.2 Sessions talking to sessions](../../architecture/README.md#62-sessions-talking-to-sessions) |
| ADRs | [0003 Engine runs as a child process per chat](../../architecture/decisions/0003-engine-runs-as-a-child-process-per-chat.md) |

## 1. Context and constraints

Paths are relative to the repository root. This section records what existed
when the design was written and the reference behaviour it follows; section
3 is the design as built, section 5 where the build differs.

### 1.1 Reference behaviour

**Subagents** in a reference coding agent:

- **The tool.** The model calls an `Agent` tool with a short `description`
  (3–5 words, shown in the UI), a `prompt` (the whole brief: the child knows
  nothing else), an optional agent type, and options: `model`, worktree
  isolation, run in the background.
- **Agent types** are Markdown files with YAML frontmatter in a project
  folder and a user folder. The frontmatter gives `name`, `description` (when
  to use it — the parent model reads this list), `tools` (an allow-list) and
  `model`; the body is the child's system prompt. Built-in types exist (a
  general-purpose one, a read-only explorer, a planner).
- **Fresh context, one report.** The child starts with only its brief. Its
  intermediate tool calls never enter the parent's context; the parent gets
  the final message. This is the main point of subagents: wide searches and
  file dumps stay out of the parent's context window.
- **Parallel.** Several calls in one assistant message run at once.
- **Background.** The tool returns at once; when the child finishes, a
  notification is injected into the parent as a new turn (the parent is woken
  if idle). The parent can send the finished child more messages and it
  resumes with its own context.
- **Worktree isolation.** The child works in a temporary Git worktree; an
  unchanged one is cleaned up, a changed one's path and branch come back.
- **No recursion** by default: a subagent cannot start subagents.
- **UI.** The tool call shows the agent's description, a live list of its
  tool calls, counts (tool uses, tokens) and elapsed time, then the report.

**Nested sessions** in a reference desktop agent app:

- **The tool.** The model calls `start_session` with a `title`, a brief, a
  `context` (`fresh`, or `fork` = a copy of this conversation), whether to use
  its own worktree, and optionally a model/effort. The result is a separate,
  full session the person can open, steer and stop.
- **Who decides.** An `initiation` field separates "the person asked for
  this" (starts now) from "the agent proposes it" (a card the person must
  click; it expires after a week). Agents cannot silently fan out sessions.
- **Sidebar.** Children are listed under their parent with a vertical guide
  line, each with a status dot (running, needs attention, unread). Long lists
  fold into a footer: "26 more nested sessions · 22 unread".
- **Back to the parent.** When a child ends a turn, the parent receives a
  note quoting the start of the child's latest report. If the parent is idle
  it is woken with an automated turn (marked as such, never mistaken for the
  person). After many automated wake-ups in a row without the person, notes
  wait for the person's next turn.
- **Talking to a child.** The parent sends follow-ups to the child session by
  id instead of starting a new one; it can list its linked sessions and their
  states.
- **Merging.** A child in its own worktree commits on its own branch; the
  parent merges only when the person says so.

### 1.2 What evo had before (engine)

- **Child agents existed, but only plugins could start them.**
  `crates/evo-engine/src/child_agents.rs` runs plugin-owned children through
  the host action `child_agent` (`start | poll | cancel | dispose`), used by
  the optional `evo-subagents` plugin's `delegate_task` tool
  (`crates/evo-engine/embedded-docs/user-guide.md:410-431`). Limits: 16 jobs,
  `maxTurns` 1–32, `timeoutSeconds` 10–1800, task ≤ 20 KB.
- **Child construction** is `AgentHarness::create_child_with_tools`
  (`crates/evo-harness/src/agent_harness/child.rs`): a snapshot of the
  parent's model, prompt, resources, hooks and tools (narrow-only), its own
  in-memory session, recursion refused, `delegate_task` filtered out.
- **Worktree isolation** (then new): `"isolation": "worktree"` on `start`,
  `crates/evo-engine/src/worktrees.rs`, location from **Settings → Sandbox**.
  Unchanged worktrees are removed, changed ones kept and reported.
- **Gaps at the time:**
  - No built-in tool could reach the harness. Tools are built before the
    harness exists; the late-bound handle to copy is `harness_cell`
    (`crates/evo-engine/src/session.rs:421`, filled at `:1385`).
  - **Child events reached nobody.** The child's emitter kept only text
    deltas for plugin polling (`child_agents.rs` `Job::observe`); the RPC
    stream had no child events and no `parentToolCallId`.
  - **A child died with the run that started it** (`scope =
    active_run.children.child_token()`, `agent_harness.rs:3860`). Only side
    questions used the session-lifetime scope (`child.rs:216-221`) — the one
    a background subagent needs.
  - **Nothing woke an idle parent.** `queue_message {deliverAs:
    steer|followUp|nextTurn}` queues; an idle harness keeps it for the next
    explicit run (`modes.rs:2121-2147`). `send_message(trigger_turn)` would
    run, but outside RPC's run slot, so no `agent_settled` reaches the UI.
  - **Child usage was not counted** (`run_outcome_json` had no usage).
  - **No agent definitions**: no `.evo/agents`, only a free-text `role`.
    Skills show the loader to mirror (`crates/evo-harness/src/skills.rs`,
    frontmatter in `crates/evo-harness/src/frontmatter.rs`, then
    `pub(crate)`; resource dirs in `crates/evo-engine/src/resource_dirs.rs`).
- **Useful, then unused:** RPC already had an engine → client request/reply
  channel, **external tools**: the client registers tools with
  `configure_external_tools`; when the model calls one the engine emits
  `external_tool_request` and waits (≤ 60 s) for `external_tool_response`
  (`crates/evo-engine/src/rpc/external_tools.rs`, `client_requests.rs`). The
  desktop did not use it yet. It is exactly the shape of "start a session and
  return its id".

### 1.3 What evo had before (desktop)

- **Transcript** (`apps/desktop/src/features/chat/transcript.ts`): turns of
  text, reasoning and tool parts; `tool_execution_update` replaces a tool
  part's `output` and `details` with each update (snapshots, not deltas).
  Rendering: `apps/desktop/src/features/chat/chat-turn.tsx` (`ProcessRows`,
  `ProcessGroup`), `apps/desktop/src/components/ui/trace.tsx` (already draws
  an indented guide line inside `TraceCollapsibleContent`),
  `apps/desktop/src/components/ai-elements/tool.tsx` (kind per tool name,
  body per kind).
- **Chats**: the `chats` table
  (`crates/evo-store/src/migrations/0003_chats_sessions_logs.sql`) had no
  parent column; the transcript `sessions` table has `parent_session_id`
  (used by Fork). Migrations are numbered, checksummed, append-only
  (`crates/evo-store/src/lib.rs`).
- **Sidebar**: flat lists per workspace
  (`apps/desktop/src/features/shell/app-sidebar.tsx`,
  `apps/desktop/src/features/shell/sidebar-chats.tsx`); `SidebarMenuSub`
  (`apps/desktop/src/components/ui/sidebar.tsx:639`) already provides the
  shadcn nested list with a guide line, unused.
- **Lifecycle**: one engine per chat; `launch()` can start a runtime without
  showing it, busy runtimes are never trimmed (`trimIdle`), other windows see
  `busyElsewhere`. There was no API to create and run a chat
  programmatically; `newChat`/`sendPrompt` assume the active chat.
- **Engine → UI requests**: only `ui_dialog_request` (approvals) was
  answered.

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | Subagents, agent types, the read-only guard and background delivery run in the engine. The session tools are answered by the shell's mesh hub (routing, not agent decisions); the worktree manager is a shared crate. |
| Layers point down; library crates stay free of engine/desktop concerns | ok | `evo-worktrees` knows only Git; `evo-harness` exposes child construction and the tool guard hook, not engine policy. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | ok | Progress rides on the existing `tool_execution_update.details`; `ready.lostBackgroundAgents` and the mesh events changed engine and desktop together. |
| Models come from models.dev; no hardcoded model facts | ok | An agent type's `model` is resolved like `set_model`; `thinking` is clamped to what the model supports. |
| Real engine in the app; settings and credentials reload live | ok | Agent files are read when used (NFR-3); **Start sessions without asking** is pushed to the hub live. |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | Children go through the same approval prompts and the process-wide Sandbox policy; read-only access is enforced before the prompt; sessions start only on the person's click by default. |
| Desktop UI structure and `DESIGN.md` | ok | New components under `components/ai-elements/`; state through `engine-store.ts` and `session-store.ts`; nested lists reuse shadcn `SidebarMenuSub`. |

## 3. Design

### 3.1 Overview

```text
 parent engine (one chat)                              desktop
 ┌─────────────────────────────────────┐   tool_execution_update   ┌──────────────────────┐
 │ agent loop ── agent tool ──► child  │ ── details.child ───────► │ agent-run.tsx        │
 │   ▲            │  (own context,     │                           │ (live steps, report) │
 │   │ report     │   read-only guard, │                           └──────────────────────┘
 │   └────────────┘   optional worktree)│
 │ message_agent ─► kept child          │
 └───────────────┬─────────────────────┘
                 │ start_session / message_session / list_sessions
                 ▼
        shell mesh hub ──► child chat (own engine, own transcript, nested in sidebar)
                 ▲                │
                 └── note on each finished turn (follow-up or automated wake)
```

A subagent is a child harness inside the parent's engine, run by the `agent`
tool; its progress travels as the tool's `details` and its report as the
tool result. A nested session is a normal chat with a parent link, started
through tools the shell's mesh hub answers; its finished turns come back to
the parent as notes.

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| engine | `crates/evo-engine/src/agents.rs` | Agent type loader (project, user, built-in), built-in prompts and report formats | FR-1, FR-2, NFR-3 |
| engine | `crates/evo-engine/src/read_only.rs` | Read-only guard: tool and shell-command allow-lists | FR-3 |
| crate | `crates/evo-harness/src/agent_harness/child.rs`, `crates/evo-harness/src/frontmatter.rs` | Child harness construction, tool guard hook (`ChildToolGuard`), frontmatter parser | FR-1, FR-3, FR-7 |
| engine | `crates/evo-engine/src/agent_tool.rs` | The `agent` and `message_agent` tools: runner, progress snapshots, usage, limits, background registry, steering release, lost-agent reports | FR-4–FR-13, NFR-1 |
| engine | `crates/evo-engine/src/child_agents.rs` | Plugin child agents (`child_agent` host action), shared limits | FR-7, NFR-2 |
| engine | `crates/evo-engine/src/session.rs` | Builds the tools with the late-bound harness handle (also on `/reload`) | FR-4 |
| crate | `crates/evo-worktrees/src/lib.rs` | Managed worktrees: create, list, changes, apply, remove; shared by engine and shell | FR-13, FR-21, FR-22, NFR-4 |
| engine | `crates/evo-engine/src/worktrees.rs` | Engine side of worktree isolation for children | FR-13 |
| crate | `crates/evo-store/src/chats.rs`, `crates/evo-store/src/migrations/0004_chat_parents.sql`, `0005_chat_worktrees.sql` | Parent link, origin, worktree path | FR-14, FR-21 |
| desktop shell | `apps/desktop/src-tauri/src/mesh.rs` | Mesh hub: defines and answers `start_session`, `message_session`, `list_sessions`; delivers notes and wakes | FR-15–FR-19 |
| desktop shell | `apps/desktop/src-tauri/src/worktrees.rs` | Worktree commands for the review dialog | FR-21, FR-22 |
| desktop UI | `apps/desktop/src/components/ai-elements/agent-run.tsx`, `tool.tsx` | `agent` tool kind: nested steps, footer, report, worktree badge | FR-5, FR-13 |
| desktop UI | `apps/desktop/src/features/chat/chat-turn.tsx`, `transcript.ts` | Event lines and chips, settling background calls after an engine start | FR-9, FR-12, FR-19 |
| desktop UI | `apps/desktop/src/components/ai-elements/session-proposal.tsx` | Proposal card **Start session** with Start / Dismiss | FR-16 |
| desktop UI | `apps/desktop/src/components/ai-elements/worktree-review.tsx` | Review dialog: changes, Apply, Discard | FR-22 |
| desktop UI | `apps/desktop/src/stores/engine-store.ts`, `session-store.ts` | Starting child chats in the background, mesh settings, child chat state | FR-15, FR-16, FR-19 |
| desktop UI | `apps/desktop/src/features/shell/sidebar-chats.tsx`, `app-sidebar.tsx` | Nested sidebar rows, footer, roll-up | FR-20 |
| desktop UI | `apps/desktop/src/features/settings/sections/sandbox-settings.tsx` | **Start sessions without asking**, worktree list | FR-16, FR-22 |

### 3.3 Interfaces

**Agent type file** (`<cwd>/.evo/agents/<name>.md`, `~/.evo/agent/agents/<name>.md`):

```markdown
---
name: reviewer
description: Reviews a change for bugs. Use after editing several files.
tools: [read, bash]        # optional allow-list; default: the parent's tools
model: <model id>          # optional; `inherit` (default) keeps the parent's
isolation: worktree        # optional; run in its own Git worktree by default
access: read-only          # optional; refuse writes and state-changing commands
thinking: high             # optional; `inherit` (default) keeps the parent's
maxTurns: 40               # optional; model turns per run (1-100, default 32)
---
You review code changes. Report bugs with file:line and a fix …
```

`name` is lowercase with hyphens. `model` is resolved like `set_model`;
`thinking` is clamped to what the model supports and ignored for a model
without reasoning. The `agent` tool's description lists the available types
with their descriptions.

Built-in types:

| Type | Tools | Access | Thinking | Turns | Report |
|---|---|---|---|---|---|
| `general` | parent's | full | inherit | 80 | Done / Changes / Checks / Not done |
| `explore` | `read`, `bash`, `powershell` | read-only | low | 40 | Answer / Evidence (`path:line`) / Not found |
| `plan` | `read`, `bash`, `powershell` | read-only | high | 40 | Goal / Approach / Changes / Steps / Risks / Verification / Open questions |

**`agent` tool** (model-facing):

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

Background result: `{ "agentId": "…", "status": "running" }`, returned at
once.

**`message_agent` tool**: `{ agentId, message }` — resumes a kept child with
its own context.

**Progress** — the tool's `details`, a cumulative snapshot sent through the
existing `tool_execution_update` and saved with the tool result:

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

No new RPC event is needed for progress; the desktop already replaces
`details` per update, and because `details` is saved with the tool result a
reopened chat shows the finished child too.

**Usage**: the child's total goes into `AgentToolResult.usage` (persisted on
the tool result); the desktop adds tool-result usage to the turn's cost.

**Background report note**: a message tagged `<background-agent id=…>`
carrying the agent's report. On engine start, `ready` lists
`lostBackgroundAgents`.

**Background-agent RPC (superseded)**: phase 2 added the RPC commands
`get_background_agents`, `ack_background_agents` and
`cancel_background_agent`; the session mesh (phase 2) replaced them and the
desktop's polling with push events and wake requests on the session node.
The design had proposed an RPC event `agent_task_settled {agentId,
description, status, report}` instead; it was not built (section 5).

**Session tools** (model-facing; defined and answered by the shell's mesh
hub since session mesh phase 3, originally desktop-provided external tools
registered with `configure_external_tools` right after `ready` and answered
in `engine-store.ts` `onMessage` with `external_tool_response`):

| Tool | Does |
| --- | --- |
| `start_session {title, prompt, context: fresh\|fork, workspace?, worktree?, model?}` | Creates the child chat (parent link, workspace = parent's unless given), starts its engine in the background, sends the prompt, returns `{sessionId, title, status}` — or `{status: "proposed", proposalId}` when the person must click |
| `message_session {sessionId, message}` | Sends a message to a child: a running child reads it at its next step (steering), an idle one starts a turn |
| `list_sessions {}` | The parent's children: id, title, status, unread, last report excerpt |

**Starting a child chat** (engine-store action beside `newChat` /
`forkChat`):

```ts
startChildChat(parentId, { title, prompt, workspaceId, cwd, origin: "agent" })
```

**Note to the parent**: `{sessionId, title, status, report}` (report = first
400 characters). Multi-window delivery was first designed as a Tauri event
`nested://settled {parentId, note}` from the window holding the child
runtime to the window holding the parent's runtime (or the main window,
which attaches it); the mesh hub now delivers notes.

**Mesh settings**: `mesh_configure { autoStartSessions }` (Tauri command)
pushes the **Start sessions without asking** switch to the hub.

### 3.4 Data and storage

Migration `crates/evo-store/src/migrations/0004_chat_parents.sql`:

```sql
ALTER TABLE chats ADD COLUMN parent_chat_id TEXT
    REFERENCES chats (id) ON DELETE SET NULL;
ALTER TABLE chats ADD COLUMN origin TEXT NOT NULL DEFAULT 'user'
    CHECK (origin IN ('user', 'agent'));
CREATE INDEX chats_by_parent ON chats (parent_chat_id, updated_at DESC);
```

- `Chat`, `NewChat`, `CHAT_COLUMNS`, `chat_row`, `create_chat` gain the
  fields; `DbChat` / `SessionSummary` in the UI too.
- `ON DELETE SET NULL` moves children to the top level when a parent is
  deleted; archiving a parent archives nothing else.
- Transcript lineage (`sessions.parent_session_id`) is set too when the child
  is a fork of the parent's conversation (`context: "fork"`, via
  `fork_chat`).

Migration `crates/evo-store/src/migrations/0005_chat_worktrees.sql` adds a
chat's `worktree_path`.

In memory: running and finished children live in the engine's background
registry, keyed by `agentId`, at most 16 per session; a finished child's
harness (in-memory session) is kept for follow-ups and evicted on session
close or after a number of idle minutes. Background children die with their
engine process.

### 3.5 Behaviour

**Agent types.** The loader sits beside `load_skills` and uses the public
`frontmatter::parse_frontmatter`. Project types win over user types of the
same name; both win over the built-ins. Files are read when the tool runs, so
a file added later is usable at once.

**Building the tool.** The `agent` tool is built in `build_tools` with a
clone of `harness_cell` (a `WeakAgentHarness`), the way `HarnessActionHost`
holds it; it is rebuilt on `/reload`.

**Per-type setup** after `create_child_with_tools`: narrow the tools, apply
the type's instructions (designed as `set_system_prompt` with the parent
prompt plus the agent body; built as the opening of the child's first
message, section 5), `set_model` and the thinking level.

**Foreground.** The tool awaits the child and returns its final text as the
tool result. Parallel calls in one assistant message run concurrently (the
loop executes tool batches in parallel). A report over 16 KiB is cut with a
pointer to `message_agent`.

**Steering releases a foreground wait.** The parent reads steering only
between steps, so a message sent while it waits on foreground agents used to
wait for all of them. A `queue_message` steer (the person, or another
session's `message_session`) calls `agent_tool::steered(session)`; every
waiting foreground call returns at once ("moved to the background, its report
comes as a message"), the child runs on with the session's lifetime instead
of the parent run's, and reports like a background agent (steered into a
running parent, or queued with a wake). A child that finishes in the same
instant reports to its call as before: an `ATTACHED → FINISHED | DETACHED`
switch decides. Background agents' own notes do not release anything.

**Progress.** The child's emitter turns child `AgentEvent`s into the
cumulative snapshot of 3.3 and calls the tool's `on_update`, throttled (an
update at most every 250 ms, about 4 per second), with the last 50 tool rows
and 4 KB of text.

**Background.** The child starts on the session-lifetime scope (as
`create_side_question` does), so it survives the end of the parent's run; it
is cancelled on session close or switch. When it finishes:

- parent run active → `lane.follow_up(<agent-result>)`, picked up in the same
  run;
- parent idle → the report is queued for the next run and a wake request
  starts one (through the session node since session mesh phase 2). The
  desktop sends a normal `prompt` with an automated-event message, which keeps
  RPC's single run slot and `agent_settled` intact.

**Lost background agents.** An engine that exits loses its background agents
(they run in its process: the app closed or crashed). When an engine opens a
session in RPC mode it finds the background calls in the branch with no
`<background-agent id=…>` report after them
(`agent_tool::unreported_background_agents`) and queues their report for the
next run, `status="error"`, saying the agent stopped with no report
(`report_lost_background_agents`; a report already queued is not queued
again; no wake: opening a chat does not start a run). `ready` lists them in
`lostBackgroundAgents`. A saved call keeps its snapshot from when it returned
(`status: "running"`), so the desktop applies each report to its call when it
rebuilds a transcript, and after an engine start (`ready`) shows a call with
no report as stopped (`transcript.ts`, `settleBackgroundAgents`) instead of
running forever.

**Desktop rendering of subagents.**

- Tool kind `agent` in `tool.tsx` (`kinds`), label "Agent · {description}"
  with the shimmer while running; the "running without output" early return
  is skipped so the body shows from the first update.
- Body: a nested `<Trace>` of the child's tool rows, reusing the `Tool` row
  component (`ProcessRows` exported from `chat-turn.tsx`), the latest text
  line, and a footer "7 tool uses · 12.3k tokens · 34s". When done: the report
  (Markdown), collapsed by default for long ones.
- Worktree kept → a badge with the branch and actions "Open in…" (the
  existing Open in apps), "Show changes" (the review dialog), "Discard"
  (remove the worktree).
- A "Background agents" chip above the composer lists running ones; the
  wake-up turn renders as an event chip, not a person's bubble.

**Running a chat in the background** (`startChildChat`):

1. `db.createChat({ id, parentChatId, workspaceId, title, origin })`, applied
   to the session store (and to other windows via `chat://updated`);
2. `launch(id, cwd, false)` without activating it;
3. on `ready`, `dispatch(id, {type: "prompt", text})` and
   `client.request(id, "prompt", {message})` — the per-chat variant of
   `sendPrompt`, which assumes the active chat;
4. the runtime stays alive while busy (`trimIdle` skips busy ones); idle
   children are trimmed like any chat and reopen from the database.

With `worktree: true` the child's worktree is created before its engine
starts and used as its working folder.

**Telling the parent.** At the end of each of the child's turns
(`recordFinishedTurn`), when the chat has a parent:

- build the note (3.3);
- parent busy → `queue_message {deliverAs: "followUp"}` to the parent;
- parent idle → after a 2 s coalescing window, one automated `prompt` to the
  parent containing all pending notes, tagged so the transcript shows it as a
  "Nested sessions update" event chip;
- guard rails: no automated wake while the person is typing in that chat; at
  most 5 automated wakes in a row without a person's message, then notes wait
  for the person's next prompt; never wake an archived parent.

Since session mesh phase 3 notes go through the shell's mesh hub and reach
the parent in any window, or after its engine starts.

**Sidebar.**

- Children are left out of the top-level lists (`app-sidebar.tsx`) and drawn
  under their parent's row in a `SidebarMenuSub` (the guide line).
- Up to 3 children show: running and unread first, then most recent. A
  footer row "26 more nested sessions · 22 unread" expands the rest.
- Child rows reuse `ChatItem`: title (shimmering while running), status dot
  (amber = waiting for approval, blue = unread, red = stopped).
- A collapsed parent shows a roll-up: spinner if any child runs, otherwise a
  dot if any child is unread.
- Chat header of a child: "Parent title › Child title", clicking the parent
  opens it. Chat menu: "Open parent", "Detach from parent".

**Worktree review.** The dialog lists the changes measured from the fork
point. **Apply** applies them to the working folder uncommitted (no merge, no
commit) and removes the worktree; when the patch does not apply cleanly it
changes nothing. **Discard** removes the worktree.

### 3.6 Errors and edge cases

- Unknown agent type or model → the call is refused with the reason.
- Read-only refusal → the model is told to retry with a plainer command.
- Recursion (a child calling `agent`) → refused.
- More than 4 foreground children in a run, or 16 kept per session → the
  limit is enforced by the runner (shared with plugin children).
- Engine exit with background agents → reported once as lost (3.5).
- Steer during a foreground wait → the call returns at once; the child
  reports later.
- Parent deleted → children move to the top level; parent archived → never
  woken.
- Conflicting apply → nothing changes; outside a repository → an error.

### 3.7 Security and trust

- Children use the parent's approval prompts, hooks and the process-wide
  Sandbox policy (environment, timeouts, denied patterns); their tools can
  only narrow the parent's.
- **`access: read-only` is enforced** (`crates/evo-engine/src/read_only.rs`):
  every tool call of the child goes through a `ChildToolGuard` (evo-harness)
  before it reaches an approval prompt, and again right before it runs (hooks
  may rewrite arguments). It passes reading tools and the mesh tools, refuses
  `write`/`edit` and any tool it does not know (connector tools included), and
  splits `bash`/`powershell` commands into simple commands that must each be
  on a read-only allow-list (`rg`, `git log/show/diff/status/blame`,
  `Get-ChildItem`, …) without their writing options (`find -delete`,
  `rg --pre`, `git -c`, `--output`, …). Redirection to a file,
  here-documents, command substitution in double quotes, PowerShell method
  calls, static .NET calls, property assignment and `&` are refused. Unknown
  commands are refused; the refusal tells the model to retry with a plainer
  command.
- Agents cannot silently fan out sessions: `start_session` is a proposal the
  person clicks unless they turn on **Start sessions without asking**; child
  sessions cannot start sessions; at most 8 run per parent. Proposals also
  make the 60 s external-tool timeout irrelevant.
- Automated wakes are tagged so they never pass for the person's message.
- Agent files are project content: their instructions go into the child's
  first message, not into the parent's system prompt.
- Worktree changes reach the workspace only through **Apply**; only managed
  worktrees are removed.

### 3.8 Configuration

| Setting | Type, default | Where | Applies |
| --- | --- | --- | --- |
| Project agent types | Markdown files | `<cwd>/.evo/agents/*.md` | at the next `agent` call |
| User agent types | Markdown files | `~/.evo/agent/agents/*.md` | at the next `agent` call |
| `agentDirs` (designed, like `skills`) | list of folders | settings | not built (section 5) |
| **Start sessions without asking** (`autoStartSessions`; designed as "Let agents start sessions without asking") | bool, `false` | UI store, pushed to the hub with `mesh_configure` | live |
| Worktree location | folder | **Settings → Sandbox** | next worktree |

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| Wake an idle parent from inside the engine with `send_message(trigger_turn)` | Runs outside RPC's single run slot, so no `agent_settled` reaches the UI. |
| A new RPC event for child progress | `tool_execution_update` already carries `details`, the desktop already replaces it per update, and saved `details` make reopened chats work. |
| Extend the parent's system prompt with the agent type's body | The harness has no getter for the parent's system prompt; the body opens the child's first message instead. |
| Run the `agent` tool through the plugin job runner | Run directly; it shares the worktree helpers and the recursion guard, and the plugin API stays unchanged. |
| Move the worktree manager into `evo-tools` (`evo_tools::worktrees`) and link it from the shell, or run it through an engine subcommand | A crate of its own (`evo-worktrees`) keeps the shell free of tool dependencies and is shared by engine and shell. |
| Merge a worktree's branch on review | **Apply** leaves the changes uncommitted so the person reviews and commits them. |
| Start sessions immediately | Agents could fan out whole sessions silently; proposals by default (spec 6.2). |

## 5. As-built notes

- **Phase 1** differs from the design in two small ways: an agent type's
  instructions open the child's first message (the harness has no getter for
  the parent's system prompt to extend), and the `agent` tool runs its child
  directly rather than through the plugin job runner (it shares the worktree
  helpers and the recursion guard; the plugin API is unchanged). The design
  had factored `run_child` and the job bookkeeping out of `child_agents.rs`
  into one runner for `delegate_task` and `agent`.
- **`maxTurns` default**: the design's limits named a default of 24; the
  built default for a type without `maxTurns` is 32 (`DEFAULT_MAX_TURNS`).
- **`agentDirs`**: the designed settings key is not in the engine settings
  (checked 2026-11-07); agent files load from the two folders only.
- **Phase 2** originally differed in one way: the engine had no event for "a
  background agent finished" (`agent_task_settled` was not built), so the
  desktop polled `get_background_agents` once a second, only while one ran or
  waited to be delivered. Session mesh phase 2 then replaced the
  background-agent RPC commands and the polling with push events and wake
  requests on the session node.
- **Phase 3** first limited notes to a parent held by this window (or started
  here to receive them); a parent open in a separate chat window did not get
  them. Since session mesh phase 3 notes go through the shell's mesh hub and
  reach the parent in any window, or after its engine starts, and the hub —
  not `engine-store.ts` — defines and answers `start_session`,
  `message_session` and `list_sessions`
  ([session mesh](../session-mesh-protocol/spec.md)).
- **Phase 4** moves the worktree manager into its own crate
  (`crates/evo-worktrees`: create, list, changes, apply, remove; the engine
  and the desktop shell share it) rather than `evo-tools`, adds migration
  `0005_chat_worktrees.sql`, `start_session`'s `worktree` option, the shell
  commands in `apps/desktop/src-tauri/src/worktrees.rs`, and the review
  dialog. The design's "merge" action became **Apply**: the changes land
  uncommitted and the worktree is removed.
- **Steering release** was added on 2026-11-06 (3.5).
- **Tests**: the desktop logic is covered by typecheck and a preview with
  sample data, not by automated tests (the desktop has no test runner).
