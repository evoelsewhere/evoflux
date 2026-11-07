# Memory and the Scheduler — Plan

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Tasks | [tasks.md](tasks.md) |
| Updated | 2026-11-07 |
| ADD sections | [7. Data view](../../architecture/README.md#7-data-view) |
| ADRs | none |

## 1. Context and constraints

- The engine builds each chat's system prompt and re-reads the chat's
  resources on `reload_resources`; idle engines reload on app changes
  ([ADR 0005](../../architecture/decisions/0005-real-engine-and-live-reload.md)).
- The agent dir is `~/.evo/agent/` (relocatable by `EVO_CODING_AGENT_DIR`,
  [ADD 7](../../architecture/README.md#7-data-view)).
- The desktop already offers app-implemented agent tools to the engine as
  external tools, with approvals in the composer.
- Scheduled runs need evo running; the tray icon keeps it running with the
  window closed, and Keep awake stops the computer from sleeping.
- Paths are relative to the repository root.

## 2. Architecture check

| Rule | Result | Notes |
| --- | --- | --- |
| The engine owns agent logic; the shell relays and provides native features | ok | Memory (files, prompt section, tool) lives in the engine. The Scheduler starts chats and sends prompts like the person would; its agent tools are external tools offered by the app, and the engine still runs the loop and the approval. |
| Layers point down; library crates stay free of engine/desktop concerns | ok | No library crate changes. |
| Protocol changes update `evo-protocol`, the engine and the desktop together | ok | Memory RPC commands ship with the desktop panel that calls them. |
| Models come from models.dev; no hardcoded model facts | n/a | No model facts involved. |
| Real engine in the app; settings and credentials reload live | ok | Memory changes re-read the chat's resources and reload idle chats; `memoryEnabled` applies without restart. |
| Untrusted input stays untrusted; permissions, sandbox and project trust stay in the path | ok | Remembered text is untrusted data; the prompt tells the agent to check a memory is still true before relying on it. Scheduler tool calls that create, change or delete show an approval first. |
| Desktop UI structure and `DESIGN.md` | ok | The Memory panel and the Scheduler page are features reading stores; the scheduler store talks to the engine only through the engine store. |

## 3. Design

### 3.1 Overview

```text
 Memory
   agent ──memory tool──► engine memory.rs ──► <agent dir>/memory/*.md
                                   │            <agent dir>/projects/<slug>/memory/*.md
                                   └─ prompt_block → "# Memory" section + both MEMORY.md indexes
   Memory panel ──RPC list/save/delete/set_enabled──► engine ──► reload other idle chats

 Scheduler
   scheduler-store (main window, every 20 s) ──due?──► new top-level chat ──► prompt
        ▲  saved in app DB `scheduler.tasks`
   agent ──create/list/update/delete_scheduled_task (external tools, approval)──┘
   Scheduler page ──────────────────────────────────────────────────────────────┘
```

Memory is engine-owned files plus a prompt section. The Scheduler lives in
the desktop: it stores tasks in the app database and, from the main window,
starts the due ones as new chats.

### 3.2 Components

| Layer | Path | Responsibility | Requirements |
| --- | --- | --- | --- |
| engine | `crates/evo-engine/src/memory.rs` | Memory files and indexes, `prompt_block`, the `memory` tool, `describe` for the RPC list. | FR-1, FR-2, FR-3, FR-4, FR-5, FR-7, NFR-1 |
| engine | `crates/evo-engine/src/modes.rs` | RPC `list_memories`, `save_memory`, `delete_memory`, `set_memory_enabled`; each change re-reads the chat's resources. | FR-7, FR-9 |
| desktop UI | `apps/desktop/src/features/memory/` (`memory-panel.tsx`) | The Memory tool in the side panel. | FR-8, FR-9 |
| desktop UI | `apps/desktop/src/components/ai-elements/tool.tsx` | Memory transcript rows. | FR-6 |
| desktop UI | `apps/desktop/src/stores/scheduler-store.ts` | Tasks saved under `scheduler.tasks`; the 20-second check, run start, skip, catch-up, run history, notifications. | FR-10, FR-12, FR-13, FR-14, FR-16, NFR-2 |
| desktop UI | `apps/desktop/src/lib/schedule.ts` | Schedule kinds, cron parsing, next run in local time. | FR-11 |
| desktop UI | `apps/desktop/src/features/scheduler/agent-tools.ts` | The four scheduler tools for top-level chats, with approval. | FR-17 |
| desktop UI | `apps/desktop/src/features/scheduler/scheduler-page.tsx`, `time-fields.tsx` | **Sidebar → Scheduler** page. | FR-18 |
| desktop UI | tray and Keep awake (`apps/desktop/src/features/settings/sections/general-settings.tsx`) | Keep evo running with the window closed; stop sleep. | FR-15 |

### 3.3 Interfaces

Agent tool `memory` (engine):

```jsonc
{
  "action": "save | read | list | delete",
  "scope": "personal | project",   // default project
  "name": "kebab-case-name",
  "description": "one line, used to judge relevance",
  "type": "user | feedback | project | reference",
  "content": "the memory; for feedback and project, why and how to apply"
}
```

`save` with an existing name replaces it (the result says `updated`).

RPC commands (engine):

| Command | Params |
| --- | --- |
| `list_memories` | — |
| `save_memory` | `{scope, name, description, kind, content, previous?}` — `kind` is the memory type; `previous` renames |
| `delete_memory` | `{scope, name}` |
| `set_memory_enabled` | `{enabled}` |

Scheduler agent tools (external tools offered by the app to top-level
chats):

```ts
type Schedule =
  | { kind: "manual" }
  | { kind: "once"; at: number }
  | { kind: "hourly"; minute: number }
  | { kind: "daily"; time: string }
  | { kind: "weekdays"; time: string }
  | { kind: "weekly"; time: string; days: number[] }
  | { kind: "cron"; expression: string };

create_scheduled_task { name, prompt, schedule: Schedule, folder? }  // folder defaults to the chat's
list_scheduled_tasks  {}
update_scheduled_task { id, name?, prompt?, schedule?, folder?, enabled? }
delete_scheduled_task { id }
```

### 3.4 Data and storage

- Personal memories: `<agent dir>/memory/` (`~/.evo/agent/memory/`).
- A project's memories: `<agent dir>/projects/<folder slug>/memory/`; the
  slug is the folder's path with every non-alphanumeric character turned
  into `-` (`C:\work\app` → `C--work-app`). Outside the repository.
- One markdown file per memory, `<name>.md`, with frontmatter `name`,
  `description`, `type` and `updated` (ms), then the memory itself.
  `MEMORY.md` in each folder is the index, one line per memory, rewritten on
  every change.
- `memoryEnabled` in `~/.evo/agent/settings.json`.
- Scheduler tasks: the app database under `scheduler.tasks` — name, prompt,
  folder (`null`: this computer), schedule, on/off, creator, next run, last
  30 runs (time, chat, trigger, or error).

### 3.5 Behaviour

Memory in a chat:

1. At start and on every resource reload, `prompt_block` adds a `# Memory`
   section to the system prompt (with the append text): when to save and
   what not to save, update rather than duplicate, read before relying and
   check it is still true, then both indexes (at most 200 lines each).
2. The agent calls `memory`; files and the index change; the transcript row
   names the action.
3. The panel re-reads after each turn of the active chat. A change from the
   panel re-reads the chat's resources; the app reloads the other idle chats
   so the new index applies from their next message.

Scheduler:

1. The main window checks every 20 seconds for due tasks.
2. For each due task whose previous chat is not still working, it creates a
   new top-level chat in the task's folder (making the folder a workspace if
   needed), titled with the task's name, and sends the prompt once the
   engine is ready. The chat shows in the sidebar, unread when done.
3. A notification says the task started (or could not) and opens the chat.
4. At launch, a task missed while evo was closed runs once with trigger
   "caught up", then continues from now. A one-time task switches itself
   off after it ran.
5. Every repeating kind is a cron expression underneath; times are local.

### 3.6 Errors and edge cases

- Memory off: no prompt section, the tool refuses.
- A run that could not start records the error in the run history and says
  so in the notification.
- A run due while the previous chat works is skipped.
- evo closed: no runs; one caught-up run at the next launch.

### 3.7 Security and trust

- Memories may hold what the person said; they stay outside the repository
  (NFR-1) and the prompt says not to save secrets.
- Remembered text is untrusted data; the agent is told to check a memory is
  still true before relying on it.
- An agent cannot create, change or delete a scheduled task without the
  person's approval in the composer; only top-level chats get the tools.
- A scheduled run is an ordinary chat: the folder's trust, permissions and
  sandbox apply as for any chat.

### 3.8 Configuration

| Key | Type | Default | Where | Applies |
| --- | --- | --- | --- | --- |
| `memoryEnabled` | boolean | on | `~/.evo/agent/settings.json` | through `set_memory_enabled`; edited by the switch in the Memory panel |
| `scheduler.tasks` | list of tasks | empty | app database | live; edited on the Scheduler page and by the scheduler tools |

## 4. Alternatives considered

n/a — the old design notes record no alternatives.

## 5. As-built notes

n/a — built as described above; no recorded deviations.
