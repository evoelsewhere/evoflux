# Desktop shell

The Tauri v2 shell is the production host for EvoFlux. It packages the React
build, supervises the Python sidecar, exposes bounded native commands, owns the
persistent in-app browser, and integrates native windows, tray and updates.

## Sidecar handshake

1. Tauri opens the WebView immediately in a backend-loading state.
2. It tries a remembered external backend when configured.
3. Otherwise it resolves the bundled standalone Python runtime.
4. It launches `evoflux serve --port 0 --handshake --generate-token
   --parent-pid <tauri-pid>`.
5. The sidecar binds loopback and prints `EVOFLUX_HANDSHAKE` JSON.
6. Tauri waits for `/api/health/live` with bounded retry/backoff.
7. It injects the backend origin and desktop token into the WebView.
8. On exit it terminates the sidecar and force-kills only after a grace period.

Secondary windows reuse the same backend and token. Startup failures remain on
the splash screen with Retry and backend-log actions.

Primary ownership: `desktop/src-tauri/src/sidecar.rs` and
`app/cli/commands/serve.py`.

## Native capability boundary

The shell exposes only commands granted in Tauri capability files. Native code
owns operations that cannot be safely or portably implemented in browser JS:

- window lifecycle, drag regions, tray and notifications;
- native open/save/folder dialogs and OS openers;
- workspace discovery and selected filesystem integration;
- direct control of the persistent browser profile;
- native messaging used by WebBridge discovery/pairing;
- application updates and package installation handoff.

The Python sidecar remains the authority for agent permissions, workspace
authorization, application persistence and WebBridge policy.

## Development variants

| Mode | Web assets | Backend |
|---|---|---|
| `make dev-desktop` | Vite development server | source FastAPI at `127.0.0.1:8000` |
| `make -C desktop dev` | Vite development server | external source backend |
| `make -C desktop dev-bundled` | Vite development server | packaged-style bundled sidecar and isolated dev data |
| production package | bundled `web/dist` | bundled standalone Python sidecar |

Development and production Tauri configurations are intentionally separate.
A sidecar/auth/plugin change must be checked across the relevant config variants
and on all affected platforms.

## Platform packaging

- macOS builds an application bundle/DMG, supports signing, notarization and
  the Tauri updater.
- Windows builds a current-user NSIS installer; public artifacts should be
  Authenticode-signed. Pure Python dependencies may be zip-imported to reduce
  Defender cold-start cost.
- Linux builds an x86_64 Debian package and delegates updates to the package
  manager. Direct pointer/keyboard injection currently depends on X11/XWayland.

The exact build and release flow is in
[Release and packaging](../development/release-and-packaging.md). Component-local
details remain in `desktop/README.md`.

## Security invariants

- production sidecars bind loopback and use a random per-launch token;
- external/LAN servers require the configured access policy;
- WebView requests do not receive the token for cross-origin URLs;
- native commands are allowlisted by capability, not globally exposed;
- parent-death monitoring prevents orphaned embedded backends;
- updater keys, signing identities and certificates are supplied by the build
  environment and are never stored in the repository.

## Verification

Use `cargo check` for Rust changes, the Tauri capability tests under
`tests/desktop`, and the relevant package workflow tests under `tests/scripts`.
Run a bundled-sidecar smoke path when changing launch, handshake, migrations or
resource packaging.
