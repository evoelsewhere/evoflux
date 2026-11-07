# Application database (`evo.db`) and provider settings — Tasks

| | |
| --- | --- |
| Spec | [spec.md](spec.md) |
| Plan | [plan.md](plan.md) |
| Updated | 2026-11-07 |

## 1. Phases

`evo-store` tests run with `cargo test -p evo-store <name>`; the transcript
file tests in the engine with `cargo test -p evo-engine
transcript_file_tests`. Migrations 4 and 5 (chat parents, chat worktrees)
are tracked by [subagents and nested sessions](../subagents-and-nested-sessions/tasks.md).

### Phase 1 — Database, connection and migrations

Done when: the database opens from several processes, applies pending
migrations once, and refuses foreign, tampered and newer files.

- [x] T1 [FR-1] [FR-2] Open with `application_id`, WAL, `busy_timeout`, `foreign_keys`, `synchronous = NORMAL`; short-lived connections; `BEGIN IMMEDIATE` for read-then-write — `crates/evo-store/src/lib.rs` — check: `refuses_a_foreign_database`, `creates_and_reopens_idempotently`
- [x] T2 [FR-3] [FR-4] [NFR-3] [NFR-4] Embedded numbered migrations, `schema_migrations` with SHA-256, `user_version`, `Tampered` / `TooNew`, lock-free reopen of a current database, LF/CRLF checksums, `.gitattributes` for `*.sql` — `crates/evo-store/src/lib.rs`, `.gitattributes` — check: `applies_only_pending_migrations`, `rejects_edited_and_newer_schemas`, `reopening_a_migrated_database_takes_no_write_lock`, `anything_but_a_current_database_takes_the_locked_path`, `line_endings_do_not_change_a_migration`

### Phase 2 — Provider settings and the models.dev cache

Done when: provider settings and model lists are shared by every window and
model facts come from models.dev only.

- [x] T3 [FR-5] [FR-12] Migration 1: `provider_settings`, `provider_models`, `provider_discovery`; no secret columns — `crates/evo-store/src/migrations/0001_provider_settings.sql`, `crates/evo-store/src/settings.rs` — check: `cascade_removes_a_providers_models`, `roundtrip`
- [x] T4 [FR-13] Migration 2: `models_dev_cache`; background revalidation (ETag, 6 h, on demand) and hot-swap; offline snapshot — `crates/evo-store/src/migrations/0002_models_dev.sql`, `crates/evo-engine/src/models_dev.rs`, `crates/evo-runtime/src/models_dev.rs`, `crates/evo-runtime/data/models_dev_snapshot.json`, `crates/evo-runtime/scripts/gen_models_dev_snapshot.py` — check: manual check of **Settings → Providers → Refresh**
- [x] T5 [FR-16] Providers of the support matrix, plan usage and discovery — `crates/evo-runtime/data/provider_catalog.json`, `crates/evo-engine/src/provider_settings.rs`, `crates/evo-engine/src/provider_usage.rs` — check: manual check per provider

### Phase 3 — Workspaces, chats, preferences and the run log

Done when: the shell keeps workspaces, chats, preferences and the run log in
`evo.db`.

- [x] T6 [FR-14] [FR-15] Migration 3: `workspaces`, `chats`, `sessions` / `progress_*`, `app_settings`, `app_logs` — `crates/evo-store/src/migrations/0003_chats_sessions_logs.sql`, `crates/evo-store/src/chats.rs`, `crates/evo-store/src/logs.rs` — check: `chat_lifecycle`, `workspaces_are_unique_by_path`, `append_query_prune`, `formats_utc`
- [x] T7 [FR-14] [FR-15] Shell database access and the batched run-log writer (500 ms, prune at startup and hourly) — `apps/desktop/src-tauri/src/db.rs` — check: manual check of **Settings → Data & logs**
- [x] T8 [FR-14] Migration 6: `mail` — `crates/evo-store/src/migrations/0006_mail.sql`, `crates/evo-store/src/mail.rs` — check: `mail_waits_until_delivered_and_goes_with_its_receiver`, `chats_with_pending_mail_skip_delivered_and_archived`

### Phase 4 — Transcript files and chat search

Done when: each chat's transcript is its own file, legacy transcripts move
out of `evo.db` safely, and chat search follows transcript changes.

- [x] T9 [FR-6] Transcript file rules: safe names, `prepare` stamp, `SESSION_SCHEMA`; the engine opens `--session-db <file>` — `crates/evo-store/src/transcripts.rs`, `crates/evo-engine/src/session/transcript_file_tests.rs` — check: `ids_become_file_names_only_when_safe`, `prepare_stamps_new_files_and_refuses_others`, `evo_store_writes_the_harness_session_schema`, `a_new_transcript_file_holds_only_the_session`, `other_sqlite_files_are_refused`, `chats_in_separate_files_do_not_share_a_lock`
- [x] T10 [FR-7] Fork through a `.partial` file and rename — `crates/evo-store/src/transcripts.rs`, `crates/evo-store/src/chats.rs` — check: `fork_copies_the_committed_history_under_a_new_id`, `files_evo_store_makes_open_as_sessions`
- [x] T11 [FR-8] Delete the file and its companions after the engine stops — `crates/evo-store/src/transcripts.rs`, `apps/desktop/src-tauri/src/db.rs` — check: `remove_deletes_the_file_and_its_companions`
- [x] T12 [FR-9] [NFR-2] Startup: `adopt_legacy` (crash-safe, conflict files, `VACUUM` once) and `sweep` — `crates/evo-store/src/transcripts.rs`, `crates/evo-store/src/lib.rs` — check: `adopt_moves_legacy_transcripts_with_their_progress`, `adopt_finishes_after_a_crash_and_keeps_disagreeing_files`, `sweep_removes_orphans_and_partials_only`, `sweep_reports_a_file_still_in_use`
- [x] T13 [FR-10] `Db::transcript_for_engine` guard — `crates/evo-store/src/lib.rs` — check: code review
- [x] T14 [FR-11] Migration 7: `chat_search` with stamps; search refresh and `LIKE` match; latest-query-only palette — `crates/evo-store/src/migrations/0007_chat_search.sql`, `crates/evo-store/src/chats.rs` — check: `search_follows_transcript_changes`, `stamp_changes_when_the_transcript_is_written`, `searchable_text_keeps_words_not_identifiers_or_data`, `chat_search_arrives_without_touching_legacy_transcripts`
- [x] T15 [NFR-1] Transcript connection with WAL and `synchronous = NORMAL`; busy retry up to 60 s — `crates/evo-harness/src/session/sqlite/busy.rs` — check: code review
- [x] T16 [FR-6] [FR-7] [FR-8] [FR-9] End-to-end run of the desktop app on a copy of a real `evo.db` — check: manual run

### Phase 5 — Usage history

Done when: every model response writes one usage row.

- [x] T17 [FR-14] [NFR-3] Migrations 8 and 9: `usage_events`, `duration_ms`; engine writer thread — `crates/evo-store/src/migrations/0008_usage_events.sql`, `crates/evo-store/src/migrations/0009_usage_durations.sql`, `crates/evo-store/src/usage.rs` — check: `usage_events_arrive_empty_and_keep_existing_chats`, `records_and_sums_by_model_chat_and_source`, `bad_costs_are_stored_as_zero`

### Phase 6 — Planned tables

Done when: each planned table has shipped with its own feature spec and
migration (design: [plan, Planned tables](plan.md#planned-tables)). The
tasks are independent of each other.

- [ ] T18 [P] [FR-12] Model picker curation: use `provider_models.hidden` / `position`; UI in the model menu — `crates/evo-store/src/settings.rs`, desktop model menu — check: a test of hide and order
- [ ] T19 [P] [FR-13] Model metadata overrides: `model_overrides(provider_id, model_id, metadata_json)`, merged after models.dev — new migration — check: a migration test from the previous version
- [ ] T20 [P] [FR-14] Spend limits: `spend_limits(scope, provider_id, period, limit_usd)`, checked before a run against `usage_events` — new migration — check: a migration test and a limit test
- [ ] T21 [P] [FR-6] Append-only transcripts: `session_entries(session_id, seq, entry_json)` in each transcript file — `crates/evo-store/src/transcripts.rs`, evo-harness session store — check: the schema-match test still passes
- [ ] T22 [P] [FR-11] Full-text search: FTS5 over chat titles and `chat_search.body` — new migration — check: a ranking test
- [ ] T23 [P] [FR-12] Provider health: `provider_health(provider_id, at, status, latency_ms, error)` for status dots and fallback — new migration — check: a migration test
- [ ] T24 [P] [FR-12] OAuth metadata in `provider_settings.options_json` (plan/tier, token scope, last refresh; no tokens) — `crates/evo-store/src/settings.rs` — check: a test that no token is stored
- [ ] T25 [P] [FR-5] Keychain secrets: move `auth.json` secrets to the OS keychain, `auth.json` as fallback — `crates/evo-runtime/src/credentials.rs` — check: a test per platform backend

## 2. Verification

The transcript-file checks below are recorded as run on 2026-11-06 for the
transcript-file change; the record does not state their outcome.

| Requirement | Test or check | Result |
| --- | --- | --- |
| FR-1 | `cargo test -p evo-store -- refuses_a_foreign_database creates_and_reopens_idempotently` | not run |
| FR-2 | `cargo test -p evo-store anything_but_a_current_database_takes_the_locked_path`; code review of `BEGIN IMMEDIATE` | not run |
| FR-3 | `cargo test -p evo-store -- applies_only_pending_migrations reopening_a_migrated_database_takes_no_write_lock` | not run |
| FR-4 | `cargo test -p evo-store rejects_edited_and_newer_schemas` | not run |
| FR-5 | Code review: no secret column in any migration | not run |
| FR-6 | `cargo test -p evo-store` (transcript paths, identity); `cargo test -p evo-engine transcript_file_tests` | run (2026-11-06) |
| FR-7 | `cargo test -p evo-store fork_copies_the_committed_history_under_a_new_id`; `files_evo_store_makes_open_as_sessions` | run (2026-11-06) |
| FR-8 | `cargo test -p evo-store remove_deletes_the_file_and_its_companions` | run (2026-11-06) |
| FR-9 | `cargo test -p evo-store` (sweep, legacy move incl. a crash and a disagreeing file); desktop run on a copy of a real `evo.db` | run (2026-11-06) |
| FR-10 | Code review of `Db::transcript_for_engine` | not run |
| FR-11 | `cargo test -p evo-store` (search refresh, migration 6 → 7) | run (2026-11-06) |
| FR-12 | `cargo test -p evo-store -- cascade_removes_a_providers_models roundtrip` | not run |
| FR-13 | Manual check: **Settings → Providers → Refresh** reloads providers without a restart | not run |
| FR-14 | `cargo test -p evo-store -- chat_lifecycle workspaces_are_unique_by_path`, `mail`, `usage` tests | not run |
| FR-15 | `cargo test -p evo-store -- append_query_prune formats_utc`; manual check of **Settings → Data & logs** | not run |
| FR-16 | Manual check per provider in **Settings → Providers** | not run |
| NFR-1 | Code review of the transcript connection settings and `busy.rs` | not run |
| NFR-2 | `cargo test -p evo-store -- adopt_finishes_after_a_crash_and_keeps_disagreeing_files sweep_removes_orphans_and_partials_only` | run (2026-11-06) |
| NFR-3 | `cargo test -p evo-store -- chat_search_arrives_without_touching_legacy_transcripts usage_events_arrive_empty_and_keep_existing_chats` | not run |
| NFR-4 | `cargo test -p evo-store line_endings_do_not_change_a_migration` | not run |
