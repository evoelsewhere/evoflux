# Usage and cost history — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

### Phase 1 — Table, recorder, descriptor prices, Usage page

Done when: each response of a desktop chat is recorded with its usage and
cost, the model list carries prices and the Usage page shows the history
(FR-1 to FR-6, NFR-1 to NFR-4). Implemented 2026-11-06.

- [x] T1 [FR-1, FR-6, NFR-4] Migration 8 `usage_events` and the `usage` module (`record`, `summary`, `events`, `clear`) with tests — `crates/evo-store/src/migrations/0008_usage_events.sql`, `crates/evo-store/src/usage.rs` — check: `cargo test -p evo-store` (`usage::tests::*`, `usage_events_arrive_empty_and_keep_existing_chats`)
- [x] T2 [FR-1, FR-3, NFR-1, NFR-2, NFR-3] Recorder: channel to a writer thread that batches in one `BEGIN IMMEDIATE` transaction, retries 3×, answers `flush`; `UsageTap`; `record(message, source)` skips empty responses and is a no-op until `start` — `crates/evo-engine/src/usage_log.rs` — check: `usage_log::tests::the_writer_batches_retries_and_answers_flushes`
- [x] T3 [FR-1, NFR-3] Tap the session's broadcast emitter; start the recorder in RPC mode with `--session-id`; flush for up to 3 s at exit — `crates/evo-engine/src/session.rs`, `crates/evo-engine/src/host.rs` — check: real engine over RPC, one prompt writes one row
- [x] T4 [FR-2] Record subagents, plugin child runs and side questions with their source — `crates/evo-engine/src/agent_tool.rs`, `crates/evo-engine/src/child_agents.rs`, `crates/evo-engine/src/side_questions.rs` — check: `cargo test -p evo-engine usage_log` (`row_for` mapping)
- [x] T5 [FR-5] Add `cost` and `costConfigured` to every model descriptor — `crates/evo-engine/src/rpc/protocol.rs` — check: real engine: `get_available_models` descriptors carry them
- [x] T6 [FR-4, FR-6] Shell commands `usage_summary`, `usage_events` (blocking thread), `usage_clear` — `apps/desktop/src-tauri/src/db.rs` — check: `cargo check` in `src-tauri`
- [x] T7 [FR-4, FR-6] Usage page, store, `usageOpen`, sidebar entry and route — `apps/desktop/src/stores/usage-store.ts`, `apps/desktop/src/features/usage/usage-page.tsx`, `apps/desktop/src/stores/ui-store.ts`, `apps/desktop/src/features/shell/app-sidebar.tsx`, `apps/desktop/src/app/app.tsx` — check: desktop app end to end; `bun run typecheck`

### Phase 1b — Durations, failures, time buckets by model, efficiency, observations, price check

Done when: the page shows durations and speed, failures, the chart stacked
by model per hour, day or week, model efficiency, observations and the price
check (FR-4, FR-7, FR-8, FR-9). Implemented 2026-11-06.

- [x] T8 [FR-4, FR-7] Migration 9 `duration_ms`; `summary` counts failures and timing and splits the series by bucket × model — `crates/evo-store/src/migrations/0009_usage_durations.sql`, `crates/evo-store/src/usage.rs` — check: `cargo test -p evo-store` (`the_series_splits_buckets_by_model`, `errors_and_speed_are_counted`)
- [x] T9 [FR-7] Record each response's duration from its provider stamp (unknown when missing or over an hour) — `crates/evo-engine/src/usage_log.rs` — check: `usage_log` duration cases
- [x] T10 [FR-4, FR-7, FR-8, FR-9] Charts stacked by model (top four in `--viz-*` colours, the rest Other), efficiency figures and bars, observations, price check — `apps/desktop/src/features/usage/usage-charts.tsx`, `apps/desktop/src/features/usage/analysis.ts`, `apps/desktop/src/features/usage/usage-page.tsx`, `apps/desktop/src/index.css` — check: desktop dev app on the real `evo.db`

### Phase 2 — Spend limits and alerts

Done when: proposed — the spec gains requirements for spend limits first.

- [ ] T11 [no FR yet] Spend limits and alerts on top of the history: add the requirements to the spec, then a `spend_limits` table and an engine check before a run — `docs/features/usage-and-cost/spec.md`, `crates/evo-store/src/migrations/`, `crates/evo-engine/src/` — check: spec accepted with the new requirements

### Phase 3 — Compaction usage and plan-billed labels

Done when: a compaction shows under source "compaction" on the Usage page,
and plan-billed providers' spend is labelled API-equivalent.

- [ ] T12 [FR-10] Return usage from compaction and branch summaries and record it with source "compaction" — `crates/evo-harness/src/`, `crates/evo-engine/src/usage_log.rs` — check: a test that compacts with the `faux` provider and finds a "compaction" row
- [ ] T13 [FR-11] Mark plan-billed providers in the provider catalog and label their spend "API-equivalent" on the Usage page — `crates/evo-runtime/src/provider_catalog.rs`, `apps/desktop/src/features/usage/` — check: manual check in the running app with a plan-billed provider

## 2. Verification

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | Real engine over RPC (`--session-id`, copy of a real `evo.db`): one prompt to a model through a subscription provider; the row's tokens and cost equal the response's `usage` | passed (2026-11-06) |
| FR-2 | `cargo test -p evo-engine usage_log` | passed (2026-11-06) |
| FR-3 | Same run as FR-1: the recorded `cost_usd` equals the response's `usage.cost.total` | passed (2026-11-06) |
| FR-4 | Desktop app end to end (WebView2 DevTools): new chat, prompt, Usage page shows the chat's $0.011 matching the turn footer; range buttons, model filter, latest responses. Phase 1b: desktop dev app on the real `evo.db` (v9) shows the weekly chart; a stacked bar rendering only ~3% of its height was found and fixed (grow factors below 1). The multi-model chart was not checked visually: the app was in use; checked by type and build only | passed (2026-11-06; 1b 2026-11-07) |
| FR-5 | Same run as FR-1: 37 of 41 models carry a models.dev price | passed (2026-11-06) |
| FR-6 | `cargo test -p evo-store` (`usage::tests::*`, incl. `usage::tests::events_page_backwards_and_show_chat_titles`) | passed (2026-11-06) |
| FR-7 | Desktop dev app on the real `evo.db` (v9): a real GPT-6.1 Sol response through a subscription provider shows duration and speed (3.6 s, 5 tok/s) and the efficiency table; `cargo test -p evo-store` (`the_series_splits_buckets_by_model`, `errors_and_speed_are_counted`), `usage_log` duration cases | passed (2026-11-07) |
| FR-8 | Desktop dev app on the real `evo.db` (v9): an observation shows | passed (2026-11-07) |
| FR-9 | Visual check with several models in the app | not run: the app was in use; checked by type and build only |
| FR-10 | Compaction test with the `faux` provider (T12) | not run |
| FR-11 | Manual check with a plan-billed provider (T13) | not run |
| NFR-1 | `usage_log::tests::the_writer_batches_retries_and_answers_flushes` | passed (2026-11-06) |
| NFR-2 | `usage_log::tests::the_writer_batches_retries_and_answers_flushes` | passed (2026-11-06) |
| NFR-3 | An engine started without a chat id writes no rows | not run |
| NFR-4 | `cargo test -p evo-store` (`tests::usage_events_arrive_empty_and_keep_existing_chats`) | passed (2026-11-06) |
| all | `cargo test -p evo-engine` (637 passed), `bun run typecheck`, `cargo check` in `src-tauri` | passed (2026-11-06) |
