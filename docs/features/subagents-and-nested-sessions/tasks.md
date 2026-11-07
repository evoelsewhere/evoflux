# Subagents and nested sessions — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

Phases 1 and 3 are independent and were built in parallel; phase 2 builds on
phase 1, phase 4 on phases 1 and 3. Engine tests below run with
`cargo test -p evo-engine <name>` (faux provider); `evo-store` and
`evo-worktrees` tests with `cargo test -p <crate> <name>`.

### Phase 1 — Foreground subagents

Done when: a model call runs an `explore` child, the UI shows its steps live
and its report, the cost includes the child, and tests with the faux
provider pass.

- [x] T1 [FR-1] [FR-2] [NFR-3] Agent type loader beside `load_skills`, public `parse_frontmatter`, built-in `general` / `explore` / `plan` with their prompts and report formats — `crates/evo-engine/src/agents.rs`, `crates/evo-harness/src/frontmatter.rs`, `crates/evo-harness/src/skills.rs` — check: `files_define_types_and_project_wins`, `access_thinking_and_turns_are_read_and_checked`, `explore_and_plan_are_read_only_and_general_is_not`, `a_file_can_replace_a_builtin`, `an_agent_file_added_later_is_usable_at_once`
- [x] T2 [FR-3] Read-only guard (`ChildToolGuard`) before the approval prompt and before the call runs; shell command allow-lists — `crates/evo-engine/src/read_only.rs`, `crates/evo-harness/src/agent_harness/child.rs` — check: `bash_reading_commands_pass`, `bash_writing_commands_are_refused`, `powershell_reading_commands_pass`, `powershell_writing_commands_are_refused`, `guard_passes_reading_tools_and_refuses_the_rest`, `explore_agents_cannot_write`, `read_only_agents_cannot_write_through_the_shell_or_their_tools`
- [x] T3 [FR-4] [FR-7] [FR-8] Built-in `agent` tool built in `build_tools` with the late-bound harness handle (also on `/reload`); per-type setup; foreground run; limits; report cut at 16 KiB — `crates/evo-engine/src/agent_tool.rs`, `crates/evo-engine/src/session.rs` — check: `a_subagent_works_and_reports_back`, `unknown_types_and_models_are_refused`, `long_reports_are_cut_with_a_way_to_the_rest`
- [x] T4 [FR-5] [NFR-1] Cumulative `details.child` progress snapshots, throttled, 50 rows / 4 KB — `crates/evo-engine/src/agent_tool.rs` — check: `a_subagent_is_a_mesh_node_with_live_summary_events`; manual check in the running app
- [x] T5 [FR-6] Child usage in `AgentToolResult.usage`; the desktop adds tool-result usage to the turn's cost — `crates/evo-engine/src/agent_tool.rs`, `apps/desktop/src/features/chat/transcript.ts` — check: manual check in the running app
- [x] T6 [FR-5] Desktop `agent` tool kind: nested trace, latest text, footer, report — `apps/desktop/src/components/ai-elements/agent-run.tsx`, `apps/desktop/src/components/ai-elements/tool.tsx`, `apps/desktop/src/features/chat/chat-turn.tsx` — check: `bun run typecheck` and a preview with sample data
- [x] T7 [NFR-2] Plugin child agents keep their action API and share limits with the `agent` tool — `crates/evo-engine/src/child_agents.rs` — check: `child_limits_reject_wrong_types_and_out_of_range_values`, `capacity_is_bounded_even_while_disposed_children_are_cleaning_up`, and the other `child_agents` tests

### Phase 2 — Background subagents

Done when: a background child finishes while the parent is idle and the
parent continues with its report.

- [x] T8 [FR-9] `background: true`: session-lifetime scope, immediate `{agentId, status}`, report to a running or idle parent, cancellation — `crates/evo-engine/src/agent_tool.rs`, `crates/evo-engine/src/modes.rs`, `crates/evo-engine/src/rpc/protocol.rs` — check: `a_background_agent_reports_to_the_idle_parent_on_its_next_run`, `a_background_agent_can_be_cancelled`
- [x] T9 [FR-10] `message_agent` resumes a kept child — `crates/evo-engine/src/agent_tool.rs` — check: `a_finished_agent_continues_with_its_context`
- [x] T10 [FR-9] Desktop wake-ups, "Background agents" chip and event lines (first by polling `get_background_agents`, now by mesh push events) — `apps/desktop/src/stores/engine-store.ts`, `apps/desktop/src/features/chat/chat-turn.tsx` — check: `bun run typecheck` and a preview with sample data
- [x] T11 [FR-12] Lost background agents reported once on engine start; `ready.lostBackgroundAgents`; the desktop settles unreported calls — `crates/evo-engine/src/agent_tool.rs`, `apps/desktop/src/features/chat/transcript.ts` — check: `background_agents_without_a_report_are_found`, `lost_background_agents_are_reported_once_to_the_next_run`
- [x] T12 [FR-11] A steer releases waiting foreground calls (`agent_tool::steered`, `ATTACHED → FINISHED | DETACHED`) — `crates/evo-engine/src/agent_tool.rs` — check: `steering_releases_a_waiting_foreground_agent_into_the_background`, `without_steering_a_foreground_agent_reports_to_its_call`

### Phase 3 — Nested sessions

Done when: a chat proposes a session, the person starts it, it appears
nested, and its finished turn reaches the parent.

- [x] T13 [FR-14] Migration `0004_chat_parents.sql`; `Chat` / `NewChat` gain `parent_chat_id` and `origin` — `crates/evo-store/src/migrations/0004_chat_parents.sql`, `crates/evo-store/src/chats.rs` — check: `nested_sessions_link_to_their_parent`
- [x] T14 [FR-15] [FR-17] [FR-18] `start_session` / `message_session` / `list_sessions` and `startChildChat` (now defined and answered by the mesh hub) — `apps/desktop/src-tauri/src/mesh.rs`, `apps/desktop/src/stores/engine-store.ts`, `apps/desktop/src/stores/session-store.ts` — check: manual check in the running app
- [x] T15 [FR-16] Proposal card and **Start sessions without asking** — `apps/desktop/src/components/ai-elements/session-proposal.tsx`, `apps/desktop/src/features/settings/sections/sandbox-settings.tsx` — check: `bun run typecheck` and a preview with sample data
- [x] T16 [FR-19] Notes to the parent: follow-up when busy, coalesced automated wake when idle, guard rails — `apps/desktop/src-tauri/src/mesh.rs`, `apps/desktop/src/stores/engine-store.ts` — check: manual check in the running app
- [x] T17 [FR-20] Sidebar nesting: children under the parent, footer, status dots, roll-up, header and menu — `apps/desktop/src/features/shell/sidebar-chats.tsx`, `apps/desktop/src/features/shell/app-sidebar.tsx` — check: `bun run typecheck` and a preview with sample data

### Phase 4 — Worktree review

Done when: a kept worktree can be reviewed and applied or discarded from the
UI.

- [x] T18 [FR-13] [FR-22] [NFR-4] Worktree manager in its own crate, shared by engine and shell — `crates/evo-worktrees/src/lib.rs`, `crates/evo-engine/src/worktrees.rs` — check: `cargo test -p evo-worktrees` (`changes_are_measured_from_the_fork_and_applied_to_the_working_folder`, `a_conflicting_apply_changes_nothing`, `only_managed_worktrees_are_removed`, `both_locations_are_listed_and_removable`, `outside_a_repository_is_an_error`, …)
- [x] T19 [FR-21] Migration `0005_chat_worktrees.sql` and `start_session`'s `worktree` option — `crates/evo-store/src/migrations/0005_chat_worktrees.sql`, `crates/evo-store/src/chats.rs`, `apps/desktop/src-tauri/src/mesh.rs` — check: manual check in the running app
- [x] T20 [FR-13] [FR-22] Shell worktree commands and the review dialog, reached from a subagent's kept worktree, a worktree session's toolbar chip and **Settings → Sandbox** — `apps/desktop/src-tauri/src/worktrees.rs`, `apps/desktop/src/components/ai-elements/worktree-review.tsx` — check: `bun run typecheck` and a preview with sample data

### Phase 5 — Follow-ups

Done when: the designed settings that are not built yet exist.

- [ ] T21 [FR-1] Add the `agentDirs` settings key (extra agent folders, like `skills`) — `crates/evo-engine/src/settings.rs`, `crates/evo-engine/src/agents.rs` — check: a test that a type in an extra folder loads
- [ ] T22 [FR-18] Make the nested-session depth and the running-children limit configurable — `apps/desktop/src-tauri/src/mesh.rs` — check: a hub test with a changed limit

## 2. Verification

No results are recorded yet; the desktop logic has no automated tests (the
desktop has no test runner).

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-engine -- files_define_types_and_project_wins access_thinking_and_turns_are_read_and_checked` | not run |
| FR-2 | `cargo test -p evo-engine -- explore_and_plan_are_read_only_and_general_is_not a_file_can_replace_a_builtin` | not run |
| FR-3 | `cargo test -p evo-engine read_only` and `explore_agents_cannot_write`, `read_only_agents_cannot_write_through_the_shell_or_their_tools` | not run |
| FR-4 | `cargo test -p evo-engine -- a_subagent_works_and_reports_back unknown_types_and_models_are_refused` | not run |
| FR-5 | Manual check in the running app; `bun run typecheck` | not run |
| FR-6 | Manual check in the running app: the turn's cost includes the child | not run |
| FR-7 | `cargo test -p evo-engine child_limits_reject_wrong_types_and_out_of_range_values`; manual recursion check | not run |
| FR-8 | `cargo test -p evo-engine long_reports_are_cut_with_a_way_to_the_rest` | not run |
| FR-9 | `cargo test -p evo-engine a_background_agent_reports_to_the_idle_parent_on_its_next_run` | not run |
| FR-10 | `cargo test -p evo-engine -- a_finished_agent_continues_with_its_context a_background_agent_can_be_cancelled` | not run |
| FR-11 | `cargo test -p evo-engine -- steering_releases_a_waiting_foreground_agent_into_the_background without_steering_a_foreground_agent_reports_to_its_call` | not run |
| FR-12 | `cargo test -p evo-engine -- background_agents_without_a_report_are_found lost_background_agents_are_reported_once_to_the_next_run` | not run |
| FR-13 | `cargo test -p evo-worktrees`; manual check of the badge in the running app | not run |
| FR-14 | `cargo test -p evo-store nested_sessions_link_to_their_parent` | not run |
| FR-15 | Manual check in the running app: an allowed `start_session` creates and runs a child | not run |
| FR-16 | Manual check: default proposal card; setting on starts at once | not run |
| FR-17 | Manual check: `message_session` reaches the child; `list_sessions` lists it | not run |
| FR-18 | Manual check: a child session has no `start_session` | not run |
| FR-19 | Manual check: an idle parent is woken once with a **Nested sessions update** chip | not run |
| FR-20 | `bun run typecheck` and a preview with sample data | not run |
| FR-21 | Manual check: `worktree: true` runs the child in a new worktree | not run |
| FR-22 | `cargo test -p evo-worktrees -- a_conflicting_apply_changes_nothing changes_are_measured_from_the_fork_and_applied_to_the_working_folder`; manual check of the dialog | not run |
| NFR-1 | Code review of the throttle and caps in `agent_tool.rs`; `a_subagent_is_a_mesh_node_with_live_summary_events` | not run |
| NFR-2 | `cargo test -p evo-engine child_agents` | not run |
| NFR-3 | `cargo test -p evo-engine an_agent_file_added_later_is_usable_at_once` | not run |
| NFR-4 | `cargo test -p evo-worktrees -- only_managed_worktrees_are_removed a_conflicting_apply_changes_nothing` | not run |
