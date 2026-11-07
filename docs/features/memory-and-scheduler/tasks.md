# Memory and the Scheduler — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

### Phase 1 — Memory in the engine

Done when: the agent saves, reads, lists and forgets memories in both
scopes, and the system prompt carries the Memory section and indexes.

- [x] T1 [FR-1, FR-2, FR-3, NFR-1] Memory files, folders and indexes — `crates/evo-engine/src/memory.rs` — check: `cargo test -p evo-engine save_list_rename_and_delete_keep_the_index`, `project_memories_live_outside_the_project`, `names_are_cleaned`
- [x] T2 [FR-4, FR-7] `prompt_block` and the `memoryEnabled` switch — `crates/evo-engine/src/memory.rs` — check: manual, a chat's system prompt with memory on and off
- [x] T3 [FR-5, FR-7] The `memory` tool — `crates/evo-engine/src/memory.rs` — check: manual, each action from a chat
- [x] T4 [FR-9] RPC `list_memories`, `save_memory`, `delete_memory`, `set_memory_enabled` — `crates/evo-engine/src/modes.rs` — check: manual from the panel

### Phase 2 — Memory in the app

Done when: the panel manages memories and transcript rows name each action.

- [x] T5 [P] [FR-8, FR-9] Memory panel — `apps/desktop/src/features/memory/` — check: manual in the running app
- [x] T6 [P] [FR-6] Memory transcript rows — `apps/desktop/src/components/ai-elements/tool.tsx` — check: manual in the running app

### Phase 3 — Scheduler

Done when: tasks run on their schedules as new chats, and agents can manage
them with approval.

- [x] T7 [FR-11] Schedule kinds and cron — `apps/desktop/src/lib/schedule.ts` — check: manual, next run shown for each kind
- [x] T8 [FR-10, FR-12, FR-13, FR-14, FR-16, NFR-2] Task store and runner — `apps/desktop/src/stores/scheduler-store.ts` — check: manual in the running app
- [x] T9 [P] [FR-17] Scheduler agent tools — `apps/desktop/src/features/scheduler/agent-tools.ts` — check: manual, an agent's create shows the approval
- [x] T10 [P] [FR-18] Scheduler page — `apps/desktop/src/features/scheduler/scheduler-page.tsx`, `time-fields.tsx` — check: manual in the running app
- [x] T11 [P] [FR-15] Tray and Keep awake keep runs going — `apps/desktop/src/features/settings/sections/general-settings.tsx` — check: manual in the running app

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-engine project_memories_live_outside_the_project` | not run |
| FR-2 | `cargo test -p evo-engine save_list_rename_and_delete_keep_the_index`, `names_are_cleaned` | not run |
| FR-3 | Review of the `memory` tool schema | not run |
| FR-4 | Manual: system prompt of a new chat with memories | not run |
| FR-5 | `cargo test -p evo-engine save_list_rename_and_delete_keep_the_index`; manual tool calls from a chat | not run |
| FR-6 | Manual: transcript rows after each memory action | not run |
| FR-7 | Manual: `memoryEnabled: false`, then start a chat and call the tool | not run |
| FR-8 | Manual: Memory panel in the running app | not run |
| FR-9 | Manual: edit in the panel, then message another idle chat | not run |
| FR-10 | Manual: run history on the Scheduler page | not run |
| FR-11 | Manual: next run for each schedule kind on the Scheduler page | not run |
| FR-12 | Manual: a task due now starts its chat | not run |
| FR-13 | Manual: a run due while the previous chat works is skipped | not run |
| FR-14 | Manual: caught-up run after a restart; a one-time task switches off | not run |
| FR-15 | Manual: close the window with the tray icon on; a task still runs | not run |
| FR-16 | Manual: notification on start opens the chat | not run |
| FR-17 | Manual: an agent creates a task; the approval shows first | not run |
| FR-18 | Manual: Scheduler page in the running app | not run |
| NFR-1 | `cargo test -p evo-engine project_memories_live_outside_the_project` | not run |
| NFR-2 | Manual: a task due in a minute starts within 20 s | not run |
