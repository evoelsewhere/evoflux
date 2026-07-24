"""Deterministic target-build verification for AIM conversion attempts."""

from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid7

import yaml

_UNIT_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


class VerificationError(RuntimeError):
    pass


def resolve_verification_command(kb_root: Path, unit: str) -> Path:
    if not _UNIT_RE.fullmatch(unit):
        raise VerificationError(f"invalid unit key: {unit!r}")
    module, name = unit.split("/", 1)
    candidates = (
        kb_root / "mapping" / module / f"{name}.verify.command",
        kb_root / "mapping" / module / name / "verify.command",
        kb_root / "mapping" / f"{module}-{name}.verify.command",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise VerificationError(
        "verification command is missing; expected one of: "
        + ", ".join(str(path.relative_to(kb_root)) for path in candidates)
    )


def conversion_evidence_path(kb_root: Path, unit: str, execution_id: str) -> Path:
    module, name = unit.split("/", 1)
    return (
        kb_root
        / "state"
        / "evidence"
        / "conversion"
        / module
        / name
        / f"{execution_id}.yaml"
    )


def has_conversion_evidence(kb_root: Path, unit: str, execution_id: str) -> bool:
    path = conversion_evidence_path(kb_root, unit, execution_id)
    if not path.is_file():
        return False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    return (
        data.get("unit") == unit
        and data.get("workflow_execution_id") == execution_id
        and data.get("status") == "pass"
    )


async def verify_target_conversion(
    kb_root: Path,
    target_root: Path,
    unit: str,
    *,
    execution_id: str,
    timeout_seconds: int = 1800,
) -> Path:
    try:
        UUID(execution_id)
    except ValueError as exc:
        raise VerificationError("workflow execution id is not a UUID") from exc
    if not target_root.is_dir():
        raise VerificationError(f"target repository is unavailable: {target_root}")
    command_path = resolve_verification_command(kb_root, unit)
    environment = {
        "AIM_UNIT": unit,
        "AIM_KB_ROOT": str(kb_root.resolve()),
        "AIM_TARGET_ROOT": str(target_root.resolve()),
        "AIM_WORKFLOW_EXECUTION_ID": execution_id,
    }
    shell_command = [
        "env",
        *[f"{key}={value}" for key, value in environment.items()],
        "bash",
        str(command_path.resolve()),
    ]
    try:
        completed = await asyncio.to_thread(
            subprocess.run,
            shell_command,
            cwd=target_root,
            capture_output=True,
            text=True,
            timeout=max(1, min(timeout_seconds, 4 * 3600)),
        )
    except subprocess.TimeoutExpired as exc:
        raise VerificationError(
            f"target verification timed out after {timeout_seconds}s"
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise VerificationError(
            f"target verification failed with exit code {completed.returncode}: "
            f"{detail[:4000]}"
        )
    revision = None
    git_result = await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", str(target_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if git_result.returncode == 0:
        revision = git_result.stdout.strip() or None

    evidence_id = str(uuid7())
    evidence_path = conversion_evidence_path(kb_root, unit, execution_id)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        yaml.safe_dump(
            {
                "id": evidence_id,
                "kind": "conversion-verification",
                "unit": unit,
                "workflow_execution_id": execution_id,
                "status": "pass",
                "command": str(command_path.relative_to(kb_root)),
                "target_revision": revision,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return evidence_path
