#!/usr/bin/env bash
# End-to-end smoke suite (design 9a): Playwright against Vite + evoflux-server
# (Python behind it), temp EVOFLUX_*_DIRs and the contract-tests mock provider.
#
# Usage: bash scripts/migration/e2e.sh [--rust-forward] [--route-override <unit>=<owner>] [-- <playwright args>]
#
# --rust-forward routes every unit in server/rust-ready.toml to Rust (design 9a);
# with an empty list it says so and runs the default routing. An explicit
# --route-override is appended last, so it wins.
#
# --route-override runs the main journeys with that unit owned by <owner>
# (for example edge-stateless=rust); the rollback drill always sets its own.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
override=""
rust_forward=0
while [ $# -gt 0 ]; do
  case "$1" in
    --route-override)
      [ $# -ge 2 ] || { echo "error: --route-override needs <unit>=<owner>" >&2; exit 2; }
      case "$2" in
        *=python | *=rust) override="$2" ;;
        *) echo "error: --route-override expects <unit>=python|rust, got '$2'" >&2; exit 2 ;;
      esac
      shift 2
      ;;
    --rust-forward)
      rust_forward=1
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "error: unknown argument '$1'" >&2
      exit 2
      ;;
  esac
done

cd "$root"
if [ "$rust_forward" = 1 ]; then
  override="$(uv run python scripts/migration/checkpoint_lib.py override --explicit "$override")"
  echo "e2e: route override: ${override:-<none, default routing>}"
fi
(cd server && cargo build -p evoflux-server)
case "$(uname -s)" in
  MINGW* | MSYS* | CYGWIN*) server_bin="$root/server/target/debug/evoflux-server.exe" ;;
  *) server_bin="$root/server/target/debug/evoflux-server" ;;
esac
python_bin="$(uv run python -c 'import sys; print(sys.executable)')"

cd web
bun install --frozen-lockfile
if [ "${EVOFLUX_E2E_INSTALL_DEPS:-}" = "1" ]; then
  bunx playwright install --with-deps chromium
else
  bunx playwright install chromium
fi

bunx vite build --outDir e2e/.dist --emptyOutDir

export EVOFLUX_E2E_WEB_DIST="$root/web/e2e/.dist"
export EVOFLUX_E2E_SERVER_BIN="$server_bin"
export EVOFLUX_E2E_PYTHON_BIN="$python_bin"
export EVOFLUX_E2E_ROUTE_OVERRIDE="$override"
exec bunx playwright test "$@"
