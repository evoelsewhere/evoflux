import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASH = (
    Path("C:/Program Files/Git/bin/bash.exe")
    if os.name == "nt"
    else shutil.which("bash")
)


def dry_run(area):
    if not BASH or not Path(BASH).exists():
        pytest.skip("Git Bash is required for the migration gate script")
    return subprocess.run(
        [str(BASH), "scripts/migration/gates.sh", area],
        cwd=ROOT,
        env={**os.environ, "GATES_DRY_RUN": "1"},
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    ).stdout


def test_cutover_runs_contract_without_lane_steps():
    output = dry_run("cutover-edge-stateless")
    assert "check_paths cutover-edge-stateless" in output
    assert "contract-all gateway" in output
    assert "evoflux-area-cutover" not in output
    assert "mutants" not in output


def test_lane_runs_lane_specific_steps():
    output = dry_run("quote")
    assert "nextest evoflux-area-quote" in output
    assert "mutants" in output
