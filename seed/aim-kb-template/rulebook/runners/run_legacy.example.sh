#!/usr/bin/env bash
# Inactive example. Copy to run_legacy.sh and declare it in rulebook.yaml.
set -euo pipefail
: "${AIM_UNIT:?}"
: "${AIM_CASE_DIR:?}"
: "${AIM_OUT_DIR:?}"
echo "Implement the legacy adapter for $AIM_UNIT" >&2
exit 1