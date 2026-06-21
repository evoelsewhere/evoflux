# CLI reference

The `EvoFlux` binary is the single entry point for running, managing, and inspecting the server.

## Start

```bash
EvoFlux                            # start in the background
EvoFlux start --lan --key          # save LAN host + required client access key
EvoFlux restart                    # reuse settings.yaml server.host/port/access_key
```

**Flags**

| Flag | Default | Description |
|---|---|---|
| `--host` | `settings.yaml server.host` | Bind address and save it to `settings.yaml` |
| `--port` | `settings.yaml server.port` | API port and save it to `settings.yaml` |
| `--lan` | off | Save/bind `0.0.0.0` and print LAN addresses |
| `--key` | off | Prompt for a LAN access key, save it to `settings.yaml`, and require API clients to send `Authorization: Bearer <key>` |

The server runs as a detached background process and exposes the API on port 4082 by default. It does not serve the React Web UI; use the desktop app for the packaged UI or `make dev` from source for Vite + API development. Logs go to `~/.local/state/evoflux/logs/app/app.log`. The server auto-migrates the database on startup. For clients on the same network, use `evoflux start --lan --key` in public or shared networks. `--lan`, `--host`, `--port`, and `--key` update `~/.config/evoflux/settings.yaml`, so later `evoflux restart` keeps the same bind address, port, and access-key protection without another prompt. The desktop/web backend connection dialog has an **Access key** field that stores the key locally and sends it on API/SSE requests.

If EvoFlux hasn't been initialised yet, `EvoFlux` automatically runs `evoflux init` before starting the server.

For local frontend + backend development with hot-reload, use `make dev` (from the source checkout): it starts uvicorn with `--reload` on `:8000` and Vite on `:5173` together.

---

## init

```bash
EvoFlux init           # interactive setup (~/.config/evoflux/)
```

Interactive first-time setup wizard. Prompts for provider, model, and API key, then installs the default agent team and editable config. Re-running `init` is safe — existing files are never overwritten.

See [Install — First run](install.md#first-run) for a full walkthrough.

---

## auth

```bash
EvoFlux auth copilot         # GitHub Copilot — device-flow OAuth
EvoFlux auth codex           # OpenAI Codex — PKCE OAuth (browser)
EvoFlux auth codex --device  # OpenAI Codex — headless device-code flow
EvoFlux auth --list          # list available OAuth providers
```

Authenticates with an OAuth-based provider. Only needed for providers that don't use an API key (GitHub Copilot, OpenAI Codex). Token is cached locally and reused on subsequent runs.

In the desktop/web UI, the same OAuth setup is available from **Settings → Providers**.

---

## migrate

```bash
EvoFlux migrate openclaw --model openai:gpt-5.5
EvoFlux migrate hermes --model openai:gpt-5.5
```

Imports OpenClaw or Hermes identity/context Markdown files into one EvoFlux lead agent. Use `--from`, `--name`, `--config-dir`, and `--force` to override defaults.

See [`../../MIGRATION.md`](../../MIGRATION.md) for source files, output paths, and manual migration notes for Claude Code and Codex CLI.

---

## stop

```bash
EvoFlux stop
```

Sends `SIGTERM` to the background server process. Waits up to 5 seconds for a clean shutdown, then sends `SIGKILL` if needed. Clears the PID file.

---

## restart

```bash
EvoFlux restart
EvoFlux restart --host 127.0.0.1
EvoFlux restart --key
```

Stops the background server when it is running, then starts it again. `restart` reuses `settings.yaml` server config; pass `--host`, `--port`, `--lan`, or `--key` to update that config before the server starts.

---

## status

```bash
EvoFlux status
```

Reports whether a background server is running, the PIDs, local/LAN addresses, and the log file path.

---

## address

```bash
EvoFlux address
EvoFlux address --lan
```

Prints the local server URL and detected LAN URLs for desktop pairing.

---

## health

```bash
EvoFlux health
EvoFlux health --lan
```

Runs server-focused diagnostics for desktop clients: PID state, port reachability, `/api/health/live`, `/api/health/ready`, and LAN binding guidance. Exits non-zero when required server checks fail.

---

## logs

```bash
EvoFlux logs           # tail last 50 lines and follow
EvoFlux logs -n 100    # tail last 100 lines and follow
```

Tails the server log file (equivalent to `tail -n <lines> -f`). Reads from `~/.local/state/evoflux/logs/app/app.log`.

---

## doctor

```bash
EvoFlux doctor
```

Runs a series of health checks and exits with code 1 if any fail:

| Check | Pass | Fail |
|---|---|---|
| Python version | ≥ 3.14 | < 3.14 |
| API key / OAuth | Any provider key set, or OAuth-only provider (`copilot`, `codex`, `vertexai`, `cliproxy`, `router9`, `ollama`) configured | No key and no OAuth provider found |
| Provider/key match | Lead agent's provider has a matching key (or is OAuth-only) | Provider set but key missing |
| Database | `evoflux.db` exists | Not found (warning only — created on first run) |
| Alembic config | `alembic.ini` next to `app/core/db.py` | Missing (reinstall) |
| Port 4082 | Available | In use |
| Agents directory | At least one `.md` in `{EVOFLUX_CONFIG_DIR}/agents/` | Missing (run `evoflux init`) |

Warnings (degraded but bootable) don't affect the exit code. Run this first when something looks wrong.

---

## upgrade

```bash
EvoFlux upgrade
```

Stops the background server if it is running, upgrades EvoFlux to the latest published version, then restarts the server. Detects how EvoFlux was installed and delegates to the right package manager:

| Install method | Command run |
|---|---|
| Homebrew | `brew upgrade EvoFlux` |
| uv tool | `uv tool upgrade EvoFlux` |
| pipx | `pipx upgrade EvoFlux` |
| pip (fallback) | `pip install $1evoflux` |

The desktop bundle has its own update path — **EvoFlux → Check for Updates…** in the menu bar — backed by `tauri-plugin-updater` against a signed minisign manifest, not the PyPI flow above.

---

## version

```bash
EvoFlux version
EvoFlux --version
```

Prints the installed version and exits.

---

## Related

- [Install](install.md)
- [Configuration](configuration.md)
- [Troubleshooting](troubleshooting.md)
