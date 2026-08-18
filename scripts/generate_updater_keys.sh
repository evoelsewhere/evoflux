#!/usr/bin/env bash
# Generate a Tauri updater signing key pair.
#
# Run once, locally, by a maintainer. The private key is stored as the
# `TAURI_SIGNING_PRIVATE_KEY` GitHub secret (and its password as
# `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`). The public key is stored as the
# `TAURI_SIGNING_PUBLIC_KEY` GitHub secret and injected into release builds.
#
# Re-running this script invalidates every installed copy of the app —
# only do it on a security incident.

set -euo pipefail

if ! command -v cargo >/dev/null; then
    echo "error: cargo not found — install Rust first" >&2
    exit 1
fi

if ! command -v cargo-tauri >/dev/null && ! cargo tauri --version >/dev/null 2>&1; then
    echo "Installing tauri-cli..."
    cargo install tauri-cli --version "^2.0" --locked
fi

OUT_DIR="${1:-.tauri-keys}"
mkdir -p "$OUT_DIR"

# Tauri v2 stores keys at the path you pass; password is read interactively.
cargo tauri signer generate -w "$OUT_DIR/EvoFlux.key"

cat <<EOF

Generated:
  Private key: $OUT_DIR/EvoFlux.key
  Public key:  $OUT_DIR/EvoFlux.key.pub

Next steps:
  1. Add the public and private keys as GitHub secrets:
       gh secret set TAURI_SIGNING_PUBLIC_KEY < "$OUT_DIR/EvoFlux.key.pub"
       gh secret set TAURI_SIGNING_PRIVATE_KEY < "$OUT_DIR/EvoFlux.key"

     If you protected the key with a password, add it separately:
       gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD

  2. NEVER commit the private key. The default .tauri-keys/ directory is
     already ignored by this repository.

If you lose the private key, you cannot publish updates. Back it up
to a password manager.
EOF
