"""Same-attempt evidence for AIM understanding work."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid7

import yaml

from app.services.aim import kb_store


class UnderstandingEvidenceError(ValueError):
    pass


def _split_unit(unit: str) -> tuple[str, str]:
    if "/" not in unit:
        raise UnderstandingEvidenceError(f"invalid unit key: {unit!r}")
    return tuple(unit.split("/", 1))  # type: ignore[return-value]


def _body_digest(kb_root: Path, unit: str) -> str:
    module, name = _split_unit(unit)
    result = kb_store.read_unit(kb_root, module, name)
    if result is None:
        raise UnderstandingEvidenceError(f"unit {unit} is missing from the KB")
    return hashlib.sha256(result[1].encode("utf-8")).hexdigest()


def snapshot_understanding(kb_root: Path, units: list[str]) -> dict[str, str]:
    return {unit: _body_digest(kb_root, unit) for unit in units}


def understanding_evidence_path(kb_root: Path, unit: str, execution_id: str) -> Path:
    module, name = _split_unit(unit)
    return (
        kb_root
        / "state"
        / "evidence"
        / "understanding"
        / module
        / name
        / f"{execution_id}.yaml"
    )


def verify_understanding(
    kb_root: Path,
    units: list[str],
    baseline: dict[str, str],
    *,
    execution_id: str,
) -> list[Path]:
    try:
        UUID(execution_id)
    except ValueError as exc:
        raise UnderstandingEvidenceError("workflow execution id is not a UUID") from exc

    verified: list[tuple[str, str, str]] = []
    for unit in units:
        before = baseline.get(unit)
        if before is None:
            raise UnderstandingEvidenceError(f"baseline digest is missing for {unit}")
        module, name = _split_unit(unit)
        result = kb_store.read_unit(kb_root, module, name)
        if result is None:
            raise UnderstandingEvidenceError(f"unit {unit} is missing from the KB")
        body = result[1]
        if not body.strip():
            raise UnderstandingEvidenceError(f"unit {unit} documentation body is empty")
        after = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if after == before:
            raise UnderstandingEvidenceError(
                f"unit {unit} documentation did not change during this workflow"
            )
        verified.append((unit, before, after))

    paths: list[Path] = []
    created_at = datetime.now(timezone.utc).isoformat()
    for unit, before, after in verified:
        path = understanding_evidence_path(kb_root, unit, execution_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {
                    "id": str(uuid7()),
                    "kind": "understanding-verification",
                    "unit": unit,
                    "workflow_execution_id": execution_id,
                    "status": "pass",
                    "before_sha256": before,
                    "after_sha256": after,
                    "created_at": created_at,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def has_understanding_evidence(kb_root: Path, unit: str, execution_id: str) -> bool:
    path = understanding_evidence_path(kb_root, unit, execution_id)
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
        and data.get("before_sha256") != data.get("after_sha256")
    )
