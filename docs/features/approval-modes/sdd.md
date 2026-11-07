# Approval modes enforced in the engine

| | |
| --- | --- |
| Status | Accepted |
| Area | engine, protocol, desktop shell, desktop UI |
| Created | 2026-11-07 |
| Updated | 2026-11-07 |
| ADD sections | [4. Process view](../../architecture/README.md#4-process-view), [8. Interfaces](../../architecture/README.md#8-interfaces), [9. Cross-cutting concepts](../../architecture/README.md#9-cross-cutting-concepts) |
| ADRs | [0010 The engine enforces the approval mode on every tool call](../../architecture/decisions/0010-engine-enforces-approval-mode.md) |
| Related | [Agent terminal](../agent-terminal/sdd.md), [Subagents and nested sessions](../subagents-and-nested-sessions/sdd.md), [Customize: hooks](../customize-skills-plugins-connectors/sdd.md), [Memory and the Scheduler](../memory-and-scheduler/sdd.md) |

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
  [agent terminal](../agent-terminal/sdd.md) 5.7 — reading the same mode.
- Per-tool or per-command allow / deny lists in settings files: a later SDD on
  top of this gate.
- Denying with a message for the agent: later; the composer's queued message
  covers it.
- Changing what `PreToolUse` hooks, plugin handlers, the self-kill guard or
  read-only agent types do; they keep running in the same chain.
- Sandboxing; the sandbox config is unchanged.

## 3. Requirements

### 3.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | The approval mode is one app setting (`approvalMode`: `ask` · `auto-edits` · `auto`, default `ask`), edited from the composer's menu and kept in the app database. | Change it in the composer, restart the app: the menu shows the same mode. |
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

### 3.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Classifying a call takes under 1 ms (no process start, no file read). | Benchmark in the unit tests. |
| NFR-2 | Engines that do not know `set_approval_mode` (older builds) keep working; the app logs the unknown command once. | Run the app against an older engine binary. |
| NFR-3 | A prompt waiting forever never blocks other chats or the app; stopping the turn closes it. | Stop a turn with an open prompt: the panel closes and the turn ends. |

## 4. Context and constraints

- **Mode today.** `ApprovalMode` in `apps/desktop/src/stores/ui-store.ts`
  (persisted in local storage), menu in
  `apps/desktop/src/features/chat/chat-composer.tsx`. Nothing else reads it.
- **Approval chain today.** `crates/evo-engine/src/session.rs` builds the
  `before_tool_call` hook: plugin tool-call handlers
  (`extension_tool_call_hook`), then `PreToolUse` hooks
  (`crates/evo-engine/src/hooks.rs`), then the self-kill guard
  (`crates/evo-engine/src/self_kill.rs`). Prompts go through the UI dialog
  mailbox (`hooks::confirm`: `ui_dialog_request` with `kind: "confirm"`,
  answered from `apps/desktop/src/features/chat/approval-panel.tsx` via
  `answerPermission` in `engine-store.ts`). Without a UI, `confirm` returns
  false.
- **Read-only checker.** `crates/evo-engine/src/read_only.rs` already
  classifies tools and splits `bash` / `powershell` commands against an
  allow-list for read-only agent types (`guard`, `check_command`).
- **Subagents** inherit the parent's `before_tool_call`
  (`crates/evo-harness/src/agent_harness/child.rs`), so their prompts already
  reach the parent's panel.
- **Engine start.** `apps/desktop/src-tauri/src/engine.rs` starts every engine
  (including nested sessions the mesh hub starts) with `--sandbox-config` read
  from the app database (`evo_store::settings`). Live settings use RPC
  commands such as `set_hooks_disabled` and `reload_providers`
  (`crates/evo-engine/src/modes.rs`), sent per engine from `engine-store.ts`.
- **Rules.** Settings apply without restart (ADR 0005); protocol changes are
  additive (ADD §8); the engine owns agent decisions, the shell relays.

## 5. Design

### 5.1 Overview

```text
composer menu ──set──▶ app settings (evo.db: approvalMode)
      │                     │ read at spawn
      │                     ▼
      │      engine.rs ── evo-engine --approval-mode <mode>
      └─ broadcast set_approval_mode ──▶ every running engine
                                              │
 tool call ─▶ read-only guard ─▶ self-kill ─▶ PreToolUse hooks ─▶ plugin handlers ─▶ approval gate
                                                                                       │ classify: read / edit / command
                                                                                       │ mode + chat grants say ask?
                                                                                       ▼
                                                                         ui_dialog_request (confirm) ─▶ approval panel
```

The mode lives in the app database so the shell can give it to every engine
it starts. A new last link in the `before_tool_call` chain classifies the call
and, when the mode and the chat's grants say so, asks through the existing
dialog mailbox. The mode is held in a shared atomic value, so
`set_approval_mode` takes effect on the next call.

### 5.2 Components

| Layer | Path | Responsibility |
| --- | --- | --- |
| engine | `crates/evo-engine/src/approval.rs` (new) | `ApprovalMode`, `ApprovalState` (mode + chat grants, shared), `classify(tool, args) -> Kind`, `before_tool_call` link, prompt text. |
| engine | `crates/evo-engine/src/read_only.rs` | Exposes the per-command check `approval.rs` reuses (no behaviour change for read-only agents). |
| engine | `crates/evo-engine/src/session.rs` | Puts the approval link last in the chain; passes the subagent name for labels. |
| engine | `crates/evo-engine/src/args.rs` | `--approval-mode ask|auto-edits|auto` (default `auto` outside RPC mode, `ask` in RPC mode when absent — see 5.8). |
| engine | `crates/evo-engine/src/modes.rs` | RPC `set_approval_mode`, `get_approval_state`, `clear_approval_grants`; `get_state` includes the mode and grants. |
| protocol | `crates/evo-protocol/src/client.rs` | The three commands and the `approval` field of state. |
| desktop shell | `apps/desktop/src-tauri/src/engine.rs` | Reads `approvalMode` from the app database and passes `--approval-mode`. |
| desktop UI | `apps/desktop/src/stores/ui-store.ts` | Drops the local `approval` value; reads/writes the app setting (one-time move of the stored local value). |
| desktop UI | `apps/desktop/src/stores/engine-store.ts` | Broadcasts `set_approval_mode` on change; reads grants from state; `clearApprovalGrants(chat)`. |
| desktop UI | `apps/desktop/src/features/chat/chat-composer.tsx` | New hints (FR-14); grant chips (FR-7). |
| desktop UI | `apps/desktop/src/features/chat/approval-panel.tsx` | Shows the summary line and the third option; subagent label. |
| desktop UI | `apps/desktop/src/features/scheduler/` | "When it needs approval" on a task (FR-11). |

### 5.3 Interfaces

**Engine argument:** `--approval-mode <ask|auto-edits|auto>`.

**RPC commands** (additive; an older engine answers "unknown command"):

```jsonc
// app → engine
{ "type": "set_approval_mode", "mode": "ask" }            // → { "mode": "ask" }
{ "type": "clear_approval_grants" }                         // → { "grants": [] }
{ "type": "get_approval_state" }                            // → { "mode": "ask", "grants": ["command"] }
// get_state gains: "approval": { "mode": "ask", "grants": ["edit"] }
```

**Prompt** (existing `ui_dialog_request`, `ui.kind = "confirm"`, extra fields
the panel may use and older panels ignore):

```jsonc
{
  "type": "ui_dialog_request",
  "requestId": "approve:<toolCallId>",
  "toolCallId": "<id>",
  "ui": {
    "kind": "confirm",
    "title": "Run a command?",
    "description": "npm install --save-dev vitest",
    "approval": { "kind": "command", "tool": "bash", "agent": "explore-2" },
    "options": [
      { "title": "Allow" },
      { "title": "Allow commands for this chat", "permission": "allow-chat" },
      { "title": "Deny", "permission": "reject" }
    ]
  }
}
```

**Classification** (`approval::classify`):

| Kind | Tools |
| --- | --- |
| read | `read`, `grep`, `find`, `ls`, `lsp`, `docs`, `document_preview`, `web_search`, `web_fetch`, `ask_user`, `update_todos`, `send_file`, `notify`, mesh tools, `skill` (its `` !`command` `` lines stay under Customize → Skills settings), `agent` and `message_agent` (the subagent's own calls are checked one by one); `bash` / `powershell` commands that `read_only::check_command` accepts |
| edit | `write`, `edit`, and tools that write files (Office document tools, `memory` writes) |
| command | other `bash` / `powershell` commands and every engine tool not listed above |
| (skipped) | external tools registered by the app — gated by the app |

Unknown engine tools count as commands, so a new tool asks until it is
classified.

### 5.4 Data and storage

- `approvalMode` in the app database's settings table (`evo_store::settings`,
  the same table as `sandbox`); no migration needed (key/value).
- Chat grants: in memory in the chat's engine (`ApprovalState`), lost when the
  engine stops (idle trim, app restart). Shown through `get_state`.
- Scheduled task setting: a field on the task record in the scheduler's
  existing storage.
- One-time move (FR-15): on first start of this version the UI writes its
  local `approval` value to the setting (`ask` if none), then forgets it; an
  `approvalNoteSeen` flag in local storage hides the note afterwards.

### 5.5 Behaviour

```mermaid
sequenceDiagram
  participant M as Model
  participant E as Engine (approval link)
  participant A as App (approval panel)
  participant P as Person
  M->>E: tool call bash "npm install"
  E->>E: earlier links (guards, hooks, plugins) pass
  E->>E: classify → command; mode ask; no grant
  E->>A: ui_dialog_request (confirm)
  A->>P: panel: Run a command? npm install
  P-->>A: Allow commands for this chat
  A-->>E: ui_dialog_response index 1
  E->>E: grants += command
  E-->>M: run the tool
```

- **Mode change mid-run:** the app sends `set_approval_mode` to every ready
  engine; calls already past the gate keep running, the next one uses the new
  mode. Engines that are starting get the mode from their argument.
- **Subagents:** the child's chain is the parent's, so the same state and
  grants apply; the prompt carries the child's name.
- **Nested sessions** are separate chats with their own engine and grants;
  their prompts show in their own chat and in the sidebar (FR-10).
- **Scheduled runs:** a run whose task says "run without asking" starts its
  engine with `--approval-mode auto` and the app does not send it later mode
  changes; otherwise it follows the global mode and waits.

### 5.6 Errors and edge cases

| Case | Model sees | Person sees |
| --- | --- | --- |
| Denied | "The user declined this command." | Panel closes |
| Turn stopped while waiting | Turn ends | Panel closes |
| Engine restarts mid-prompt | The call is lost with the run (as today) | Panel closes; grants gone |
| No UI (`text` / `json` mode) and the mode asks | "Not run: approval needed and no one can approve in this mode (use --approval-mode auto)." | — |
| Unclassifiable shell (method calls, substitutions) | Counts as a command | A prompt |
| Older engine | Mode not applied; app logs once | Nothing (the app and engine ship together) |
| A hook asks and the mode asks | One prompt (the hook's), then the mode does not ask again for that call | One prompt |

### 5.7 Security and trust

- The gate is in the engine, after every other link, so nothing the model
  writes in arguments can skip it; external tools are the app's job and are
  listed in 2.2.
- `read_only::check_command` is an allow-list: anything it cannot prove
  read-only asks.
- Grants are per chat and per kind, never per pattern, and end with the
  engine; they cannot be set by the model.
- Defaults are conservative: the app starts in `ask`; only headless use
  defaults to `auto`, where there is no person to ask and today's behaviour is
  kept.

### 5.8 Configuration

| Key | Type | Default | Where | Applies |
| --- | --- | --- | --- | --- |
| `approvalMode` | `"ask" \| "auto-edits" \| "auto"` | `"ask"` | app database settings | live (broadcast) and on every engine start |
| `--approval-mode` | engine argument | RPC mode: `ask` when absent; `text` / `json`: `auto` | engine command line | engine start |
| Task "When it needs approval" | `wait` · `auto` | `wait` | scheduler task record | next run |

Edited from the composer's menu (mode) and the task editor (task setting).

## 6. Alternatives considered

| Option | Why not |
| --- | --- |
| Gate in the app when the engine reports a tool call | The tool has already started by the time the app hears of it; the engine owns agent decisions (ADD rules). |
| A `PreToolUse` hook shipped with the app | Hooks are user configuration, can be switched off, and run a process per call. |
| Per-chat modes | The composer shows one global mode today and the person expects one switch; per-chat grants cover the common need (the terminal SDD chose global too). |
| Keep the mode in local storage and pass it from the webview | The Rust shell starts engines (nested sessions) without the webview; the database is where it can read settings. |
| Prompt for every tool, reads included, in `ask` | A prompt per `read` / `grep` makes `ask` unusable; reads change nothing. |

## 7. Delivery plan

| Phase | Scope | Main files | Done when |
| --- | --- | --- | --- |
| 1 | Engine gate, classification, argument, RPC commands, protocol; app setting, broadcast, panel options, hints, grant chips; one-time move and upgrade note; ADD §9 and §8 lines | `approval.rs`, `session.rs`, `modes.rs`, `args.rs`, `evo-protocol`, `engine.rs` (shell), `ui-store.ts`, `engine-store.ts`, `chat-composer.tsx`, `approval-panel.tsx` | FR-1–10, 12–15 pass |
| 2 | Scheduled task setting | `features/scheduler/*`, scheduler store | FR-11 passes |

## 8. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-4, NFR-1 | `cargo test -p evo-engine approval::` (classification table, shell commands, unknown tools) | not run |
| FR-5, FR-7, FR-8, FR-13 | `cargo test -p evo-engine` RPC tests: each mode × kind, grants, hook allow/block ordering | not run |
| FR-3, FR-12, NFR-3 | RPC tests: `set_approval_mode` mid-run, headless refusal, stop with an open prompt | not run |
| FR-1, FR-2, FR-6, FR-9, FR-10, FR-14, FR-15 | Running app over WebView2 DevTools: menu, restart, prompts, subagent label, sidebar dot | not run |
| FR-11 | Scheduled task set to run without asking | not run |
| NFR-2 | App with an older engine binary | not run |

## 9. Open questions

None open. Resolved on 2026-11-07, when the owner accepted the proposals:

1. Read-only shell commands run without a prompt in `ask` (FR-4, 5.3).
2. Existing users keep the mode they last picked in the menu (`ask` if they
   never picked one), and the composer shows a one-time note that approvals
   now apply (FR-15).
3. Chat grants end with the chat's engine; they are not stored (5.4).
4. Allow / deny rule lists are a later SDD on top of this gate (2.2).
5. An older engine that does not know `set_approval_mode` is logged once; the
   UI shows nothing (5.6).
6. "Deny with a message" is later; the composer's queued message covers it
   (2.2).

## 10. As-built notes

Empty until `In progress`.

## 11. History

- 2026-11-07 — Draft.
- 2026-11-07 — Accepted with the proposed answers to every open question; ADR 0010 accepted.
