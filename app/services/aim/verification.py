"""Deterministic target-build verification for AIM conversion attempts."""

from __future__ import annotations

import asyncio
import hashlib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid7

import yaml

from app.services.aim import kb_store

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


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_digest(path: Path) -> str:
    if path.is_file():
        return _file_digest(path)
    if not path.is_dir():
        raise VerificationError(f"target artifact is not a file or directory: {path}")
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_file_digest(child).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def has_conversion_evidence(
    kb_root: Path,
    unit: str,
    execution_id: str,
    *,
    target_root: Path | None = None,
) -> bool:
    path = conversion_evidence_path(kb_root, unit, execution_id)
    if not path.is_file():
        return False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return False
    structurally_valid = (
        data.get("unit") == unit
        and data.get("workflow_execution_id") == execution_id
        and data.get("status") == "pass"
    )
    if not structurally_valid:
        return False
    if target_root is None:
        return True
    try:
        command_path = resolve_verification_command(kb_root, unit)
        if data.get("verification_command_sha256") != _file_digest(command_path):
            return False
        module, name = unit.split("/", 1)
        unit_result = kb_store.read_unit(kb_root, module, name)
        if unit_result is None:
            return False
        recorded_hashes = data.get("target_path_sha256")
        if not isinstance(recorded_hashes, dict):
            return False
        current_hashes: dict[str, str] = {}
        target_root_resolved = target_root.resolve()
        for declared_path in unit_result[0].target_paths:
            resolved = (target_root_resolved / declared_path).resolve()
            if not resolved.is_relative_to(target_root_resolved) or not resolved.exists():
                return False
            current_hashes[declared_path] = _path_digest(resolved)
        return current_hashes == recorded_hashes
    except (OSError, VerificationError, ValueError):
        return False


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
    module, name = unit.split("/", 1)
    unit_result = kb_store.read_unit(kb_root, module, name)
    if unit_result is None:
        raise VerificationError(f"unit {unit} is missing from the KB")
    target_paths = unit_result[0].target_paths
    if not target_paths:
        raise VerificationError(f"unit {unit} records no target_paths")
    target_root_resolved = target_root.resolve()
    resolved_target_paths: dict[str, Path] = {}
    for declared_path in target_paths:
        relative = Path(declared_path)
        if relative.is_absolute():
            raise VerificationError(
                f"unit {unit} target path must be relative: {declared_path!r}"
            )
        resolved = (target_root_resolved / relative).resolve()
        if not resolved.is_relative_to(target_root_resolved):
            raise VerificationError(
                f"unit {unit} target path escapes target repository: {declared_path!r}"
            )
        if not resolved.exists():
            raise VerificationError(
                f"unit {unit} target path does not exist: {declared_path!r}"
            )
        resolved_target_paths[declared_path] = resolved
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
    status_result = await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", str(target_root), "status", "--porcelain=v1"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    target_status = (
        [line for line in status_result.stdout.splitlines() if line.strip()]
        if status_result.returncode == 0
        else []
    )
    target_path_hashes = {
        declared_path: _path_digest(path)
        for declared_path, path in resolved_target_paths.items()
    }

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
                "verification_command_sha256": _file_digest(command_path),
                "target_revision": revision,
                "target_dirty": bool(target_status),
                "target_status": target_status,
                "target_path_sha256": target_path_hashes,
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
