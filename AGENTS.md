# EvoFlux — Agent Instructions

EvoFlux is a local-first desktop workspace for Work and Coding agent teams. The
production application is a Tauri shell embedding a React UI and supervising a
local FastAPI sidecar.

## Instruction precedence

This file applies to the whole repository. Before changing a file, also read the
nearest nested `AGENTS.md`; nested instructions add to or override this root
contract for their directory.

Scoped instruction files currently live under:

- `app/`, including `app/agent/`, `app/api/`, and `app/services/`;
- `web/` and `web/src/`;
- `desktop/` and `desktop/src-tauri/`;
- `seed/`;
- `scripts/`.

## Repository map

```text
app/          Python sidecar: API, agents, services, persistence, automation
web/          React/TypeScript interface embedded by Tauri
desktop/      Rust/Tauri shell and native packaging
seed/         First-install agent and configuration templates
scripts/      Development, build, validation, and release utilities
tests/        Python backend, integration, CLI, and packaging tests
documents/    Single documentation root and EASD repository data
```

Start with:

- `documents/README.md` for documentation navigation;
- `documents/features/README.md` for implemented features and code ownership;
- `documents/architecture/system-overview.md` for process and trust boundaries;
- `documents/reference/repository-map.md` for the detailed source map.

## Architecture boundaries

- Keep FastAPI routes thin. Durable behavior belongs in `app/services/`,
  `app/agent/`, `app/workflow/`, `app/scheduler/`, or `app/core/`.
- Keep provider-specific payloads behind `app/agent/providers/`; generic API and
  team schemas must remain provider-neutral.
- Use TanStack Query for frontend server state, Zustand for live/client state,
  and shared shell/workbench primitives for application chrome.
- Tauri owns native lifecycle, capabilities, browser integration, and packaging;
  the Python sidecar owns agent policy, persistence, and workspace authorization.
- The application database stores product state. Repository code indexes remain
  cache-local per-repository databases and must not move into application tables.
- Work mode uses session workspaces. Coding mode may access only repositories
  authorized by the active workspace or Coding project.
- Tools, MCP, plugins, browser content, imported documents, and remembered text
  remain subject to explicit trust, permission, sandbox, and untrusted-data
  boundaries.

## Development operating model

EvoFlux follows **Specification-Driven Development (SDD)** and
**Agent-Driven Development (ADD)**. The specification defines the intended
contract; agents implement and verify that contract with traceable evidence.
The named product-executable method is **EASD — Evo Agent Specification-Driven
Development**; its product/UI name is **Evo Agent Specs**. Its normative
lifecycle, roles, trust levels, and convergence rules live in
`documents/reference/easd-methodology.md`.

The workflow is:

```text
discover → specify → [plan when required] → implement → review → verify → reconcile docs → hand off
```

Do not start a non-trivial implementation from a vague request. First resolve
the intended behavior, affected boundaries, and acceptance criteria. Do not
silently change an accepted specification to fit an implementation.

### Change classification

Apply process in proportion to risk:

| Change | Required specification work |
|---|---|
| New feature, user-visible behavior, public API/event, persistence, security, or compatibility change | Full specification and acceptance matrix before implementation |
| Bug that violates an existing documented contract | Cite the existing contract and add a failing regression test; update the spec only if it is ambiguous or changes |
| Internal refactor or performance work with unchanged behavior | Record invariants, measurable outcome, and verification plan; do not invent a new product spec |
| Trivial typo, comment, mechanical rename, or docs-only correction | The task request is sufficient when scope and expected result are unambiguous |

When uncertain, use the stronger specification path. “Small diff” does not mean
“low risk” when the change touches auth, permissions, migrations, concurrency,
provider protocol, filesystem scope, or release/update behavior.

## Specification-Driven Development (SDD)

### Sources of truth

- `documents/features/` describes implemented product behavior.
- `documents/architecture/` defines process, storage, concurrency, trust, and system
  boundaries.
- `documents/reference/` defines public API, configuration, CLI, and repository
  contracts.
- `documents/plans/` holds proposed or historical design work and is not proof that a
  feature is implemented.
- Tests are executable evidence for a contract, not a substitute for an absent
  product specification.
- Existing code is evidence when reverse-engineering current behavior. If code,
  tests, and current-state documentation disagree, investigate and reconcile the
  discrepancy explicitly; do not choose the convenient source silently.

For a planned change, the accepted specification is normative. During
reverse-engineering, code and tests remain the evidence used to correct the
specification.

### Specification lifecycle

1. **Discover**
   - Read applicable `AGENTS.md`, current feature/architecture/reference pages,
     owning code, migrations, APIs/events, frontend consumers, and focused tests.
   - Record current behavior, constraints, known edge cases, and affected owners.
   - Distinguish implemented behavior from proposals and stale historical docs.
2. **Specify**
   - Write a proposed design under `documents/plans/` for an unimplemented feature.
   - Update the current feature contract in `documents/features/` when behavior ships.
   - Update architecture/reference documents before or with any boundary change.
   - Resolve material ambiguity with the user instead of encoding an assumption
     that changes product behavior.
3. **Plan**
   - Map every requirement to owning files/layers and verification evidence.
   - Identify migration, compatibility, security, observability, Help, and
     rollout implications.
   - Order work into independently verifiable vertical slices.
4. **Implement**
   - Implement only accepted scope. Keep each slice reviewable and keep the
     application usable between slices where practical.
   - If implementation discovery invalidates the spec, stop that slice, update
     the spec/plan, and make the deviation visible before continuing.
5. **Verify**
   - Demonstrate every acceptance criterion with an automated test, focused
     command, or explicit inspection evidence.
   - Run boundary-specific regression checks from the nearest `AGENTS.md`.
6. **Reconcile**
   - Update feature status, architecture/reference pages, in-app Help, examples,
     and migration/release notes so documentation matches the shipped result.
   - Preserve design rationale in `documents/plans/` or `documents/analysis/`, clearly
     labelled as historical when it no longer defines current behavior.

### Minimum full specification

A full specification must make these sections discoverable, even if a section
states that it is not applicable:

```markdown
# <Feature or change>

Status: proposed | accepted | implemented | deprecated

## Problem and outcome
## Goals
## Non-goals
## User flows and states
## Requirements and acceptance criteria
## API, event, tool, and UI contracts
## Data model, migration, and retention
## Permissions, security, privacy, and trust
## Concurrency, failure, recovery, and idempotency
## Observability and diagnostics
## Compatibility, rollout, and rollback
## Verification matrix
## Ownership and source map
```

Acceptance criteria use stable IDs such as `AC-1`, `AC-2`, and must be
observable and testable. Prefer concrete Given/When/Then behavior over phrases
such as “works correctly,” “handles errors,” or “is production-ready.”

### Traceability contract

For non-trivial work, maintain this chain:

```text
requirement/AC → implementation owner → automated test or evidence → current docs
```

- Plans and delegated tasks cite the relevant AC IDs.
- Tests should name the behavior clearly; add AC references where the mapping is
  otherwise difficult to discover.
- The final handoff reports evidence per AC and calls out any deviation,
  unverified claim, or deferred requirement.
- A code change without an acceptance criterion is scope drift; an acceptance
  criterion without evidence is incomplete.

### Definition of Ready

Implementation may begin when:

- the outcome, scope, non-goals, and acceptance criteria are unambiguous;
- current behavior and affected ownership are mapped;
- public interfaces and data/security/concurrency implications are identified;
- compatibility, migration, and rollback needs are decided where applicable;
- the verification plan names focused tests or other concrete evidence;
- unresolved product choices that materially alter the result have user input.

### Definition of Done

Work is done only when:

- every accepted AC has evidence;
- required tests and quality gates pass, or failures are explicitly identified
  as pre-existing with evidence;
- negative paths, recovery, authorization, and boundary cases are covered in
  proportion to risk;
- migrations and compatibility behavior are verified when applicable;
- telemetry/diagnostics make important runtime failure modes inspectable;
- current docs, feature catalogue, API/config references, and in-app Help match
  implementation;
- the diff contains no accidental unrelated changes and `git diff --check`
  passes;
- the handoff lists what changed, evidence, remaining risks, and checks not run.

## Agent-Driven Development (ADD)

ADD means agents own bounded engineering work under an explicit specification;
it does not mean maximizing delegation. A simple task should stay with one
agent. Delegate only when subtasks are concrete, independent, and useful in
parallel.

### Lead agent responsibilities

The lead owns the end-to-end outcome:

- establish or confirm the specification and acceptance criteria;
- build the impact/source map and read all applicable instructions;
- choose whether delegation improves correctness or latency;
- assign disjoint ownership and prevent overlapping edits;
- integrate cross-layer contracts and resolve conflicting handoffs;
- independently inspect diffs and verify specialist evidence;
- run final acceptance and regression checks;
- reconcile documentation and deliver the final evidence-backed handoff.

The lead must not treat a specialist’s “done” message as verification.

### Delegation packet

Every delegated task must include:

- objective and relevant AC IDs;
- exact scope and owned files/layer;
- constraints, non-goals, and interfaces that must not change;
- expected output or artifact;
- required verification command/evidence;
- known dependencies and whether the task may edit shared files.

Bad delegation: “implement the backend.”

Good delegation: “Implement `AC-3` in the scheduler service and focused service
tests; own `app/scheduler/` and `tests/scheduler/`; do not change API schemas;
return changed files, test command/output, assumptions, and remaining risks.”

### Shared-worktree coordination

- All agents share the same worktree. Inspect status before editing and preserve
  user-owned or other-agent changes.
- Prefer disjoint file ownership. If two tasks require the same file or contract,
  serialize them or assign one integration owner.
- Specialists must not reset, revert, stage, commit, or rewrite another agent’s
  work unless the lead explicitly assigns that operation.
- Do not create duplicate infrastructure because another agent is working in the
  owning module. Coordinate through the lead and existing abstractions.
- Communicate newly discovered blockers, contract gaps, and cross-task
  dependencies immediately; do not hide them in the final message.
- Only the lead integrates and commits by default. A specialist commits only
  when explicitly assigned a separate commit boundary.

### Specialist handoff contract

A specialist handoff must contain:

1. outcome and ACs addressed;
2. files changed and contracts affected;
3. commands/tests run with results;
4. assumptions and decisions made;
5. unresolved risks, blockers, or follow-up work;
6. confirmation that unrelated work was preserved.

Review-only agents report findings by severity with file/line evidence and do
not mutate code unless explicitly asked. Investigation agents distinguish facts
observed in code/tests from recommendations.

### ADD quality gates

- Parallel work is complete only after integration tests cover the seams between
  agent-owned slices.
- Cross-layer changes require one owner to validate the complete flow, not only
  isolated backend/frontend success.
- If specialist outputs conflict with the specification, the specification wins
  until it is explicitly revised.
- If the same blocker repeats and safe in-scope alternatives are exhausted,
  surface it with evidence rather than fabricating completion.

## Development commands

Install dependencies:

```bash
uv sync
cd web && bun install --frozen-lockfile
```

Run locally:

```bash
make run          # FastAPI only
make dev-web      # FastAPI + Vite
make dev-desktop  # FastAPI + Vite + Tauri
```

Backend quality gate:

```bash
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run ty check app/
uv run pytest --no-cov -q
```

Frontend quality gate:

```bash
cd web
bun run lint
bun run typecheck
bun run build
```

Desktop baseline:

```bash
cd desktop/src-tauri
cargo check
```

During iteration, run the smallest focused tests named by the nearest nested
`AGENTS.md`. Expand verification in proportion to the risk and affected layers.

## Change rules

- Preserve unrelated changes in a dirty worktree. Never discard or rewrite
  user work to simplify the current task.
- Prefer small, reviewable changes that follow existing module boundaries.
- Do not perform filesystem scans, Git operations, model calls, process startup,
  or network I/O inside a database transaction.
- A schema change must update SQLModel metadata/imports, add an Alembic revision,
  and pass migration-head plus upgrade-path tests.
- An API or SSE shape change must update backend schemas, frontend API parsing,
  stores/queries, rendering, and focused tests together.
- A tool change must check registry metadata, permissions, sandbox behavior,
  observation/result rendering, and tests.
- A user-visible feature change must update in-app Help under
  `web/src/help/locales/` when applicable.
- Never commit generated sidecars, `target/`, `web/dist`, credentials, signing
  keys, machine-specific paths, or local `.evoflux/` runtime state such as
  `team_state.json`, sessions, caches, and worktrees. Repository-owned
  `.evoflux/easd/config.json`, `.evoflux/easd/RULES.md`, the manifest-selected
  EASD `data_directory`, repository-scoped `.evoflux/skills/easd-*/**`, and
  normative `.evoflux/trace/**` contracts are the explicit version-controlled
  exception. `.evoflux/easd/.local/**` remains machine-local and ignored.

## Documentation contract

`documents/` is the only product/contributor documentation root. The
manifest-owned `documents/easd/` subtree is EASD run data, not product or
contributor documentation.

- Current behavior belongs in `documents/features/`, `documents/architecture/`, and
  `documents/reference/`.
- Contributor and release procedures belong in `documents/development/`.
- Historical audits, research, plans, and release evidence belong in their
  existing `documents/analysis/`, `documents/research/`, `documents/plans/`, and
  `documents/releases/` directories and must not override current contracts.
- Use repository-relative Markdown links and keep README media under
  `documents/images/`.
- When a feature changes, update its feature page, catalogue entry, affected
  architecture/API/config reference, and in-app Help in the same change.

## Verification and handoff

- Run `git diff --check` before handoff.
- Report the exact focused checks run and any checks not run.
- Distinguish pre-existing failures or user-owned changes from failures caused
  by the current work.
- Do not claim completion while required migrations, generated contracts,
  documentation links, or affected-layer tests remain unresolved.
