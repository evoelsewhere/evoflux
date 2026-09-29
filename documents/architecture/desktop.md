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
- Computer App Control on Windows and macOS (`app_computer_*`): window capture,
  the accessibility tree (UI Automation / the macOS Accessibility API) and
  input posted to one attached app window;
- native messaging used by WebBridge discovery/pairing;
- application updates and package installation handoff.

The Python sidecar remains the authority for agent permissions, workspace
authorization, application persistence and WebBridge policy.

## Desktop settings

Run on startup, the tray icon and Keep computer awake are shell-owned
(`desktop_settings.rs`, `autostart.rs`, `keep_awake.rs`) and exposed through
`app_desktop_settings` / `app_update_desktop_settings`. The OS login entry is
the source of truth for Run on startup; the other two persist in
`desktop-settings.json` beside `desktop-backend.json` and `window-state.json`.
A launch with `--autostart` builds the main window hidden when the tray (or
the macOS Dock) can bring it back. With the tray icon off on Windows or Linux,
closing the last visible window quits instead of hiding. See
[Desktop app settings](../features/desktop-app-settings.md).

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

## Application updates

An update is downloaded and installed in two separate steps
(`app_download_update`, then `app_restart_to_update`):

1. The shell downloads the release package, verifies its minisign signature
   and stages it under `<app local data>/updates/` with a `staged.json` that
   records the version and the signature it was verified against. EvoFlux
   keeps running; the dialog then asks whether to **Restart now**.
2. The staged package installs on **Restart now**, or — if the user chooses
   **Install when I quit** — the next time EvoFlux exits (`ExitRequested`,
   except restarts). Before either, the sidecar and its job-object process
   tree are stopped.

On Windows the shell runs the staged NSIS installer itself in passive mode
(`/P /UPDATE`, plus `/R` only for Restart now), so the installer shows its own
progress window instead of copying the whole install invisibly. The NSIS
pre-install hook also stops `evoflux-webbridge-host.exe` (a hard link to
`EvoFlux.exe`) and `evoflux-tailnet.exe`, which would otherwise hold files the
installer must replace. macOS installs through the Tauri updater's bundle
replacement.

A check that finds the release already staged (same version and signature)
reports it as ready, so a relaunch never downloads the same update twice. The
staged package is removed once the running version equals it, when a newer
release is staged, or when a check finds no update.

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
