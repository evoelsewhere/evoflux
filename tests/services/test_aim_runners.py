import subprocess
from pathlib import Path

import pytest

from app.agent.tools.builtin.shell_runtime import BashNotFoundError
from app.services.aim import kb_store
from app.services.aim.golden import (
    GoldenCaseError,
    load_golden_case_meta,
    validate_expected_integrity,
)
from app.services.aim.runners import (
    RunnerExecutionError,
    capture_legacy_case,
    execute_legacy_case,
    execute_target_case,
    resolve_legacy_runner,
    resolve_target_runner,
)

TARGET_RUNNER = """#!/usr/bin/env bash
set -euo pipefail
command_file="$AIM_CASE_DIR/target.command"
[[ -f "$command_file" ]] || { echo "missing target command: $command_file" >&2; exit 3; }
cd "$AIM_TARGET_ROOT"
bash "$command_file"
"""

LEGACY_RUNNER = """#!/usr/bin/env bash
set -euo pipefail
command_file="$AIM_CASE_DIR/legacy.command"
[[ -f "$command_file" ]] || { echo "missing legacy command: $command_file" >&2; exit 3; }
cd "$AIM_SOURCE_BASE"
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
        "  legacy: runners/run_legacy.sh\n"
        "  target: runners/run_target.sh\n",
        encoding="utf-8",
    )
    (runners / "run_legacy.sh").write_text(LEGACY_RUNNER, encoding="utf-8")
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


@pytest.mark.asyncio
async def test_execute_legacy_case_uses_separate_staging_dir(tmp_path: Path):
    _root, kb_root = _project(tmp_path)
    case_dir = kb_root / "golden" / "units" / "core" / "Pay" / "cases" / "smoke"
    case_dir.mkdir(parents=True)
    (case_dir / "legacy.command").write_text(
        'printf "legacy\n" > "$AIM_OUT_DIR/out.txt"\n', encoding="utf-8"
    )

    result = await execute_legacy_case(kb_root, "core/Pay", "smoke")

    assert result.role == "legacy"
    assert result.actual_dir == kb_root / ".aim-legacy-actuals/core/Pay/smoke"
    assert (result.actual_dir / "out.txt").read_text() == "legacy\n"


@pytest.mark.asyncio
async def test_capture_legacy_case_promotes_validated_output(tmp_path: Path):
    _root, kb_root = _project(tmp_path)
    case_dir = kb_root / "golden" / "units" / "core" / "Pay" / "cases" / "smoke"
    case_dir.mkdir(parents=True)
    (case_dir / "meta.yaml").write_text(
        "provenance: captured\n"
        "canonicalizer_profile: default\n"
        "source_revision: test-source-revision\n"
        "environment_fingerprint: test-environment\n"
        "capture_command: test-capture\n"
    )
    (case_dir / "legacy.command").write_text(
        'printf "baseline\n" > "$AIM_OUT_DIR/out.txt"\n', encoding="utf-8"
    )
    (case_dir / "target.command").write_text("true\n", encoding="utf-8")

    await capture_legacy_case(kb_root, "core/Pay", "smoke")

    assert (case_dir / "expected/out.txt").read_text() == "baseline\n"
    captured = load_golden_case_meta(case_dir)
    assert captured.expected_sha256
    assert captured.captured_at is not None
    (case_dir / "target.command").write_text("changed\n")
    with pytest.raises(GoldenCaseError, match="target.command changed"):
        validate_expected_integrity(case_dir, captured)
    with pytest.raises(RunnerExecutionError, match="already exists"):
        await capture_legacy_case(kb_root, "core/Pay", "smoke")


@pytest.mark.asyncio
async def test_capture_rejects_dirty_or_mismatched_git_source(tmp_path: Path):
    root, kb_root = _project(tmp_path)
    source = root / "aim_source_base" / "legacy"
    source.mkdir()
    subprocess.run(["git", "-C", str(source), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(source), "config", "user.email", "audit@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "config", "user.name", "Audit"], check=True
    )
    (source / "source.txt").write_text("clean\n")
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "base"], check=True)
    revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    case_dir = kb_root / "golden/units/core/Pay/cases/smoke"
    case_dir.mkdir(parents=True)
    (case_dir / "legacy.command").write_text(
        'printf "baseline\\n" > "$AIM_OUT_DIR/out.txt"\n'
    )
    (case_dir / "meta.yaml").write_text(
        "provenance: captured\n"
        "canonicalizer_profile: default\n"
        "source_revision: wrong\n"
        "environment_fingerprint: test-environment\n"
        "capture_command: test-capture\n"
    )

    with pytest.raises(RunnerExecutionError, match="does not match"):
        await capture_legacy_case(kb_root, "core/Pay", "smoke")

    text = (case_dir / "meta.yaml").read_text().replace("wrong", revision)
    (case_dir / "meta.yaml").write_text(text)
    (source / "source.txt").write_text("dirty\n")
    with pytest.raises(RunnerExecutionError, match="repository is dirty"):
        await capture_legacy_case(kb_root, "core/Pay", "smoke")


def test_target_runner_must_stay_inside_local_rulebook(tmp_path: Path):
    _root, kb_root = _project(tmp_path)
    outside = kb_root / "outside.sh"
    outside.write_text(TARGET_RUNNER, encoding="utf-8")
    (kb_root / "rulebook" / "rulebook.yaml").write_text(
        "id: java8-java21\nversion: '0.1'\nrunners:\n  target: ../outside.sh\n",
        encoding="utf-8",
    )

    with pytest.raises(RunnerExecutionError, match="escapes rulebook directory"):
        resolve_target_runner(kb_root)


def test_legacy_runner_resolves_inside_local_rulebook(tmp_path: Path):
    _root, kb_root = _project(tmp_path)

    assert resolve_legacy_runner(kb_root) == kb_root / "rulebook/runners/run_legacy.sh"


@pytest.mark.asyncio
async def test_execute_target_case_requires_usable_bash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _root, kb_root = _project(tmp_path)
    case_dir = kb_root / "golden" / "units" / "core" / "Pay" / "cases" / "smoke"
    case_dir.mkdir(parents=True)
    (case_dir / "target.command").write_text("true\n", encoding="utf-8")

    def _no_bash() -> str:
        raise BashNotFoundError("No usable bash found for AIM runners/verification.")

    monkeypatch.setattr("app.services.aim.runners.require_bash", _no_bash)

    with pytest.raises(RunnerExecutionError, match="No usable bash"):
        await execute_target_case(kb_root, "core/Pay", "smoke")
