# desktop/ — Agent Instructions

Tauri v2 desktop shell that supervises the Python sidecar, opens the embedded web UI, and owns desktop packaging.

## Tech stack

- Rust 2021, minimum Rust 1.77.
- Tauri 2 with opener, dialog, notification, process, log, and single-instance plugins.
- Python sidecar bundle is API-only; the React Web UI is packaged by Tauri from `web/dist`.

## Layout

```
src-tauri/       Rust app, Tauri config, icons, Cargo project
scripts/         Desktop packaging/release helper scripts
sidecar-bundle/  Generated Python sidecar output (build artifact)
Makefile         Desktop dev, sidecar, icon, and build targets
README.md        Architecture and packaging notes
```

## Essential commands

```bash
make -C desktop sidecar       # build slim sidecar bundle
make -C desktop sidecar-full  # include audio + Azure Document Intelligence extras
make -C desktop icons         # regenerate icons from src-tauri/icons/icon.png
make -C desktop dev           # Tauri shell against root make dev
make -C desktop dev-bundled   # Tauri shell with bundled sidecar
make -C desktop build         # release desktop build
make -C desktop clean
```

For normal desktop development, run `make dev` at the repo root first, then `make -C desktop dev` in another terminal.

## Code style

- Keep sidecar lifecycle and auth-token handshake changes small and platform-aware.
- Preserve dev/prod config split (`tauri.dev.conf.json`, `tauri.dev-bundled.conf.json`, production config).
- Do not commit generated sidecar bundles or target artifacts.

## Documentation pointers

- Local architecture: `README.md`.
- Release/signing/update pipeline: `../documents/research/desktop-packaging-signing.md`.
