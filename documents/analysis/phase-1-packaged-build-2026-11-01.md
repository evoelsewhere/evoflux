# Phase 1 packaged build with the web UI (2026-11-01)

Task T5. `scripts/build_sidecar.py` now builds the web UI (`bun install --frozen-lockfile && bun run build` in `web/`) when `web/dist/index.html` is missing; `--no-build-web` keeps the `web bundle missing` error and exits 1. `make package` runs the web build, `build_sidecar.py --no-build-web`, then `cargo tauri build` in `desktop/src-tauri`.

## Result (Windows x64, built from `wip/claude/p1-t5`)

- Installer: `desktop/src-tauri/target/release/bundle/nsis/EvoFlux_3.1.1_x64-setup.exe`, 98,044,626 bytes, version 3.1.1.
- SHA-256: `3bc6cb8122e62e9923bcfb3554c6e12b4e9ab79e832f5fe5a6fe4b20470dd337`.
- Sidecar bundle 285 MB; its own smoke test (migration upgrade, handshake, auth, WebSocket) passed.
- The first `cargo tauri build` stopped at `makensis` with no detail; the identical rerun succeeded.

## Smoke check (not installed)

`evoflux-server.exe serve --handshake --generate-token` run from `desktop/sidecar-bundle` with `EVOFLUX_RUST_FORWARD=1` and temporary config and data directories: the handshake line arrived (version 3.1.1), `/api/health/live` 200, `/` 200, `/assets/index-*.js` 200. The temporary directories were deleted. The installer itself was not run.

## Rust-forward in the packaged app

The desktop shell (`desktop/src-tauri/src/sidecar_gateway.rs`) passes no `--rust-forward` and sets no `EVOFLUX_RUST_FORWARD`, so the installed app starts with Python owning every unit. The gateway reads `EVOFLUX_RUST_FORWARD=1`, and the shell's child process inherits its environment, so launching the app from a shell where that variable is set turns it on. Making it the packaged default needs a change to `gateway_args` or `gateway_env` in `sidecar_gateway.rs` (one `--rust-forward` argument), plus its tests.
