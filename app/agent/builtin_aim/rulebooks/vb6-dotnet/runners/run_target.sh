#!/usr/bin/env bash
# Runs a migration unit's target (.NET) implementation against a golden
# case's input and captures output for aim_compare. Customize per project.
set -euo pipefail

UNIT="$1"
CASE_SET="${2:-smoke}"   # smoke | full

echo "TODO: build (dotnet build) and run the target for unit '$UNIT', case set '$CASE_SET'" >&2
echo "TODO: for screen units, drive the scenario via browser automation and compare task-completion state, not pixels" >&2
echo "TODO: write actual output under .aim-actuals/ for aim_compare to read" >&2
exit 1
