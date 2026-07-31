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

# Build the web UI first
cd web && bun install && bun run build && cd ..

# Build a slim Python sidecar bundle (uses uv + python-build-standalone)
make -C desktop sidecar

# Run the desktop shell in dev mode (prefer ``make dev`` from this
# directory so the dev override picks up — see ``Makefile``).
cd desktop && make dev
```

## Packaging

Windows production builds must be Authenticode-signed:

```powershell
$env:EVOFLUX_WINDOWS_CERTIFICATE_THUMBPRINT = "YOUR_CERT_THUMBPRINT"
.\scripts\build_msi.ps1
```

WiX MSI validation requires the Windows **VBScript** optional capability. The
build script checks both the 32-bit and 64-bit script engines before starting
the expensive build and prints the Windows capability command if either engine
is unavailable.

For a local-only unsigned artifact, pass `-AllowUnsigned` explicitly. Release
MSIs reject downgrades so a newer database is never opened by an older
migration bundle. The sidecar build also validates the Alembic head marker and
an upgrade from the previous revision before packaging.

On Windows, safe pure-Python packages are stored in one zipimport archive to
reduce the number of small files Defender scans during a cold start. Pass
`--no-zip-purelib` to `scripts/build_sidecar.py` only when debugging packaging.
