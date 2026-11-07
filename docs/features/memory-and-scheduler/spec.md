# Memory and the Scheduler — Spec

| | |
| --- | --- |
| Status | Implemented |
| Area | engine, desktop UI |
| Created | 2026-11-06 |
| Updated | 2026-11-07 |
| Plan | [plan.md](plan.md) |
| Tasks | [tasks.md](tasks.md) |
| Related | [Notifications](../notifications/spec.md), [Approval modes](../approval-modes/spec.md) |

## 1. Summary

**Memory** is what the agent keeps across chats, so it gets more useful over
time: who the person is, how they want it to work, what is going on in a
project and where things live. The agent saves and reads memories itself;
the person sees, edits and forgets them in the app, and can switch memory
off.

**The Scheduler** runs prompts on a schedule, each run as a new chat. The
person, or an agent with the person's approval, creates tasks; evo starts
them when they are due while it is running.

## 2. Scope

### 2.1 Goals

- Memories that apply to every project and memories private to one project.
- An agent tool to save, read, list and forget memories, with guidance in
  the system prompt on what is worth keeping.
- A panel to browse, search, edit, add and forget memories.
- Scheduled prompts with common schedules and cron expressions, run as new
  chats, with a run history.
- Tools so a chat can manage scheduled tasks, behind an approval.

### 2.2 Non-goals

- Runs while evo is closed: tasks need evo running; a missed task runs once
  when evo starts again.
- Memories stored in the repository: project memories stay outside it so
  they never end up in a commit.

## 3. User scenarios

### US-1 The agent remembers a correction (priority P1)

A person wants the agent to keep a correction or preference so that they do
not repeat it in every chat.

Acceptance scenarios:

1. **Given** memory is on, **when** the person corrects how the agent
   works, **then** the agent saves a feedback memory and the transcript
   shows "Saved memory · name".
2. **Given** a saved memory, **when** a new chat starts, **then** the
   memory index is in the agent's context and the agent can read the memory.
3. **Given** a memory with the same name, **when** the agent saves again,
   **then** the memory is replaced, not duplicated.

### US-2 The person manages what is remembered (priority P1)

A person wants to see and change what the agent keeps so that it stays true
and private.

Acceptance scenarios:

1. **Given** memories exist, **when** the person opens the Memory panel,
   **then** they see this project's and every project's memories, can
   search, filter by type, read, edit, add and forget (with a confirm).
2. **Given** the person switches memory off, **when** a chat runs, **then**
   the agent gets no memory section and the tool refuses.

### US-3 A prompt runs every morning (priority P1)

A person wants a prompt to run on a schedule so that routine work happens
without them starting it.

Acceptance scenarios:

1. **Given** a daily task at 09:00, **when** 09:00 passes while evo runs,
   **then** a new chat titled with the task's name starts in the task's
   folder with the prompt, and a notification opens it.
2. **Given** evo was closed at 09:00, **when** it starts later, **then** the
   task runs once ("caught up") and continues from now.
3. **Given** the previous run's chat is still working, **when** the next run
   is due, **then** that run is skipped.

### US-4 An agent schedules a task (priority P2)

A person wants to ask a chat to set up a scheduled task so that they do not
fill the form themselves.

Acceptance scenarios:

1. **Given** a top-level chat, **when** the agent creates, changes or
   deletes a task, **then** an approval shows in the composer first, and the
   default folder is the chat's.

### Edge cases

- A one-time task switches itself off after it ran.
- A task with no folder runs on "this computer".
- A task whose folder is not a workspace yet: the folder becomes one.
- A task that could not start: the notification says so; the run history
  keeps the error.
- Saving a memory from the app while other chats are idle: they get the new
  index from their next message.

## 4. Requirements

### 4.1 Functional

Memory:

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-1 | Memories have two scopes: personal (every project) and project (one project folder). | Given both scopes, when the agent lists memories, then each shows its scope. |
| FR-2 | Each memory has a kebab-case name, a one-line description (used to judge relevance), a type and an update time, then its text; each scope has an index with one line per memory, rewritten on every change. | Given a save, rename and delete, then the index matches the memories. |
| FR-3 | A memory's type is one of: `user` (who the person is: role, expertise, preferences), `feedback` (how they want the agent to work: corrections and confirmed approaches, with why and how to apply), `project` (goals, decisions, deadlines, constraints of ongoing work, dates written in full), `reference` (where things live outside the code). | Given the `memory` tool's schema, then `type` offers exactly these four values. |
| FR-4 | The system prompt gets a Memory section, with the append text, at start and on every resource reload: when to save and what not to save (secrets, one-off details, what the repository already records), to update rather than duplicate, to read a memory before relying on it and check it is still true, then both indexes (at most 200 lines each). | Given memories, when a chat starts, then its system prompt holds the section and both indexes. |
| FR-5 | The agent has a `memory` tool: `save` (name, description, type, content, scope; the same name replaces), `read`, `list`, `delete`; scope `project` by default. | Given each action, then the files and index change as described. |
| FR-6 | The transcript shows "Saved memory · name", "Updated memory · name", "Read memory", "Forgot · name"; a save shows what was saved. | Manual check in the running app. |
| FR-7 | Memory can be switched off: then no section is in the prompt and the tool refuses. | Given memory off, when a chat starts, then no Memory section; when the tool is called, then it refuses. |
| FR-8 | The Memory tool in the side panel shows memories of this project and of every project, with search, filter by type, open to read, edit, forget (with a confirm), add, show in folder, and the on/off switch; it re-reads after each turn of the active chat. | Manual check in the running app. |
| FR-9 | A change made in the app re-reads the chat's resources, and the other idle chats reload, so the new index applies from their next message. | Given an edit in the panel, when another idle chat sends a message, then it sees the new index. |

Scheduler:

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| FR-10 | A task has a name, a prompt, a folder (none: this computer), a schedule, on/off, who made it (the person, or an agent with approval), the next run, and the last 30 runs (time, chat, trigger — schedule, run now or caught up — or the error). | Given a task with 31 runs, then 30 are kept. |
| FR-11 | Schedules: manual (only Run now), once (date and time), hourly (at minute), daily, weekdays, weekly (days and time), or a five-field cron expression (`*`, lists, ranges, `/step`; day of month and day of week combine as in cron), in local time. | Given each kind, then the next run shown is correct. |
| FR-12 | A due task starts a new top-level chat in the task's folder (the folder becomes a workspace if it is not one), titled with the task's name, its prompt sent once the engine is ready; it shows in the sidebar like any chat, unread when done. | Manual: a task due now starts its chat. |
| FR-13 | A run whose previous chat is still working is skipped. | Given a running chat from the last run, when the next run is due, then no new chat starts. |
| FR-14 | At launch, a task missed while evo was closed runs once ("caught up"), then continues from now. A one-time task switches itself off after it ran. | Manual: close evo past a run time, start it, and see one caught-up run. |
| FR-15 | With the tray icon on, closing the window keeps runs going; Keep awake stops the computer from sleeping. | Manual check in the running app. |
| FR-16 | A notification says when a task starts (or could not); it opens the chat. | Manual check in the running app. |
| FR-17 | Top-level chats get tools to create, list, update and delete scheduled tasks; creating, changing and deleting show an approval in the composer first; the default folder is the chat's. | Given an agent's create call, then the approval shows before the task exists. |
| FR-18 | **Sidebar → Scheduler** opens a full page: tasks on the left (switch, schedule, next run); the chosen task on the right (name, prompt, folder, schedule editor with the next run, Run now, on/off, delete, past runs that open their chats); and examples to start from. | Manual check in the running app. |

### 4.2 Non-functional

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| NFR-1 | Project memories live outside the repository, so they stay private and never end up in a commit. | Given a project memory, then no file is written inside the project folder. |
| NFR-2 | A due task starts within 20 seconds of its time while evo runs. | Manual: a task due in a minute starts within 20 s of its time. |

## 5. Success criteria

- SC-1 A preference told to the agent once is followed in a later chat in
  the same project without being repeated.
- SC-2 A daily task created in the morning runs every day while evo is
  running, and a missed day runs once when evo starts again.
- SC-3 No memory file ever appears in the project's version control.

## 6. Clarifications

### 6.1 Open

n/a — no open questions.

### 6.2 Resolved

n/a — the old design notes record no questions.

## 7. History

- 2026-11-06 — Built.
- 2026-11-07 — Moved to the spec / plan / tasks format.
