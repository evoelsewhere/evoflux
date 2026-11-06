# Agent tools for working with the person

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
  (like an approval): a card per question, radio or check options, "answer in
  your own words", digits pick the first question's options, `Ctrl+Enter`
  sends, "Skip — let the agent decide" dismisses. A chat in the background
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
| Code intelligence (diagnostics, definitions, references) | `lsp` (see `code-intelligence.md`) |
