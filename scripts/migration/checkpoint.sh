#!/usr/bin/env bash
# Automated checkpoint (design 9a, "Rust-forward build").
#
# Usage: bash scripts/migration/checkpoint.sh <phase> [--real-model]
# Env: CHECKPOINT_CONTRACT_PATHS narrows the contract step (default: contract-tests).
#
# Builds evoflux-server, runs the e2e suite with default routing and with
# --rust-forward, runs the TARGET=gateway contract suite with the same
# Rust-forward override, and writes documents/analysis/checkpoint-<phase>-<date>.md.
# Exits non-zero when any step failed. The report is labelled "automated: not
# owner use".
#
# --real-model also re-runs only the chat journey against the owner's provider
# config: ~/.config/evoflux is copied to a temp dir that is deleted on exit
# (success or failure) and nothing from it is printed or written to the report.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
phase=""
real_model=0
for arg in "$@"; do
  case "$arg" in
    --real-model) real_model=1 ;;
    -*) echo "error: unknown argument '$arg'" >&2; exit 2 ;;
    *) [ -z "$phase" ] && phase="$arg" || { echo "error: unexpected argument '$arg'" >&2; exit 2; } ;;
  esac
done
case "$phase" in
  "" | *[!A-Za-z0-9._-]*) echo "usage: checkpoint.sh <phase> [--real-model]  (phase: letters, digits, . _ -)" >&2; exit 2 ;;
esac

cd "$root"
work="$(mktemp -d)"
# Native Windows Python must be able to open the logs: use a C:/ style path.
if command -v cygpath >/dev/null 2>&1; then work="$(cygpath -m "$work")"; fi
cleanup() { rm -rf "$work"; }
trap cleanup EXIT

commit="$(git rev-parse --short HEAD)"
[ -n "$(git status --porcelain)" ] && commit="$commit+dirty"
date_utc="$(date -u +%F)"
report="documents/analysis/checkpoint-$phase-$date_utc.md"
lib="scripts/migration/checkpoint_lib.py"

echo "checkpoint $phase: building evoflux-server"
(cd server && cargo build -p evoflux-server) || { echo "error: server build failed" >&2; exit 1; }

override="$(uv run python "$lib" override)" || exit 1
units="$(echo "$override" | sed 's/=rust//g')"
steps=()

run_step() { # name kind logfile -- command...
  local name="$1" kind="$2" log="$3"
  shift 4
  echo "== $name"
  "$@" 2>&1 | tee "$log"
  local code="${PIPESTATUS[0]}"
  steps+=(--step "$name:$code:$kind:$log")
}

run_step "e2e default" playwright "$work/e2e-default.log" -- bash scripts/migration/e2e.sh
run_step "e2e rust-forward" playwright "$work/e2e-forward.log" -- bash scripts/migration/e2e.sh --rust-forward
# The whole suite takes over 15 minutes through the gateway; CHECKPOINT_CONTRACT_PATHS
# narrows it (the report names the subset so it is never mistaken for the full run).
contract_paths="${CHECKPOINT_CONTRACT_PATHS:-contract-tests}"
contract_name="contract gateway (rust-forward)"
if [ "$contract_paths" != "contract-tests" ]; then
  contract_name="contract gateway subset: ${contract_paths//contract-tests\//}"
fi
# shellcheck disable=SC2086
run_step "$contract_name" pytest "$work/contract.log" -- \
  env TARGET=gateway EVOFLUX_ROUTE_OVERRIDE="$override" uv run --group contract pytest $contract_paths -q --no-cov

if [ "$real_model" = 1 ]; then
  real_config="${HOME}/.config/evoflux"
  if [ -d "$real_config" ]; then
    cp -r "$real_config" "$work/real-config"
    run_step "e2e real model (chat only)" playwright "$work/e2e-real.log" -- \
      env EVOFLUX_E2E_REAL_CONFIG_DIR="$(cd "$work/real-config" && pwd -W 2>/dev/null || pwd)" \
      bash scripts/migration/e2e.sh -- real-model.spec.ts
  else
    echo "error: --real-model needs a provider config at $real_config" >&2
    echo "no provider config found for --real-model" >"$work/e2e-real.log"
    steps+=(--step "e2e real model (chat only):1:playwright:$work/e2e-real.log")
  fi
fi

uv run python "$lib" report --phase "$phase" --commit "$commit" --date "$date_utc" \
  --units "$(echo "$units" | tr -d ' ')" --out "$report" "${steps[@]}"
code=$?
echo "checkpoint $phase: wrote $report (exit $code)"
exit "$code"
