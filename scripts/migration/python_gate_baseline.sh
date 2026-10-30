#!/usr/bin/env bash
# Python gates for migration PRs: fail only on failures that are new compared
# with the merge-base (server/AGENTS.md section 5.3). Pre-existing failures are
# reported. A gate that exits non-zero without yielding any failure identity
# (crash, timeout, collection error) counts as a new failure.
#
# Env: BASE_REF (default origin/migrate/rust-v4), GATES (default all four),
# PY_RUN (default "uv run"), PYTEST_ARGS (default "--no-cov -q").
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
base_ref="${BASE_REF:-origin/migrate/rust-v4}"
gates="${GATES:-ruff-check ruff-format ty pytest}"
py_run="${PY_RUN:-uv run}"
pytest_args="${PYTEST_ARGS:---no-cov -q}"
work=$(mktemp -d)
base_tree="$work/base"
cleanup() { git worktree remove --force "$base_tree" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT
git worktree add --detach "$base_tree" "$(git merge-base "$base_ref" HEAD)" >/dev/null

# run_gate <dir> <gate> <identity-file> <side>: prints exit code; writes sorted identities.
run_gate() {
  local dir=$1 gate=$2 ids=$3 log="$work/$gate.$4.log" code=0
  (
    cd "$dir"
    case "$gate" in
      ruff-check) $py_run ruff check app/ tests/ --output-format concise --no-cache ;;
      ruff-format) $py_run ruff format --check app/ tests/ --no-cache ;;
      ty) $py_run ty check app/ --output-format concise ;;
      pytest) $py_run pytest $pytest_args -rfE -p no:cacheprovider ;;
      *) echo "unknown gate $gate" >&2; exit 2 ;;
    esac
  ) >"$log" 2>&1 || code=$?
  case "$gate" in
    ruff-check|ty) grep -E '^[^ :]+:[0-9]+:[0-9]+: ' "$log" | sed -E 's/:[0-9]+:[0-9]+:/:/' ;;
    ruff-format) grep -E '^Would reformat: ' "$log" ;;
    pytest) grep -E '^(FAILED|ERROR) ' "$log" | sed -E 's/ - .*//' ;;
  esac | sort -u >"$ids" || true
  echo "$code"
}

status=0
for gate in $gates; do
  base_code=$(run_gate "$base_tree" "$gate" "$work/$gate.base" base)
  head_code=$(run_gate "$root" "$gate" "$work/$gate.head" head)
  new=$(comm -13 "$work/$gate.base" "$work/$gate.head")
  if [[ -n "$new" ]]; then
    echo "FAIL $gate: new failures compared with the base branch:" >&2
    echo "$new" >&2
    status=1
  elif [[ "$head_code" != 0 && ! -s "$work/$gate.head" ]]; then
    echo "FAIL $gate: exit $head_code with no recognised failures (incomplete run?); see $work/$gate.head.log" >&2
    cat "$work/$gate.head.log" >&2 || true
    status=1
  else
    old=$(wc -l <"$work/$gate.head" | tr -d ' ')
    echo "ok   $gate (base exit $base_code, head exit $head_code, $old pre-existing failure(s))"
  fi
done
exit "$status"
