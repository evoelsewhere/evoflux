# EASD repository knowledge-base layout

Status: accepted

## Problem and outcome

The repository store currently standardizes Run ledgers and YAML templates but
leaves living specifications, implemented feature contracts, architecture,
reference material, guides and historical records outside the configured EASD
data directory. Agents and collaborators therefore cannot discover one stable
repository knowledge root, and an accepted Spec is discoverable only through a
Run-specific path.

The outcome is one initialized, version-controlled EASD knowledge base under
the manifest-selected `data_directory` (default `documents/easd`) with explicit
authority and retention rules for every section.

## Goals

- Establish a minimal but complete folder taxonomy for living contracts, Runs,
  templates and historical records.
- Make initialization and upgrade idempotently create the same portable
  skeleton in every repository without overwriting edited documents silently.
- Publish accepted Specs into a common `specs/` catalogue while retaining the
  hash-identical Run snapshot for audit/rebuild.
- Keep existing repository documentation untouched while making the EASD
  knowledge sections available for explicit adoption and linking.
- Teach phase Skills and core rules where to read and reconcile current docs.

## Non-goals

- No new global database as a documentation source of truth.
- No automatic acceptance, activation, convergence or product-behavior choice.
- No content generation for empty feature/architecture/reference pages during
  setup; setup installs navigation/contracts only.
- No new `changes/`, `tasks/`, top-level `plans/`, or archive lifecycle parallel
  to EASD Runs.
- No migration, copy, rename or rewrite of a repository's existing knowledge
  tree during EASD setup or upgrade.
- No sixth EASD Skill or knowledge lifecycle phase. `RULES.md` and the existing
  Specify/Plan/Implement/Review/Verify Skills enforce the taxonomy.
- No full bugfix/spec-selection UI in this change; common Spec publication is
  the durable prerequisite for that follow-up.

## User flows and states

1. A repository without EASD reports `not_initialized`.
2. Initialization creates the manifest, Rules, Skills, knowledge-base index,
   section READMEs, templates and empty Run/Spec catalogues.
3. A repository with the older Run-only layout reports `upgrade_required`.
4. Upgrade creates only missing skeleton artifacts and preserves existing valid
   Skills, Runs, templates and edited knowledge documents.
5. Draft specification revisions remain under their Run.
6. Explicit user acceptance publishes the revision into `specs/` and advances
   the Run as today.
7. Implement/Review/Verify reconcile adopted EASD knowledge documents and any
   existing project documentation named by repository instructions before
   convergence.

## Requirements and acceptance criteria

- **AC-1:** Fresh setup creates the documented knowledge-base tree, root index,
  section READMEs and expanded artifact templates under custom or default safe
  repository-relative data directories.
- **AC-2:** An older valid Run-only setup reports `upgrade_required`; upgrade is
  idempotent and never replaces edited documents or Skills unless the user
  explicitly requests repair.
- **AC-3:** Unsafe paths, symlink escapes, oversized/malformed skeleton files
  and missing required artifacts fail closed under existing setup trust rules.
- **AC-4:** Accepting a Spec publishes an immutable hash-identical revision under
  `specs/<slug>--<run-id>/revisions/` and updates a CAS-protected `index.yaml`.
- **AC-5:** Run-local drafts/plans/evidence remain Run-bound; publication does
  not create a second mutable Spec contract or weaken accepted revision
  immutability.
- **AC-6:** Setup and upgrade leave existing EvoFlux/project documentation at
  its current paths and create no copied or renamed knowledge content.
- **AC-7:** Core Rules and five phase Skills distinguish normative Specs,
  current behavior/architecture/reference, Run evidence and historical records.
- **AC-8:** EN/VI/JA Help and current feature/architecture/configuration/API
  references describe initialization, taxonomy and source-of-truth boundaries.
- **AC-9:** Focused setup/store/lifecycle/frontend tests, Markdown link audit,
  lint/type checks and `git diff --check` provide handoff evidence.

## API, event, tool, and UI contracts

Setup API shapes remain compatible. `ready` now means the complete current
knowledge skeleton is present; missing current skeleton artifacts return
`upgrade_required`. Run and lifecycle endpoints remain unchanged. Spec
publication is an after-commit repository projection and cannot grant approval.

The setup UI continues to show the configured data directory; Help and README
explain its internal sections. A future spec-selection UI can consume the common
catalogue without changing this layout.

## Data model, migration, and retention

No SQL migration is required. SQLite remains a rebuildable runtime projection.
Repository additions are directories, Markdown/YAML skeleton resources and the
accepted-Spec catalogue. Accepted Spec revisions, Run evidence/events and
convergence remain immutable/append-only according to existing contracts.

## Permissions, security, privacy, and trust

All paths resolve beneath the authorized repository and configured data
directory. Setup does not follow symlinks. Knowledge files remain untrusted
repository input when sent to a model and pass through existing sandbox and
outbound-data policy.

## Concurrency, failure, recovery, and idempotency

Setup publishes the manifest last. Missing skeleton files are recoverable by
retry; valid edited files are preserved. Spec index updates use the repository
store lock and document-hash compare-and-swap. A partial post-commit filesystem
failure is surfaced as repository conflict and can be retried from durable DB
state without inventing acceptance.

## Observability and diagnostics

Existing setup state/issue fields identify missing or invalid skeleton
artifacts. Existing EASD operation metrics cover acceptance; repository errors
remain visible through conflict responses and logs.

## Compatibility, rollout, and rollback

Current initialized repositories upgrade in place. Run directory names and
files do not move. Existing documentation paths and contents do not change.
Rollback can remove new empty skeleton files without a database downgrade.

## Verification matrix

| AC | Evidence |
|---|---|
| AC-1–3 | setup service tests for fresh/custom/legacy/symlink/idempotent paths |
| AC-4–5 | repository store plus accept lifecycle tests and hash comparison |
| AC-6 | before/after path/content assertions for existing documentation |
| AC-7 | bundled/installed Skill equality and content assertions |
| AC-8 | localized Help and current documentation review/build |
| AC-9 | Ruff, ty, pytest, frontend lint/typecheck/tests/build, diff check |

## Ownership and source map

- Setup/resources: `app/easd_skills/`, `app/services/easd_setup_service.py`
- Repository storage: `app/services/easd_repository_store.py`,
  `app/services/easd_repository_sync.py`
- Lifecycle integration: `app/services/trace_service.py`
- Portable contract: `.evoflux/easd/`, `.evoflux/skills/easd-*/`
- Knowledge base: `documents/easd/`
- UI/Help: `web/src/components/EvoAgentSpecsPanel.tsx`,
  `web/src/help/locales/`
- Evidence: focused tests under `tests/services/`, `tests/api/routes/`,
  `tests/agent/`, and `web/src/__tests__/`
