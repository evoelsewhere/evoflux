#!/usr/bin/env bash
set -euo pipefail

# Build a Windows MSI installer for EvoFlux Desktop.
#
# Prerequisites:
#   - Rust toolchain (rustup default stable)
#   - Tauri CLI v2+ (cargo install tauri-cli --version "^2.0" --locked)
#   - Bun (for web frontend build)
#   - Python 3.12+ (for sidecar build)
#   - uv (for sidecar dependency management)
#   - WiX Toolset v3+ (for MSI generation)
#
# Usage:
#   ./scripts/build_msi.sh [--skip-sidecar] [--skip-frontend] [--dev]
#                          [--allow-unsigned]
#
# Note: This script is designed for Unix-like environments (WSL, Git Bash, macOS
# cross-compilation). For native Windows builds, consider using PowerShell or
# the equivalent commands directly.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DESKTOP_DIR="$ROOT_DIR/desktop"
WEB_DIR="$ROOT_DIR/web"
SIDECAR_BUNDLE="$DESKTOP_DIR/sidecar-bundle"

# Parse arguments
SKIP_SIDECAR=false
SKIP_FRONTEND=false
DEV_MODE=false
ALLOW_UNSIGNED=false

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
    --allow-unsigned)
      ALLOW_UNSIGNED=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "========================================="
echo "  EvoFlux Windows MSI Builder"
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

# Check for WiX Toolset (Windows only)
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
  if ! command -v wix >/dev/null 2>&1; then
    echo "Warning: WiX Toolset not found. MSI build may fail."
    echo "Install WiX Toolset v3+ from: https://wixtoolset.org/"
  fi
fi

echo "Prerequisites OK."
echo ""

WINDOWS_CERT_THUMBPRINT="${EVOFLUX_WINDOWS_CERTIFICATE_THUMBPRINT:-}"
WINDOWS_TIMESTAMP_URL="${EVOFLUX_WINDOWS_TIMESTAMP_URL:-http://timestamp.digicert.com}"
if [ "$DEV_MODE" = false ] && [ -z "$WINDOWS_CERT_THUMBPRINT" ] && [ "$ALLOW_UNSIGNED" = false ]; then
  echo "Error: production Windows builds must be Authenticode-signed."
  echo "Set EVOFLUX_WINDOWS_CERTIFICATE_THUMBPRINT, or pass --allow-unsigned for a local build."
  exit 1
fi

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

# Step 3: Build Tauri app with MSI target
echo "Step 3/3: Building Tauri app (MSI target)..."
cd "$DESKTOP_DIR/src-tauri"

if [ "$DEV_MODE" = true ]; then
  echo "Building DEV MSI..."
  cargo tauri build -c tauri.dev-bundled.conf.json --bundles msi
else
  echo "Building PRODUCTION MSI..."
  if [ -n "$WINDOWS_CERT_THUMBPRINT" ]; then
    SIGNING_CONFIG="{\"bundle\":{\"windows\":{\"certificateThumbprint\":\"$WINDOWS_CERT_THUMBPRINT\",\"digestAlgorithm\":\"sha256\",\"timestampUrl\":\"$WINDOWS_TIMESTAMP_URL\",\"allowDowngrades\":false}}}"
    cargo tauri build --bundles msi --config "$SIGNING_CONFIG"
  else
    echo "WARNING: producing an unsigned local build."
    cargo tauri build --bundles msi
  fi
fi

echo ""
echo "========================================="
echo "  Build Complete!"
echo "========================================="
echo ""
echo "Output locations:"
echo "  MSI: $DESKTOP_DIR/src-tauri/target/release/bundle/msi/"
echo "  EXE: $DESKTOP_DIR/src-tauri/target/release/bundle/nsis/"
echo ""

# List the MSI files if they exist
if [ -d "$DESKTOP_DIR/src-tauri/target/release/bundle/msi" ]; then
  echo "Generated MSI files:"
  ls -lh "$DESKTOP_DIR/src-tauri/target/release/bundle/msi/"
fi

if [ -d "$DESKTOP_DIR/src-tauri/target/release/bundle/nsis" ]; then
  echo ""
  echo "Generated NSIS installer files:"
  ls -lh "$DESKTOP_DIR/src-tauri/target/release/bundle/nsis/"
fi
