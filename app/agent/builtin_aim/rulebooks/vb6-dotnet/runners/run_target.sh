#!/usr/bin/env bash
# Runs a migration unit's target (.NET) implementation and writes its
# canonical-ready output for aim_compare. Customize per project.
#
# Arg contract (identical for run_legacy and run_target):
#   $1 UNIT      module / unit name
#   $2 CASE_SET  which cases to run, e.g. smoke | full
#   $3 OUT_DIR   absolute directory this script must write its output into
set -euo pipefail

UNIT="${1:-}"
CASE_SET="${2:-smoke}"   # smoke | full
OUT_DIR="${3:-}"         # absolute dir to write canonical-ready output into

echo "run_target stub — received: UNIT='$UNIT' CASE_SET='$CASE_SET' OUT_DIR='$OUT_DIR'" >&2
echo "Contract: \$1=UNIT  \$2=CASE_SET (smoke|full)  \$3=OUT_DIR (absolute output dir)" >&2
echo "TODO: build (dotnet build) and run the target (.NET) for unit '$UNIT', case set '$CASE_SET'" >&2
echo "TODO: for screen units, drive the scenario via browser automation and compare task-completion state, not pixels" >&2
echo "TODO: write its output into '$OUT_DIR' for aim_compare to read" >&2
exit 1
