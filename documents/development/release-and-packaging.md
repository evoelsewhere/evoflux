# Release and packaging

EvoFlux releases combine a React production build, a standalone Python sidecar
and a Tauri native package. The Python wheel remains an API-only distribution;
the desktop product packages `web/dist` through Tauri.

## Version sources

The project version in `pyproject.toml` and `app/version.txt` must stay aligned.
Tauri/package metadata and release tags must describe the same product version.
Tagged desktop builds require signed updater metadata for platforms that use the
Tauri updater.

## Build layers

### Web

```bash
make build-web
```

This installs Bun dependencies and produces `web/dist`.

### Python wheel

```bash
make build
```

Hatch packages `app/`, Alembic resources and the offline `seed/` bundle. The
web UI is not embedded in the wheel.

### Desktop sidecar

```bash
make -C desktop sidecar
make -C desktop sidecar-full  # adds Azure Document Intelligence
```

`scripts/build_sidecar.py` downloads/assembles the target Python runtime,
installs project dependencies and optional Office preview engines, includes app
and migration resources, and validates the resulting entry path. Generated
`desktop/sidecar-bundle` is a build artifact and must not be committed.

### Native package

```bash
make -C desktop build
```

Run on the target platform. Tauri packages the web build, sidecar and native
resources according to `desktop/src-tauri/tauri.conf.json`.

## CI package matrix

`.github/workflows/desktop-packages.yml` builds:

| Target | Runner/package |
|---|---|
| macOS Intel | `macos-15-intel`, DMG |
| macOS Apple Silicon | `macos-15`, DMG |
| Windows x64 | Windows 2022, current-user NSIS |
| Linux x64 | Ubuntu 22.04, amd64 DEB |

The workflow can run manually per platform or on `v*` tags. It caches Cargo and
Tauri, builds the native sidecar, validates package artifacts and publishes
platform outputs/checksums in the release flow.

## Signing and updates

- macOS uses a Developer ID certificate plus Apple API credentials for
  notarization. Non-release manual runs may use ad-hoc signing when selected.
- Windows imports a CI-provided PFX into the current-user certificate store and
  uses SHA-256 Authenticode with timestamping.
- Tauri updater artifacts use a minisign key pair supplied by CI. Tagged builds
  fail if required updater signing material is absent.
- Linux packages are updated through apt/manual DEB installation; the Tauri
  updater does not overwrite package-manager-owned files.

Keys and certificates are CI/environment inputs. Never commit them or echo
decoded secret material.

## Release gates

Before tagging:

1. synchronize version sources and release notes;
2. run backend, frontend and Rust quality gates;
3. pass migration-head and previous-revision upgrade tests;
4. build the standard sidecar and verify handshake/auth/health;
5. validate Tauri capabilities and bundled MCP/browser CSP behavior;
6. run package workflow regression tests;
7. verify signing/updater public key configuration;
8. install and launch each target package, then confirm the bundled backend
   reaches ready state;
9. validate artifact architecture, filenames and SHA-256 checksums.

## Platform notes

Windows pure-Python packages may be stored in a zipimport archive to reduce
Defender cold-start scanning. Linux direct browser input requires X11/XWayland
and does not claim native Wayland injection. macOS Intel dependency resolution
pins compatible ONNX runtime versions through project constraints.

The detailed historical investigation remains in
[`../research/desktop-packaging-signing.md`](../research/desktop-packaging-signing.md),
while this page describes the current release contract.
