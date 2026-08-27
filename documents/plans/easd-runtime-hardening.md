# EASD runtime hardening

Status: implemented

## Problem and outcome

Ignored EASD runtime data no longer creates Git churn, but the first local
layout is checkout-relative. A clean Git worktree therefore has no runtime or
templates and reports invalid setup, while phase Skills still tell agents to
look for Runs below the tracked knowledge directory. The explicit legacy
migration can also leave partial moves or remove a generated file that changed
after preview. Finally, the manifest declares manual converged-Run publication
without providing a product action.

The outcome is a worktree-safe local runtime owned by the canonical source
repository, consistent phase instructions, recoverable migration execution, an
exact destructive-action preview, and an explicit compact convergence record
that users may choose to publish to the repository.

## Goals

- Share one ignored runtime across linked worktrees of the same repository.
- Treat absent ignored runtime/templates as initializable local state, not
  corrupt tracked setup.
- Keep accepted Specs and living knowledge branch/repository-owned.
- Make every bundled EASD phase Skill use `runtime_directory` and injected
  runtime context correctly.
- Prevent partial legacy migrations and revalidate generated content before
  deletion.
- Show every Run source/target and generated file in migration confirmation.
- Make `publish_converged_runs=manual` executable through API and UI.

## Non-goals

- Cross-host active-Run synchronization.
- Automatic commits or automatic publication.
- Publishing raw prompts, provider payloads, chat transcripts, absolute
  workspaces, or complete local evidence bodies.
- Automatic deletion of local Runs. Retention remains explicit because the
  local ledger is the Recovery source of truth.
- Sharing runtime between unrelated clones that do not share a Git common dir.

## User flows and states

- Opening EASD in a linked worktree resolves runtime/templates through the
  source repository and remains ready when the source runtime is initialized.
- A fresh clone containing tracked EASD setup but no ignored local directories
  reports `upgrade_required`; **Upgrade** recreates only local state.
- Legacy cleanup displays every Run ID and exact source/target plus every
  generated file before confirmation.
- Migration either completes for the selected repositories or restores moved
  Runs and removed defaults before returning an error.
- A converged Run offers **Publish audit record**. The confirmation previews the
  compact fields; publishing creates or reuses one deterministic tracked YAML
  record under `<data_directory>/records/runs/`.

## Requirements and acceptance criteria

- **AC-13:** Linked worktrees resolve the same canonical runtime owner without
  executing Git or filesystem discovery inside a database transaction.
- **AC-14:** Missing ignored runtime/templates produce `upgrade_required`, and
  initialization hydrates them without requiring destructive repair.
- **AC-15:** Project-scoped EASD accepts a workspace whose canonical source is a
  project member while retaining the project repository scope.
- **AC-16:** All five bundled phase Skills read `runtime_directory` or injected
  EASD context; exact prior bundled copies upgrade while edited Skills remain
  untouched.
- **AC-17:** Migration serializes repository runtime writes, revalidates every
  generated default immediately before deletion, and rolls back completed moves
  and removals when execution fails.
- **AC-18:** Migration confirmation renders exact Run IDs, source/target paths,
  file counts/bytes, and generated paths.
- **AC-19:** Only a converged Run can publish a compact record; the record omits
  absolute workspace paths and raw evidence content, is deterministic and
  idempotent, and never commits automatically.
- **AC-20:** Run detail exposes publication eligibility/state and a manual
  confirmation action with clear Git-visible wording.
- **AC-21:** Tests cover fresh clone/worktree hydration, project worktree scope,
  Skill upgrade preservation, migration rollback/revalidation, publication
  validation/idempotency, API shape, and UI preview/action states.
- **AC-22:** Documentation and Help distinguish canonical machine-local runtime,
  tracked knowledge, manual compact publication, and explicit retention.

## API, event, tool, and UI contracts

Setup repository responses add:

```text
runtime_owner_path
runtime_shared_across_worktrees
```

Publication endpoints:

```text
GET  /api/easd/runs/{run_id}/publication
POST /api/easd/runs/{run_id}/publication { confirm: true }
```

The response reports eligibility, already-published state, repository-relative
path, and the compact preview/record. No lifecycle state changes and no new SSE
event are required.

## Data model, migration, and retention

No database or Alembic migration. Linked worktrees use the source repository's
ignored `.evoflux/easd/.local/` directory. Existing checkout-local runtime is
still read from its originating worktree for compatibility; new Runs use the
canonical source runtime and no implicit cross-path move occurs.

Manual publication writes:

```text
<data_directory>/records/runs/<slug>--<run-id>.yaml
```

The record contains IDs/hashes, timestamps, Git revision, aggregate mission
counts, and evidence/deviation identifiers already present in convergence. It
does not contain local paths or raw evidence. Local Runs are retained until the
user explicitly manages them outside this change; publication is not deletion.

## Permissions, security, privacy, and trust

Runtime-owner resolution accepts only a regular Git worktree marker and
`commondir` whose resolved common directory is a `.git` directory with a valid
source parent. All local paths remain bounded under that owner. Published data
uses an allowlist and is previewed before the Git-visible write.

## Concurrency, failure, recovery, and idempotency

A repository runtime lock serializes local Run mutations and migration. The
migration preflights every target, snapshots removable generated defaults,
revalidates content, and maintains a rollback journal. A repeated successful
migration has no legacy inputs. Publication compares deterministic content and
returns the existing record when identical; conflicting existing content fails
closed.

## Observability and diagnostics

Setup exposes the runtime owner and whether it is shared across worktrees.
Migration errors distinguish execution from rollback failure. Publication
returns its exact path and whether it created a new record.

## Compatibility, rollout, and rollback

Ordinary repositories keep `.evoflux/easd/.local/` at the same path. Linked
worktrees change only their runtime resolution. Legacy tracked Runs remain
readable. Rolling back code leaves source-local runtime and published YAML
readable as normal files; no database downgrade is required.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-13–16 | setup/store/route/Skill service tests and temporary Git worktree probe |
| AC-17 | injected move/delete failure tests plus content-change regression |
| AC-18, AC-20 | focused component tests and sampleproject browser inspection |
| AC-19 | store/API publication tests including conflict and redaction assertions |
| AC-21–22 | focused suites, frontend gates, docs/Help review and Git dry-run audit |

## Ownership and source map

- Runtime identity/locking: `app/services/easd_runtime.py`
- Setup/migration: `app/services/easd_setup_service.py`
- Store/publication: `app/services/easd_repository_store.py`
- Project scope/API: `app/api/routes/easd.py`, `app/api/schemas/easd.py`
- Skills: `app/easd_skills/`, repository-installed `.evoflux/skills/`
- UI/client/query: `web/src/components/EvoAgentSpecsPanel.tsx`, `web/src/api/`,
  `web/src/queries/`
- Tests/docs/Help: `tests/`, `web/src/__tests__/`, `documents/`,
  `web/src/help/locales/`
