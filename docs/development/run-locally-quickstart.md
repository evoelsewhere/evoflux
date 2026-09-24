# Run EvoFlux locally — quick start (Windows)

Status: contributor quick-reference. For full detail, see
[local-development-windows-macos.md](local-development-windows-macos.md).

This project runs as **three processes** together:

```text
FastAPI backend (port 8000)  +  Vite UI (port 5173)  +  Tauri desktop window
```

You need **3 PowerShell windows** open at the same time, one per process.
Run everything from the repository root: `D:\evoflux\evoflux`.

---

## 0. One-time setup (skip if already done)

Only needed the very first time, or after pulling changes that touch
dependencies.

```powershell
uv sync --frozen
cd web
bun install --frozen-lockfile
cd ..
cd desktop\src-tauri
cargo check
cd ..\..
```

---

## 1. Every time you start working

### Terminal 1 — Backend (FastAPI)

```powershell
$env:APP_ENV = "development"
uv run alembic -c app\alembic.ini upgrade head
uv run uvicorn app.server:app --host 127.0.0.1 --port 8000 --reload --reload-dir app --no-access-log
```

Wait until you see `critical_startup_ready` in the log. Leave this terminal open.

### Terminal 2 — Frontend (Vite)

```powershell
cd web
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8000"
bun dev
```

Wait until you see `VITE ... ready`. Leave this terminal open.

### Terminal 3 — Desktop window (Tauri)

```powershell
cd desktop\src-tauri
$env:EVOFLUX_DESKTOP_DEV_BACKEND_URL = "http://127.0.0.1:8000"
cargo tauri dev -c tauri.dev.conf.json
```

The first build compiles Rust code and can take 30–60+ seconds. When it
finishes you'll see `Running target\debug\evoflux-desktop.exe` and a window
titled **EvoFlux (dev)** will open.

---

## 2. Check it worked

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health/live
```

Should return `status: ok`. The **EvoFlux (dev)** window should be visible and
past its loading screen.

---

## 3. While you work

- **Backend (Python) changes** → Terminal 1 auto-reloads (`--reload`). No restart needed.
- **Frontend (React/TypeScript) changes** → Terminal 2 hot-reloads in the open window. No restart needed.
- **Desktop shell (Rust) changes** → Terminal 3 detects the change and rebuilds/relaunches automatically. Just wait for it to finish.

### If you changed dependencies (not just code)

| You changed... | Run this before restarting |
|---|---|
| `pyproject.toml` / `uv.lock` | `uv sync --frozen` |
| `web/package.json` / `web/bun.lock` | `cd web && bun install --frozen-lockfile && cd ..` |
| `desktop/src-tauri/Cargo.toml` | `cd desktop\src-tauri && cargo check && cd ..\..` |

### If you changed database models

```powershell
$env:APP_ENV = "development"
uv run alembic -c app\alembic.ini upgrade head
```

---

## 4. Restarting after a fix (or after closing everything)

Stop each terminal with `Ctrl+C`, in this order: Terminal 3, then Terminal 2,
then Terminal 1. Then just repeat **section 1** above (Terminal 1 → 2 → 3) —
Terminal 1's `alembic upgrade head` is safe to re-run every time, it does
nothing if the database is already current.

If a terminal was closed by accident (not with `Ctrl+C`), check nothing is
still holding the ports before restarting:

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue
```

If something is listed, stop that leftover process (or just close its
terminal window) before starting a fresh one on the same port.

---

## 5. Common problems

| Symptom | Fix |
|---|---|
| Vite complains a package "could not be resolved" | `cd web && bun install --frozen-lockfile && cd ..`, then restart Terminal 2 |
| `alembic current` is behind `alembic heads` | `uv run alembic -c app\alembic.ini upgrade head` |
| Port 8000 or 5173 already in use | Find and close the old terminal/process, don't force-kill blindly |
| Tauri window never opens | Check Terminal 3 for a Rust compile error; fix the error, save, it rebuilds automatically |
| UI loads but can't reach backend | Confirm Terminal 1 shows `critical_startup_ready` and `http://127.0.0.1:8000/api/health/live` returns `ok` |

---

## 6. Stopping everything

`Ctrl+C` in Terminal 3, then Terminal 2, then Terminal 1, in that order.
