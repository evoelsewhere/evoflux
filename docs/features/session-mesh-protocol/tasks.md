# Session mesh protocol — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

Phases 1 → 2 → 3 → 4 in order; phase 4's in-engine part (agent ↔ agent)
can start right after phase 1.

### Phase 1 — Envelope and addresses

Planned scope: a `mesh` module in `evo-protocol` (envelope, node, ops,
events); an engine `LocalRouter` merging the job tables of
`child_agents.rs`, `agent_tool.rs` and side questions; all engine events
carry `from`. Main files: `crates/evo-protocol/src/mesh.rs`,
`crates/evo-engine/src/child_agents.rs`, `agent_tool.rs`, `modes.rs`. (As
built, the job tables stay and legacy events are not tagged — plan 5.)

Done when: the desktop renders a subagent from `summary` events; protocol
round-trip tests pass.

- [x] T1 [FR-1, FR-2, FR-3, FR-5, FR-7, FR-8] Wire types: envelope, `Address`, `Node`, `Level`, `MeshEvent` (`node_state`, `node_report`, `node_activity`, `node_usage`, `node_event`), `MeshCommand` (`subscribe`, `list`, `get`, `cancel`), typed errors — `crates/evo-protocol/src/mesh.rs` (moved to `crates/evo-mesh/src/wire.rs` in T9) — check: `cargo test -p evo-mesh -- addresses_route_by_session_and_keep_lineage_apart child_nodes_inherit_root_and_depth event_envelopes_round_trip_on_the_wire wire_names_are_stable levels_are_ordered_and_assigned commands_parse_and_answer_with_correlation malformed_and_foreign_messages_are_refused`
- [x] T2 [FR-1, FR-6, FR-7, FR-8, NFR-3] `LocalRouter`, one per engine: registry, per-subscriber levels, cancel cascade; the `agent` tool, plugin children and side questions register their nodes with a cancel handle and report state, activity, usage and reports — `crates/evo-engine/src/mesh.rs`, `crates/evo-engine/src/agent_tool.rs`, `crates/evo-engine/src/child_agents.rs` — check: `cargo test -p evo-engine -- lifecycle_reaches_subscribers_in_order_and_closed_nodes_leave summary_events_exist_only_while_wanted cancel_cascades_children_first_and_reports_what_stopped commands_answer_through_envelopes a_new_session_replaces_the_root a_subagent_is_a_mesh_node_with_live_summary_events`
- [x] T3 [FR-4, FR-5, FR-9] RPC: `ready.mesh` advertises version 1; a `{"type":"mesh",…}` command line is answered with `res` (`corr` = its `id`), then the replay; events go out as `{"type":"mesh",…}` lines; the root node is `running` from an accepted prompt until `agent_settled`, then `idle` — `crates/evo-engine/src/modes.rs`, `crates/evo-engine/src/rpc/protocol.rs` — check: `cargo test -p evo-engine -- rpc_mesh_subscribe_answers_with_correlation_and_streams_session_state customization_and_mesh_commands_pass_payload_validation`
- [x] T4 [FR-11] Desktop: mesh types and the fold into the agent view, `EngineClient.mesh()`, subscribe at `summary` on `ready` and on attach, render subagents from `node_*` events — `apps/desktop/src/engine/mesh.ts`, `apps/desktop/src/engine/client.ts`, `apps/desktop/src/stores/engine-store.ts` — check: manual check in the running app

### Phase 2 — Push lifecycle

Planned scope: `node_state` / `node_report` / `node_usage` from the engine;
`get_background_agents` polling removed. Main files: `modes.rs`,
`rpc/protocol.rs`, desktop `engine-store.ts`.

Done when: a background agent finishing wakes the parent with no polling.

- [x] T5 [FR-12] Remove the RPC commands `get_background_agents`, `ack_background_agents`, `cancel_background_agent` and the registry's wake flag — `crates/evo-engine/src/rpc/protocol.rs`, `crates/evo-engine/src/agent_tool.rs` — check: `cargo test -p evo-engine -- a_background_agent_reports_to_the_idle_parent_on_its_next_run a_background_agent_can_be_cancelled`
- [x] T6 [FR-12] Wake requests on the session node (`LocalRouter::request_wake`, cleared by `mesh::session_run`) — `crates/evo-engine/src/mesh.rs` — check: `cargo test -p evo-engine wake_requests_live_on_the_session_until_its_next_run`
- [x] T7 [FR-10] Activity fold for every node and one snapshot per node for a new `summary` subscriber — `crates/evo-engine/src/mesh.rs` — check: `cargo test -p evo-engine late_summary_subscribers_get_one_activity_snapshot_per_node`
- [x] T8 [FR-13, FR-14] Desktop: wake an idle chat 1 s after a session `node_state` / `agent_settled` for unhandled `meta.wake` reports (`address@endedAt`), at most 5 automated wakes in a row; cancel via mesh `cancel`; keep idle chats with running subagents out of the idle trim — `apps/desktop/src/stores/engine-store.ts` — check: manual check in the running app

### Phase 3 — Hub

Planned scope: `crates/evo-mesh` (registry, router, policy, `MailStore`)
embedded in the shell; nested-session spawn, notes, wakes and proposals
moved out of the webview; `mail` + `proposals` migration; windows subscribe
via Tauri events. Main files: `crates/evo-mesh`,
`apps/desktop/src-tauri/src/engine.rs`, `crates/evo-store`. (As built, no
`proposals` table — plan 5.)

Done when: a child session in window 2 reports to its parent in window 1;
mail to a closed session is delivered after reopen.

- [x] T9 [FR-3, FR-17] `crates/evo-mesh`: move the wire types (`evo_protocol::mesh` re-exports them); `Hub` as pure logic from engine stdout lines to effects (`Send`, `MailWaiting`); `MailStore` trait; mail op `message` with `MailBody {text, deliver, title}` — `crates/evo-mesh/src/wire.rs`, `crates/evo-mesh/src/hub.rs`, `crates/evo-protocol/src/mesh.rs` — check: `cargo test -p evo-mesh mail_round_trips_and_answers_with_correlation`
- [x] T10 [FR-15, FR-16] Engine: a session `node_report` per finished turn (not compactions); mail to the session queued as steer or for the next run, `deliver: wake` adds `meta.wake` + `meta.wakeTitles`, `res` with `corr` = mail id, a taken mail id dropped — `crates/evo-engine/src/mesh.rs`, `crates/evo-engine/src/modes.rs` — check: `cargo test -p evo-engine rpc_mesh_mail_queues_a_note_with_a_wake_and_turns_report`
- [x] T11 [FR-17, NFR-1] `mail` table and store — `crates/evo-store/src/migrations/0006_mail.sql`, `crates/evo-store/src/mail.rs` — check: `cargo test -p evo-store mail_waits_until_delivered_and_goes_with_its_receiver`
- [x] T12 [FR-17, NFR-1] Shell hub: a nested session's `node_report` becomes a `<nested-session …>` note mailed to the parent with `wake`, stored, written if the parent's engine is ready, marked delivered on its answer; otherwise `mesh://mail-waiting` and the main window starts the parent; resend after restart; replayed reports not mailed twice — `apps/desktop/src-tauri/src/mesh.rs`, `apps/desktop/src-tauri/src/engine.rs`, `crates/evo-mesh/src/hub.rs` — check: `cargo test -p evo-mesh -- a_nested_sessions_turn_reaches_its_running_parent_as_a_wake_note mail_for_a_closed_session_asks_for_a_host_and_waits unanswered_or_refused_mail_is_sent_again_after_a_restart only_a_sessions_own_report_with_a_parent_makes_mail a_replayed_report_makes_no_second_mail long_reports_are_cut_and_titles_quoted`; manual check in the app
- [x] T13 [FR-17] Desktop: drop `recordFinishedTurn`, `pendingNotes`, `flushNotes`; a note wakes the parent through `meta.wake` with a `<nested-sessions-done>` prompt and a "Session finished a turn" chip; no empty turn for a queued report in restored transcripts — `apps/desktop/src/stores/engine-store.ts` — check: manual check in the app
- [x] T14 [FR-18, FR-19, FR-20, FR-25] Session tools in the hub: `session_tools()` via `mesh_session_tools` on top-level chats; `start_session` proposes or auto-starts (`mesh_configure`); `mesh_start_session`; `DbMailStore::create_session` (chat row, fork, worktree), `chat://updated`, brief with `deliver: prompt`; at most 8 running children; nested sessions get no session tools; `list_sessions` with live state — `crates/evo-mesh/src/hub.rs`, `apps/desktop/src-tauri/src/mesh.rs` — check: `cargo test -p evo-mesh -- start_session_proposes_unless_auto_start_is_on running_children_are_capped list_sessions_shows_live_state_and_nested_sessions_cannot_start_more`
- [x] T15 [FR-21] Prompt mail after `mesh_hosted`: RPC `prompt` (idle) or `queue_message` steer (busy), `agent_start` / `agent_settled` tracking, refused prompts resent when the run ends, `mesh://prompted` — `crates/evo-mesh/src/hub.rs`, `apps/desktop/src-tauri/src/mesh.rs`, `apps/desktop/src/stores/engine-store.ts` — check: `cargo test -p evo-mesh -- a_started_session_gets_its_brief_once_a_window_hosts_it message_session_prompts_an_idle_child_and_steers_a_busy_one a_refused_prompt_goes_out_when_the_run_ends`
- [x] T16 [FR-22, FR-23] Hosting: `mesh://host {chat, cwd, restore}`, `mesh_hosted`, background start by the main window, `onReadyNested`; restart a died engine at most 3 times in 2 minutes per chat — `apps/desktop/src-tauri/src/mesh.rs`, `apps/desktop/src/stores/engine-store.ts` — check: `cargo test -p evo-mesh a_message_to_a_closed_child_hosts_it_first`; manual check with an engine that dies on start
- [x] T17 [FR-24] Mail left at startup: `mesh_pending_chats` over `evo_store::mail::chats_with_pending_mail` (archived excluded), each hosted — `crates/evo-store/src/mail.rs`, `apps/desktop/src-tauri/src/mesh.rs`, `apps/desktop/src/stores/engine-store.ts` — check: `cargo test -p evo-store chats_with_pending_mail_skip_delivered_and_archived`

### Phase 4 — Peer messaging

Planned scope: `send_message` to siblings / tree, `ask` / `reply`,
deadlock and loop guards, optional topics (not yet, spec 6.2). Main files:
`evo-mesh`, `evo-engine` tools. Built within one engine.

Done when: two agents coordinate via `ask` / `reply`; a cyclic ask is
refused.

- [x] T18 [FR-26, FR-27, FR-28] `send_message`, `ask`, `reply`, `list_nodes`, `cancel_node` bound to each node (passed as the child's tool replacements); reach (parent, children, siblings with `mail.siblings`); `<mail …>` delivery as steer, next run with a `mail` wake request, or on continue — `crates/evo-engine/src/mesh_tools.rs` — check: `cargo test -p evo-engine asking_the_session_that_waits_on_you_is_refused_and_a_message_reaches_it`
- [x] T19 [FR-29] `ask` blocks until `reply`, the receiver's run ending, the timeout (600 s, max 1800 s) or cancellation; an `ask` to an idle agent continues it and its report goes to the asker — `crates/evo-engine/src/mesh_tools.rs` — check: `cargo test -p evo-engine -- a_subagent_asks_its_sibling_and_gets_the_answer the_refusal_says_why_and_reply_checks_the_asker`
- [x] T20 [FR-30, FR-31, NFR-2] Guards in the `LocalRouter`: wait-for graph over open `ask`s and foreground `agent` calls (`would_deadlock`); `MAX_PAIR_MAIL` (20) per directed pair between two runs — `crates/evo-engine/src/mesh.rs` — check: `cargo test -p evo-engine -- a_wait_that_closes_a_cycle_is_refused a_pair_talking_in_a_loop_is_stopped`
- [x] T21 [FR-28] Desktop: wake for reason `mail` (`meta.wakeReasons`) with `<mail-arrived>`, chips "Message/Question from …" — `apps/desktop/src/stores/engine-store.ts` — check: manual check in the app with a real model
- [ ] T22 [FR-32] Mail between nodes of different engines (today sessions talk through notes and `message_session`) — `crates/evo-mesh`, `crates/evo-engine/src/mesh_tools.rs` — check: an agent in one session messages a nested session and it receives the mail

### Phase 5 — Remote (later)

Planned scope: the hub over TCP for `--connect` and remote engines. Main
files: `evo-protocol/client.rs`, `evo-mesh`.

Done when: a remote engine joins the mesh.

- [ ] T23 [FR-33] Hub over TCP for `--connect` and remote engines — `crates/evo-protocol/src/client.rs`, `crates/evo-mesh` — check: a remote engine connects and its nodes are listed and routable

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-mesh child_nodes_inherit_root_and_depth`; `cargo test -p evo-engine a_subagent_is_a_mesh_node_with_live_summary_events` | not run |
| FR-2 | `cargo test -p evo-mesh addresses_route_by_session_and_keep_lineage_apart` | not run |
| FR-3 | `cargo test -p evo-mesh -- event_envelopes_round_trip_on_the_wire wire_names_are_stable malformed_and_foreign_messages_are_refused` | not run |
| FR-4 | `cargo test -p evo-engine rpc_mesh_subscribe_answers_with_correlation_and_streams_session_state` | not run |
| FR-5 | `cargo test -p evo-mesh commands_parse_and_answer_with_correlation`; `cargo test -p evo-engine -- commands_answer_through_envelopes customization_and_mesh_commands_pass_payload_validation` | not run |
| FR-6 | `cargo test -p evo-engine cancel_cascades_children_first_and_reports_what_stopped` | not run |
| FR-7 | `cargo test -p evo-mesh levels_are_ordered_and_assigned`; `cargo test -p evo-engine summary_events_exist_only_while_wanted` | not run |
| FR-8 | `cargo test -p evo-engine lifecycle_reaches_subscribers_in_order_and_closed_nodes_leave` | not run |
| FR-9 | `cargo test -p evo-engine -- rpc_mesh_subscribe_answers_with_correlation_and_streams_session_state a_new_session_replaces_the_root` | not run |
| FR-10 | `cargo test -p evo-engine late_summary_subscribers_get_one_activity_snapshot_per_node` | not run |
| FR-11 | Manual check: a subagent renders from `summary` events, also after a window reload | not run |
| FR-12 | `cargo test -p evo-engine -- wake_requests_live_on_the_session_until_its_next_run a_background_agent_reports_to_the_idle_parent_on_its_next_run` | not run |
| FR-13 | Manual check: two reports for an idle chat wake it once | not run |
| FR-14 | Manual check: an idle chat with a running background agent survives the idle trim | not run |
| FR-15 | `cargo test -p evo-engine rpc_mesh_mail_queues_a_note_with_a_wake_and_turns_report` | not run |
| FR-16 | `cargo test -p evo-engine rpc_mesh_mail_queues_a_note_with_a_wake_and_turns_report`; `cargo test -p evo-mesh mail_round_trips_and_answers_with_correlation` | not run |
| FR-17 | `cargo test -p evo-mesh -- a_nested_sessions_turn_reaches_its_running_parent_as_a_wake_note mail_for_a_closed_session_asks_for_a_host_and_waits a_replayed_report_makes_no_second_mail only_a_sessions_own_report_with_a_parent_makes_mail`; manual check in the app: a child's turn reaches its parent in the same window, from a separate chat window, and while the parent's engine is stopped | unit tests not run; manual check passed (date not recorded) |
| FR-18 | `cargo test -p evo-mesh list_sessions_shows_live_state_and_nested_sessions_cannot_start_more` | not run |
| FR-19 | `cargo test -p evo-mesh -- start_session_proposes_unless_auto_start_is_on a_started_session_gets_its_brief_once_a_window_hosts_it`; manual check in the app: a proposal answered by the hub and started from its card, the child's brief, auto-start | unit tests not run; manual check passed (date not recorded) |
| FR-20 | `cargo test -p evo-mesh running_children_are_capped` | not run |
| FR-21 | `cargo test -p evo-mesh -- message_session_prompts_an_idle_child_and_steers_a_busy_one a_refused_prompt_goes_out_when_the_run_ends`; manual check in the app: `message_session` to the child | unit tests not run; manual check passed (date not recorded) |
| FR-22 | `cargo test -p evo-mesh -- a_message_to_a_closed_child_hosts_it_first mail_for_a_closed_session_asks_for_a_host_and_waits` | not run |
| FR-23 | Manual check: an engine that dies on start is restarted at most 3 times in 2 minutes | not run |
| FR-24 | `cargo test -p evo-store chats_with_pending_mail_skip_delivered_and_archived`; manual check: mail delivered after an app restart | not run |
| FR-25 | `cargo test -p evo-mesh list_sessions_shows_live_state_and_nested_sessions_cannot_start_more`; manual check in the app: `list_sessions` | unit test not run; manual check passed (date not recorded) |
| FR-26 | `cargo test -p evo-engine asking_the_session_that_waits_on_you_is_refused_and_a_message_reaches_it` (faux provider) | not run |
| FR-27 | `cargo test -p evo-engine a_subagent_asks_its_sibling_and_gets_the_answer` (faux provider) | not run |
| FR-28 | Faux-provider peers tests; manual check in the app with a real model: an agent tells the idle parent with `send_message` and the parent wakes once for the message and both reports | unit tests not run; manual check passed (date not recorded) |
| FR-29 | `cargo test -p evo-engine -- a_subagent_asks_its_sibling_and_gets_the_answer the_refusal_says_why_and_reply_checks_the_asker`; manual check in the app: one background agent asks the other for a code word | unit tests not run; manual check passed (date not recorded) |
| FR-30 | `cargo test -p evo-engine -- a_wait_that_closes_a_cycle_is_refused asking_the_session_that_waits_on_you_is_refused_and_a_message_reaches_it` | not run |
| FR-31 | `cargo test -p evo-engine a_pair_talking_in_a_loop_is_stopped` | not run |
| FR-32 | Not built (T22) | not run |
| FR-33 | Not built (T23) | not run |
| NFR-1 | `cargo test -p evo-mesh unanswered_or_refused_mail_is_sent_again_after_a_restart`; `cargo test -p evo-store mail_waits_until_delivered_and_goes_with_its_receiver` | not run |
| NFR-2 | Review: reach and guards live in `LocalRouter` and the hub | not run |
| NFR-3 | `cargo test -p evo-engine summary_events_exist_only_while_wanted` | not run |
