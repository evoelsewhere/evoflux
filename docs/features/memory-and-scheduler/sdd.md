# Memory and the Scheduler

| | |
| --- | --- |
| Status | Implemented |
| Area | engine, desktop UI |
| Format | Legacy — predates [the SDD template](../../templates/sdd.md); move to it on the next substantial edit |
| Updated | 2026-11-06 |
| ADD sections | [7. Data view](../../architecture/README.md#7-data-view) |
| ADRs | none |

Status: built. Paths are relative to the repository root.

## Memory

What the agent keeps across chats, so it gets more useful over time.

### Where it lives

- Personal memories (every project): `<agent dir>/memory/`
  (`~/.evo/agent/memory/`).
- A project's memories: `<agent dir>/projects/<folder slug>/memory/`, where the
  slug is the folder's path with every non-alphanumeric character turned into
  `-` (`C:\work\app` → `C--work-app`). They sit outside the repository, so
  they stay private and never end up in a commit.
- One markdown file per memory, `<name>.md` (kebab-case name), with
  frontmatter `name`, `description` (one line, used to judge relevance),
  `type` and `updated` (ms), then the memory itself. `MEMORY.md` in each
  folder is the index, one line per memory, rewritten on every change.

### Types

| type | holds |
| --- | --- |
| `user` | who the person is: role, expertise, preferences |
| `feedback` | how they want the agent to work: corrections and confirmed approaches, with why and how to apply |
| `project` | goals, decisions, deadlines, constraints of ongoing work (dates written in full) |
| `reference` | where things live outside the code |

### In a chat

- `crates/evo-engine/src/memory.rs` `prompt_block` adds a `# Memory` section
  to the system prompt (with the append text, at start and on every resource
  reload): when to save and what not to save (secrets, one-off details, what
  the repository already records), to update rather than duplicate, to read
  a memory before relying on it and check it is still true, then both
  indexes (at most 200 lines each).
- The `memory` tool: `save` (name, description, type, content, scope; the
  same name replaces), `read`, `list`, `delete`. Scope `project` by default.
- The transcript shows "Saved memory · name", "Updated memory · name",
  "Read memory", "Forgot · name"; a save shows what was saved.
- `memoryEnabled: false` in `~/.evo/agent/settings.json` switches it off:
  no section in the prompt, and the tool refuses.

### In the app

- The Memory tool in the side panel (`apps/desktop/src/features/memory/`):
  memories of this project and of every project, search, filter by type,
  open one to read it, edit, forget (with a confirm), add, show in folder,
  and the on/off switch. It re-reads after each turn of the active chat.
- RPC: `list_memories`, `save_memory {scope, name, description, kind,
  content, previous?}` (`kind` is the memory type; `previous` renames),
  `delete_memory {scope, name}`, `set_memory_enabled {enabled}`. Each change
  re-reads the chat's resources; the app reloads the other idle chats, so the
  new index applies from their next message.

## Scheduler

Prompts that run on a schedule, each run as a new chat.

### Tasks

- A task: name, prompt, folder (`null`: this computer), schedule, on/off,
  who made it (you, or an agent with your approval), next run, last 30 runs
  (time, chat, trigger: schedule, run now, or caught up; or the error).
- Saved in the app database under `scheduler.tasks`
  (`apps/desktop/src/stores/scheduler-store.ts`).
- Schedules (`apps/desktop/src/lib/schedule.ts`): manual (only Run now),
  once (date and time), hourly (at minute), daily, weekdays, weekly (days and
  time), or a five-field cron expression (`*`, lists, ranges, `/step`; day
  of month and day of week combine as in cron). Local time. Every repeating
  kind is a cron expression underneath.

### Running

- The main window checks every 20 seconds and starts the tasks that are due:
  a new top-level chat in the task's folder (the folder becomes a workspace
  if it is not one), titled with the task's name, its prompt sent once the
  engine is ready. It shows in the sidebar like any chat, unread when done.
- A run whose previous chat is still working is skipped.
- At launch, a task missed while evo was closed runs once ("caught up"),
  then continues from now. A one-time task switches itself off after it ran.
- Runs need evo running: with the tray icon on, closing the window keeps it
  going; Keep awake stops the computer from sleeping.
- A notification says when a task starts (or could not); it opens the chat.

### Tools for chats

Top-level chats get `create_scheduled_task`, `list_scheduled_tasks`,
`update_scheduled_task` and `delete_scheduled_task`
(`apps/desktop/src/features/scheduler/agent-tools.ts`). Creating, changing
and deleting show an approval in the composer first; the default folder is
the chat's.

### The page

Sidebar → Scheduler opens a full page (`features/scheduler/scheduler-page.tsx`):
tasks on the left (switch, schedule, next run), the chosen task on the right
(name, prompt, folder, schedule editor with the next run, Run now, on/off,
delete, past runs that open their chats), and examples to start from.
