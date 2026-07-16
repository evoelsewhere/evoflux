#!/usr/bin/env bash
# Runs a migration unit's legacy (Java 8/11) implementation against a golden
# case's input and captures output for aim_compare. Customize per project —
# this is a starting template, not a working script for any specific estate.
set -euo pipefail

UNIT="$1"
CASE_DIR="$2"   # golden/units/<unit>/cases/<case-id>

echo "TODO: build and run the legacy jar/service for unit '$UNIT'" >&2
echo "TODO: feed $CASE_DIR/input/ to it and capture output next to $CASE_DIR/expected/ layout" >&2
exit 1
