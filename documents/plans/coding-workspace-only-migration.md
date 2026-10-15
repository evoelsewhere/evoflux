# Retire the Coding project / multi-repo mechanism: Coding becomes workspace-only

Status: proposed — design only, nothing implemented.

Scope owner: Coding mode (backend + web + desktop + docs).

## 1. Goal, scope, non-goals

### 1.1 Goal

Coding mode keeps exactly one durable concept for where work happens: a
registered folder, i.e. the existing `coding_workspaces` registry. The entity
that grouped N repositories, owned Coding sessions, scoped memory and routed
scheduled tasks is deleted end to end: tables, columns, services, API routes,
URLs, sidebar sections, client state, help text and docs.

### 1.2 End state (fixed by user decision, not up for re-litigation)

1. One workspace = one durable shared root folder, registered once, reused by
   many sessions.
2. Two modes only: Work unchanged, Coding workspace-only.
3. Old data is dropped: project tables gone, legacy Coding sessions purged,
   users re-register their workspaces.
4. Old routes and URLs are removed outright — no compatibility shim, no
   redirect layer.

Concretely, after this plan lands:

- `coding_workspaces` (`app/models/chat.py:268`) is the only folder registry and
  survives untouched, column for column.
- A Coding session binds to one folder through `chat_sessions.workspace` and to
  nothing else.
- Coding URLs are `/coding` and `/coding/$sessionId`.
- The Coding sidebar lists workspaces, not projects.

### 1.3 In scope

Everything in §5: `coding_projects` / `coding_project_workspaces` storage,
`chat_sessions.project_id`, `scheduled_task.project_id`, the project API and its
schemas, the multi-repo service layer, project-scoped agent runtime and sandbox
roots, project memory scope, the app-search `project` kind, the Coding URL
contract, the project UI (sidebar, dialogs, panels, multi-repo tree), client
state and queries, notification deep-link contract, i18n keys, in-app Help,
feature/architecture/reference docs, CHANGELOG.

### 1.4 Non-goals (verified distinct, do not touch)

- Conductor "managed project" string ids: `app/conductor/models.py:104-254`
  (`project: RegisteredProject`, `project_id: str`), `app/conductor/*`
  (`governed_reconciler.py`, `managed_state.py`, `agent_runtime.py`),
  `app/core/agent_settings.py:52-66` (`agent_settings_id(*, project_id: str, ...)`,
  used at `:203`),
  and the agent settings surfaced through `app/api/routes/agents.py`.
- `managed_project_id` in `app/plugin_platform/models.py:183`.
- Skill `source == "project"` (`app/services/skills_service.py:173`,
  `app/api/schemas/skills.py:15`) — a skill directory kind, unrelated.
- `app/api/schemas/app_search.py:18` `"project"` is in scope (it is the Coding
  project kind); `"skill"` and the rest of that literal stay.
- Work mode, session folders (`chat_sessions.folder_id`), the scheduler feature,
  worktree management per workspace, coding semantic intelligence.
- `code_cross_repo_edges` — already dropped by
  `app/migrations/versions/00000046_drop_application_code_graph.py`; nothing
  left to remove.
- Frozen history: `documents/releases/**`, existing files under
  `documents/plans/**`.

## 2. Target contract after removal

### 2.1 Storage

**Drop** (one Alembic revision, §4):

| Object | Today | Action |
| --- | --- | --- |
| `coding_projects` table | `app/models/chat.py:437-474` | drop table and index `ix_coding_projects_created_at` |
| `coding_project_workspaces` table | `app/models/chat.py:477-514` | drop table including `uq_coding_project_workspaces_pair` and indexes `ix_coding_project_workspaces_project`, `ix_coding_project_workspaces_workspace` |
| `chat_sessions.project_id` | `app/models/chat.py:162-174` | drop column, index `ix_chat_sessions_project_id`, FK `fk_chat_sessions_project_id` |
| `scheduled_task.project_id` | `app/scheduler/models.py:32-40` | drop column, index `ix_scheduled_task_project_id`, FK to `coding_projects.id` |

**Keep** exactly as-is:

- `coding_workspaces` (`app/models/chat.py:268-301`): `id`, `path` (unique),
  `kind` (`repo` | `worktree`), `source_path`, `name`, `managed`, `hidden`,
  `deleted_at`, `created_at`, `updated_at`. No column is added; the registry
  already has no project column.
- `chat_sessions.workspace` (`app/models/chat.py:161`) — the session-to-folder
  binding, a nullable path string.
- `chat_sessions.folder_id` (`app/models/chat.py:177-189`) — sidebar folder,
  unchanged.
- `scheduled_task.mode` and `scheduled_task.workspace`
  (`app/scheduler/models.py:25-31`) — the routing target after this change.
- `memory_facts` (`app/models/memory.py:24-98`) with `scope_type`
  (`:45`) / `scope_key` — schema unchanged; only the `project` scope value stops
  being produced (§3, row 1).

### 2.2 Session-to-workspace binding

- A Coding session requires a non-empty `workspace`. That validation already
  exists at `app/api/routes/team/chat.py:1391-1396` and keeps its 422 branch.
  The project-resolution branch at `app/api/routes/team/chat.py:1397-1400` dies,
  together with the membership rule and the project 422.
- Registration stays on the same code path: `upsert_coding_workspace`
  (`app/services/coding_workspace_service.py:15-76`) is the only writer of
  `coding_workspaces`, called from the create-session flow and from
  `app/agent/tools/builtin/worktree.py:219`. Re-registering a path reuses the
  row through the unique index on `path`.
- Authorization collapses to: the folder exists, is not hidden, is not
  `deleted_at`, and passes the workspace trust check.
  `app/services/coding_workspace_authorization.py` (23 lines today) loses its
  delegation to `coding_project_service` and keeps only that check.
- There is no per-session repository list any more. Every consumer that today
  receives a list of repositories receives a single-element list holding the
  session workspace (see §5 P4).

### 2.3 Scheduled task target

- `scheduled_task.project_id` is gone. Routing is `mode` + `workspace`:
  `mode='work'` → the default team; `mode='coding'` → the per-workspace team for
  `workspace`.
- `_validate_project_target` (`app/scheduler/scheduler.py:119-121`) is deleted,
  and `_validate_project_compat` (`:124-166`, which loads `CodingProject` at
  `:154` and resolves the project's repository paths at `:157-162`) is replaced
  by workspace-only validation: `mode='coding'` requires `workspace`, a
  `workspace` change is revalidated as a folder that exists and is trusted, and
  the "session is bound to project X" check at `:227-230` goes away.
- Create and update paths lose every `project_id` write:
  `app/scheduler/scheduler.py:358-377`, `:414-442`, `:494`.
- The firing path stops recovering a project from the session row:
  `app/scheduler/scheduler.py:743-771` (the `row.project_id` fallback and
  `get_project_workspace_paths`), `:856-864`, `:891`.
- API schema: `app/scheduler/schemas.py:39-42` (`project_id` field),
  `:73-76` (`mode == "coding" and self.project_id is None` rule), `:119`,
  `:149-150`, `:194` are removed; the coding-requires-project rule becomes
  coding-requires-workspace.
- CLI/tool surface: `app/agent/tools/builtin/schedule.py:380` stops passing
  `project_id`; the "This task targets a folder that is not in exactly one
  project" error at `app/agent/tools/builtin/schedule.py:177-178` is deleted.

### 2.4 HTTP API kept and removed

**Removed outright** — `app/api/routes/team/projects.py` (217 lines) is deleted
whole, plus its unmount at `app/api/routes/team/__init__.py:49` and `:95`, and
`app/api/schemas/projects.py` (29 lines) with its import at
`app/api/schemas/sessions.py:12`. Endpoints going away:

| Method + path | Today |
| --- | --- |
| `GET /team/projects` | `projects.py:105` |
| `POST /team/projects` | `projects.py:112` |
| `GET /team/projects/{project_id}` | `projects.py:127` |
| `PUT /team/projects/{project_id}` | `projects.py:132` |
| `DELETE /team/projects/{project_id}` | `projects.py:151` |
| `POST /team/projects/{project_id}/workspaces` | `projects.py:157-159` |
| `DELETE /team/projects/{project_id}/workspaces/{workspace_id}` | `projects.py:178` |
| `PUT /team/projects/{project_id}/workspaces/{workspace_id}` | `projects.py:186-188` |

**Changed** — request/response shapes that carried `project_id`:

| Schema | Line | Change |
| --- | --- | --- |
| `SessionCreate` | `app/api/schemas/chat.py:58`, `:99`, `:115` | drop `project_id` |
| Coding-requires-workspace rule | `app/api/schemas/chat.py:141-146` | becomes "workspace is required when mode='coding'" (drop the `or name a project_id` escape) |
| `SessionResponse`-family | `app/api/schemas/sessions.py:26`, `:153` | drop `project_id` |
| `CodingWorkspaceTreeRepository` | `app/api/schemas/sessions.py:132-135` | drop `project_id` |
| `CodingWorkspaceTreeResponse` | `app/api/schemas/sessions.py:138-143` | drop `projects: list[ProjectResponse]` |
| `AppSearchKind` literal | `app/api/schemas/app_search.py:18` | drop `"project"` |
| `ScheduledTask` schemas | `app/scheduler/schemas.py:39-42` and refs | drop `project_id` |

**Kept unchanged**: `/team/workspace/validate`
(`app/api/routes/team/chat.py:1157`), `/team/workspace/browse` (`:1188`),
`/team/workspace/tree` (`:1465`, payload changed as below), session CRUD,
sessions listing, files, terminal, git/review endpoints (arguments narrowed per
§5 P4).

### 2.5 `GET /team/workspace/tree` — the one payload change

Today the endpoint filters every workspace without a project owner out of the
result (`app/api/routes/team/chat.py:1509-1512`, `if owner is None: continue`),
and resolves ownership through `CodingProjectWorkspace` joins. After the change:

- Every visible `CodingWorkspace` row is listed: not `hidden`, `deleted_at`
  is null, ordered by `created_at` (`app/services/coding_workspace_service.py:79-91`).
- Rows with `kind == "worktree"` and a `source_path` become children
  (`worktrees: [...]`) of the repository whose `path` equals that `source_path`;
  a worktree whose source is not in the list is listed as a top-level
  repository (the `pending_worktrees` fallback at
  `app/api/routes/team/chat.py:1501-1508` is absorbed into that rule).
- `repositories[]` keeps `workspace_id`, `path`, `name`, `kind`, `hidden`,
  `managed`, `worktrees[]` and loses `project_id`.
- `projects[]` is removed from the response.
- The endpoint keeps its name, verb and path. No new endpoint is added; the
  sidebar's existing single `coding-overview` fetch
  (`web/src/queries/keys.ts:119`, `web/src/api/client/team.ts:388`) keeps working
  with a narrower payload.

### 2.6 Client store events

`coding_workspace` and `coding_workspace_paths` are client-synthesized store
events, not server SSE frames: they are built in
`web/src/stores/useTeamStore/sse-reducer.ts:406-416` from the store's current
`projectId`. Both lose their `projectId` field in P4; `workspace` and `paths`
stay. No backend SSE payload changes.

### 2.7 Coding URL contract

| Today | After |
| --- | --- |
| `/coding` | `/coding` (unchanged; reopens the last workspace) |
| `/coding/$focusId` | deleted |
| `/coding/$focusId/$sessionId` | `/coding/$sessionId` |

`$focusId` was the project UUID (`web/src/utils/workspace.ts:100-101`,
`web/src/router.ts:48-83`). The new single dynamic segment follows the existing
Work-mode pattern (`web/src/router.ts:30-41`): `$sessionId` must look like a
UUID; anything else is treated as unknown and lands on `/coding`. No redirect
shim is added for `/coding/$focusId` (user decision 4); a stale bookmark or a
stale saved route falls through the router's existing unknown-path handling, and
`loadModeRoute('coding')` must drop a saved route that is no longer routable
(`web/src/lib/mode-route.ts`, exercised by
`web/src/__tests__/lib/mode-route.test.ts`).

### 2.8 Frontend state after removal

- Sidebar anchor: the **workspace path**, not a project id. The one-shot scope
  request and the "selected project" state in
  `web/src/stores/useUIStore.ts:108-130` and `:712-720` are re-keyed to
  `workspace: string`.
- `STORAGE_KEYS.coding.lastProject` and `lastFocus`
  (`web/src/lib/storage-keys.ts:58-63`) are replaced by one
  `coding.lastWorkspace` key. Stale values from older installs are never read.
- Queries: `web/src/queries/useProjectsQuery.ts` stops being a project query
  file. `queryKeys.projects` (`web/src/queries/keys.ts:120-122`) is deleted;
  `queryKeys.codingOverview()` (`:119`) stays.
- `sessionRepositoryPaths` (`web/src/components/TeamChatView/index.tsx:456-479`)
  collapses to `[workspace]`, so its nine consumers keep their signatures and
  receive one folder.

## 3. Decision table for the non-mechanical items

Each row: recommended default, rationale, and whether the user must confirm it
before the coder starts.

| # | Item | Recommended default | Rationale | User must confirm |
| --- | --- | --- | --- | --- |
| 1 | Memory scope key | Delete the `project` scope value and the rows that carry it | `project` was a first-class memory scope (`app/services/scoped_memory.py:106-107`), it is the first fallback in scope coercion (`:139`), and the extractor defaults to it (`:394`). With projects gone, `scope_key` holds a UUID of a deleted row: dead weight that can never be read back. Default: drop `project` from `:106-107`, `:139`, the weight table and `:394` (default becomes `workspace`), and `DELETE FROM memory_facts WHERE scope_type = 'project'` in the new migration. | Yes — deleting user memory is destructive |
| 2 | Scheduler routing target | Route on `mode` + `workspace` only | `scheduled_task.project_id` (`app/scheduler/models.py:32-40`) existed only to pick a project's team. The task already stores the folder it runs in (`coding_purge_service` reads `task.workspace`), so the workspace is the natural and sufficient target. Coding tasks that have no `workspace` cannot be routed at all after the change: disable and delete them in the migration rather than guessing a folder. | Yes — deletes unroutable Coding tasks |
| 3 | Notification deep-link contract | Remove `focus_id` for both modes | Coding notifications required a UUID `focus_id` = project (`desktop/src-tauri/src/notification_activation.rs:72-83` rejects a non-UUID, `:101-103` appends it, `web/src/lib/notification-activation.ts:170-195`, `:209` read it back). With no project there is no focus id; a Coding notification now deep-links to `/coding/$sessionId`, which is already carried by `session`. The protocol is app-internal (Rust produces, the same app's web layer consumes) and both sides change in P3, so keep `v=1` and make `focus_id` forbidden for every mode. | No — engineering decision, no external consumer |
| 4 | Sidebar anchor without `$focusId` | Anchor on the workspace path, persisted once | The sidebar needs a stable selection to restore: today it is the project id (`useUIStore.codingSelectedProjectId`) plus the `$focusId` URL segment and two localStorage keys. The replacement is the registered folder path, which is also the session binding, so URL, sidebar, store and scope requests agree on one identity. `$focusId` is deleted rather than repurposed. | No — engineering decision |
| 5 | Multi-repo diff / review / search scopes | Every scope collapses to one workspace | Today one project fans out to N repositories through `sessionRepositoryPaths` (`TeamChatView/index.tsx:456-479`) for the file watcher (`:770`), global search (`:1296`), the changes review panel, the file tree (`:1662`) and the git panel (`:1794`); the backend equivalent is the project path helpers used by session creation (`app/api/routes/team/chat.py:317-323`, `:1361-1369`) and by the scheduler (`app/scheduler/scheduler.py:139-162`, `:761-762`). After the change a session has one folder, so each of these receives `[workspace]`. The loss is real: no PR list or cross-repo diff spanning several repositories. Working across repositories becomes: open the other folder in its own session. | Yes — visible functional loss |
| 6 | Legacy folder-focus fallback | Delete both legacy branches, keep the generic not-found toast | `web/src/routes/work.tsx:130-142` (project-focus toast) and `:250-263` (`legacyFolderFocus`) existed to rescue old standalone-folder URLs. Under the new contract `/coding/$sessionId` is the only session URL, so an unresolvable id is handled by the existing generic branch at `work.tsx:266-275`. No bespoke message survives. | No — engineering decision |
| 7 | Cross-repo semantics loss in prompts, help and docs | Rewrite as "one workspace = one folder" | Project semantics are baked into agent guidance (`app/agent/tools/builtin/code_reviews.py:139`, `:147-148`, `:160-162`, `:455`), the built-in prompts (`app/agent/builtin_prompts.py:295`) and in-app Help. The default keeps the guidance honest: the agent sees one folder and is told how to work across folders (one session each / ask the user). No cross-repo tooling is invented. | Yes — product wording and capability change users will notice |

Items 1, 2, 5 and 7 are the four that need a user answer (§8). Items 3, 4 and 6
are engineering decisions the coder can take as written.

## 4. Migration strategy

### 4.1 New revision

One revision, `app/migrations/versions/00000075_drop_coding_project_tables.py`,
`revision = "00000075"`, `down_revision = "00000074"` (current head:
`app/migrations/versions/00000074_retire_sleep_text_sentinel.py:24-25`; no file
revises 74).

Upgrade order matters, because a child row must stop referencing a parent before
the parent disappears (SQLite does not enforce it, but migration 00000053
re-reads the schema and a dangling FK makes the upgrade path unreproducible):

1. Purge legacy project-owned sessions first, reusing the rules that already
   exist in `app/services/coding_purge_service.py` (`_session_closure`,
   `_stop_session_runtime`, `purge_project`): every Coding session with a
   non-null `project_id` is deleted, together with messages, participants,
   todos, notes and any sibling sessions in its closure. Work sessions are
   untouched.
2. Disable and delete unroutable Coding scheduled tasks (§3 row 2); null out
   `project_id` on the remaining tasks so no row references a table that is
   about to be dropped.
3. `DELETE FROM memory_facts WHERE scope_type = 'project'` (§3 row 1).
4. `chat_sessions`: drop index `ix_chat_sessions_project_id`, drop FK
   `fk_chat_sessions_project_id`, drop column `project_id` — the exact inverse of
   how `00000014_create_coding_projects.py` added them, using
   `op.batch_alter_table("chat_sessions")` and `batch_op.drop_constraint(..., type_="foreignkey")`
   as `00000044_add_scheduler_routing_targets.py:31-35` does for the scheduler
   column. Batch mode is mandatory for SQLite table rebuilds.
5. `scheduled_task`: same three steps for `project_id`.
6. Drop `coding_project_workspaces` (its FK to `coding_projects` cascades), then
   `coding_projects`.

### 4.2 Generated files and worktrees of purged sessions

Purged Coding sessions leave real directories on disk: worktrees created under a
session (`app/agent/tools/builtin/worktree.py`) and registered as
`coding_workspaces` rows with `kind = "worktree"`. The migration:

- deletes `coding_workspaces` rows whose `kind = "worktree"` and whose
  `source_path` no longer resolves to a registered repository (orphans);
- leaves untouched every `kind = "repo"` row, including folders that used to be
  a project's repositories — those are exactly the folders users re-register and
  must not be lost;
- **does not delete files or directories on disk.** A database migration must
  not delete user source. Orphaned worktree directories are reported to the user
  as a startup log line and left alone.

### 4.3 Ordering versus 00000048 and 00000053

- `00000048_backfill_project_session_ownership.py` repaired legacy project
  ownership; `00000053_repair_foreign_key_integrity.py` repairs dangling FKs and
  references `chat_sessions.project_id`. Both run **before** 00000075 on every
  upgrade path (a fresh database walks 1→75 in order; an installed database sits
  at some revision < 75 and upgrades forward), so neither needs editing. Do not
  back-edit them: they are history and their assertions about the schema at
  their own revision stay true.
- 00000075 is the new head, so no successor revision has to be reordered.

### 4.4 Downgrade stance

`downgrade()` recreates the columns and tables but **not the data** — purged
sessions, purged project rows and purged memory facts are not recoverable. Follow
the existing convention (`00000048:71-74`, `00000053:191-194`): recreate the
shape, and state in the function docstring that the downgrade restores schema
only. Recreating the columns is required so `alembic downgrade -1` does not leave
a database that SQLModel metadata can no longer describe.

### 4.5 Required companion changes for the migration

- `app/core/schema_version.py`: bump `SCHEMA_HEAD` to `"00000075"`. This is the
  desktop startup compatibility gate, and `tests/core/test_schema_version.py:27`
  asserts exactly one head equal to `SCHEMA_HEAD`.
- `tests/core/test_alembic_migrations.py`: the fresh-upgrade test ends with a
  version assertion (`:891`, `assert version == SCHEMA_HEAD`) and a set of
  disjoint-column assertions for retired tables; add `coding_projects` and
  `coding_project_workspaces` to the retired set and assert `project_id` is
  absent from `chat_sessions` and `scheduled_task`.

## 5. Phase-by-phase work breakdown

Landing boundary: P1 and P2–P5 are one coordinated removal. Each phase keeps
every quality gate green in order, but the Coding UI is functionally degraded
between P1 and P4 (the backend no longer serves projects while the sidebar still
draws them). Do not release a build between P1 and P4; P6 is the first
release-ready state.

### P1 — Backend: delete the project entity end to end (one atomic commit)

The model class, its FK columns, the services, the routes and their tests form
one connected component — deleting `CodingProject` breaks every importer, so
this cannot be split into smaller green commits. Backend docs that describe the
removed API/storage land here too.

| File | Change |
| --- | --- |
| `app/migrations/versions/00000075_drop_coding_project_tables.py` | new revision per §4.1 |
| `app/core/schema_version.py` | `SCHEMA_HEAD = "00000075"` |
| `app/models/chat.py:437-514` | delete `CodingProject` and `CodingProjectWorkspace` |
| `app/models/chat.py:162-174` | delete `ChatSession.project_id` |
| `app/scheduler/models.py:32-40` | delete `ScheduledTask.project_id` |
| `app/services/coding_project_service.py` | delete the whole file (329 lines) |
| `app/services/coding_workspace_authorization.py` | keep only the folder/trust check; drop the `coding_project_service` delegation |
| `app/services/coding_purge_service.py` (450 lines) | delete `purge_project`, `purge_project_workspace`, `purge_standalone_coding_sessions` and the `project_id` reassignment block; keep session-closure and session-scoped purging used by other callers |
| `app/services/coding_workspace_service.py:15-76` | unchanged (registry writer) |
| `app/services/scoped_memory.py:106-107`, `:139`, `:394` | drop the `project` scope and its fallback; extractor default becomes `workspace` |
| `app/services/memory.py:400-401` | drop the project-scoped visibility widening |
| `app/services/app_search_service.py:37-40`, `:387-407`, `:410-471` | drop the `project` search kind and its item builder; workspace items lose the `project_id` metadata |
| `app/services/chat_service.py:1044`, `:1079-1080`, `:1135`, `:1144-1145`, `:1182-1187` | drop the `project_id` argument and the project-scoped branch of `get_latest_top_level_session`; lookups key on `workspace` |
| `app/services/agent_service.py:512`, `:568`, `:591`, `:665`, `:685` | drop the `project_id` pass-throughs |
| `app/services/interactive_message_service.py:59-72`, `:94` | delete `_project_paths_for_session` and its call site; the interactive session's roots are its own workspace |
| `app/services/shell_service.py:50`, `:80` | drop the project scope |
| `app/api/routes/team/projects.py`, `app/api/schemas/projects.py` | delete both files |
| `app/api/routes/team/__init__.py:49`, `:95` | unmount the projects router |
| `app/api/routes/team/chat.py:73-74`, `:317-323`, `:519-523`, `:1361-1369` | delete the `coding_project_service` import block and the three multi-repo path helpers (`get_visible_project_ids_for_workspace_path`, `get_project_workspace_paths`, `split_project_paths_for_workspace`) |
| `app/api/routes/team/chat.py:1397-1400`, `:1465-1530` | delete the project-resolution branch; rewrite the tree payload per §2.5 |
| `app/api/routes/team/reviews.py:435`, `:438`, `:446-453`, `:516` | drop `project_id` from the request/response path |
| `app/api/routes/team/editor.py:95-100` | same |
| `app/api/routes/team/git_ai.py:38-43` | same |
| `app/api/routes/team/suggested_tasks.py:26`, `:168-178`, `:201`, `:233` | drop the project lookup, the "not exactly one project" error and the two `project_id` writes |
| `app/api/schemas/chat.py:58`, `:99`, `:115`, `:141-146`, `app/api/schemas/sessions.py:12`, `:26`, `:132-143`, `:153`, `app/api/schemas/app_search.py:18` | drop `project_id` / `projects` and the "or name a project_id" escape per §2.4 |
| `app/api/app.py:152-158` | delete the startup `purge_standalone_coding_sessions` block and its import |
| `app/scheduler/scheduler.py:119-166`, `:227-230`, `:358-377`, `:414-442`, `:494`, `:743-771`, `:856-891` | delete `_validate_project_target`; replace the project-compat validation with workspace-only validation; drop every `project_id` write and the firing-path project recovery |
| `app/scheduler/schemas.py:39-42`, `:73-76`, `:119`, `:149-150`, `:194` | drop `project_id`; coding requires `workspace` |
| `app/agent/mode/team/team.py:1637`, `:1667`, `:1688`, `:1723` | single-workspace team snapshot; drop the multi-repo repository resolution |
| `app/agent/mode/team/member.py:496-501`, `:518`, `:544-553` | drop project ownership when a member session row is created or adopted |
| `app/agent/sandbox.py:4`, `:100`, `:344`, `:454` | comments and error/docstring wording only; the sandbox already grants the session workspace, and no project root expansion happens here |
| `app/agent/tools/builtin/code_reviews.py:64-77`, `:139`, `:147-148`, `:160-162`, `:455` | drop the project-repository target resolution and the repository-choice prompt; one workspace is the target |
| `app/agent/tools/builtin/schedule.py:177-178`, `:380` | drop the project target and its error |
| `app/agent/builtin_prompts.py:295` | rewrite the multi-repo guidance (§3 row 7) |
| `tests/services/test_coding_purge_service.py`, `tests/api/routes/test_scheduler.py`, `tests/services/test_coding_workspace_service.py`, `tests/api/routes/test_team_db.py`, `tests/services/test_scoped_memory.py`, `tests/api/routes/test_reviews.py`, `tests/agent/tools/test_schedule_tool.py`, `tests/services/test_app_search_service.py`, `tests/api/routes/test_team_worktrees.py`, `tests/scheduler/test_schemas.py`, `tests/api/routes/test_suggested_tasks.py`, `tests/core/test_alembic_migrations.py`, `tests/core/test_schema_version.py` | delete project-driven cases, rewrite the rest against workspaces; add the new tests from §6 |
| `documents/reference/http-api.md:31`, `:64` | remove the projects route row and its description |
| `documents/architecture/data-and-storage.md`, `system-overview.md`, `backend-runtime.md` | table list and project-ownership statements |
| `CHANGELOG.md:5` | first `## [Unreleased]` entry (Changed) |

Exit criteria: no `project_id`/`CodingProject` symbol remains in `app/` except
the out-of-scope Conductor/plugin sites; the full backend gate is green; the
migration upgrades a fresh database and an installed pre-75 database.

Verify:
```bash
uv run ruff check app/ tests/ && uv run ruff format --check app/ tests/ && uv run ty check app/ && uv run pytest --no-cov -q
```
Plus a scope check that only allowed references remain:
```bash
grep -rn "CodingProject\|coding_project_workspaces\|coding_projects" app tests
```

### P2 — Frontend data layer: collapse project queries to workspaces

No UI change; consumers keep compiling because the hooks keep their names and
their return shapes stay list-shaped.

| File | Change |
| --- | --- |
| `web/src/queries/useProjectsQuery.ts:17-160` (163 lines) | keep the file and the exported hook names; `useCodingOverviewQuery` (`:17`) returns workspaces only, `useSessionProjectQuery` (`:47`) returns the session workspace, the five project mutations (`:60`, `:73`, `:90`, `:105`, `:124`, `:144`) are dropped in P5; `projectId` fields become `null` |
| `web/src/queries/keys.ts:120-122` | delete `queryKeys.projects`; keep `codingOverview()` at `:119` |
| `web/src/hooks/useActiveSkillDiscoveryScope.ts:13-25` | discovery scope = the active workspace only; drop `useProjectQuery` |
| `web/src/components/TeamChatView/index.tsx:452` | drop the session-project query; the active workspace comes from the store/URL |
| `web/src/api/client/team.ts:387-390` | `getCodingWorkspaceTree` keeps its path; its parsed type loses `projects` |
| `web/src/api/types.ts:693-715` | keep `CodingProject`-shaped types only where P5 deletes them; the tree types lose `projects` and repository `project_id` |
| `web/src/__tests__/**` | update fixtures that assert project lists |

Exit criteria: `bun run lint`, `typecheck` and `build` are green; no query hook
issues `/team/projects`.

Verify:
```bash
cd web && bun run lint && bun run typecheck && bun run build
```

### P3 — Coding URL contract and deep links

| File | Change |
| --- | --- |
| `web/src/router.ts:48-83` | replace `/coding/$focusId` + `/coding/$focusId/$sessionId` with `/coding` + `/coding/$sessionId`; mirror the Work route guard at `:30-41` |
| `web/src/router.ts:56-101` | delete `loadLastCodingFocusId`, `clearLastCodingFocus`, `codingFocusId`, `isProjectFocusId`, `PROJECT_FOCUS_ID_RE`; keep `workspaceFromSession` |
| `web/src/utils/workspace.ts:90-101` | same deletions; the file keeps path helpers |
| `web/src/routes/work.tsx:100-142`, `:240-275` | delete the project-focus toast and `legacyFolderFocus`; resolve `$sessionId` only; keep the generic not-found toast |
| `web/src/routes/work.tsx:296-310` | stop priming `projectId` in `useTeamStore` |
| `web/src/components/CodingSidebar.tsx:744`, `:886-887`, `:1049`, `:1104-1105` | retarget every `navigate({ to: "/coding/$focusId…" })` call (the project navigator at `:1119` and its 311 project references belong to P4a) |
| `web/src/components/TeamChatView/index.tsx:877-884`, `:934-937` | retarget the navigate call and drop the `projectId` priming (`:935` reads `session.project_id`) |
| every `/coding` link producer | `grep -rn "\"/coding\|'/coding" web/src` and retarget each |
| `web/src/lib/mode-route.ts` (consumed by `web/src/__tests__/lib/mode-route.test.ts`) | drop a saved coding route that is not `/coding` or `/coding/<uuid>` |
| `web/src/lib/notification-activation.ts:170-195`, `:209` | drop the coding `focus_id` requirement and the `focusId` field |
| `desktop/src-tauri/src/notification_activation.rs:72-83`, `:101-103` | stop requiring a UUID focus for coding; stop appending `focus_id`; a coding activation with a focus id is rejected like Work's |
| `web/src/__tests__/lib/notification-activation.test.ts` | update to the focus-less contract |
| new `web/src/__tests__/lib/coding-route.test.ts` | route-shape test (§6) |
| `desktop/src-tauri/src/main.rs` (menu/tray at `:173`, `:4302`, `:5018`, `:5143`) | verify only — no change expected |

Exit criteria: no `$focusId` or project focus id remains in web or desktop;
`cargo check` green.

Verify:
```bash
cd web && bun run lint && bun run typecheck && bun run build
cd desktop/src-tauri && cargo check
grep -rn "focusId\|focus_id\|PROJECT_FOCUS_ID_RE" web/src desktop/src-tauri/src
```

### P4 — Coding UI collapse (sidebar, panels, dead components)

Recommended as three commits, each ending green:

**P4a — Coding sidebar becomes a workspace list.**
`web/src/components/CodingSidebar.tsx` (2340 lines, 311 project references) is
rewritten around the `coding-overview` workspace list: the PROJECTS navigator
(`:1119`) and its section, the add-repository dialog (`:1557-1573`), the
trust-into-project dialog (`:1801-1858`), the create-project dialog
(`:1865-1890`), the follow-on dialogs at `:2106-2120` and `:2196-2214`
("Remove repository from project"), the delete-project dialog (`:2272-2290`) and
the `ProjectSetupModal` mount (`:1543`) all go; "create a project for this
folder" (`:755-782`) becomes "register this folder as a workspace"; the sidebar
composes existing shell primitives (`web/src/components/shell/`). New-session
creation sends `workspace` only.

**P4b — Panels take one workspace.**
`web/src/components/CodingWorkspacePanel.tsx:251-265`, `:393`, `:451-453`,
`:627`: delete the `isProjectMode` branch and keep the single-workspace path
(`WorkspaceFileTree` + `getCodingWorkspaceGitDiff(workspace)`);
`web/src/components/TeamChatView/index.tsx:448`, `:452-479` returns
`[workspace]`; consumers narrow without signature changes (`:718`, `:770`,
`:1296`, `:1662`, `:1794`);
`web/src/components/GitWorkspacePanel.tsx`, `ChangesReviewPanel.tsx`,
`PullRequestsPanel.tsx`, `web/src/components/InputBar.mentions.ts:19`,
`web/src/hooks/useWorkspaceFileWatcher.ts:718`,
`web/src/queries/useProblemsQuery.ts:28` and
`web/src/components/TeamChatView/useGlobalSearch.ts:34-35`, `:111-143`,
`:174-177` take a single workspace.

**P4c — Delete the dead project components.**
`web/src/components/MultiRepoFileTree.tsx` (178 lines),
`ProjectInfoCard.tsx` (149), `ProjectSetupModal.tsx` (425), and
`web/src/__tests__/components/ProjectInfoCard.test.tsx`; update
`web/src/__tests__/utils/workspace.test.ts` and
`web/src/__tests__/utils/coding-sidebar-selection.test.ts`; sweep the ~11
remaining test files with incidental project references.

Exit criteria: no project dialog, panel or component remains under
`web/src/components/`; the sidebar lists workspaces and creates sessions without
a project.

Verify:
```bash
cd web && bun run lint && bun run typecheck && bun run build
```

### P5 — Client state and API client cleanup

| File | Change |
| --- | --- |
| `web/src/stores/useTeamStore/types.ts:36-43`, `:101`, `:185` | drop `projectId` from the event payloads, the state field and `beginResolvedSession` |
| `web/src/stores/useTeamStore/index.ts:316`, `:395-421`, `:518-549`, `:615`, `:1460` | drop the persisted key, the state field, the two synthesized events and the draft restore |
| `web/src/stores/useTeamStore/sse-reducer.ts:406-416` | drop `projectId` from the two synthesized events |
| `web/src/stores/useUIStore.ts:108-130`, `:712-720` | re-key the scope request and selection to `workspace: string` |
| `web/src/stores/cache-invalidation-bridge.ts:19-31`, `:81`, `:89-92` | delete `sessionRepositories` and invalidate only the event's workspace |
| `web/src/lib/storage-keys.ts:59-63` | replace `lastProject` / `lastFocus` with `coding.lastWorkspace` |
| `web/src/api/client/team.ts:37-40`, `:1067-1150` | delete the whole Coding Projects API section and its type imports |
| `web/src/api/types.ts:193`, `:198`, `:644`, `:693-703`, `:786`, `:1031`, `:1486`, `:1508`, `:1708` | delete the project types and `project_id` fields; keep `managed_project_id` at `:2096` (Conductor) |
| `web/src/queries/useProjectsQuery.ts:17-160`, `web/src/queries/keys.ts:19`, `:39`, `:115-122` | delete the eight project hooks/mutations, `queryKeys.projects` and the project session key |

Exit criteria: `grep -rn "projectId\|project_id" web/src` returns only
Conductor/plugin-platform sites and unrelated words like "projection".

Verify:
```bash
cd web && bun run lint && bun run typecheck && bun run build
grep -rn "projectId\|project_id" web/src | grep -v managed_project_id
```

### P6 — Copy, in-app Help, i18n and documentation

| File | Change |
| --- | --- |
| `web/src/i18n/messages/en.json`, `ja.json`, `vi.json` | remove every Coding-project key in all three files in one change (they are line-aligned; `web/src/__tests__/i18n/i18n.test.tsx` asserts parity and a key-count floor, so a partial removal fails the suite). Keep Conductor-managed `project` keys ("Project library", "Project version", "Star an Agent …") |
| `web/src/help/locales/en.ts:42` | description no longer says "projects" |
| `web/src/help/locales/en.ts:1147-1236` (`coding-workspaces`) plus the matching ranges in `ja.ts` and `vi.ts` | rewrite to workspace wording: register a folder, sessions in that folder, how to work across folders |
| `web/src/routes/settings.language-servers.tsx:29`, `:206` | wording and query name follow P2 |
| `documents/features/modes-workspaces-and-sessions.md` | primary rewrite: drop the project ownership section (`:35-37` and the startup-purge note at `:38-40`), document the workspace-only model |
| `documents/features/README.md` | add the catalogue row for the modes page (it is currently an orphan page; the README is 9 lines and has no Coding row) |
| `documents/architecture/web-frontend.md`, `coding-semantic-intelligence.md` | routes, sidebar structure, scope statements |
| `CHANGELOG.md:5-13` | final wording of the `[Unreleased]` entries |

Exit criteria: three locales hold identical key sets; Help renders the new
wording in en/ja/vi; no feature page still describes a project.

Verify:
```bash
cd web && bun run lint && bun run typecheck && bun run build
uv run pytest --no-cov -q
```

### P7 — Verification sweep

Run every gate once on the assembled change, plus a manual smoke pass: register
a folder, create two sessions in it, restart the app and confirm both reopen
under `/coding/$sessionId`; run a Coding scheduled task with no project target;
open a stale `/coding/<project-uuid>` URL and confirm it lands on `/coding`.

Verify: §6 command block, plus `git diff --check`.

## 6. Verification plan

### 6.1 New tests to add

| Test | File | Asserts |
| --- | --- | --- |
| Migration head and dropped objects | `tests/core/test_alembic_migrations.py` | fresh upgrade reaches `SCHEMA_HEAD == "00000075"`; `coding_projects` and `coding_project_workspaces` absent; `project_id` absent from `chat_sessions` and `scheduled_task`; a pre-75 database with a project-owned Coding session upgrades with that session gone and its workspace folder row intact |
| Migration downgrade shape | same file | `alembic downgrade -1` recreates the columns and tables (schema only) and the schema still matches SQLModel metadata |
| Route shape | new `web/src/__tests__/lib/coding-route.test.ts` | `/coding` and `/coding/<uuid>` match; `/coding/<project-uuid>/<session-uuid>` and `/coding/not-a-uuid` do not resolve to a session route; `loadModeRoute('coding')` drops a saved legacy route |
| Workspace-only session creation | `tests/api/routes/test_team_db.py` | creating a Coding session with `workspace` succeeds and registers the folder; a Coding session without `workspace` returns 422; `/team/workspace/tree` lists an unowned workspace and a `worktree` row nests under its `source_path` repository |
| Scheduler without a project target | `tests/api/routes/test_scheduler.py`, `tests/scheduler/test_schemas.py`, `tests/agent/tools/test_schedule_tool.py` | a Coding task is created and routed on `mode` + `workspace`; `project_id` is rejected as an unknown field; an unroutable coding task is not created |
| Memory scope | `tests/services/test_scoped_memory.py` | a Coding session's scopes are user/session/workspace/folder; no `project` scope is produced or coerced |
| Search kind | `tests/services/test_app_search_service.py` | `project` is not a returned kind; workspace hits carry no project metadata |
| Review/git scopes | `tests/api/routes/test_reviews.py`, `tests/api/routes/test_team_worktrees.py` | single-workspace request shapes; no project id accepted |
| Notification contract | `web/src/__tests__/lib/notification-activation.test.ts` | a coding activation without `focus_id` parses; one carrying `focus_id` is rejected |

### 6.2 Commands (repository's own)

```bash
# backend
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run ty check app/
uv run pytest --no-cov -q
# frontend
cd web && bun run lint && bun run typecheck && bun run build
# desktop
cd desktop/src-tauri && cargo check
# hygiene
git diff --check
```

## 7. Risks, rollback, exclusions

### 7.1 Top risks

1. **`app/api/routes/team/chat.py` is 2014 lines and holds the create-session
   rule, the tree endpoint and the project import at once** (`:73-74`,
   `:1397-1400`, `:1465-1530`). Mitigation: land P1 as one reviewed commit with
   the tree-payload rewrite and its route tests in the same diff; do not split
   `chat.py` edits across phases.
2. **`CodingSidebar.tsx` (2340 lines, 311 references) is a rewrite, not an
   edit.** Mitigation: P4a replaces it with a workspace list built from the
   existing shell primitives, and P2/P3 must land first so the rewrite has
   workspace data and the new URL to link to.
3. **Silent URL breakage for saved routes and notifications.** A project-shaped
   URL or a persisted mode route resolves to nothing. Mitigation: the P3 route
   test plus the `loadModeRoute` sanitizer; the generic not-found toast already
   covers the session case.
4. **Data loss beyond what was agreed.** Two destructive actions are easy to get
   wrong: deleting `kind = "repo"` workspace rows (must never happen) and
   deleting memory facts. Mitigation: the migration only removes `kind =
   "worktree"` orphans and `scope_type = 'project'` facts; both need the user's
   answer in §8 before the coder starts.
5. **Test-suite blast radius**: 22 backend test files and roughly 806 project
   references in `tests/`, plus frontend suites. Mitigation: update tests inside
   the phase that changes the behaviour (P1 backend, P2–P5 frontend), never in a
   later cleanup phase.
6. **i18n parity**: three locales plus a key-count floor in
   `web/src/__tests__/i18n/i18n.test.tsx`. Mitigation: single commit per key
   removal across all three files (P6).

### 7.2 Rollback

- Before P1 lands: nothing to roll back.
- P1: `alembic downgrade` restores schema only; purged lessons are gone, so the
  real rollback for a bad P1 is restoring a database backup. Call this out in the
  release notes (`Upgrade notes` in `CHANGELOG.md`).
- P2–P6: pure source changes, reverted by reverting the commit range.
- `CodingWorkspace` rows and on-disk folders are never deleted, so no rollback
  step depends on them.

### 7.3 Out of scope and pre-existing

- Conductor managed projects, plugin-platform `managed_project_id`, skill
  `project` source (§1.4).
- Work mode, session folders, scheduler, worktrees, coding semantic intelligence.
- `documents/releases/**` and existing `documents/plans/**` files: frozen.
- Unknown paths in the router and the pre-existing generic not-found toast.
- Pre-existing uncommitted user work in the shared tree, including edits in
  `web/src/components/CodingSidebar.tsx` and
  `app/agent/mode/team/{team,member}.py`: the coder must rebase the plan's line
  anchors onto the working tree at the moment of the change and must not revert
  that work.

## 8. Open decisions for the user

1. Memory facts scoped to a project: delete them in the migration (recommended,
   they can never be read again) or keep the rows as dead data?
2. Coding scheduled tasks with no routable folder: delete them (recommended) or
   disable them and surface them in the scheduler UI for the user to repoint?
3. Multi-repo scopes: accept that diffs, PR lists and global search now cover one
   folder per session (recommended) — or is a later "open several folders in one
   session" feature expected, which would change the query shapes kept now?
4. Cross-repo wording in prompts and Help: adopt "one workspace = one folder, use
   a session per folder" (recommended), and confirm the loss of "the active
   Coding project" phrasing in agent guidance is acceptable.

## 9. Effort estimate and commit boundaries

| Phase | Size | Effort | Commit boundary |
| --- | --- | --- | --- |
| P1 Backend removal + migration | XL | 12–16 h | 1 commit: schema change, model, services, routes, runtime, backend tests, backend docs, first CHANGELOG entry |
| P2 Frontend data layer | M | 3–5 h | 1 commit: queries, keys, skill scope, tree types |
| P3 URL contract + deep links | M | 4–6 h | 1 commit: router, work route, notification (web + Rust), new route test |
| P4 Coding UI collapse | XL | 12–18 h | 3 commits: P4a sidebar, P4b panels/scopes, P4c dead components + tests |
| P5 Client state + API client | M | 4–6 h | 1 commit: stores, storage keys, api client, types |
| P6 Copy, Help, i18n, docs | L | 6–9 h | 1–2 commits: locales + Help in one (parity), docs + CHANGELOG in the next |
| P7 Verification sweep | S | 2–3 h | no commit (evidence attached to the change) |
| **Total** | | **43–63 h** | 8–10 commits, one landing |

Recommended order of commits mirrors P1 → P7. P1 is the only commit that cannot
be reviewed in isolation from deployment intent: mark it "do not release alone"
in its message.
