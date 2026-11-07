# Agent tools for working with the person — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [4. Process view](../../architecture/README.md#4-process-view) |
| ADRs | [0001 The desktop app is the only front end](../../architecture/decisions/0001-desktop-app-is-the-only-front-end.md) |

## 1. Context and constraints

- `ask_user` and `update_todos` are engine tools in
  `crates/evo-engine/src/interaction.rs`. `ask_user` reuses the engine's
  UI-dialog channel (`ui_dialog_request` / `ui_dialog_response`), the same
  channel approvals use, so it needs a client that can show a dialog.
- `send_file` and `notify` are desktop tools every chat gets, answered in the
  webview (`apps/desktop/src/features/chat/user-tools.ts`). `notify` goes
  through the [notifications](../notifications/plan.md) pipeline.

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | `ask_user` and `update_todos` run in the engine; the desktop only renders the dialog and the list. `send_file` and `notify` are desktop tools that touch only native features (files, notifications). |
| Layers point down; library crates stay free of engine/desktop concerns | ok | All engine code is in `evo-engine`; no library crate changes. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | ok | No new protocol messages: `ask_user` uses the existing UI-dialog channel with `ui.kind = "questions"`. |
| Models come from models.dev; no hardcoded model facts | n/a | No model data. |
| Real engine in the app; settings and credentials reload live | ok | Checked with a real model over RPC. |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | See 3.7. |
| Desktop UI structure and `DESIGN.md` | ok | The questions panel and todo bar live in `features/chat/`. |

## 3. Design

### 3.1 Overview

```text
model ──ask_user──► engine (interaction.rs) ──ui_dialog_request {ui.kind: "questions"}──► desktop questions panel
model ◄── "1. question → …" ── engine ◄──ui_dialog_response {answer.answers}────────────── person answers / skips

model ──update_todos──► engine: check + summary ──► transcript ──► desktop todo bar (latest list of latest turn)

model ──send_file / notify──► desktop (user-tools.ts) ──► file cards in the chat / notify()
```

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| engine | `crates/evo-engine/src/interaction.rs` | `ask_user`: schema, checks, dialog request, answer formatting, dismissed and headless results, tool description | FR-1, FR-2, FR-3, FR-4 |
| engine | `crates/evo-engine/src/interaction.rs` | `update_todos`: schema, checks, summary; no state | FR-8, NFR-1 |
| desktop UI | `apps/desktop/src/features/chat/questions-panel.tsx` | the questions panel in place of the chat input | FR-5, FR-6 |
| desktop UI | `apps/desktop/src/features/chat/todo-bar.tsx` | the pinned todo bar above the chat input | FR-9, NFR-1 |
| desktop UI | `apps/desktop/src/features/chat/` (transcript rows) | "Asked you · question" and "Updated tasks · 2/5 done" rows | FR-7, FR-10 |
| desktop UI | `apps/desktop/src/features/chat/user-tools.ts` | `send_file` and `notify`, registered on every chat | FR-11, FR-12 |

### 3.3 Interfaces

`ask_user` input:

```jsonc
{
  "questions": [                       // 1–4
    {
      "question": "Which database?",
      "header": "Database",            // optional: a short chip
      "options": [                     // 0, or 2–6
        { "label": "Postgres", "description": "…" }   // description optional
      ],
      "multi_select": false            // optional
    }
  ]
}
```

The engine opens a dialog with `ui_dialog_request` (`ui.kind = "questions"`)
and waits. The client answers with `ui_dialog_response`:

```jsonc
{ "answer": { "answers": [ { "selected": ["Postgres"], "other": "…" } ] } }  // other optional
```

The model reads the answer as `1. question → "choice", (their own words) …`.

`update_todos` input — the whole list on every call:

```jsonc
{
  "todos": [
    { "content": "Add the login form", "status": "in_progress",   // pending | in_progress | completed
      "active_form": "Adding the login form" }                     // optional, shown while in progress
  ]
}
```

Result: a summary such as "1 of 3 done. In progress: …".

Desktop tools:

```jsonc
// send_file
{ "paths": ["out/report.pdf"], "caption": "…" }   // paths: 1–10; caption optional
// notify
{ "title": "Build finished", "body": "…" }         // body optional
```

### 3.4 Data and storage

No engine state. The task list and the answers live in the transcript, so
the todo bar and the transcript rows are rebuilt from it after a restart.
The `notify` rate limit is per chat, in the webview's memory.

### 3.5 Behaviour

- **`ask_user`.** The engine tool call blocks on the dialog request. The
  desktop shows the questions panel in place of the chat input (its steps and
  keys are in spec FR-5) and sends `ui_dialog_response` with the answers, or
  a dismissal on "Skip". The engine formats the answers for the model and
  returns.
- **`update_todos`.** The engine checks the list and returns the summary at
  once; it keeps nothing. The desktop reads the latest `update_todos` call of
  the latest turn from the transcript for the todo bar (FR-9).
- **`send_file` / `notify`.** The webview answers the tool request itself:
  `send_file` resolves each path against the chat's folder and adds the
  cards; `notify` calls `notify()` unless the chat notified in the last 30
  seconds.

### 3.6 Errors and edge cases

- `ask_user` dismissed: the model is told to decide and say what it assumed.
- `ask_user` with no one to ask (a headless run): an error saying the same.
- `ask_user` with invalid questions (none, more than 4, one option): refused.
- `send_file` with missing files: the tool checks the files exist.
- `notify` more often than once per chat every 30 seconds: rate-limited.

### 3.7 Security and trust

- `ask_user` only shows text from the model to the person and returns the
  person's answer; its description keeps it for real decisions, never as a
  permission prompt ("may I proceed?") — approvals stay a separate path.
- `send_file` shows existing files as cards; opening them is the person's
  action.
- `notify` is rate-limited per chat and respects Do not disturb and muting.

### 3.8 Configuration

n/a — no settings; `notify` follows the notification center's Do not disturb
and muted sources.

## 4. Alternatives considered

n/a — the original design records no alternatives.

## 5. As-built notes

- `ask_user` and `update_todos` were built on 2026-11-06 as described above.
- Plan mode (`plan_mode_start` / `plan_mode_complete`) and an end-of-turn
  summary are not built; the names are reserved (spec 6.2).
