"""Parity of the read-only agent tools (unit ``agent-runtime``, lane ``tools``).

Not an HTTP contract: the tools have no route. ``TARGET=python`` runs the real
Python tools on the fixture workspaces and checks them against the recorded
golden file (``--snapshot-update`` re-records it); ``TARGET=rust`` runs the Rust
crate's ``run_cases`` example on the same workspaces and must match that file.

Cases that need workspace links (symlink or junction) are skipped where the
platform will not create one; the skip is printed, not silent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cases as cases_module  # noqa: E402
import runner  # noqa: E402


@pytest.fixture
def rust_units() -> list[str]:
    return []


@pytest.fixture(scope="module")
def data() -> dict:
    return runner.load_cases()


def test_cases_json_is_current(data: dict) -> None:
    built = json.loads(json.dumps(cases_module.build(), ensure_ascii=False))
    assert data == built, "run: uv run python contract-tests/tools/cases.py"


def test_case_ids_are_unique(data: dict) -> None:
    ids = [c["id"] for c in data["cases"]]
    assert len(ids) == len(set(ids))


def test_tools_match_golden(
    data: dict, target, request, tmp_path: Path, capsys
) -> None:
    driver = runner.rust_driver if target == "rust" else runner.python_driver
    results, skipped = runner.run_all(data, driver, tmp_path)
    if skipped:
        with capsys.disabled():
            print(
                f"\nSKIPPED (no workspace links on this platform): {len(skipped)} cases"
            )
    golden_path = runner.PARITY / "golden.json"
    if request.config.getoption("--snapshot-update"):
        assert target == "python", "--snapshot-update records from TARGET=python only"
        # Re-record the cases that ran; keep the rest (platform-specific ones).
        recorded = (
            json.loads(golden_path.read_text(encoding="utf-8"))
            if golden_path.exists()
            else {}
        )
        merged = {**recorded, **results}
        golden_path.write_text(
            json.dumps(
                {k: merged[k] for k in sorted(merged)}, indent=1, ensure_ascii=False
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    mismatches = {
        case_id: {"golden": golden.get(case_id), target: got}
        for case_id, got in results.items()
        if golden.get(case_id) != got
    }
    assert not mismatches, json.dumps(mismatches, indent=1, ensure_ascii=False)[:6000]


def test_specs_match_python(target) -> None:
    snapshot_path = (
        Path(__file__).resolve().parents[2]
        / "server/crates/area-tools/tests/snapshots/specs.json"
    )
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if target == "python":
        from app.agent.tools.builtin.date import get_date
        from app.agent.tools.builtin.filesystem.glob import glob_files
        from app.agent.tools.builtin.filesystem.grep import grep_files
        from app.agent.tools.builtin.filesystem.ls import list_directory
        from app.agent.tools.builtin.filesystem.read import read_file

        live = {
            t.name: t.definition
            for t in (read_file, list_directory, glob_files, grep_files, get_date)
        }
        assert live == expected
    else:
        pytest.skip(
            "the Rust side checks specs.json in `cargo nextest` (tests/specs.rs)"
        )
