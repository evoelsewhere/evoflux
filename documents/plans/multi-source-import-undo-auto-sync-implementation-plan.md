# Multi-source Import Undo and Auto-sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe undo, bulk re-import, and periodic auto-sync for new sessions, skills, and agents while keeping MCP imports under manual review.

**Architecture:** Add a durable per-item journal linked to each import job, with prior snapshots for replacements and fingerprints for safe rollback. Keep auto-sync in one coordinator mounted above route navigation, reuse the existing scan/detect/execute APIs, and deliver summaries through the app notification path. Keep auto-sync opt-in, skip existing conflicts automatically, and allow explicit preview actions to re-import matched targets in place.

**Tech Stack:** FastAPI, SQLModel, Alembic, SQLite, React, TypeScript, TanStack Router/Query, existing EvoFlux desktop notification APIs.

**Spec:** [`documents/plans/multi-source-import-undo-auto-sync-design.md`](multi-source-import-undo-auto-sync-design.md)

## Global Constraints

- Auto-sync runs while EvoFlux is running and stops when the application exits.
- Auto-sync automatically imports only new `session`, `skill`, and `agent` items.
- Auto-sync skips existing conflicts and never imports MCP configuration, credentials, or unsupported item kinds.
- A manual **Re-import** replaces the matched item in place and must not create a duplicate session.
- Undo preserves targets edited after import and reports partial outcomes instead of silently overwriting user changes.
- Import history is retained after undo; jobs created before item journaling show Undo unavailable.
- Keep the real EvoFlux database untouched in tests and smoke tests; use temporary or repo-local isolated databases.
- Preserve unrelated working-tree changes and keep the design/plan documents local unless the user asks to commit them.

## Review Focus

- Same source and title but different source item IDs must remain separate sessions; test in Task 2 with `test_distinct_source_ids_with_same_title_do_not_conflict`.
- A legacy title-only match that is ambiguous must not be replaced; test in Task 2 with `test_ambiguous_legacy_session_match_requires_manual_resolution`.
- A target edited after import must survive Undo and produce a partial result; test in Task 2 with `test_undo_skips_session_changed_after_import` and Task 3 API coverage.
- A mixed auto-sync bundle must import only new sessions/skills/agents and leave MCP items for review; test in Task 5 with `test_auto_sync_skips_mcp_and_notifies_review_count`.
- A file-backed target changed after import must survive Undo; test in Task 2 with `test_undo_skips_modified_skill_file`.

---

## File Map

- `app/models/import_job_item.py` — durable per-item operation journal and before/after undo data.
- `app/models/import_job.py`, `app/models/import_job_item.py`, `app/models/chat.py`, `app/models/__init__.py` — job trigger, session source identity, and journal model.
- `app/migrations/versions/00000073_import_item_journal.py` — create journal table, add job metadata, and add session source identity after current schema head `00000072`.
- `app/core/schema_version.py` — update `SCHEMA_HEAD` to the new migration revision.
- `app/services/import_service.py` — stable matching, journal writes, in-place re-import, fingerprints, and per-item undo.
- `app/api/routes/import_route.py` — bulk action, job detail/undo routes, and enriched history payload.
- `tests/services/test_import_service.py`, `tests/api/routes/test_import_route.py`, `tests/core/test_alembic_migrations.py` — service, API, and migration regressions.
- `web/src/api/import.ts` — typed API calls and history/item result contracts.
- `web/src/routes/settings.import.tsx` — conflict labels, selection/bulk actions, undo controls, and outcome rendering.
- `web/src/lib/import-auto-sync.ts` — single-flight periodic scan/detect/execute coordinator.
- `web/src/App.tsx` — mount auto-sync above `RouterProvider` after backend readiness.
- `web/src/lib/desktop-notifications.ts` — import notification kind and Settings → Import action target.
- `web/src/__tests__/lib/import-auto-sync.test.ts`, `web/src/__tests__/routes/settings.import.test.tsx` — coordinator and import UI tests, following existing Vitest setup.
- `web/src/help/locales/en.ts`, `web/src/help/locales/vi.ts`, `web/src/help/locales/ja.ts` — explain safe auto-sync, re-import, and undo limits.
- `documents/features/multi-source-import.md`, `documents/features/README.md`, `CHANGELOG.md` — update the shipped behavior after implementation.

## Implementation Tasks

### Task 1: Add the import item journal schema

**Files:**
- Create: `app/models/import_job_item.py`
- Modify: `app/models/import_job.py`
- Modify: `app/models/__init__.py`
- Create: `app/migrations/versions/00000073_import_item_journal.py`
- Modify: `app/core/schema_version.py`
- Test: `tests/core/test_alembic_migrations.py`
- Test: `tests/core/test_schema_version.py`

**Interfaces:**
- `ImportJobItem` stores `id`, `job_id`, `source_item_id`, `kind`, `label`, `operation`, `target_ref`, `outcome`, `before_snapshot`, `after_fingerprint`, and timestamps.
- `ImportJob` gains an `origin` value (`manual` or `auto_sync`) and an undo state (`available`, `undone`, `partially_undone`, or `unavailable`). Existing rows migrate to `origin=manual`, `undo_state=unavailable`.
- The migration creates the journal table with a foreign key to `import_jobs`, an index on `(job_id, id)`, and a unique constraint on `(job_id, source_item_id)`; it also adds nullable `chat_sessions.source_item_id` with a unique `(source, source_item_id)` index.

- [ ] **Step 1: Write failing migration and schema-head assertions**

Add a migration test that upgrades a temporary database from `00000072` to head and checks `import_job_items`, its foreign key, and the two job columns. Use the existing pattern in `tests/core/test_alembic_migrations.py`: point `settings.DATABASE_URL` at a `tmp_path` SQLite database, load `app/alembic.ini`, run `command.upgrade(cfg, "00000072")`, insert a legacy job, then run `command.upgrade(cfg, "head")`. Inspect the resulting columns and foreign keys with SQLAlchemy, and assert the legacy row has `origin=manual` and `undo_state=unavailable`. Add a schema-version assertion that the declared head equals the sole Alembic head.

- [ ] **Step 2: Run the migration tests and confirm the expected failure**

Run: `.\.venv\Scripts\python.exe -m pytest --no-cov -q tests/core/test_alembic_migrations.py tests/core/test_schema_version.py`

Expected: failure because revision `00000073` and the journal table do not exist.

- [ ] **Step 3: Add the SQLModel journal and migration**

Use nullable `before_snapshot` for newly created targets; set `target_ref` and `after_fingerprint` only after a target is created or replaced. Store before-snapshots as local JSON text. Register `ImportJobItem` in `app/models/__init__.py` so metadata and migrations see it.

```python
class ImportJobItem(SQLModel, table=True):
    __tablename__ = "import_job_items"
    id: str = Field(sa_column=Column(sa.String(32), primary_key=True))
    job_id: str = Field(foreign_key="import_jobs.id", index=True)
    source_item_id: str = Field(sa_column=Column(sa.Text(), nullable=False))
    kind: str = Field(sa_column=Column(sa.String(40), nullable=False))
    operation: str = Field(sa_column=Column(sa.String(20), nullable=False))
    target_ref: str | None = Field(default=None, sa_column=Column(sa.Text()))
    outcome: str = Field(sa_column=Column(sa.String(24), nullable=False))
    before_snapshot: str | None = Field(default=None, sa_column=Column(sa.Text()))
    after_fingerprint: str | None = Field(default=None, sa_column=Column(sa.String(64)))
```

- [ ] **Step 4: Run migration and schema tests to green**

Run: `.\.venv\Scripts\python.exe -m pytest --no-cov -q tests/core/test_alembic_migrations.py tests/core/test_schema_version.py`

Expected: migration upgrades from `00000072`, preserves prior job rows as non-undoable, and reports the new sole head.

### Task 2: Journal imports, re-import matched targets, and implement safe undo

**Files:**
- Modify: `app/services/import_service.py`
- Modify: `tests/services/test_import_service.py`
- Modify: `app/models/import_job.py`
- Modify: `app/models/import_job_item.py`

**Interfaces:**
- `execute_import(db, bundle, *, origin: Literal["manual", "auto_sync"] = "manual") -> ImportResult` writes a job and item outcomes.
- `undo_import(db, job_id: str) -> ImportUndoResult` returns `undone`, `skipped`, and per-item reasons; repeating it returns the saved outcome without applying changes again.
- A conflict action `reimport` resolves a matched target and updates it in place. A normal `import` action is valid only for a new item; a stale conflict is returned as skipped with a reason.
- Matching uses `(source, source_item_id)` first. Legacy session fallback is `(source, title)` only when exactly one target matches.

- [ ] **Step 1: Add service tests for created-item journaling and undo**

Add a test that imports one session with two messages, checks a `created` journal row points to its session ID, calls `undo_import`, then asserts both the session and messages are removed while the job remains marked undone.

```python
result = await execute_import(db, bundle)
job = await get_latest_import_job(db)
assert result.imported == {"session": 1}
assert (await count_sessions(db)) == 1
assert (await undo_import(db, job.id)).undone == 1
assert (await count_sessions(db)) == 0
assert await get_import_job(db, job.id) is not None
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest --no-cov -q tests/services/test_import_service.py -k undo_created_session`

Expected: failure because no item journal or `undo_import` implementation exists.

- [ ] **Step 3: Implement job/item journal writes for created sessions and files**

Create the `ImportJob` before applying items. For sessions, persist the target session ID and a fingerprint of imported metadata/messages. For skills/agents, record the resolved file path and SHA-256 of the written file. Record failures and skipped/review items individually. Keep SQLite writes in database transactions; stage filesystem snapshots/writes outside database transactions and update journal state after successful file operations.

```python
async def execute_import(
    db: AsyncSession,
    bundle: ImportBundle,
    *,
    origin: Literal["manual", "auto_sync"] = "manual",
) -> ImportResult:
    ...
```

- [ ] **Step 4: Add tests for explicit session re-import and ambiguous legacy matching**

Test that selecting `reimport` updates the matched session messages without increasing session count. Test that the same title with a different source item ID creates a distinct session. Test that multiple legacy `(source, title)` candidates are not replaced and return a manual-resolution result.

- [ ] **Step 5: Implement in-place re-import and prior snapshots**

For a matched target, save its before-image and current fingerprint, apply the imported content, then save the after-fingerprint. For sessions, update metadata and replace message rows inside one DB transaction. For files and MCP entries, capture the prior content and write the new content before marking the journal row successful.

- [ ] **Step 6: Add tests for safe, partial, and idempotent Undo**

Test that Undo restores a re-imported session's original messages; test that changing session content or a skill file after import causes Undo to leave that target untouched and return one skipped reason; call Undo twice and assert the second call makes no additional changes.

- [ ] **Step 7: Implement Undo checks and run service tests**

Compare each current target fingerprint with the journal's after-fingerprint before delete/restore. Mark only matching rows undone. Return partial outcome for changed/missing targets and retain the import job and item rows as audit history.

Run: `.\.venv\Scripts\python.exe -m pytest --no-cov -q tests/services/test_import_service.py`

Expected: all import, conflict, journal, re-import, and undo service tests pass.

### Task 3: Expose bulk actions, job details, and Undo through the import API

**Files:**
- Modify: `app/api/routes/import_route.py`
- Create: `tests/api/routes/test_import_route.py`

**Interfaces:**
- `PATCH /api/import/preview/{import_id}/items` accepts `{ "indexes": [0, 2], "action": "skip" | "import" | "reimport" }` and validates every index before changing any action.
- `POST /api/import/history/{job_id}/undo` returns job status plus per-item undone/skipped counts and reasons.
- `GET /api/import/history` adds `origin`, `undo_state`, `undo_available`, and item counts without removing existing response fields.
- `GET /api/import/history/{job_id}` returns item labels, kind, operation, outcome, and reason; it never returns before-snapshot contents.

- [ ] **Step 1: Add route tests for bulk action validation and API history state**

Assert that valid indexes update together, an invalid index changes none, old jobs return `undo_available=false`, and an Undo request reports the service result without exposing snapshot text.

- [ ] **Step 2: Run the API tests to confirm they fail for missing routes/fields**

Run: `.\.venv\Scripts\python.exe -m pytest --no-cov -q tests/api/routes/test_import_route.py`

Expected: 404/validation failures for the not-yet-implemented bulk, detail, and undo routes.

- [ ] **Step 3: Implement routes and response schemas in `import_route.py`**

Validate all bulk indexes before mutating the bundle. Re-run conflict detection at execution and preserve explicit `reimport`; if the target changed or became ambiguous after preview, return an item-level stale-conflict outcome rather than silently resetting it to skip.

- [ ] **Step 4: Run the focused route tests and existing import service tests**

Run: `.\.venv\Scripts\python.exe -m pytest --no-cov -q tests/api/routes/test_import_route.py tests/services/test_import_service.py`

Expected: route response shapes, item outcomes, and service behavior pass together.

### Task 4: Add explicit conflict re-import and bulk selection to Settings → Import

**Files:**
- Modify: `web/src/api/import.ts`
- Modify: `web/src/routes/settings.import.tsx`
- Test: `web/src/__tests__/routes/settings.import.test.tsx`

**Interfaces:**
- Add typed `ImportJobDetail`, `ImportItemOutcome`, and `ImportUndoResponse` frontend models matching Task 3.
- Add `updateItemsAction(importId, indexes, action)`, `getImportJob(jobId)`, and `undoImport(jobId)` API client functions.
- Preview selection applies only to currently visible/filtered rows; the separate **Select all conflicts** action selects every conflict in the detected bundle.

- [ ] **Step 1: Write UI tests for single conflict and bulk re-import**

Render a preview with two conflicts and one new item. Assert the conflict action reads **Re-import**, selecting one conflict enables **Re-import selected (1)**, and executing does not change the unselected conflict or new item action.

- [ ] **Step 2: Run the targeted UI test and confirm it fails**

Run from `web`: `bun run vitest run src/__tests__/routes/settings.import.test.tsx`

Expected: the test fails because the current preview has no bulk selection and uses the old `Replace` action.

- [ ] **Step 3: Add API client types and methods**

Model the new history and undo response fields exactly as returned by Task 3 and use the existing `apiFetch` helper.

- [ ] **Step 4: Implement row selection, conflict action labels, and confirmation**

Add per-row checkboxes, **Select all conflicts**, a selected count, and **Re-import selected**. Show a confirmation summary before replacing existing content. Keep new rows on **Import / Skip** and conflict rows on **Skip / Re-import**. Render partial undo reasons and disable Undo for pre-journal jobs.

- [ ] **Step 5: Run targeted UI tests and typecheck**

Run from `web`: `bun run vitest run src/__tests__/routes/settings.import.test.tsx` and `bun run typecheck`.

Expected: bulk action state and API types pass with no TypeScript errors.

### Task 5: Implement global auto-sync and result notifications

**Files:**
- Create: `web/src/lib/import-auto-sync.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/lib/desktop-notifications.ts`
- Test: `web/src/__tests__/lib/import-auto-sync.test.ts`
- Modify: `web/src/api/import.ts`

**Interfaces:**
- `startImportAutoSync({ onResult }): () => void` loads settings, starts one interval while enabled, and returns cleanup to stop the timer and abort outstanding work.
- A cycle scans each discovered source sequentially, detects it, assigns `skip` to existing conflicts and all kinds outside `session|skill|agent`, then executes only when at least one safe new item remains.
- Notification payload kind adds `import_sync`; notification body reports imported, failed, and review counts, with an action target for Settings → Import.

- [ ] **Step 1: Write coordinator tests for interval, allowlist, conflicts, and notification**

Use fake timers and mocked API boundaries to assert that no execution occurs for an empty scan, MCP is marked skip, a conflict is not replaced, a new skill/session is executed, no-change cycles stay quiet, and stop cleanup prevents later scans.

- [ ] **Step 2: Run the coordinator test to verify failure**

Run from `web`: `bun run vitest run src/__tests__/lib/import-auto-sync.test.ts`

Expected: module/function or behavior failures because no coordinator exists.

- [ ] **Step 3: Implement the single-flight coordinator**

Use the configured scan interval, avoid overlapping cycles, cancel pending detections when disabled/unmounted, cancel preview bundles that contain no importable work, and pass `origin: auto_sync` to the execute API. Add an optional request body to `POST /api/import/execute/{import_id}` and thread that origin into `execute_import`; manual callers continue to default to `manual`.

- [ ] **Step 4: Mount coordinator once above RouterProvider after backend readiness**

In `App.tsx`, keep one effect mounted in the `backend.ready` branch so route changes do not stop sync. Surface notification counts without emitting notifications when the cycle finds no changes.

- [ ] **Step 5: Add import notification action and run coordinator/UI checks**

Extend the existing notification payload and routing so clicking its action opens Settings → Import. Keep current notification enablement and sound settings.

Run from `web`: `bun run vitest run src/__tests__/lib/import-auto-sync.test.ts src/__tests__/routes/settings.import.test.tsx` and `bun run typecheck`.

Expected: automatic allowlist, scheduling cleanup, bulk UI, and notification routing pass.

### Task 6: Update help, feature docs, and changelog

**Files:**
- Modify: `web/src/help/locales/en.ts`
- Modify: `web/src/help/locales/vi.ts`
- Modify: `web/src/help/locales/ja.ts`
- Modify: `documents/features/multi-source-import.md`
- Modify: `documents/features/README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update all three Help locales**

Explain that Auto-sync imports new sessions, skills, and agents while EvoFlux is running; MCP remains manual; existing conflicts require explicit Re-import; Undo availability starts with journaled jobs and can be partial when an item was edited.

- [ ] **Step 2: Update feature documentation and Unreleased changelog**

Document user-facing behavior and limitations, add no new docs root, and extend the existing `[Unreleased]` entry for multi-source import.

- [ ] **Step 3: Verify documentation and working diff**

Run from the repo root: `git -c safe.directory=D:/evoelsewhere/evoflux diff --check` and scan the new/updated docs for `TODO`, `TBD`, stale conflict wording, and trailing whitespace.

Expected: no whitespace errors, no placeholder text, and all visible behaviors match the approved spec.

### Task 7: Run isolated end-to-end import smoke tests and final checks

**Files:**
- Test: `tests/api/routes/test_import_route.py`
- Test: `tests/services/test_import_service.py`
- Test: `tests/core/test_alembic_migrations.py`
- Test: `web/src/__tests__/lib/import-auto-sync.test.ts`
- Test: `web/src/__tests__/routes/settings.import.test.tsx`

- [ ] **Step 1: Add isolated API scenario for import → re-import → undo**

Use a temporary SQLite database and temporary config roots. Import a session, re-import changed content, fetch it through the session API, undo the re-import and verify original messages, then undo the creation job and verify no session/messages remain. Assert history rows persist with the expected statuses.

- [ ] **Step 2: Add auto-sync scenario for supported and review-only kinds**

Use a fixture bundle containing one new session, one new skill, one new agent, one MCP server, and one existing session conflict. Assert exactly three new items are imported, MCP and the conflict are skipped, and notification summary counts are accurate.

- [ ] **Step 3: Run focused backend validation**

Run: `.\.venv\Scripts\python.exe -m pytest --no-cov -q tests/services/test_import_service.py tests/api/routes/test_import_route.py tests/core/test_alembic_migrations.py tests/core/test_schema_version.py`

Expected: all focused import and migration tests pass against temporary databases.

- [ ] **Step 4: Run focused frontend validation**

Run from `web`: `bun run vitest run src/__tests__/lib/import-auto-sync.test.ts src/__tests__/routes/settings.import.test.tsx`; `bun run typecheck`; `bun run build`.

Expected: focused UI tests, types, and build pass. Report existing bundle warnings without treating them as errors.

- [ ] **Step 5: Run final repository review checks**

Run from the repo root: `.\.venv\Scripts\ruff.exe check app/services/import_service.py app/api/routes/import_route.py app/models/import_job.py app/models/import_job_item.py tests/services/test_import_service.py tests/api/routes/test_import_route.py`; `.\.venv\Scripts\ruff.exe format --check` on the same Python files; `git -c safe.directory=D:/evoelsewhere/evoflux diff --check`.

Expected: focused Ruff and whitespace checks pass; unrelated dirty files remain unchanged.
