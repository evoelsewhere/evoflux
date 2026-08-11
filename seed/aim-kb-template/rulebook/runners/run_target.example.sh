#!/usr/bin/env bash
# Inactive example. Copy to run_target.sh and declare it in rulebook.yaml.
set -euo pipefail
: "${AIM_UNIT:?}"
: "${AIM_CASE_DIR:?}"
: "${AIM_OUT_DIR:?}"
echo "Implement the target adapter for $AIM_UNIT" >&2
exit 1