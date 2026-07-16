#!/usr/bin/env bash
# Runs a migration unit's target (Java 21) implementation against a golden
# case's input and captures output for aim_compare. Customize per project.
set -euo pipefail

UNIT="$1"
CASE_SET="${2:-smoke}"   # smoke | full

echo "TODO: build (e.g. ./gradlew build or mvn -q package) and run the target for unit '$UNIT', case set '$CASE_SET'" >&2
echo "TODO: write actual output under .aim-actuals/ for aim_compare to read" >&2
exit 1
