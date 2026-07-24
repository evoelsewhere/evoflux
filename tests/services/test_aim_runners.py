from pathlib import Path

import pytest

from app.services.aim import kb_store
from app.services.aim.runners import (
    RunnerExecutionError,
    execute_target_case,
    resolve_target_runner,
)

TARGET_RUNNER = """#!/usr/bin/env bash
set -euo pipefail
command_file="$AIM_CASE_DIR/target.command"
[[ -f "$command_file" ]] || { echo "missing target command: $command_file" >&2; exit 3; }
cd "$AIM_TARGET_ROOT"
bash "$command_file"
"""


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "java-pilot"
    (root / "aim_source_base").mkdir(parents=True)
    (root / "aim_target_source").mkdir()
    kb_root = root / "aim_java-pilot_document"
    kb_root.mkdir()
    kb_store.create_manifest(
        kb_root,
        rulebook_id="java8-java21",
        rulebook_version="0.1",
        source_identities=["source"],
        target_identities=["target"],
    )
    runners = kb_root / "rulebook" / "runners"
    runners.mkdir(parents=True)
    (kb_root / "rulebook" / "rulebook.yaml").write_text(
        "id: java8-java21\n"
        "version: '0.1'\n"
        "runners:\n"
        "  target: runners/run_target.sh\n",
        encoding="utf-8",
    )
    (runners / "run_target.sh").write_text(TARGET_RUNNER, encoding="utf-8")
    return root, kb_root


@pytest.mark.asyncio
async def test_execute_target_case_produces_fresh_actuals(tmp_path: Path):
    _root, kb_root = _project(tmp_path)
    case_dir = kb_root / "golden" / "units" / "core" / "Pay" / "cases" / "smoke"
    case_dir.mkdir(parents=True)
    (case_dir / "target.command").write_text(
        'printf "fresh\\n" > "$AIM_OUT_DIR/out.txt"\n', encoding="utf-8"
    )
    actual_dir = kb_root / ".aim-actuals" / "core" / "Pay" / "smoke"
    actual_dir.mkdir(parents=True)
    (actual_dir / "out.txt").write_text("stale\n")

    result = await execute_target_case(kb_root, "core/Pay", "smoke")

    assert result.actual_dir == actual_dir
    assert (actual_dir / "out.txt").read_text() == "fresh\n"


@pytest.mark.asyncio
async def test_execute_target_case_fails_without_case_command(tmp_path: Path):
    _root, kb_root = _project(tmp_path)
    case_dir = kb_root / "golden" / "units" / "core" / "Pay" / "cases" / "smoke"
    case_dir.mkdir(parents=True)

    with pytest.raises(RunnerExecutionError, match="missing target command"):
        await execute_target_case(kb_root, "core/Pay", "smoke")


def test_target_runner_must_stay_inside_local_rulebook(tmp_path: Path):
    _root, kb_root = _project(tmp_path)
    outside = kb_root / "outside.sh"
    outside.write_text(TARGET_RUNNER, encoding="utf-8")
    (kb_root / "rulebook" / "rulebook.yaml").write_text(
        "id: java8-java21\n"
        "version: '0.1'\n"
        "runners:\n"
        "  target: ../outside.sh\n",
        encoding="utf-8",
    )

    with pytest.raises(RunnerExecutionError, match="escapes rulebook directory"):
        resolve_target_runner(kb_root)
