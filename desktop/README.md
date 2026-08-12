# EvoFlux Desktop (Tauri v2)

Native desktop shell for EvoFlux. Embeds the React Web UI, can spawn the Python backend as a sidecar or connect to an external server, and owns desktop packaging.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  EvoFlux.app  (Tauri Rust)                           │
│  ┌────────────────────────┐  ┌──────────────────────┐   │
│  │  WebView (system)      │  │  Sidecar supervisor  │   │
│  │  bundled web/dist      │  │  python ... serve    │   │
│  │  injects API base URL  │──┤  --handshake         │   │
│  └────────────────────────┘  │  --generate-token    │   │
│                              │  --parent-pid <pid>  │   │
│                              └──────────┬───────────┘   │
└─────────────────────────────────────────┼───────────────┘
                                          │
                              ┌───────────▼─────────────┐
                              │  python-build-standalone │
                              │  + site-packages         │
                              │  + app/ (FastAPI)        │
                              │  API server only          │
                              └──────────────────────────┘
```

The Python sidecar:

1. Binds 127.0.0.1 on an OS-ephemeral port.
2. Generates a random URL-safe token.
3. Emits one JSON line on stdout: `EVOFLUX_HANDSHAKE {"port":..., "token":..., "pid":...}`.
4. Then proceeds to start uvicorn normally.
5. Watches the Tauri PID; exits if the shell crashes.

The Tauri shell:

1. Opens the main WebView immediately with a loading/unreachable backend state.
2. Checks the remembered external backend from `desktop-backend.json`; if it is healthy, updates the WebView to use that server.
3. If the remembered external backend is unreachable, continues startup with the bundled sidecar so the app remains usable.
4. Otherwise locates the bundled Python runtime in `Contents/Resources/python/` (macOS),
   `resources\python\` (Windows), or `usr/lib/EvoFlux/python/` (Linux).
5. Spawns the sidecar with `--handshake --generate-token --parent-pid <our pid>`.
6. Reads stdout until the handshake line; extracts `{port, token}`. Failed
   cold starts are stopped and retried with bounded backoff.
7. Polls `http://127.0.0.1:<port>/api/health/live` until it returns 200.
8. Streams startup phases to the splash screen, then updates the already-open
   WebView with `window.__OAD_TOKEN__ = "..."` and the backend URL. Startup
   errors remain on the splash with Retry and View Backend Log actions.
9. Opens secondary WebViews against the same sidecar/token (`Cmd/Ctrl+N`).
10. On app quit: SIGTERM the sidecar; force-kill after 5s.

## Development

```sh
# Once: install Rust + Tauri CLI
rustup default stable
cargo install tauri-cli --version "^2.0" --locked

# Install source dependencies
uv sync
cd web && bun install && cd ..

# Source API + Vite + Tauri in one terminal
make dev-desktop

# Or use two terminals:
make dev-web
make -C desktop dev
```

Normal desktop development forces the Tauri shell to use the source API at
`http://127.0.0.1:8000`; it does not launch a cached sidecar. To exercise the
packaged sidecar handshake and isolated development data instead, run
`cd web && bun dev` in one terminal and `make -C desktop dev-bundled` in another.

## Packaging

Build the current-user Windows NSIS installer with:

```powershell
cargo tauri build --bundles nsis
```

The installer defaults to `%LOCALAPPDATA%\EvoFlux` and does not require
Administrator privileges. Public Windows builds should be Authenticode-signed;
the GitHub packaging workflow imports the configured PFX and supplies its
thumbprint to Tauri. The sidecar build validates the Alembic head marker and an
upgrade from the previous revision before packaging.

On Windows, safe pure-Python packages are stored in one zipimport archive to
reduce the number of small files Defender scans during a cold start. Pass
`--no-zip-purelib` to `scripts/build_sidecar.py` only when debugging packaging.
