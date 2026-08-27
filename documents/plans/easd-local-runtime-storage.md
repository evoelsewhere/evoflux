# EASD local runtime storage

Status: implemented

## Problem and outcome

EASD currently stores every active Run, event, mission snapshot, evidence row,
deviation, recovery attempt, and convergence report under the repository data
directory. This makes Git a collaboration transport but creates high file churn,
merge conflicts, and accidental retention of operational or sensitive context in
large-member projects.

The outcome is a hybrid storage policy: project contracts and accepted knowledge
remain trackable, while operational Run ledgers are local and ignored by default.
Legacy repository Runs remain readable and can be explicitly moved to local
storage after a preview/confirmation.

## Goals

- Store new Runs under `.evoflux/easd/.local/runs` by default.
- Keep accepted Specs and adopted current-state knowledge in the configured
  repository data directory.
- Preserve read compatibility for legacy `<data_directory>/runs` ledgers.
- Expose legacy Run count and an explicit localization action in Setup.
- Never silently delete or move a Git-visible Run.
- Make local runtime, publish policy, and compatibility visible in the manifest,
  API, UI, docs, and Help.
- Reduce generated tracked skeleton/template noise for new installations where
  it is safe to do so.

## Non-goals

- Cross-host active-Run collaboration without a shared service.
- Automatically committing accepted Specs or published records.
- Deleting legacy Git history or rewriting existing commits.
- Moving credentials, raw provider payloads, or arbitrary project files.
- Publishing a complete converged audit package in this slice.

## User flows and states

- New setup creates an ignored local runtime directory and no tracked Run ledger.
- Existing current-layout setup reports `upgrade_required` until its manifest is
  updated with the local-runtime policy.
- Existing Runs stay visible through compatibility reads.
- Repository Setup shows `N legacy Runs are Git-visible` and a **Move to local**
  action.
- Confirmation lists source/target, file count, byte count, and warns that
  previously tracked files will appear deleted in Git.
- After localization, Runs remain visible in EvoFlux and disappear from the
  Git-visible data directory.
- A target collision or changed source fails closed without partial overwrite.

## Requirements and acceptance criteria

- **AC-1:** The manifest declares `runtime_storage=local`, a fixed ignored
  `runtime_directory`, and `publish_converged_runs=manual`.
- **AC-2:** New Run directories are created only under the local runtime path;
  accepted Spec publication remains under `<data_directory>/specs`.
- **AC-3:** Store lookup/list reads local and legacy Run roots, rejects duplicate
  identities, and prefers neither silently.
- **AC-4:** Setup inspection returns local runtime path and legacy Run count.
- **AC-5:** Existing manifests missing the policy report `upgrade_required`, not
  invalid, and upgrade does not move legacy Runs.
- **AC-6:** Localization preview is bounded and reports exact Run IDs, paths,
  file counts, and bytes without mutation.
- **AC-7:** Localization execution requires explicit confirmation, moves only
  previewed regular Run directories, rejects collisions/symlinks, and preserves
  Run readability.
- **AC-8:** `.evoflux/easd/.local/**` remains ignored and setup verifies the
  local runtime path cannot escape the repository.
- **AC-9:** Trace, Recovery, Realtime replay, evidence, and convergence work
  unchanged for local Runs and compatible legacy Runs.
- **AC-10:** Setup UI explains local vs Git-visible data and warns about Git
  deletions before legacy localization.
- **AC-11:** Tests cover new setup, upgrade, compatibility list/read, duplicate
  identity, preview, successful move, collision, and Git-ignore behavior.
- **AC-12:** Docs/Help and a sampleproject audit show that `git add -n .` excludes
  operational Run data while accepted Specs remain visible.

## API, event, tool, and UI contracts

Manifest additions:

```json
{
  "runtime_storage": "local",
  "runtime_directory": ".evoflux/easd/.local/runs",
  "publish_converged_runs": "manual"
}
```

Setup repository response additions:

```text
runtime_directory
runtime_path
legacy_run_count
```

Migration endpoints:

```text
GET  /api/easd/setup/runtime-migration?workspace=...&project_id=...
POST /api/easd/setup/runtime-migration
     { workspace, project_id?, repository_paths?, confirm: true }
```

## Data model, migration, and retention

No application-database migration. Filesystem layout changes only. Operational
retention follows local application/project cleanup. Accepted Specs and manually
published records retain normal Git history.

## Permissions, security, privacy, and trust

All paths remain repository-contained and symlink-rejected. Migration is scoped
to authorized initialized repositories. Local storage is not a permission grant;
existing workspace/project/session checks remain authoritative.

## Concurrency, failure, recovery, and idempotency

Preview and execute re-read exact directories. Each move uses same-filesystem
atomic rename. Existing target paths fail before mutation. Repeating a completed
migration is idempotent because no legacy Runs remain. Mixed success across
multiple repositories is reported per repository; individual Run moves never
overwrite.

## Observability and diagnostics

Setup diagnostics report legacy count and collision/path errors. Logs include
bounded repository/run/file counts without raw content. No high-cardinality
metrics are added.

## Compatibility, rollout, and rollback

Legacy Runs remain readable indefinitely. Moving a local Run back into the
legacy directory is a manual filesystem rollback while the app is stopped; the
store detects duplicate IDs rather than choosing silently.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1–5, AC-8 | setup/store service tests |
| AC-6–7 | migration service/API tests |
| AC-9 | Trace/Recovery/Realtime focused regressions |
| AC-10 | Setup component tests |
| AC-11 | backend/frontend quality gates |
| AC-12 | docs/Help and sampleproject Git audit |

## Ownership and source map

- Setup/manifest/migration: `app/services/easd_setup_service.py`
- Store compatibility: `app/services/easd_repository_store.py`
- API schemas/routes: `app/api/schemas/easd.py`, `app/api/routes/easd.py`
- Setup UI/query: `web/src/components/EvoAgentSpecsPanel.tsx`, `web/src/api/`,
  `web/src/queries/`
- Tests/docs: `tests/`, `documents/`, `web/src/help/locales/`
