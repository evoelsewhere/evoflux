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
uv run pytest --no-cov -q tests/scheduler
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

## End-to-end smoke suite

`make e2e` (or `bash scripts/migration/e2e.sh`) builds `evoflux-server` and the web UI, then runs the Playwright journeys in `web/e2e/smoke/` against a Vite preview of the production build and `evoflux-server serve` with Python behind it. Each stack uses temporary `EVOFLUX_*_DIR`s and the contract-tests mock model provider, so no real keys or user data are touched. The journeys are the app load, the first-run import dialog, the slash menu, a streamed chat, session persistence, `/api/health/live` and `/api/quote` through the gateway, the rollback drill (`edge-stateless=rust` then `=python`) and the crash drill (kill the Python child, see the 502 window, then recovery).

- `make e2e ROUTE_OVERRIDE=<unit>=<owner>` runs the main journeys with that unit owned by `python` or `rust`.
- `bash scripts/migration/e2e.sh -- <playwright args>` forwards arguments such as `-g "slash menu"`.
- The tests clear `oa-last-route*` from localStorage once per tab and avoid sending right after a slash then Backspace; that input path is a known frontend quirk tracked by a `test.fixme`.
- The nightly `e2e-smoke` job in `.github/workflows/migration-gates.yml` runs it on Linux, macOS and Windows.

### Rust-forward checkpoints

- `bash scripts/migration/e2e.sh --rust-forward` routes every unit in `server/rust-ready.toml` to Rust (an explicit `--route-override` is appended last and wins). With an empty list it prints `no Rust-ready units yet` and runs the default routing.
- `bash scripts/migration/checkpoint.sh <phase> [--real-model]` builds `evoflux-server`, runs the e2e suite with default routing and with `--rust-forward`, runs the `TARGET=gateway` contract suite with the same override, and writes `documents/analysis/checkpoint-<phase>-<date>.md` (labelled "automated: not owner use"). It exits non-zero on any failure. The whole contract suite takes over 15 minutes on a slow machine; `CHECKPOINT_CONTRACT_PATHS` narrows it, and the report names the subset.
- `--real-model` re-runs only the chat journey against your own provider config: `~/.config/evoflux` is copied to a temporary directory that is deleted on exit, and nothing from it is printed or written to the report.

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
