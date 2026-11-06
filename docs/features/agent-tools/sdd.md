# Agent tools for working with the person

| | |
| --- | --- |
| Status | Implemented |
| Area | engine, desktop UI |
| Format | Legacy — predates [the SDD template](../../templates/sdd.md); move to it on the next substantial edit |
| Updated | 2026-11-06 |
| ADD sections | [4. Process view](../../architecture/README.md#4-process-view) |
| ADRs | [0001](../../architecture/decisions/0001-desktop-app-is-the-only-front-end.md) |

Status: `ask_user` and `update_todos` are built (2026-11-06). The rest of
this page lists what a full desktop agent offers and what evo has.

## Built

### `ask_user`

- Engine: `crates/evo-engine/src/interaction.rs`. Input: 1–4 `questions`,
  each `question`, optional `header` (a short chip), 0 or 2–6 `options`
  (`label`, optional `description`), `multi_select`. No options means a free
  answer; a free answer is always possible.
- It opens a dialog through the engine's UI-dialog channel
  (`ui_dialog_request`, `ui.kind = "questions"`) and waits. The answer
  (`ui_dialog_response` with `answer.answers: [{selected: [...], other?}]`)
  comes back to the model as "1. question → "choice", (their own words) …".
  Dismissed: the model is told to decide and say what it assumed. No one to
  ask (a headless run): an error saying the same.
- The tool description keeps it for real decisions: not for what the agent
  can find out itself, never "may I proceed?".
- Desktop: `features/chat/questions-panel.tsx` takes the chat input's place
  (like an approval): one question per step ("2 of 4", a chip per question
  with a check once answered, click to jump; Back / Next), radio or check
  options, "answer in your own words". A single-choice pick moves to the next
  question after a beat; digits pick the shown question's options; `Enter`
  goes next (sends on the last step) while focus is in the panel;
  `Ctrl+Enter` sends once all are answered; "Skip — let the agent decide"
  dismisses. A chat in the background
  notifies, as approvals do. The transcript row reads "Asked you · question"
  with the answers.

### `update_todos`

- Engine: the same file. Input: the whole list, each `content`, `status`
  (`pending`, `in_progress`, `completed`), optional `active_form` (shown while
  in progress). It checks the list and answers with a summary ("1 of 3 done.
  In progress: …"), nudging to keep exactly one task in progress. No state in
  the engine.
- Desktop: `features/chat/todo-bar.tsx` pins the latest list of the latest
  turn above the chat input — progress bar, `done/total`, the task in
  progress (spinner while the turn runs), collapsible. The transcript row
  reads "Updated tasks · 2/5 done" with the checklist. The list comes from
  the transcript, so it survives a restart.

Both checked with a real model over RPC: it wrote a task list, asked a
question, got the answer through the dialog channel, and finished the list.

### `send_file` and `notify`

Desktop tools every chat gets (`apps/desktop/src/features/chat/user-tools.ts`):

- `send_file {paths (1–10), caption?}` — checks the files exist and puts them
  in the chat as cards (name, size, folder; Open, View in Files, Show in
  folder). The cards stay visible when the finished turn folds its steps.
- `notify {title, body?}` — an app notification (and a system one when the
  window is in the background) that opens the chat; at most one per chat
  every 30 seconds; Do not disturb and muting apply.

## What a full desktop agent has, and evo

| Capability | evo |
| --- | --- |
| Files: read, write, edit, find, grep, ls | built in |
| Shell: bash, PowerShell, background commands | built in |
| Subagents (`agent`, `message_agent`), nested sessions | built in |
| Skills (`skill`), memory (`memory`) | built in |
| Web search and fetch | built in (`web_search`, `web_fetch`) |
| Browser, terminal, show a file in the app | desktop tools (`browser_*`, `terminal_*`, `show_file`) |
| Connectors (MCP) and tool search | desktop |
| Scheduled tasks | desktop (`create_scheduled_task`, …) |
| Questions with options | `ask_user` |
| Visible task list | `update_todos` |
| Plan mode: explore read-only, then present a plan to approve before editing | not yet (`plan_mode_start` / `plan_mode_complete` are reserved names) |
| Send a file to the person (a card in the chat) | `send_file` |
| End-of-turn summary with a next-step question | not yet |
| Notify the person when a long run needs them | `notify` |
| Code intelligence (diagnostics, definitions, references) | `lsp` (see [code intelligence](../code-intelligence/sdd.md)) |
