"""Deterministic execution of rulebook case runners."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.services.aim import kb_store
from app.services.aim.rulebook import resolve_rulebook_path, validate_rulebook_identity

_UNIT_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
_CASE_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class RunnerExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunnerExecutionResult:
    unit: str
    case_set: str
    actual_dir: Path
    stdout: str
    stderr: str


def resolve_target_runner(kb_root: Path) -> Path:
    try:
        kb_store.read_manifest(kb_root)
    except (FileNotFoundError, ValueError) as exc:
        raise RunnerExecutionError(
            "AIM manifest is unavailable for runner resolution"
        ) from exc
    pack_manifest = validate_rulebook_identity(kb_root).model_dump()
    runners = pack_manifest.get("runners")
    if not isinstance(runners, dict) or not runners.get("target"):
        raise RunnerExecutionError("rulebook declares no target runner")
    try:
        path = resolve_rulebook_path(kb_root, str(runners["target"]))
    except ValueError as exc:
        raise RunnerExecutionError(str(exc)) from exc
    if not path.is_file():
        raise RunnerExecutionError(f"target runner is missing: {path}")
    content = path.read_text(encoding="utf-8", errors="replace").lower()
    if "run_target stub" in content or "todo:" in content:
        raise RunnerExecutionError(f"target runner is still a template: {path}")
    return path


async def execute_target_case(
    kb_root: Path,
    unit: str,
    case_set: str,
    *,
    timeout_seconds: int = 3600,
) -> RunnerExecutionResult:
    if not _UNIT_RE.fullmatch(unit):
        raise RunnerExecutionError(f"invalid unit key: {unit!r}")
    if not _CASE_RE.fullmatch(case_set):
        raise RunnerExecutionError(f"invalid case set: {case_set!r}")
    module, name = unit.split("/", 1)
    runner = resolve_target_runner(kb_root)
    actual_dir = kb_root / ".aim-actuals" / module / name / case_set
    if actual_dir.exists():
        shutil.rmtree(actual_dir)
    actual_dir.mkdir(parents=True)

    if runner.suffix.lower() == ".ps1":
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if executable is None:
            raise RunnerExecutionError("PowerShell is required by the target runner")
        command = [executable, "-File", str(runner)]
    else:
        command = ["bash", str(runner)]
    command.extend([unit, case_set, str(actual_dir.resolve())])
    case_dir = kb_root / "golden" / "units" / module / name / "cases" / case_set
    project_root = kb_root.parent
    environment = {
        **os.environ,
        "AIM_UNIT": unit,
        "AIM_CASE_SET": case_set,
        "AIM_CASE_DIR": str(case_dir.resolve()),
        "AIM_INPUT_DIR": str((case_dir / "input").resolve()),
        "AIM_OUT_DIR": str(actual_dir.resolve()),
        "AIM_KB_ROOT": str(kb_root.resolve()),
        "AIM_PROJECT_ROOT": str(project_root.resolve()),
        "AIM_SOURCE_BASE": str((project_root / "aim_source_base").resolve()),
        "AIM_TARGET_ROOT": str((project_root / "aim_target_source").resolve()),
    }

    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            command,
            capture_output=True,
            text=True,
            env=environment,
            timeout=max(1, min(timeout_seconds, 4 * 3600)),
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerExecutionError(
            f"target runner timed out after {timeout_seconds}s"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RunnerExecutionError(
            f"target runner failed with exit code {completed.returncode}: {detail[:4000]}"
        )
    if not any(path.is_file() for path in actual_dir.rglob("*")):
        raise RunnerExecutionError(
            f"target runner succeeded but produced no files in {actual_dir}"
        )
    return RunnerExecutionResult(
        unit=unit,
        case_set=case_set,
        actual_dir=actual_dir,
        stdout=completed.stdout[-4000:],
        stderr=completed.stderr[-4000:],
    )
