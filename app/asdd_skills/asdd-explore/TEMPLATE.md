# Output templates — asdd-explore

Three kinds of page, and a report. Every line in all of them states something
already true of this repository, with the evidence beside it.

## `project.md`

Keep the headings the skeleton shipped; replace the italic placeholders. The
parenthetical is not decoration — it is what lets the next reader check a claim
instead of inheriting it.

```markdown
# Project context for ASDD

## Context

EvoFlux is a local-first desktop workspace for Work and Coding agent teams: a
Tauri shell embedding a React UI over a local FastAPI sidecar (`README.md`,
`desktop/src-tauri/tauri.conf.json`). It runs on a user's own machine against
their own repositories, so a change must never widen what an agent may reach
(user, Step 2).

## Conventions

- Python 3.12 and FastAPI for the sidecar; React 19 + TypeScript for the UI
  (`pyproject.toml`, `web/package.json`).
- Durable behavior belongs in `app/services/`; routes stay thin (`AGENTS.md:31`).
- `uv run pytest -q` and `bun run test:unit` prove a change; `ruff check app`
  gates style (`Makefile:44`, `.github/workflows/ci.yml:60`).

## Rules

### Proposal

- Name the affected surface, the user-visible impact, and whether it breaks an
  existing contract (user, Step 2).

### Design

- Required beyond the tier default whenever a change crosses the sidecar /
  desktop boundary (user, Step 2).

### Specs

- Every operational capability covers migration, rollback and failure (user,
  Step 2).

### Tasks

- Every change updates `CHANGELOG.md` (`AGENTS.md:120`).
```

## `architecture/<boundary>.md`

One page per boundary, named for the boundary. Not one per package.

```markdown
# Process boundaries

Three processes, one machine.

- **Tauri shell** owns the window, the native lifecycle and packaging. It never
  touches the database (`desktop/src-tauri/src/lib.rs`).
- **Python sidecar** owns agent policy, persistence and workspace
  authorization; it is the only writer of `evoflux.db`
  (`app/core/db.py`, `app/services/`).
- **Web UI** talks to the sidecar over HTTP and SSE, and holds no durable state
  of its own (`web/src/api/client/`).

The shell starts the sidecar with a generated token and a parent-pid watchdog,
so a killed window cannot leave an orphan serving the database
(`app/cli/commands/serve.py:215`).
```

## `reference/<surface>.md`

Exact names, read out of the code. Nothing remembered.

```markdown
# Configuration

Every setting is an environment variable or a `.env` key, read once at startup
(`app/core/config.py`).

| Key | Default | Effect |
|---|---|---|
| `EVOFLUX_DATA_DIR` | XDG data dir | Where the database and caches live |
| `ANTHROPIC_API_KEY` | unset | Credential for the `anthropic` provider |
| `EVOFLUX_MODEL_REGISTRY_REFRESH` | `true` | Background models.dev refresh |
```

## The report

```text
documents/asdd — explored.

project.md: written. Context and conventions from AGENTS.md + Makefile;
"must not break" and the design rule are yours, from Step 2.

architecture/: 3 pages — process-boundaries, storage, trust-and-permissions.
reference/: 2 pages — configuration (41 settings), cli (9 commands).
specs/, analysis/, decisions/: left empty, deliberately.

Decisions I can see were made but did not write up: SQLite as the single local
store; the sidecar handshake protocol. Each needs its rejected alternative,
which the code does not carry.

Next: one small real change.
```

## Rejected if

- A line in `project.md` carries no source and the user never said it.
- `specs/` gained a file, or `architecture/decisions/` gained an ADR.
- An `architecture/` page restates a package listing instead of a boundary.
- A `reference/` page documents a name that does not appear in the code.
- AGENTS.md was paraphrased into `project.md` rather than cited.
- More than five `architecture/` pages, or a page per top-level folder.
