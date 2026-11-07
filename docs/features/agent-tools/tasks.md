# Agent tools for working with the person — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

### Phase 1 — `ask_user` and `update_todos`

Done when: with a real model over RPC, the agent writes a task list, asks a
question, gets the answer through the dialog channel and finishes the list.

- [x] T1 [FR-1, FR-2, FR-3, FR-4] `ask_user`: schema, checks, dialog request, answer formatting, dismissed and headless results, description — `crates/evo-engine/src/interaction.rs` — check: `cargo test -p evo-engine questions_are_checked`, `answers_read_well`
- [x] T2 [FR-8, NFR-1] `update_todos`: schema, checks, summary, no engine state — `crates/evo-engine/src/interaction.rs` — check: `cargo test -p evo-engine todos_are_summarized`
- [x] T3 [P] [FR-5, FR-6, FR-7] Questions panel, background notification, transcript row — `apps/desktop/src/features/chat/questions-panel.tsx` — check: manual check in the running app
- [x] T4 [P] [FR-9, FR-10, NFR-1] Todo bar and transcript row, rebuilt from the transcript — `apps/desktop/src/features/chat/todo-bar.tsx` — check: manual check in the running app, including a restart
- [x] T5 [FR-1, FR-2, FR-8] End-to-end check with a real model over RPC — check: task list written, question answered through the dialog channel, list finished

### Phase 2 — `send_file` and `notify`

Done when: every chat has both tools; files show as cards and notifications
reach the person.

- [x] T6 [FR-11] `send_file` desktop tool and file cards — `apps/desktop/src/features/chat/user-tools.ts` — check: manual check in the running app
- [x] T7 [FR-12] `notify` desktop tool with the 30-second per-chat limit — `apps/desktop/src/features/chat/user-tools.ts` — check: manual check in the running app

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-engine questions_are_checked`; real model over RPC | unit test not run; RPC check passed (date not recorded) |
| FR-2 | `cargo test -p evo-engine answers_read_well`; real model over RPC | unit test not run; RPC check passed (date not recorded) |
| FR-3 | Manual check: skip in the panel; a headless run | not run |
| FR-4 | Review of the `ask_user` tool description | not run |
| FR-5 | Manual check in the running app: multi-question call, keyboard only | not run |
| FR-6 | Manual check: `ask_user` in a background chat notifies | not run |
| FR-7 | Manual check: "Asked you · question" row | not run |
| FR-8 | `cargo test -p evo-engine todos_are_summarized`; real model over RPC | unit test not run; RPC check passed (date not recorded) |
| FR-9 | Manual check: todo bar during and after a turn | not run |
| FR-10 | Manual check: "Updated tasks · 2/5 done" row | not run |
| FR-11 | Manual check: `send_file` cards stay after the turn folds | not run |
| FR-12 | Manual check: two `notify` calls within 30 s give one notification | not run |
| NFR-1 | Manual check: restart the app, the todo bar shows the same list | not run |
