# Approval modes enforced in the engine — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [4. Process view](../../architecture/README.md#4-process-view), [8. Interfaces](../../architecture/README.md#8-interfaces), [9. Cross-cutting concepts](../../architecture/README.md#9-cross-cutting-concepts) |
| ADRs | [0010 The engine enforces the approval mode on every tool call](../../architecture/decisions/0010-engine-enforces-approval-mode.md) |

## 1. Context and constraints

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

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | The gate, the classification and the grants live in the engine; the shell only reads the setting and passes it at spawn ([ADR 0010](../../architecture/decisions/0010-engine-enforces-approval-mode.md)). |
| Layers point down; library crates stay free of engine/desktop concerns | ok | New code is in `evo-engine`; no library crate changes. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | ok | Three additive commands and an `approval` state field land in `evo-protocol`, `modes.rs` and `engine-store.ts` in one phase; older engines answer "unknown command" (NFR-2). |
| Models come from models.dev; no hardcoded model facts | n/a | No model data involved. |
| Real engine in the app; settings and credentials reload live | ok | Mode changes are broadcast to running engines (FR-3, ADR 0005). |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | This is a permission gate placed after every other link; hooks, plugin handlers, guards and the sandbox config are unchanged (3.7). |
| Desktop UI structure and `DESIGN.md` | ok | Components use store actions; only `engine-store.ts` talks to the engine client; the existing approval panel and composer menu are extended. |

## 3. Design

### 3.1 Overview

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

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| engine | `crates/evo-engine/src/approval.rs` (new) | `ApprovalMode`, `ApprovalState` (mode + chat grants, shared), `classify(tool, args) -> Kind`, `before_tool_call` link, prompt text. | FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, NFR-1, NFR-3 |
| engine | `crates/evo-engine/src/read_only.rs` | Exposes the per-command check `approval.rs` reuses (no behaviour change for read-only agents). | FR-4 |
| engine | `crates/evo-engine/src/session.rs` | Puts the approval link last in the chain; passes the subagent name for labels. | FR-9, FR-13 |
| engine | `crates/evo-engine/src/args.rs` | `--approval-mode ask|auto-edits|auto` (default `auto` outside RPC mode, `ask` in RPC mode when absent — see 3.8). | FR-2, FR-12 |
| engine | `crates/evo-engine/src/modes.rs` | RPC `set_approval_mode`, `get_approval_state`, `clear_approval_grants`; `get_state` includes the mode and grants. | FR-3, FR-7, FR-12 |
| protocol | `crates/evo-protocol/src/client.rs` | The three commands and the `approval` field of state. | FR-3, FR-7, NFR-2 |
| desktop shell | `apps/desktop/src-tauri/src/engine.rs` | Reads `approvalMode` from the app database and passes `--approval-mode`. | FR-1, FR-2 |
| desktop UI | `apps/desktop/src/stores/ui-store.ts` | Drops the local `approval` value; reads/writes the app setting (one-time move of the stored local value). | FR-1, FR-15 |
| desktop UI | `apps/desktop/src/stores/engine-store.ts` | Broadcasts `set_approval_mode` on change; reads grants from state; `clearApprovalGrants(chat)`. | FR-3, FR-7, NFR-2 |
| desktop UI | `apps/desktop/src/features/chat/chat-composer.tsx` | New hints; grant chips; one-time upgrade note. | FR-7, FR-14, FR-15 |
| desktop UI | `apps/desktop/src/features/chat/approval-panel.tsx` | Shows the summary line and the third option; subagent label. | FR-6, FR-9, FR-10 |
| desktop UI | `apps/desktop/src/features/scheduler/` | "When it needs approval" on a task. | FR-11 |

### 3.3 Interfaces

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

### 3.4 Data and storage

- `approvalMode` in the app database's settings table (`evo_store::settings`,
  the same table as `sandbox`); no migration needed (key/value).
- Chat grants: in memory in the chat's engine (`ApprovalState`), lost when the
  engine stops (idle trim, app restart). Shown through `get_state`.
- Scheduled task setting: a field on the task record in the scheduler's
  existing storage.
- One-time move (FR-15): on first start of this version the UI writes its
  local `approval` value to the setting (`ask` if none), then forgets it; an
  `approvalNoteSeen` flag in local storage hides the note afterwards.

### 3.5 Behaviour

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

### 3.6 Errors and edge cases

| Case | Model sees | Person sees |
| --- | --- | --- |
| Denied | "The user declined this command." | Panel closes |
| Turn stopped while waiting | Turn ends | Panel closes |
| Engine restarts mid-prompt | The call is lost with the run (as today) | Panel closes; grants gone |
| No UI (`text` / `json` mode) and the mode asks | "Not run: approval needed and no one can approve in this mode (use --approval-mode auto)." | — |
| Unclassifiable shell (method calls, substitutions) | Counts as a command | A prompt |
| Older engine | Mode not applied; app logs once | Nothing (the app and engine ship together) |
| A hook asks and the mode asks | One prompt (the hook's), then the mode does not ask again for that call | One prompt |

### 3.7 Security and trust

- The gate is in the engine, after every other link, so nothing the model
  writes in arguments can skip it; external tools are the app's job and are
  listed in the spec's non-goals.
- `read_only::check_command` is an allow-list: anything it cannot prove
  read-only asks.
- Grants are per chat and per kind, never per pattern, and end with the
  engine; they cannot be set by the model.
- Defaults are conservative: the app starts in `ask`; only headless use
  defaults to `auto`, where there is no person to ask and today's behaviour is
  kept.

### 3.8 Configuration

| Key | Type | Default | Where | Applies |
| --- | --- | --- | --- | --- |
| `approvalMode` | `"ask" \| "auto-edits" \| "auto"` | `"ask"` | app database settings | live (broadcast) and on every engine start |
| `--approval-mode` | engine argument | RPC mode: `ask` when absent; `text` / `json`: `auto` | engine command line | engine start |
| Task "When it needs approval" | `wait` · `auto` | `wait` | scheduler task record | next run |

Edited from the composer's menu (mode) and the task editor (task setting).

## 4. Alternatives considered

| Option | Why not |
| --- | --- |
| Gate in the app when the engine reports a tool call | The tool has already started by the time the app hears of it; the engine owns agent decisions (ADD rules). |
| A `PreToolUse` hook shipped with the app | Hooks are user configuration, can be switched off, and run a process per call. |
| Per-chat modes | The composer shows one global mode today and the person expects one switch; per-chat grants cover the common need (the [agent terminal](../agent-terminal/spec.md) feature chose global too). |
| Keep the mode in local storage and pass it from the webview | The Rust shell starts engines (nested sessions) without the webview; the database is where it can read settings. |
| Prompt for every tool, reads included, in `ask` | A prompt per `read` / `grep` makes `ask` unusable; reads change nothing. |

## 5. As-built notes

n/a — empty until the status is `In progress`.
