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
docs/         Single documentation root
```

Start with:

- `docs/README.md` for documentation navigation;
- `docs/features/README.md` for implemented features and code ownership;
- `docs/architecture/system-overview.md` for process and trust boundaries;
- `docs/reference/repository-map.md` for the detailed source map.

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
- Never commit generated sidecars, `target/`, `web/dist`, local `.evoflux/`
  state, credentials, signing keys, or machine-specific paths.

## Documentation contract

`docs/` is the only documentation root. Do not recreate `documents/`.

- Current behavior belongs in `docs/features/`, `docs/architecture/`, and
  `docs/reference/`.
- Contributor and release procedures belong in `docs/development/`.
- Historical audits, research, plans, and release evidence belong in their
  existing `docs/analysis/`, `docs/research/`, `docs/plans/`, and
  `docs/releases/` directories and must not override current contracts.
- Use repository-relative Markdown links and keep README media under
  `docs/images/`.
- When a feature changes, update its feature page, catalogue entry, affected
  architecture/API/config reference, and in-app Help in the same change.

## Verification and handoff

- Run `git diff --check` before handoff.
- Report the exact focused checks run and any checks not run.
- Distinguish pre-existing failures or user-owned changes from failures caused
  by the current work.
- Do not claim completion while required migrations, generated contracts,
  documentation links, or affected-layer tests remain unresolved.
