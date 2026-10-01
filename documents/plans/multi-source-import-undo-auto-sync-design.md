# Multi-source import: auto-sync, re-import, and undo

**Status:** Draft for user review
**Date:** 2026-10-01
**Scope selected:** Automatically import new sessions, skills, and agents; keep MCP configuration under explicit review; support safe undo for newly journaled import jobs and bulk re-import of selected conflicts.

## Problem

The current Settings → Import page scans once when it opens. The Auto-sync setting stores an enabled flag and interval, but no background loop consumes them. Import history records aggregate counts only, so completed jobs cannot be rolled back item by item.

Conflict handling is also misleading. Detection marks existing items as `skip`; execution detects conflicts again and changes a selected `import` action back to `skip`. The `replace` action has no consistent target-update behavior: sessions can be duplicated while file-backed resources can be overwritten without a rollback record.

## Goals

- When enabled, sync newly detected sessions, skills, and agents periodically while EvoFlux is running, including while the user is on another route or the window is minimized.
- Keep MCP server configuration and other non-allow-listed item kinds out of automatic import. Make them visible for explicit review.
- Let users select multiple conflicting preview items and re-import them in one action.
- Make re-import update the matched existing item rather than create a duplicate.
- Let users undo a completed, journaled import job. Keep the job in history as an audit record.
- Protect edits made after import: an undo must report and leave changed targets intact instead of silently deleting or replacing them.

## Non-goals

- Running imports after the EvoFlux application has exited.
- Automatically importing MCP server commands, credentials, or unsupported item kinds.
- Reconstructing undo data for import jobs created before per-item journaling exists.
- Silently re-importing conflicts during auto-sync.

## Design

### Auto-sync coordinator

Mount one coordinator at the application root above route navigation, not inside the Import settings page. It reads the existing Auto-sync setting and interval, schedules a single-flight scan, and stops its timer when disabled or when the application shuts down. This keeps the task independent of the visible route and prevents duplicate concurrent scans.

For each discovered source, the coordinator calls the existing scan/detect/execute APIs. It permits automatic execution only for new `session`, `skill`, and `agent` items. Existing conflicts stay skipped; they are not overwritten in the background. MCP and other unsupported or non-allow-listed items stay in the review queue and appear in the result summary. If a source has nothing safe to import, cancel its temporary preview rather than create a noisy empty history entry.

Write an import-history job for each source execution, including whether it was started by auto-sync and per-item outcome summaries. Items left for review are not retained as an in-memory preview; the notification action opens Settings → Import and the source is detected again for review. If the source has disappeared, show that it must be selected again. Notify only when something was imported, an item failed, or items need review. Reuse the existing notification preferences and delivery path; include an action that opens Settings → Import. A quiet scan with no changes produces no notification.

### Per-item import journal

Add a persistent item journal associated with each new import job. Each journal row records the source item identity, item kind, operation (`created` or `reimported`), target reference, undo state, and an after-import fingerprint. Re-import rows also retain the prior target snapshot needed to restore the previous state. Session snapshots contain the session metadata and messages; file-backed snapshots contain the prior file contents or MCP entry.

The journal is written as part of the import operation so the target and its undo information cannot become detached. File snapshots and restores are staged outside database transactions; database changes remain transactional. Undo works per item and is idempotent. It deletes a created target or restores a re-imported target only when the current target still matches the recorded after-import fingerprint. Changed or missing targets are reported as skipped with a reason; other eligible items in the same job can still be undone.

Jobs created before this journal exists remain visible but show Undo as unavailable. The history row itself is retained after undo with an `undone` or `partially_undone` state and per-item outcome counts.

### Conflict and bulk re-import UX

For a new item, the row action is **Import** or **Skip**. For an existing item, the action is **Skip** or **Re-import**; choosing Re-import explicitly means replace the matched imported content in place. It never creates a second session with the same source identity.

Add row selection and bulk actions to the filtered, paginated preview. Users can select visible rows or all conflicts, then choose **Re-import selected**. The UI shows the selected count and a confirmation summary before executing replacement. Non-conflicting new items retain their Import action. If an older item has no stable source identity, use a unique source/title match; ambiguous matches require manual resolution instead of guessing.

The Previous imports table adds an Undo action for eligible jobs and shows completed, undone, partial, and failed outcomes. Undo confirmation names the job and counts the items that will be removed or restored.

### Matching and safety

- New imports store a stable `(source, source_item_id)` association where the parser supplies one.
- Legacy sessions without an association may use `(source, title)` only when the match is unique.
- Skill and agent targets use their normalized configured path/name; file fingerprints prevent undo from removing later edits.
- MCP remains manual in auto-sync. Explicit manual Re-import may update an MCP entry only after confirmation and with a saved prior entry for Undo.
- Credentials and API keys remain excluded from import.

## Data and API changes

- Add an import item journal table and migration; add job state/auto-sync metadata as needed.
- Extend execute and history responses with item outcomes and undo availability/state.
- Add an idempotent undo endpoint for completed journaled jobs.
- Add an import-job detail response so users can inspect per-item results and see which auto-sync items need manual review.
- Clarify preview action values so `reimport` has a distinct API meaning from importing a new item.
- Add a bulk action request for selected preview item indexes, validated against the pending import bundle.
- Extend the auto-sync notification kind and action target while preserving existing notification enablement and sound preferences.

Older import jobs keep their current aggregate history and cannot be undone. No schema or live database is modified by this design document.

## Acceptance criteria

1. With auto-sync enabled, a new session, skill, or agent found after the configured interval is imported without opening Settings → Import; a result notification links to that page.
2. Auto-sync never imports an MCP configuration, overwrites a conflict, or emits a notification for an unchanged scan.
3. A manually selected conflict action **Re-import** updates the matching session and messages in place; the session count does not increase.
4. Bulk selection re-imports only the selected conflicts, preserves unselected actions, and reports per-item results.
5. Undoing a new-item job removes its imported targets and leaves the history record marked undone.
6. Undoing a re-import restores the exact prior content when the target is unchanged; if a user edited a target after import, Undo leaves it intact and reports a partial result.
7. Old jobs without item journals show Undo unavailable and remain re-importable only when matching is unique.
8. Focused backend/API, migration, frontend behavior, and isolated app/API smoke tests cover these flows without touching the user's live database.

## Risks and mitigations

- Before-images for re-imported conversations can increase local storage. Store snapshots only for targets being replaced, keep them local, and report their lifecycle with the import job.
- Some source formats lack stable item IDs. Use conservative unique-match fallback and require manual resolution when ambiguous.
- A scan can encounter partially written source files. Parser warnings and per-item errors remain visible; one invalid item must not block other valid items in the same source.
- Import and file restoration span SQLite and the filesystem. The journal must support partial outcomes and idempotent retry rather than claiming atomic rollback across both stores.

## Review checklist

- Scope matches the selected option: session/skill/agent auto-sync, MCP review, safe undo, and bulk re-import.
- Existing import history remains audit data; pre-journal jobs are not falsely presented as undoable.
- Auto-sync skips conflicts; only a user-selected Re-import can replace an existing target.
- No credentials or API keys enter auto-sync.
- Implementation must add migration and update feature docs, help locales, changelog, API contracts, and focused tests.
