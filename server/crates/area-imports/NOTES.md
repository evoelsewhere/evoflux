# area-imports NOTES

Python source: `app/api/routes/import_route.py`, `app/services/import_service.py`,
`app/services/importers/{base,chatgpt,claude_code,claude_web,codex,cursor,generic}.py`,
`app/models/import_job.py`, `app/models/import_job_item.py`. Unit `import`
(`/api/import/**`, see `server/routing.toml`). Contract tests: `contract-tests/imports/`
(58 cases, all pass against Python v3.1.1; snapshots under `snapshots/`).

The board row and `check_paths.py` name the lane `imports`, so the crate is
`area-imports` and the tests live in `contract-tests/imports/` (the task brief said
`area-import` / `contract-tests/import/`).

**Status:** L6a (this crate's stub, NOTES, contract tests). L6b is blocked; see
[Blockers for L6b](#blockers-for-l6b).

## Endpoints

Every route needs auth: `401 {"detail":"Unauthorized — EvoFlux access key required."}`
for a missing or wrong token, before body validation. `422` bodies are FastAPI's
`{"detail":[{"type","loc","msg","input",...}]}` (snapshots `*_422.json`).

| Endpoint | Request | Success | Errors |
|---|---|---|---|
| `GET /scan` | – | `200 {"discovered":[{source,path,label,description,estimated_items}]}` | – |
| `GET /auto-sync` | – | `200 {"enabled","scan_interval_seconds","notify_new_items"}`; an invalid value in the file falls back to its default | – |
| `PUT /auto-sync` | partial, `strict` types, `scan_interval_seconds >= 30`; `null` fields ignored | `200` merged settings | `422` (nothing written) |
| `POST /detect` | `{"path": str, "source"?: str}` | `200 DetectResponse` | `400 {"detail":"Path not found: <resolved>"}`; `422 {"detail":{"error":"Could not detect import format","warnings":[...]}}` when the source is unknown or there are no items; `422` validation |
| `GET /preview/{import_id}` | – | `200 DetectResponse` (recomputed, see odd behaviour) | `404 {"detail":"Import not found"}` |
| `PATCH /preview/{id}/items/{item_index}` | `{"action": str}` | `200 {"status":"ok","target_name"}` | `404`; `400` `Invalid item index`, `Invalid action. Allowed: {<set repr>}`, `This item type cannot be imported`, `Keep both is available for Skills that conflict with another local source`, `This Skill exists outside EvoFlux; choose Keep both or skip it`; `422` |
| `PATCH /preview/{id}/items` | `{"indexes": [int] (min 1), "action": "import"\|"skip"\|"reimport"}` | `200 {"status":"ok","updated":n}` | `404`; `400` in this order: `Item indexes must be unique`, `Invalid item index`, `Selected item types cannot be imported`, `Re-import can only be applied to items with detected conflicts`, `External Skill conflicts must be skipped or kept as an EvoFlux copy`; `422` |
| `POST /execute/{import_id}` | optional `{"origin":"manual"\|"auto_sync"}` | `200 {"import_id": job hex32, "imported", "skipped", "errors":[{item,kind,error}]}` | `404`; `422` |
| `DELETE /{import_id}` | – | `200 {"status":"cancelled"}` (also for an unknown id) | – |
| `GET /history` | – | `200 {"imports":[...]}`, newest 50 by `created_at` | – |
| `GET /history/{job_id}` | – | `200 {"import_id","origin","undo_state","items":[{source_item_id,kind,label,operation,outcome,reason}]}` (no snapshot, fingerprint or target path) | `404 {"detail":"Import history item not found"}` |
| `POST /history/{job_id}/undo` | – | `200 {"import_id","state","undone","skipped","items":[...]}` | `404` same body |

`DetectResponse` = `{import_id (hex16), detected_source, path, summary{total_items,
new_items, already_imported, not_importable, conflicts, <kind>: n...}, items[{id
"<import_id>_<i>", kind, label, preview, action, conflicts, target_name, origin,
reason}], warnings}`.

## State, files and DB

- `_import_jobs: dict[str, ImportBundle]` (route-local, in-process). Preview, PATCH,
  execute and DELETE work on it; execute removes it after running. Moves to Rust
  state in the crate. A preview made in one process cannot be executed by another,
  so mixed Python/Rust routing of the unit is impossible: the whole unit flips.
- DB tables: `import_jobs`, `import_job_items` (written by execute and undo, read by
  history), `chat_sessions` and `session_messages` (read by conflict detection,
  written by session import, re-import and undo). Schema frozen; no DDL.
- Reads outside EvoFlux: the path given to detect (any file or folder, plus `zip`
  members), and for `/scan` fixed places under `HOME` (`Downloads`, `Desktop`,
  `.claude`, `.codex`, `projects|dev|code|repos|work/*`) and the process cwd.
  `claude_code` also follows `installed_plugins.json` `installPath` values to any
  folder on disk; `codex` reads `<parent>/.agents/skills`.

## Cross-unit writes and the Python caches that read them (Q3)

`import_service.py` never invalidates or reloads anything after it writes, so every
Python reader already treats import writes as external. A Rust writer makes nothing
stale that is not stale today.

| Write | Owner unit | Python reader and cache | Revalidates on an outside write? |
|---|---|---|---|
| `<CONFIG>/agents/<name>.md` (create; undo deletes) | agents-skills | built `Agent` in a cached team (`member.py:_detect_config_drift`, mtime stamp of its own `.md`); blueprint payload cache keyed by `.md` mtime (`routes/team/chat.py`); `validate_agents_dir_cached` (30 s TTL) | Edits: yes, next turn. **New file: no** until `GET /team/agents` (`refresh_blueprints`) or idle eviction. A deleted file leaves the running member on its last config. Both already true with Python writing. |
| `<SKILLS_DIR>/<name>/SKILL.md` (create; undo deletes file and dir) | agents-skills | `skills/registry.py:_discover_cached` (lru_cache keyed by each `SKILL.md` `mtime_ns` + size) | Yes |
| `<CONFIG>/mcp.json` (merge one server with sensitive keys removed and local ones kept; undo rewrites or unlinks) | plugins-mcp | `mcp/manager.py:_watch_config_loop` (sha256 every 0.5 s); `mcp/config.py:load_config` (read per call); agent drift stamp | Yes |
| `<WIKI>/sources/<file>` (create; undo deletes) | memory-search | `services/wiki.py`, `services/memory.py` lexical search (read per call, no index) | Yes |
| `<CONFIG>/settings.yaml` (`PUT /auto-sync` rewrites the **whole** file from `RuntimeSettings`) | settings | `load_runtime_settings` (no cache); `webbridge_service` policy (re-read every 60 s); dream scheduler; the auto-sync interval itself lives in the browser (`web/src/lib/import-auto-sync.ts`) | Yes for Python. The web scheduler only sees its own PUT until reload (true today). |
| `chat_sessions` / `session_messages` rows (insert, replace, delete on undo) | chat-core | history re-read per turn; `team_manager._session_teams[session_id]` keeps a team per session | Reads yes. A cached session team outlives an undo that deletes its session until idle eviction (true today). |

Verdict for Q3: no Python cache goes stale *because* Rust is the writer. The owner's
Q3 decision (wait for Phase 2) still stands for the reasons in the blockers below.

## Pins check

`rg "import_service|importers\.|import_route" app` outside the unit: only
`app/api/app.py` (router mount). `ImportJob` is imported by `app/models/__init__.py`
(metadata). `ImportAutoSyncSettings` lives in `app/core/runtime_settings.py` and is
read only by these routes. No adapter needed; nothing outside the unit calls the
service.

The unit **calls into** other units in-process: `app.agent.skills.registry.discover_skills`
(skill conflicts, all registered roots: EvoFlux, `~/.claude/skills`, `~/.agents/skills`,
plugin roots, built-ins) and `app.core.runtime_settings` (`RuntimeSettings` load and
save). See blockers.

## Odd behaviour (ported as is unless noted)

- **File re-import never runs.** `execute` re-runs `detect_conflicts`, and the agent,
  skill, knowledge and MCP checks set `action = "skip"` on any existing target, so
  a Re-import chosen in the preview is skipped ("Skipped by user or conflict
  detection"). Only sessions honour `reimport`. The `before_snapshot` restore path
  for file targets is therefore reachable only when a target appears between the
  check and the write. Suspected Python bug (§9); contract test
  `test_reimport_of_existing_file_target_is_skipped` pins it.
- **Undo is not byte for byte.** Files are written with `write_text` (text mode) and
  snapshots read with `read_text` (universal newlines): on Windows every `\n` becomes
  `\r\n`, and on every OS a `\r\n` in a restored file becomes the platform newline.
  Content without newlines is restored exactly. The MCP undo rewrites `mcp.json`
  with `json.dumps(indent=2) + "\n"` in text mode. Contract tests pin both.
- **Concurrent execute of one `import_id` races.** All requests see the bundle until
  the first finishes; the first imports, the others skip everything (`200`) or fail
  with an unhandled `500`. Each target is still imported once. A Rust port that takes
  the bundle out atomically answers the losers `404`; that needs a
  `KNOWN_DIFFERENCES.md` entry at L6b.
- **Journal order is random.** Items of one job share `created_at` and are ordered by a
  random hex id, so history detail and undo item order carry no meaning (tests sort).
- **Invalid action message** prints a Python `set`, whose order depends on the hash seed.
- **Detect vs preview previews differ:** detect describes agents and skills by
  description and knowledge by filename and gives `reason` from `_skip_reason`;
  preview recomputes only session and unsupported text and `reason` only for
  unsupported kinds. Detect's summary has the keys in a different order (JSON object,
  order not part of the contract).
- **Non-object JSONL lines crash detect.** A Claude Code or Codex `.jsonl` line that
  parses to a string or number reaches `entry.get` and returns `500`. Suspected bug (§9).
- `PATCH` single-item `rename` stores `_original_name` and renames to
  `<name>-evoflux`, `-evoflux-2`, ... (first free dir in `SKILLS_DIR`); any other action
  restores the original name.
- Relative `path` resolves against the server's cwd (`Path.resolve()`); `~` expands.
- `/scan` uses `Path.home()` (`USERPROFILE` on Windows) and `os.getcwd()`; directory
  order is the OS's listing order.
- Secrets: detect, preview and history never echo item data; MCP entries drop every
  key whose normalised name is in the sensitive list (`env`, `headers`, `*token*`,
  `*secret*`, `*apikey*`, `*auth*`, ...) before writing or journaling; credentials
  from `.env`/`settings.json` become `setting` items that are never imported.

## Security notes for L6b

The port reads files from other tools' folders and writes into the agents and skills
dirs, `mcp.json` and `wiki/sources`. Python does not confine source reads (any path,
`installPath` anywhere, symlinks followed, no size cap) and the target names are
sanitised (`_agent_file_name`, `_skill_directory_name`, knowledge `isalnum|.-_`).
The Rust port must: keep the target sanitisers exactly; not follow symlinks out of
the source folder; cap file and zip member sizes (and zip member count/ratio);
never log item data. Each hardening that changes a response is a
`KNOWN_DIFFERENCES.md` entry. Needs a security review.

## Blockers for L6b

1. **New dependency.** ChatGPT and Claude exports are `.zip`; the workspace has no zip
   crate (`server/Cargo.lock`). §9: the orchestrator adds `zip` (with deflate) in a
   `chore(shared)` commit after `cargo deny check`.
2. **`PUT /auto-sync` rewrites all of `settings.yaml`** via `RuntimeSettings.model_dump`
   + `yaml.safe_dump`, including defaults of every section, and its load prunes
   invalid values field by field (`load_runtime_settings_report`). Matching
   it needs the `settings` unit's schema in Rust (snapshot
   `auto_sync_saved_settings.json` shows the full dump). Owner decision: port the
   schema, or have Rust edit only the `import_auto_sync` mapping (a known difference).
3. **Skill conflicts call `discover_skills()`** of the agents-skills unit (every skill
   root and the disabled-skills setting). The same-name check needs that root list in
   Rust or a shared crate.
4. **SKILL.md frontmatter is PyYAML `safe_dump(allow_unicode, sort_keys=False)`**;
   the workspace has `yaml-rust2`, whose emitter quotes and folds differently. Needs
   a hand-written emitter that matches PyYAML for the value shapes used here.
5. Sessions: `_session_fingerprint` is sha256 of Python `json.dumps(sort_keys=True,
   ensure_ascii=False)` over `isoformat()` timestamps of SQLAlchemy-loaded rows;
   Rust must reproduce Python's datetime and float formatting or undo of Python-made
   imports reports "Session changed after import".

## Test map

| Python test | Covered by |
|---|---|
| `tests/api/routes/test_import_route.py::test_bulk_action_validates_every_index_before_mutating` | contract `test_bulk_action_validation` |
| `::test_preview_can_keep_external_skill_as_a_renamed_evoflux_copy` | contract `test_item_action_external_skill_rename_and_reimport` |
| `::test_external_skill_conflict_cannot_be_reimported_under_the_same_name` | contract `test_item_action_external_skill_rename_and_reimport`, `test_bulk_reimport_rejects_external_skill` |
| `::test_preview_action_keeps_session_target_label` | contract `test_item_action_rules` (target_name), `test_session_import_reimport_and_undo` |
| `::test_unsupported_settings_are_read_only_in_preview` | contract `test_item_action_rules`, `test_detect_generic_dir` |
| `::test_import_history_detail_hides_undo_snapshot` | contract `test_execute_generic_writes_every_target` (detail snapshot) |
| `::test_auto_sync_settings_persist_to_active_profile_and_merge` | contract `test_auto_sync_put_merges_and_persists`, `test_auto_sync_put_keeps_other_settings` |
| `::test_auto_sync_settings_reject_invalid_interval_without_writing` | contract `test_auto_sync_put_validation_writes_nothing` |
| `::test_preview_shows_skill_origin_without_exposing_source_path` | contract `test_detect_claude_code_dir` (origin), `_external_skill` helper |
| `::test_api_import_reimport_and_undo_round_trip` | contract `test_session_import_reimport_and_undo` |
| `tests/services/test_chatgpt_importer.py::test_chatgpt_conversation_id_is_stable_when_title_changes` | Rust unit (L6b, chatgpt parser) |
| `::test_chatgpt_conversation_without_id_keeps_legacy_identity_fallback` | Rust unit (L6b); contract `test_detect_chatgpt_json` (second conversation has no id and no messages) |
| `tests/services/test_import_service.py::test_imported_skill_uses_registry_root_and_valid_frontmatter` | contract `test_execute_generic_writes_every_target` (file snapshot) |
| `::test_skill_conflicts_check_registry_root` | contract `test_item_action_rename_skips_taken_evoflux_names`; Rust unit (L6b) |
| `::test_skill_conflicts_from_other_local_roots_are_visible` | contract `test_detect_claude_code_dir`, `_external_skill` |
| `::test_renamed_skill_copy_uses_a_free_evoflux_target` | contract `test_item_action_rename_skips_taken_evoflux_names` |
| `::test_claude_code_import_reads_global_skills` | contract `test_detect_claude_code_dir` |
| `::test_codex_session_keeps_function_calls_and_outputs_structured` | Rust unit (L6b, codex parser; message shapes are not visible over HTTP) |
| `::test_claude_desktop_type_rows_work_without_embedded_roles` | Rust unit (L6b) |
| `::test_claude_session_preserves_task_sidechain_and_tool_result` | Rust unit (L6b) |
| `::test_claude_session_preserves_multiple_tool_calls_without_parent_text` | Rust unit (L6b) |
| `::test_claude_tool_results_are_bounded_and_binary_fields_are_omitted` | Rust unit (L6b) |
| `::test_claude_skill_origins_and_duplicate_names_are_preserved` | contract `test_detect_claude_code_dir` (`deploy` / `deploy-my-plugin`) |
| `::test_imported_claude_skill_persists_origin_frontmatter` | Rust unit (L6b, frontmatter emitter) |
| `::test_import_session_persists_claude_tool_metadata` | Rust unit (L6b, store) |
| `::test_codex_import_reads_sibling_agents_skills` | contract `test_detect_codex_dir` |
| `::test_distinct_source_item_ids_with_same_title_do_not_conflict` | Rust unit (L6b, conflict query) |
| `::test_undo_created_session_removes_session_and_messages` | contract `test_session_import_reimport_and_undo` |
| `::test_reimport_updates_matching_session_in_place` | contract `test_session_import_reimport_and_undo` |
| `::test_chatgpt_title_change_reimports_by_stable_conversation_id` | Rust unit (L6b) |
| `::test_chatgpt_stable_id_migrates_unique_legacy_import_after_title_change` | Rust unit (L6b; needs a seeded legacy row) |
| `::test_chatgpt_legacy_match_with_duplicate_timestamp_requires_review` | Rust unit (L6b) |
| `::test_undo_reimport_restores_previous_session_content` | contract `test_session_import_reimport_and_undo` |
| `::test_undo_skips_session_changed_after_import` | Rust unit (L6b; changing a session needs another unit's route) |
| `::test_ambiguous_legacy_session_match_requires_manual_resolution` | Rust unit (L6b) |
| `::test_undo_does_not_remove_skill_file_modified_after_import` | contract `test_undo_leaves_changed_files_alone` |
| `::test_imported_agent_name_cannot_escape_agents_directory` | Rust unit (L6b, `_agent_file_name`) |
| `::test_mcp_import_does_not_copy_environment_or_auth_credentials` | contract `test_execute_generic_writes_every_target`, `test_undo_restores_mcp_config_byte_for_byte` |
| `::test_mcp_reimport_keeps_existing_credentials_out_of_journal_and_undo` | contract `test_undo_restores_mcp_config_byte_for_byte` (journal never shows local values); Rust unit (L6b, `_restore_mcp_sensitive_values`) |

Contract coverage per route: auth (all 12, missing and wrong token), validation
`422`s, every documented `400`/`404`, empty state (`/history`, `/scan`, defaults),
the 50-row history boundary, concurrent `execute` of one `import_id`, and one
detect + preview snapshot per importer (`chatgpt` json and zip, `claude_web` json,
object and zip, `claude_code`, `codex`, `cursor`, `generic` folder and single files).

Perf: no `/api/import` endpoint is in `baseline-v3.1.1.json`; SH3 measures them.
