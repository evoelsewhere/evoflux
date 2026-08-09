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
                              │  + document-runtime       │
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

# Stage a licensed, platform-specific document runtime first
python scripts/build_document_runtime.py stage \
  --source /secure/evoflux-document-runtime.tar.gz \
  --sha256 <archive-sha256> \
  --out desktop/document-runtime

# Build the Python + document runtime sidecar bundle
make -C desktop sidecar

# Run the desktop shell in dev mode (prefer ``make dev`` from this
# directory so the dev override picks up — see ``Makefile``).
cd desktop && make dev
```

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

Desktop packaging is fail-closed unless `desktop/document-runtime` (or
`EVOFLUX_DOCUMENT_RUNTIME_SOURCE`) is present and verifies against its internal
manifest. The runtime pins Node, artifact-tool, headless Chromium, LibreOffice,
Poppler, and fonts. All components are app-local resources; the installer does
not need Administrator privileges or install document tools machine-wide.
For a server-only development bundle with no document support, pass
`--skip-document-runtime` directly to `scripts/build_sidecar.py`.

The desktop packaging workflow expects a controlled runtime archive and
SHA-256 for each target in these repository secrets:

- `EVOFLUX_DOCUMENT_RUNTIME_MACOS_X64_URL` and
  `EVOFLUX_DOCUMENT_RUNTIME_MACOS_X64_SHA256`
- `EVOFLUX_DOCUMENT_RUNTIME_MACOS_ARM64_URL` and
  `EVOFLUX_DOCUMENT_RUNTIME_MACOS_ARM64_SHA256`
- `EVOFLUX_DOCUMENT_RUNTIME_WINDOWS_X64_URL` and
  `EVOFLUX_DOCUMENT_RUNTIME_WINDOWS_X64_SHA256`

The archive is staged only after both its external checksum and internal
component manifest pass. Artifact-tool input must be licensed for product
distribution; the assembler requires an explicit authorization assertion and
never copies a Codex/developer cache automatically.

On Windows, safe pure-Python packages are stored in one zipimport archive to
reduce the number of small files Defender scans during a cold start. Pass
`--no-zip-purelib` to `scripts/build_sidecar.py` only when debugging packaging.
