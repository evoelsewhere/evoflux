#!/usr/bin/env bash
# Windows: GNU make is optional; run bash scripts/migration/gates.sh shared directly.
set -euo pipefail
cd "$(dirname "$0")/../.."
area="${1:?usage: gates.sh <area>}"
base="${GATES_DIFF_BASE:-origin/migrate/rust-v4}"
if [[ -n "${GATES_DIFF_BASE:-}" ]]; then diff_range="$base..HEAD"; else diff_range="$base...HEAD"; fi
if [[ "${GATES_DRY_RUN:-0}" == 1 ]]; then
  echo "shared gates"
  echo "check_paths $area"
  case "$area" in
    shared) ;;
    cutover-*) echo "contract-all gateway" ;;
    *) echo "nextest evoflux-area-$area"; echo "mutants evoflux-area-$area"; echo "openapi $area" ;;
  esac
  exit 0
fi
fixture=$(mktemp -d)
output=$(mktemp)
cleanup() { rm -rf "$fixture"; rm -f "$output"; }
trap cleanup EXIT
cp -R server/lint-fixtures/bad-blocking/src "$fixture/src"
cp server/lint-fixtures/bad-blocking/Cargo.toml "$fixture/Cargo.toml"
# Copy the actual workspace tables; losing a workspace lint must break this gate.
python - "$fixture/Cargo.toml" <<'PYCODE'
import pathlib, re, sys, tomllib
source = pathlib.Path("server/Cargo.toml").read_text(encoding="utf-8")
lints = tomllib.loads(source)["workspace"]["lints"]
required = ("unwrap_used", "expect_used", "panic", "indexing_slicing", "todo", "unimplemented", "await_holding_lock", "disallowed_methods")
if lints.get("rust", {}).get("unsafe_code") != "forbid" or any(lints.get("clippy", {}).get(name) != "deny" for name in required):
    raise SystemExit("workspace lint table is missing a required deny/forbid")
sections = re.findall(r"(?ms)^\[workspace\.lints\.(?:rust|clippy)\]\s*\n(?:(?!\[)[^\n]*\n)*", source)
if len(sections) != 2:
    raise SystemExit("missing workspace lint tables")
with pathlib.Path(sys.argv[1]).open("a", encoding="utf-8", newline="\n") as manifest:
    for section in sections:
        manifest.write("\n" + section.replace("[workspace.lints.", "[lints."))
PYCODE
if CLIPPY_CONF_DIR="$(pwd)/server" cargo clippy --manifest-path "$fixture/Cargo.toml" -- -D warnings >"$output" 2>&1; then
  cat "$output"
  echo "error: intentionally bad lint fixture passed" >&2
  exit 1
fi
cat "$output"
for expected in 'std::thread::sleep' 'std::fs::read' '#unwrap_used' 'std::process::Command::new' '#expect_used' '#panic' '#todo' '#unimplemented' '#indexing_slicing' '#await_holding_lock'; do
  if ! grep -Fq "$expected" "$output"; then
    echo "error: fixture failed without expected diagnostic: $expected" >&2
    exit 1
  fi
done
(cd server && cargo fmt --check && cargo clippy --workspace --all-targets -- -D warnings && cargo nextest run --workspace --no-tests=warn && cargo deny check)
if [[ "$area" != shared && "$area" != cutover-* ]]; then
  (cd server && cargo nextest list -p "evoflux-area-$area" --message-format json) |
    python -c 'import json, sys; n = json.load(sys.stdin)["test-count"]; sys.exit(0 if n > 0 else "error: lane has no tests")'
fi
python scripts/migration/check_paths.py "$area"
# The compatibility gate is mandatory whenever the DB implementation or its
# pinned SQLite changes, including local unstaged/staged changes.
db_changes=$(git diff --name-only "$diff_range" -- server/crates/core/src/db server/vendor server/crates/core/examples/db_stress.rs contract-tests/db contract-tests/fixtures/upgrade)
db_changes+=$(git diff --name-only HEAD -- server/crates/core/src/db server/vendor server/crates/core/examples/db_stress.rs contract-tests/db contract-tests/fixtures/upgrade)
if [[ -n "$db_changes" ]]; then
  (cd server && cargo build -p evoflux-core --example db_stress)
  uv run --group contract pytest contract-tests/db -q --no-cov
fi
if [[ "$area" == cutover-* ]]; then
  (cd server && cargo build -p evoflux-server && cargo build -p evoflux-gateway --bin evoflux-gateway-harness && cargo build -p evoflux-core --example db_stress)
  TARGET=gateway uv run --group contract pytest contract-tests -q --no-cov
elif [[ "$area" != shared ]]; then
  diff=$(mktemp)
  trap 'cleanup; rm -f "$diff"' EXIT
  git diff "$diff_range" > "$diff"
  (cd server && cargo mutants --in-diff "$diff" --package "evoflux-area-$area")
  # The lane's routes come from its server/MIGRATION_BOARD.md row.
  if [[ ! -f scripts/migration/openapi_diff.py ]]; then
    echo "error: scripts/migration/openapi_diff.py is missing (contract harness, PR 45)" >&2
    exit 1
  fi
  python scripts/migration/openapi_diff.py "$area" \
    --candidate "${OPENAPI_CANDIDATE:?set OPENAPI_CANDIDATE to the lane Rust openapi.json (file or URL)}"
fi
