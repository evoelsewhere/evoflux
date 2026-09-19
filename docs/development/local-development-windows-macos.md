# Local development setup for Windows and macOS

Status: current operational plan

Audience: contributors installing EvoFlux from source for the first time and
maintaining a repeatable daily development environment.

This guide covers native Windows and macOS development for the complete EvoFlux
desktop stack:

```text
FastAPI sidecar (:8000) + Vite UI (:5173) + Tauri desktop shell
```

It was derived from the repository's `README.md`, `Makefile`,
`scripts/run_dev.py`, `desktop/Makefile`, package lockfiles, Tauri configuration,
platform tests, and desktop packaging workflow. Use
[Development and testing](setup-and-testing.md) for the concise quality-gate
reference and [Project deep dive](project-deep-dive.md) for architecture and
change ownership.

## Findings from the repository

The project already contains:

- Python `>=3.12` metadata and a committed `uv.lock`;
- a committed Bun lockfile at `web/bun.lock`;
- a committed Rust lockfile at `desktop/src-tauri/Cargo.lock`;
- `make dev-web` for FastAPI plus Vite;
- `make dev-desktop` for FastAPI, Vite, and Tauri;
- a supervisor in `scripts/run_dev.py` that stops sibling processes when one
  fails;
- distinct external-backend and bundled-sidecar Tauri development configs;
- first-start initialization that creates runtime roots and installs local seed
  agents without overwriting existing user files;
- Windows and macOS package jobs in `.github/workflows/desktop-packages.yml`.

There is one important platform gap: `scripts/run_dev.py` currently assumes
Unix process and port tools (`lsof`, `os.killpg`, POSIX signals, and
`start_new_session`). The root Make targets also use Unix shell syntax. This is
appropriate for macOS, but native Windows should use the three-terminal
PowerShell flow in this guide until a Windows supervisor is added.

## Choose the run mode

| Mode | Use it for | Command style |
|---|---|---|
| API only | Backend/API debugging | one terminal |
| Web development | Normal backend/frontend work without native capabilities | API + Vite |
| Desktop development | Default product-development loop | API + Vite + Tauri against source |
| Bundled-sidecar development | Sidecar imports, migrations, token handshake, resources, cleanup | rebuilt sidecar + Vite + Tauri |
| Native package | Installer/updater/release validation | host-platform release build |

Start with desktop development. Use web-only mode when native commands do not
matter. Use bundled-sidecar mode only for changes that can behave differently
after Python packaging.

## Shared requirements

Both platforms need:

- Git;
- Python 3.12 managed through `uv`;
- Bun;
- Rust stable and Cargo;
- Tauri CLI v2;
- platform-native Tauri build dependencies;
- an LLM provider credential, OAuth connection, or local model runtime to run
  real agent turns.

Official prerequisite references:

- [Tauri v2 prerequisites](https://v2.tauri.app/start/prerequisites/)
- [uv installation](https://docs.astral.sh/uv/getting-started/installation/)
- [Bun installation](https://bun.sh/docs/installation)
- [Rust installation](https://www.rust-lang.org/tools/install/)

Do not install a separate global Python package copy of EvoFlux for source
development. `uv sync` creates and manages the repository environment.

## Windows: first-time setup

Use 64-bit Windows 10/11 and PowerShell. The production package is x64, while
the Rust crate uses the MSVC toolchain.

### 1. Install native build prerequisites

Install [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
and select **Desktop development with C++**. Include the recommended MSVC and
Windows SDK components.

Tauri uses Microsoft Edge WebView2. It is normally already present on current
Windows 10/11 systems. If it is missing, install the
[WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).

EvoFlux builds NSIS packages on Windows, so the MSI-only VBSCRIPT prerequisite
is not needed for the normal project build.

### 2. Install command-line tools

Run PowerShell as the normal development user:

```powershell
winget install --id Git.Git -e
winget install --id astral-sh.uv -e
powershell -c "irm bun.sh/install.ps1|iex"
winget install --id Rustlang.Rustup -e
```

Close and reopen PowerShell so user `PATH` changes are visible. Then select the
MSVC Rust toolchain and install Tauri CLI:

```powershell
rustup default stable-msvc
cargo install tauri-cli --version "^2" --locked
```

If Bun installed successfully but is not on `PATH`, verify it directly:

```powershell
& "$env:USERPROFILE\.bun\bin\bun" --version
```

Then restart the terminal. Follow Bun's official `PATH` instructions if the
direct command works but `bun --version` does not.

### 3. Verify the toolchain

```powershell
git --version
uv --version
bun --version
rustup --version
rustc --version
cargo --version
cargo tauri --version
```

Do not proceed until every command succeeds in a newly opened PowerShell
window. If Cargo fails to link a minimal build, reopen the Visual Studio Build
Tools installer and confirm the C++ desktop workload and Windows SDK.

### 4. Clone or open the repository

If the repository is not already present:

```powershell
git clone https://github.com/evoelsewhere/evoflux.git
Set-Location evoflux
```

From an existing checkout, start at the repository root containing
`pyproject.toml`, `uv.lock`, `web/`, and `desktop/`.

### 5. Install locked project dependencies

```powershell
uv python install 3.12
uv sync --frozen

Push-Location web
bun install --frozen-lockfile
Pop-Location

Push-Location desktop\src-tauri
cargo check
Pop-Location
```

`uv sync --frozen` creates `.venv` and installs backend plus development
dependencies from `uv.lock`. `bun install --frozen-lockfile` creates
`web/node_modules` without changing `web/bun.lock`. The first Cargo check
downloads and compiles Rust dependencies and can take several minutes.

### 6. Initialize source-development configuration

Keep source data separate from a packaged/production EvoFlux installation:

```powershell
$env:APP_ENV = "development"
uv run evoflux init
```

The interactive initializer stores development configuration beneath
`.evoflux/dev/`. It asks for a provider/model and writes credentials to the
development config root. Alternatively, skip the interactive command, start
the UI, and configure a provider in Settings; startup will still seed agent
blueprints automatically.

Source development does not auto-apply Alembic revisions. Create or upgrade the
isolated development database before the first run:

```powershell
$env:APP_ENV = "development"
uv run alembic -c app\alembic.ini upgrade head
```

Never commit `.evoflux/`, `.env`, OAuth tokens, API keys, or provider
credentials.

## Windows: run the project

The current reliable native-Windows flow uses three PowerShell terminals.

### Terminal 1: FastAPI

```powershell
Set-Location D:\path\to\evoflux
$env:APP_ENV = "development"
uv run uvicorn app.server:app `
  --host 127.0.0.1 `
  --port 8000 `
  --reload `
  --reload-dir app `
  --no-access-log
```

### Terminal 2: Vite

```powershell
Set-Location D:\path\to\evoflux\web
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8000"
bun dev
```

### Terminal 3: Tauri

```powershell
Set-Location D:\path\to\evoflux\desktop\src-tauri
$env:EVOFLUX_DESKTOP_DEV_BACKEND_URL = "http://127.0.0.1:8000"
cargo tauri dev -c tauri.dev.conf.json
```

Replace `D:\path\to\evoflux` with the checkout's real path. The desktop window
should be named **EvoFlux (dev)** and coexist with a packaged EvoFlux install.

Stop development with `Ctrl+C` in Terminal 3, then Terminal 2, then Terminal 1.
Check ports before restarting if a process was force-closed:

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue
```

### Windows web-only shortcut

Use only Terminals 1 and 2, then open `http://localhost:5173`. Native Tauri
commands, persistent browser behavior, tray integration, and native dialogs are
not fully represented in browser-only mode.

## macOS: first-time setup

The same steps work on Apple Silicon and Intel Macs. The repository and CI
build both architectures.

### 1. Install Apple build tools

For desktop-only development:

```bash
xcode-select --install
```

If full Xcode is already installed, launch it once to finish component setup
and accept its license. Verify:

```bash
xcode-select -p
clang --version
make --version
lsof -v
```

The unified launcher requires `make` and `lsof`; both are normally available
after the Apple command-line tools are installed.

### 2. Install uv, Bun, and Rust

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -fsSL https://bun.com/install | bash
curl --proto '=https' --tlsv1.2 https://sh.rustup.rs -sSf | sh
```

Open a new Terminal, or load the Rust environment in the current shell:

```bash
source "$HOME/.cargo/env"
```

Install Tauri CLI:

```bash
rustup default stable
cargo install tauri-cli --version '^2' --locked
```

Homebrew is optional. If the standalone installers are not desired, official
package-manager alternatives include `brew install uv` and
`brew install oven-sh/bun/bun`; use one installation method per tool to avoid
conflicting upgrade paths.

### 3. Verify the toolchain

```bash
git --version
uv --version
bun --version
rustup --version
rustc --version
cargo --version
cargo tauri --version
```

### 4. Clone and install locked dependencies

```bash
git clone https://github.com/evoelsewhere/evoflux.git
cd evoflux

uv python install 3.12
uv sync --frozen

cd web
bun install --frozen-lockfile
cd ..

cd desktop/src-tauri
cargo check
cd ../..
```

Skip the clone commands when using an existing checkout.

### 5. Initialize source-development configuration

```bash
APP_ENV=development uv run evoflux init
APP_ENV=development uv run alembic -c app/alembic.ini upgrade head
```

As on Windows, the UI can perform provider setup after launch if the
interactive initializer is skipped.

## macOS: run the project

Run the complete source stack from the repository root:

```bash
APP_ENV=development make dev-desktop
```

The supervisor starts FastAPI, Vite, and Tauri, prefixes their logs, and stops
the remaining services when one exits. Stop the group with `Ctrl+C`.

For backend/frontend work without native capabilities:

```bash
APP_ENV=development make dev-web
```

Open `http://localhost:5173` if a browser does not open automatically.

## Verify a successful run

Use these acceptance checks on either platform:

1. FastAPI logs show startup reached `critical_startup_ready`.
2. `http://127.0.0.1:8000/api/health/live` returns a successful response.
3. Vite reports `http://localhost:5173` ready.
4. **EvoFlux (dev)** opens and passes its backend loading screen.
5. Work mode creates or resolves a session.
6. Coding mode can select an authorized repository.
7. A configured model can complete one simple response.
8. Closing the Tauri dev process does not leave an unexpected desktop child
   process; in source mode the separately started API/Vite processes remain
   until their terminals are stopped.

PowerShell health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/live
```

macOS health check:

```bash
curl -fsS http://127.0.0.1:8000/api/health/live
```

## Daily continuous-development loop

### Start of day

1. Open the repository and inspect existing work:

   ```bash
   git status --short
   git branch --show-current
   ```

2. Update safely when appropriate:

   ```bash
   git pull --ff-only
   ```

3. Reconcile dependencies when lockfiles changed:

   ```bash
   uv sync --frozen
   cd web && bun install --frozen-lockfile && cd ..
   cd desktop/src-tauri && cargo check && cd ../..
   ```

4. Apply new database revisions when `app/migrations/` changed:

   ```bash
   APP_ENV=development uv run alembic -c app/alembic.ini upgrade head
   ```

5. Start the macOS unified flow or Windows three-terminal flow.
6. Keep `APP_ENV=development` on the source backend so dev state stays under
   `.evoflux/dev/`.

PowerShell uses `Push-Location`/`Pop-Location` instead of the chained `cd`
examples above.

### During development

- Read root and nearest nested `AGENTS.md` files before editing.
- Follow the specification and acceptance workflow in the
  [project deep dive](project-deep-dive.md#continued-development-workflow).
- Run the smallest focused test while iterating.
- Keep secrets and generated state out of Git.
- Do not delete `.evoflux/dev/config`, wiki, or workspaces merely to fix a
  cache problem; cache and state have different retention rules.
- Restart only the affected service where possible. Python and Vite normally
  reload automatically; Rust changes rebuild the Tauri process.

### Before handoff

Backend gate:

```bash
uv run ruff check app/ tests/
uv run ruff format --check app/ tests/
uv run ty check app/
uv run pytest --no-cov -q
```

Frontend gate:

```bash
cd web
bun run lint
bun run typecheck
bun run build
```

Desktop gate:

```bash
cd desktop/src-tauri
cargo check
```

Finish with `git diff --check` and report exact commands, failures, and checks
not run.

## Dependency update policy

The committed lockfiles are the reproducibility boundary.

| Ecosystem | Normal install | Intentional dependency change |
|---|---|---|
| Python | `uv sync --frozen` | edit `pyproject.toml`, run the appropriate `uv add`/`uv lock`, review `uv.lock` |
| Web | `bun install --frozen-lockfile` | edit `web/package.json` or use `bun add`, review `package.json` and `bun.lock` |
| Rust | `cargo check --locked` where appropriate | edit `Cargo.toml` or use `cargo add`, review `Cargo.toml` and `Cargo.lock` |

Do not casually upgrade all three ecosystems during an unrelated feature.
Toolchain upgrades should be a separate, verified change because they affect
desktop packaging and CI.

## Bundled-sidecar validation

Use this after changes to sidecar packaging, startup imports, migrations,
desktop token authentication, bundled resources, process cleanup, or Office
preview dependencies.

### macOS

Run Vite in one terminal:

```bash
cd web
bun dev
```

Run the packaged-style sidecar/Tauri path in another:

```bash
make -C desktop dev-bundled
```

### Windows

Build the sidecar from the repository root:

```powershell
uv run python scripts\build_sidecar.py `
  --root . `
  --out desktop\sidecar-bundle `
  --python-version 3.12 `
  --extras office-preview
```

Start Vite in one terminal, then run the bundled Tauri configuration from
`desktop\src-tauri` in another. Set `EVOFLUX_APP_ENV=development` and explicit
`EVOFLUX_*_DIR` values under the repository's `.evoflux\dev` directory before
launching so the Rust supervisor passes isolated paths to the child sidecar.

This Windows flow should receive a project-owned PowerShell wrapper before it
becomes a routine developer command.

## Native package smoke builds

Package only on the target operating system.

### Windows NSIS

```powershell
uv run python scripts\build_sidecar.py `
  --root . `
  --out desktop\sidecar-bundle `
  --python-version 3.12 `
  --extras office-preview

Push-Location desktop\src-tauri
cargo tauri build --bundles nsis
Pop-Location
```

### macOS app/DMG

```bash
make -C desktop sidecar
make -C desktop build
```

Unsigned or ad-hoc local packages may trigger operating-system trust prompts.
Signing, notarization, updater metadata, and release artifact validation follow
the [release and packaging contract](release-and-packaging.md), not this daily
development guide.

## Troubleshooting decision tree

### A command is not found

1. Open a new shell after installation.
2. Run the tool by its known install path to distinguish installation from
   `PATH` configuration.
3. Confirm only one package manager owns the tool.
4. Re-run the toolchain verification block before retrying EvoFlux.

### Port 8000 or 5173 is already in use

- Stop the known prior EvoFlux dev terminal with `Ctrl+C`.
- Inspect the owning PID before terminating anything.
- Do not indiscriminately kill all Python, Bun, Node, or Cargo processes.

### Backend starts but the UI cannot connect

- Confirm `/api/health/live` works directly.
- Confirm Vite has `VITE_API_PROXY_TARGET=http://127.0.0.1:8000`.
- Confirm Tauri has
  `EVOFLUX_DESKTOP_DEV_BACKEND_URL=http://127.0.0.1:8000`.
- Check that a stale packaged backend selection is not being used; the dev
  environment variable should force the source backend.

### Python imports or migrations fail

- Run `uv sync --frozen` again.
- Confirm `uv run python --version` is Python 3.12 or newer.
- Confirm `APP_ENV=development` and inspect `.evoflux/dev/state` logs.
- Do not delete the database before reading the migration error.

### Windows linker or WebView failure

- Confirm the Visual Studio **Desktop development with C++** workload.
- Run `rustup default stable-msvc`.
- Confirm the Windows SDK and Edge WebView2 Runtime are installed.
- Restart the terminal or computer after native toolchain installation.

### macOS compiler or permission failure

- Run `xcode-select -p` and `xcodebuild -license` if prompted.
- Launch full Xcode once after an update.
- Treat microphone, screen capture, accessibility, and automation permissions
  as OS-managed state; dev and packaged app identifiers may receive separate
  permission records.

## Planned Windows developer-experience improvement

The immediate three-terminal flow is functional, but continued development
should add a native PowerShell supervisor. This is an internal developer-tool
change with unchanged product behavior.

### Invariants

- Start the same API, Vite, and optional Tauri commands as `run_dev.py`.
- Preserve API/Vite port configuration and environment propagation.
- Stop only processes started by the supervisor.
- Leave pre-existing unrelated listeners untouched unless the user explicitly
  chooses to replace them.
- Preserve `Ctrl+C` cleanup and non-zero sibling-failure propagation.
- Default source runs to isolated development roots.

### Proposed acceptance criteria

- **DEV-AC-1:** Given a native Windows checkout with required tools, one
  documented PowerShell command starts API, Vite, and Tauri with prefixed logs.
- **DEV-AC-2:** Given port 8000 or 5173 is occupied, preflight exits before
  starting children and identifies the occupied port without killing it.
- **DEV-AC-3:** Given any child exits non-zero, the supervisor stops its own
  remaining children and returns the failing status.
- **DEV-AC-4:** Given `Ctrl+C`, every owned child exits and no new listener
  remains on the configured ports.
- **DEV-AC-5:** Given source mode, backend data/config/state/cache/workspace/wiki
  roots resolve beneath `.evoflux/dev/` unless explicitly overridden.
- **DEV-AC-6:** Focused Windows-compatible tests cover command construction,
  environment propagation, occupied ports, sibling failure, and interrupt
  cleanup.

### Suggested ownership

| Work | Files |
|---|---|
| Windows supervisor | new `scripts/run_dev.ps1` or a cross-platform revision of `scripts/run_dev.py` |
| Root entry command | a PowerShell-documented command; avoid making GNU Make mandatory on Windows |
| Regression tests | `tests/scripts/test_run_dev.py` plus Windows-specific tests |
| Current docs | this guide, `setup-and-testing.md`, and the README source-run section |

Do not implement this by relying on WSL for the native Tauri shell. WSL may be
useful for backend-only development, but it is not the primary Windows desktop
capability and process-lifecycle environment.

## Setup completion checklist

- [ ] Platform-native Tauri prerequisites installed
- [ ] Git, uv, Bun, Rust, Cargo, and Tauri CLI verified in a new shell
- [ ] Python 3.12 installed through uv
- [ ] `uv sync --frozen` completed
- [ ] `bun install --frozen-lockfile` completed
- [ ] `cargo check` completed
- [ ] Alembic upgraded the isolated development database to `head`
- [ ] Source backend runs with `APP_ENV=development`
- [ ] FastAPI health endpoint succeeds
- [ ] Vite serves port 5173
- [ ] EvoFlux (dev) opens through Tauri
- [ ] Provider/model configured without committing credentials
- [ ] One Work session and one Coding workspace smoke-tested
- [ ] Stop/restart leaves no unexpected owned processes
- [ ] Focused baseline tests recorded before feature development begins
