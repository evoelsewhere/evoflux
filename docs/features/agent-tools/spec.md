# Agent tools for working with the person — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | engine, desktop UI |
| Created | 2026-11-06 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Notifications](../notifications/spec.md), [Code intelligence](../code-intelligence/spec.md) |

## 1. Summary

Tools that let the agent work with the person, not only with files: ask
questions with options when a real decision is needed (`ask_user`), keep a
visible task list (`update_todos`), hand the person a file as a card in the
chat (`send_file`), and notify them when a long run needs them (`notify`).
The tool names and inputs below are what the model sees.

Where these tools sit among everything a full desktop agent offers:

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
| Code intelligence (diagnostics, definitions, references) | `lsp` (see [code intelligence](../code-intelligence/spec.md)) |

## 2. Scope

### 2.1 Goals

- The agent can ask the person for a decision and wait for the answer.
- The person sees the agent's plan of work and its progress at a glance.
- The agent can put files in front of the person.
- The agent can call the person back when a long run needs them.

### 2.2 Non-goals

- Asking for things the agent can find out itself, or asking "may I
  proceed?" — approvals are a separate mechanism.
- Plan mode and an end-of-turn summary with a next-step question (not yet, see
  6.2).
- The other capabilities in the table above; they live in their own
  features.

## 3. User scenarios

### US-1 Answer the agent's question (priority P1)

A person wants the agent to ask them when a real decision is needed, with
options to pick from, so that the agent does not guess.

Acceptance scenarios:

1. **Given** the agent asks two questions with options, **when** the person
   picks an option for each and sends, **then** the agent continues with
   both answers.
2. **Given** a question, **when** the person writes their own answer instead
   of picking an option, **then** the agent gets their words.
3. **Given** a question, **when** the person chooses "Skip — let the agent
   decide", **then** the agent decides and says what it assumed.

### US-2 Follow the agent's progress (priority P1)

A person wants to see the agent's task list and which task is in progress,
so that they know how far a long task is.

Acceptance scenarios:

1. **Given** the agent writes a task list, **when** it marks tasks done,
   **then** the bar above the chat input shows `done/total` and the task in
   progress.
2. **Given** a chat with a task list, **when** the app restarts, **then** the
   list is shown again.

### US-3 Receive a file from the agent (priority P2)

A person wants the agent to hand them the files it made, so that they can
open them directly.

Acceptance scenarios:

1. **Given** the agent sends two files, **when** the turn finishes, **then**
   two cards stay visible in the chat with Open, View in Files and Show in
   folder.

### US-4 Be called back (priority P2)

A person working elsewhere wants the agent to notify them when a long run
needs them.

Acceptance scenarios:

1. **Given** the window is in the background, **when** the agent calls
   `notify`, **then** a system notification appears and opening it leads to
   the chat.

### Edge cases

- No one can answer (a headless run): `ask_user` returns an error telling
  the agent to decide and say what it assumed.
- A question arrives while its chat is in the background: the app notifies,
  as it does for approvals.
- The agent calls `notify` repeatedly: at most one notification per chat
  every 30 seconds.
- `send_file` with a path that does not exist: the tool checks the files
  exist.

## 4. Requirements

### 4.1 Functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | `ask_user` takes 1–4 `questions`, each with `question`, an optional `header` (a short chip), 0 or 2–6 `options` (`label`, optional `description`) and `multi_select`. No options means a free answer; a free answer is always possible. | Given 5 questions, or a question with 1 option, when the tool runs, then it is refused; given 1–4 valid questions, it opens the dialog. |
| FR-2 | `ask_user` waits for the person's answer and returns it to the model as a readable list: `1. question → "choice", (their own words) …`. | Given answers to two questions, when they are sent, then the model reads one line per question with the choices and free text. |
| FR-3 | A dismissed `ask_user` tells the model to decide and say what it assumed; with no one to ask (a headless run) it returns an error saying the same. | Given the person skips, when the tool returns, then the result tells the model to decide and state its assumption. |
| FR-4 | The `ask_user` description keeps it for real decisions: not for what the agent can find out itself, never "may I proceed?". | Review of the tool description. |
| FR-5 | The questions panel takes the chat input's place (like an approval): one question per step ("2 of 4"), a chip per question with a check once answered (click to jump), Back / Next, radio or check options, "answer in your own words". A single-choice pick moves to the next question after a beat; digits pick the shown question's options; `Enter` goes next (sends on the last step) while focus is in the panel; `Ctrl+Enter` sends once all are answered; "Skip — let the agent decide" dismisses. | Manual check in the running app with a multi-question call, keyboard only. |
| FR-6 | A question in a chat in the background notifies, as approvals do. | Given the chat is in the background, when `ask_user` opens, then a notification appears. |
| FR-7 | The transcript row for `ask_user` reads "Asked you · question" with the answers. | Manual check in a finished turn. |
| FR-8 | `update_todos` takes the whole list, each item with `content`, `status` (`pending`, `in_progress`, `completed`) and an optional `active_form` (shown while in progress). It checks the list and answers with a summary ("1 of 3 done. In progress: …"), nudging to keep exactly one task in progress. The engine keeps no state for it. | Given a list with two tasks in progress, when the tool runs, then the summary nudges to keep exactly one in progress. |
| FR-9 | The todo bar pins the latest list of the latest turn above the chat input: progress bar, `done/total`, the task in progress (spinner while the turn runs), collapsible. | Manual check in the running app. |
| FR-10 | The transcript row for `update_todos` reads "Updated tasks · 2/5 done" with the checklist. | Manual check in a finished turn. |
| FR-11 | Every chat has `send_file {paths (1–10), caption?}`: it checks the files exist and puts them in the chat as cards (name, size, folder; Open, View in Files, Show in folder). The cards stay visible when the finished turn folds its steps. | Given two existing files, when the tool runs, then two cards show and stay after the turn folds. |
| FR-12 | Every chat has `notify {title, body?}`: an app notification (and a system one when the window is in the background) that opens the chat; at most one per chat every 30 seconds; Do not disturb and muting apply. | Given two calls within 30 s, when they run, then only one notification appears. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | The task list survives an app restart: it is rebuilt from the transcript. | Given a chat with a task list, when the app restarts, then the todo bar shows the same list. |

## 5. Success criteria

- SC-1 A person can answer up to four questions from the keyboard alone.
- SC-2 A person sees how far a multi-step task is at a glance, also after a
  restart.
- SC-3 With a real model, an agent writes a task list, asks a question, gets
  the answer and finishes the list.

## 6. Clarifications

### 6.1 Open

None.

### 6.2 Resolved

- 2026-11-07 — Q: Should evo add plan mode (explore read-only, then present a plan
  to approve before editing)? → A: Not yet; `plan_mode_start` /
  `plan_mode_complete` stay reserved until it is specified (section 2.2).
- 2026-11-07 — Q: Should evo add an end-of-turn summary with a next-step question?
  → A: Not yet; specify it when wanted (section 2.2).

## 7. History

- 2026-11-06 — `ask_user` and `update_todos` built; `send_file` and
  `notify` documented; legacy single-file format.
- 2026-11-07 — Moved to the spec / plan / tasks format.
- 2026-11-07 — Open clarifications answered by the owner (accepted as proposed).
