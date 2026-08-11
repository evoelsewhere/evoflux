"""Same-attempt evidence for AIM understanding work."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import yaml

from app.services.aim import kb_store
from app.uuid7 import uuid7


class UnderstandingEvidenceError(ValueError):
    pass


_MIN_DOCUMENT_CHARS = 600
_MIN_DOCUMENT_SECTIONS = 3


def _split_unit(unit: str) -> tuple[str, str]:
    if "/" not in unit:
        raise UnderstandingEvidenceError(f"invalid unit key: {unit!r}")
    module, name = unit.split("/", 1)
    return module, name


def _body_digest(kb_root: Path, unit: str) -> str:
    module, name = _split_unit(unit)
    result = kb_store.read_unit(kb_root, module, name)
    if result is None:
        raise UnderstandingEvidenceError(f"unit {unit} is missing from the KB")
    return hashlib.sha256(result[1].encode("utf-8")).hexdigest()


def _document_quality(body: str) -> dict[str, int | bool]:
    lines = body.splitlines()
    characters = len(body.strip())
    sections = sum(line.startswith("## ") for line in lines)
    return {
        "characters": characters,
        "lines": len(lines),
        "sections": sections,
        "substantive": (
            characters >= _MIN_DOCUMENT_CHARS and sections >= _MIN_DOCUMENT_SECTIONS
        ),
    }


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

    verified: list[tuple[str, str, str, str, dict[str, int | bool]]] = []
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
        quality = _document_quality(body)
        if not quality["substantive"]:
            raise UnderstandingEvidenceError(
                f"unit {unit} documentation is still a stub "
                f"({quality['characters']} chars, {quality['sections']} sections; "
                f"requires at least {_MIN_DOCUMENT_CHARS} chars and "
                f"{_MIN_DOCUMENT_SECTIONS} sections)"
            )
        after = hashlib.sha256(body.encode("utf-8")).hexdigest()
        change_kind = "updated" if after != before else "reviewed_unchanged"
        verified.append((unit, before, after, change_kind, quality))

    paths: list[Path] = []
    created_at = datetime.now(timezone.utc).isoformat()
    for unit, before, after, change_kind, quality in verified:
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
                    "change_kind": change_kind,
                    "before_sha256": before,
                    "after_sha256": after,
                    "quality": quality,
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
    if (
        data.get("unit") != unit
        or data.get("workflow_execution_id") != execution_id
        or data.get("status") != "pass"
    ):
        return False
    before = data.get("before_sha256")
    after = data.get("after_sha256")
    if not isinstance(before, str) or not isinstance(after, str):
        return False
    try:
        if _body_digest(kb_root, unit) != after:
            return False
    except UnderstandingEvidenceError:
        return False

    change_kind = data.get("change_kind")
    if change_kind is None:
        # Backward compatibility for evidence written before change_kind.
        return before != after
    quality = data.get("quality")
    if not isinstance(quality, dict) or quality.get("substantive") is not True:
        return False
    if change_kind == "updated":
        return before != after
    if change_kind == "reviewed_unchanged":
        return before == after
    return False
