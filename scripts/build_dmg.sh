#!/usr/bin/env bash
set -euo pipefail

# Build a macOS DMG package for EvoFlux Desktop.
#
# Prerequisites:
#   - Rust toolchain (rustup default stable)
#   - Tauri CLI v2+ (cargo install tauri-cli --version "^2.0" --locked)
#   - Bun (for web frontend build)
#   - Python 3.12+ (for sidecar build)
#   - uv (for sidecar dependency management)
#
# Usage:
#   ./scripts/build_dmg.sh [--skip-sidecar] [--skip-frontend] [--dev]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DESKTOP_DIR="$ROOT_DIR/desktop"
WEB_DIR="$ROOT_DIR/web"
SIDECAR_BUNDLE="$DESKTOP_DIR/sidecar-bundle"

# Parse arguments
SKIP_SIDECAR=false
SKIP_FRONTEND=false
DEV_MODE=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-sidecar)
      SKIP_SIDECAR=true
      shift
      ;;
    --skip-frontend)
      SKIP_FRONTEND=true
      shift
      ;;
    --dev)
      DEV_MODE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "========================================="
echo "  EvoFlux macOS DMG Builder"
echo "========================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."
command -v cargo >/dev/null 2>&1 || { echo "Error: cargo not found. Install Rust."; exit 1; }
command -v bun >/dev/null 2>&1 || { echo "Error: bun not found. Install bun."; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 not found."; exit 1; }

# Check for Tauri CLI
if ! cargo tauri --version >/dev/null 2>&1; then
  echo "Installing Tauri CLI..."
  cargo install tauri-cli --version "^2.0" --locked
fi

echo "Prerequisites OK."
echo ""

# Step 1: Build web frontend
if [ "$SKIP_FRONTEND" = false ]; then
  echo "Step 1/3: Building web frontend..."
  cd "$WEB_DIR"
  bun install --frozen-lockfile
  bun run build
  echo "Web frontend built successfully."
  echo ""
else
  echo "Step 1/3: Skipping web frontend build."
fi

# Step 2: Build Python sidecar
if [ "$SKIP_SIDECAR" = false ]; then
  echo "Step 2/3: Building Python sidecar bundle..."
  cd "$ROOT_DIR"
  python3 scripts/build_sidecar.py \
    --root "$ROOT_DIR" \
    --out "$SIDECAR_BUNDLE" \
    --python-version 3.12
  echo "Sidecar bundle built successfully."
  echo ""
else
  echo "Step 2/3: Skipping sidecar build."
fi

# Step 3: Build Tauri app with DMG target
echo "Step 3/3: Building Tauri app (DMG target)..."
cd "$DESKTOP_DIR/src-tauri"

if [ "$DEV_MODE" = true ]; then
  echo "Building DEV DMG..."
  cargo tauri build -c tauri.dev-bundled.conf.json --bundles dmg
else
  echo "Building PRODUCTION DMG..."
  cargo tauri build --bundles dmg
fi

echo ""
echo "========================================="
echo "  Build Complete!"
echo "========================================="
echo ""
echo "Output locations:"
echo "  DMG: $DESKTOP_DIR/src-tauri/target/release/bundle/dmg/"
echo "  APP: $DESKTOP_DIR/src-tauri/target/release/bundle/macos/"
echo ""

# List the DMG files if they exist
if [ -d "$DESKTOP_DIR/src-tauri/target/release/bundle/dmg" ]; then
  echo "Generated DMG files:"
  ls -lh "$DESKTOP_DIR/src-tauri/target/release/bundle/dmg/"
fi
