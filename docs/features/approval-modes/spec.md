# Approval modes enforced in the engine — Spec

| | |
| --- | --- |
| Status | Accepted |
| Area | engine, protocol, desktop shell, desktop UI |
| Created | 2026-11-07 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Agent terminal](../agent-terminal/spec.md), [Subagents and nested sessions](../subagents-and-nested-sessions/spec.md), [Customize: hooks](../customize-skills-plugins-connectors/spec.md), [Memory and the Scheduler](../memory-and-scheduler/spec.md) |

## 1. Summary

The composer offers three approval modes — "Ask every time", "Approve edits"
and "Approve for me" — but the choice is only stored in the webview: it never
reaches the engine, and shell commands and file edits run without a prompt in
every mode. This feature makes the engine ask before a tool call whenever the
mode says so, through the approval panel the composer already has, and lets
the person allow a kind of call for the rest of a chat. It closes a gap
between what the UI promises and what happens.

## 2. Scope

### 2.1 Goals

- One approval mode, kept with the app's settings, that every engine knows
  from its start and that changes live, even in the middle of a run.
- Classify each tool call as a read, an edit or a command, and ask for edits
  and commands as the mode says; read-only shell commands count as reads.
- "Allow for this chat" answers that stop the same kind of prompt for the rest
  of the chat.
- Subagents, nested sessions and scheduled runs follow the same rules, and a
  run waiting for an answer is easy to find.

### 2.2 Non-goals

- App-side tools (connectors, scheduler, sessions, browser, terminal): the app
  gates them with their own rules — connector permissions,
  [agent terminal](../agent-terminal/plan.md) 3.7 — reading the same mode.
- Per-tool or per-command allow / deny lists in settings files: a later spec
  on top of this gate.
- Denying with a message for the agent: later; the composer's queued message
  covers it.
- Changing what `PreToolUse` hooks, plugin handlers, the self-kill guard or
  read-only agent types do; they keep running in the same chain.
- Sandboxing; the sandbox config is unchanged.

## 3. User scenarios

### US-1 Approve edits and commands before they run (priority P1)

A person working in a chat wants the agent to stop and ask before it changes
files or runs commands, so that nothing happens on their machine that they did
not agree to.

Acceptance scenarios:

1. **Given** the mode "Ask every time", **when** the agent wants to run
   `npm install`, **then** the approval panel asks "Run a command?" with the
   command and the options Allow, Allow commands for this chat, Deny.
2. **Given** the mode "Ask every time", **when** the agent wants to edit a
   file, **then** the panel reads "Edit src/app.ts (+12 −3)" with the three
   options.
3. **Given** an open prompt, **when** the person denies it, **then** the agent
   is told the call was declined and goes on with its turn without retrying it
   unchanged.
4. **Given** any mode, **when** the agent only reads (including a read-only
   shell command such as `git status`), **then** no prompt appears.

### US-2 Change the mode at any time (priority P1)

A person wants to switch the mode from the composer, even while the agent is
working, and have it hold across restarts.

Acceptance scenarios:

1. **Given** a long run in "Approve for me", **when** the person switches to
   "Ask every time", **then** the next command waits for approval.
2. **Given** a mode picked in the composer, **when** the app restarts,
   **then** the menu shows the same mode.
3. **Given** the composer's menu, **when** the person opens it, **then** each
   mode is described by what it asks for.

### US-3 Stop asking for one kind of call in this chat (priority P2)

A person who trusts the current task wants to stop being asked about commands
(or edits) for the rest of the chat, and to undo that later.

Acceptance scenarios:

1. **Given** a command prompt, **when** the person picks "Allow commands for
   this chat", **then** later commands in that chat run without a prompt and a
   chip shows next to the mode.
2. **Given** that chip, **when** the person clears it, **then** prompts come
   back.

### US-4 Notice a chat or subagent that is waiting (priority P2)

A person running several chats wants to see which one is waiting for them and
who is asking.

Acceptance scenarios:

1. **Given** a background chat in "Ask every time", **when** it wants to run a
   command, **then** the sidebar shows the "Waiting for approval" dot and a
   notification arrives if the window is not focused.
2. **Given** a subagent in a chat, **when** it wants to run a command,
   **then** the prompt appears in the parent chat's panel as "<agent name>
   wants to run …".

### US-5 Let a scheduled task run unattended (priority P3)

A person wants a scheduled task to finish its work while they are away.

Acceptance scenarios:

1. **Given** a task set to "run without asking", **when** it runs with nobody
   at the computer, **then** it edits files without waiting.
2. **Given** a task left on "wait for me", **when** it needs approval,
   **then** it waits under the app's mode.

### US-6 Use the engine without a UI (priority P3)

Someone running the engine headless wants today's behaviour by default and a
clear failure when they ask for approvals nobody can give.

Acceptance scenarios:

1. **Given** the engine in `json` mode with `--approval-mode ask`, **when**
   the agent runs a command, **then** the tool result explains that no one
   could approve it.

### Edge cases

- The turn is stopped while a prompt is open: the panel closes and the turn
  ends (NFR-3).
- The engine restarts while a prompt is open: the call is lost with the run
  and the chat's grants are gone.
- A shell command that cannot be classified (method calls, substitutions)
  counts as a command and asks.
- A `PreToolUse` hook asks as well: the person sees one prompt for that call,
  not two.
- An older engine does not know approval modes: the mode is not applied and
  the person sees nothing; the app and engine ship together (NFR-2).

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | The approval mode is one app setting (`ask` · `auto-edits` · `auto`, default `ask`), edited from the composer's menu and kept in the app database. | Change it in the composer, restart the app: the menu shows the same mode. |
| FR-2 | Every engine the app starts — chats, nested sessions, scheduled runs — starts with the current mode. | A nested session started by the mesh hub asks before a command in `ask`. |
| FR-3 | A mode change reaches every running engine at once and applies from its next tool call, including in a run already in progress. | Start a long run in `auto`, switch to `ask`: the next command waits for approval. |
| FR-4 | Tool calls are classified as **read** (tools that only read, plus `bash` / `powershell` commands the read-only checker accepts), **edit** (tools that change files) or **command** (other shell commands and every other engine tool that has effects). | Unit tests: `read` → read, `edit` → edit, `bash "git status"` → read, `bash "npm install"` → command. |
| FR-5 | `ask` asks for edits and commands; `auto-edits` asks for commands only; `auto` asks for none. Reads never ask. | One edit and one command in each mode give the prompts in this table. |
| FR-6 | The prompt shows the tool, a one-line summary (the command, or the file and change size) and the options Allow, Allow <kind> for this chat, Deny. Enter allows once, Esc denies (as today). | An edit prompt reads "Edit src/app.ts (+12 −3)" with the three options. |
| FR-7 | "Allow edits for this chat" / "Allow commands for this chat" stop prompts of that kind in that chat until the chat's engine stops; it shows as a chip next to the mode that can be cleared. | After "Allow commands for this chat", the next command runs without a prompt; clearing the chip brings prompts back. |
| FR-8 | A denied call returns "The user declined this <edit/command>." to the model, which goes on with its turn. | Deny an edit: the agent says it was declined and does not retry it unchanged. |
| FR-9 | A subagent's calls ask in its parent chat's panel, labelled with the subagent's name. | A subagent's `bash` call shows "<agent name> wants to run …". |
| FR-10 | A chat waiting for approval shows the existing "Waiting for approval" dot in the sidebar and sends a notification when its window is not focused. | Background chat in `ask` runs a command: the sidebar dot shows and a notification arrives. |
| FR-11 | A scheduled task has its own setting "When it needs approval": wait for me (default) or run without asking; the run uses `auto` for the second. | A task set to run without asking edits a file with nobody at the computer. |
| FR-12 | Without a UI (the engine's `text` and `json` modes) the default mode is `auto`, and `--approval-mode ask` makes calls that need approval fail with a clear reason. | `evo-engine --mode json --approval-mode ask` with a command → the tool result explains no one could approve it. |
| FR-13 | Order of checks for one call: read-only agent guard → self-kill guard → `PreToolUse` hooks → plugin handlers → approval mode. A hook's or handler's block always wins; a hook's explicit `allow` skips the mode's prompt. | A hook that allows `npm test` runs it in `ask` without a prompt; a hook that blocks it blocks it in `auto`. |
| FR-14 | The composer's menu describes each mode by what it asks for. | The hints read "Asks before edits and commands", "Edits run, commands ask", "Everything runs". |
| FR-15 | The first time this version starts, the mode is the one last picked in the menu (`ask` if none), and the composer shows a one-time note that approvals now apply, with a link to the menu. | Upgrade with `auto` picked: still `auto`, note shown once. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Classifying a call takes under 1 ms (no process start, no file read). | Benchmark in the unit tests. |
| NFR-2 | Engines that do not know the live mode-change command (older builds) keep working; the app logs the unknown command once. | Run the app against an older engine binary. |
| NFR-3 | A prompt waiting forever never blocks other chats or the app; stopping the turn closes it. | Stop a turn with an open prompt: the panel closes and the turn ends. |

## 5. Success criteria

- SC-1 In "Ask every time", no file edit and no command with effects runs
  without the person's answer; in "Approve edits", no command does.
- SC-2 A mode change made in the composer applies from the agent's next tool
  call in every open chat, without restarting anything.
- SC-3 Reads, including read-only shell commands, never show a prompt in any
  mode.
- SC-4 A person who upgrades keeps the mode they last picked and sees the
  approvals note exactly once.
- SC-5 Every chat waiting for an answer is visible from the sidebar.

## 6. Clarifications

### 6.1 Open

n/a — none open.

### 6.2 Resolved

- 2026-11-07 — Q: Do read-only shell commands ask in `ask`? → A: No, they run
  without a prompt (FR-4, [plan 3.3](plan.md#33-interfaces)).
- 2026-11-07 — Q: Which mode do existing users get? → A: The one they last
  picked in the menu (`ask` if they never picked one), and the composer shows
  a one-time note that approvals now apply (FR-15).
- 2026-11-07 — Q: Are chat grants stored? → A: No; they end with the chat's
  engine (FR-7, [plan 3.4](plan.md#34-data-and-storage)).
- 2026-11-07 — Q: Allow / deny rule lists? → A: A later spec on top of this
  gate (section 2.2).
- 2026-11-07 — Q: What happens with an older engine that does not know the
  live mode-change command? → A: The app logs it once; the UI shows nothing
  (NFR-2, [plan 3.6](plan.md#36-errors-and-edge-cases)).
- 2026-11-07 — Q: Deny with a message? → A: Later; the composer's queued
  message covers it (section 2.2).

## 7. History

- 2026-11-07 — Draft.
- 2026-11-07 — Accepted with the proposed answers to every open question; ADR 0010 accepted.
- 2026-11-07 — Moved to the spec / plan / tasks format.
