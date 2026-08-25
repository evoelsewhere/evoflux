# Development and testing

## Toolchain

- Python 3.12+ and `uv`
- Bun for the React/Vite application
- Rust stable (minimum declared by the Tauri crate) and Tauri CLI v2
- platform desktop build dependencies when running native packages

Install backend and frontend dependencies:

```bash
uv sync
cd web
bun install --frozen-lockfile
```

For desktop development, install Rust and Tauri:

```bash
rustup default stable
cargo install tauri-cli --version '^2' --locked
```

## Run modes

```bash
make run          # FastAPI only, no reload
make dev-web      # FastAPI :8000 + Vite :5173
make dev-desktop  # FastAPI + Vite + Tauri source shell
```

`make dev` is an alias for `make dev-web`. To exercise the packaged sidecar
handshake and isolated development state:

```bash
cd web && bun dev
# another terminal
make -C desktop dev-bundled
```

Do not use `dev-bundled` as the normal edit loop; rebuild it when testing
sidecar imports, migrations, auth, resources or process cleanup.

## Backend checks

Full backend quality gate:

```bash
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run ty check app/
uv run pytest --no-cov -q
```

Use focused suites during iteration:

```bash
uv run pytest --no-cov -q tests/agent
uv run pytest --no-cov -q tests/api
uv run pytest --no-cov -q tests/services
uv run pytest --no-cov -q tests/workflow tests/scheduler
```

The nearest `AGENTS.md` contains component-specific commands and invariants.
Tests mirror code ownership; add route, service and frontend coverage when a
feature crosses those boundaries.

## Frontend checks

```bash
cd web
bun run lint
bun run typecheck
bun run build
```

Run the focused Vitest file or package script defined in `web/package.json`
during development. Build is required for changes to routes, lazy imports,
assets, Vite config or Tauri packaging.

## Desktop checks

```bash
cd desktop/src-tauri
cargo check
```

Also run relevant tests under `tests/desktop` and `tests/scripts`. Use
`make -C desktop dev-bundled` for sidecar lifecycle/auth changes and a real
platform package for installer/updater changes.

## Database migrations

Development applies migrations explicitly:

```bash
make migrate
make revision MSG='describe change'
```

Production auto-migrates after checking that the existing revision is
supported. A schema change must update SQLModel imports/metadata, add an
Alembic revision and pass migration-head plus upgrade-path tests. Do not perform
filesystem/network/model work inside a database transaction.

## Documentation workflow

Current behavior belongs in `documents/features`, `documents/architecture` and
`documents/reference`. Design exploration belongs in `documents/plans`, `analysis` or
`research` and must not be presented as implemented behavior.

When a feature changes:

1. update code and focused tests;
2. update its feature contract and catalogue row;
3. update API/config/architecture references if the public boundary changes;
4. update localized in-app Help for user-visible UI behavior;
5. run the documentation link audit described in `documents/README.md`.

## Change discipline

- Preserve unrelated user changes in a dirty worktree.
- Keep routes thin and provider-specific shapes behind adapters.
- Keep repository mutations reviewable and workspace-scoped.
- Use existing shell/UI/state primitives instead of parallel infrastructure.
- Verify behavior in proportion to risk and report the exact commands run.
