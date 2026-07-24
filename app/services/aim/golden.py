"""Validation for AIM golden-master case metadata."""

from __future__ import annotations

import hashlib
from pathlib import Path
from datetime import datetime, timezone

import yaml
from pydantic import ValidationError

from app.services.aim.models import GoldenCaseMeta


class GoldenCaseError(ValueError):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def load_golden_case_meta(case_dir: Path) -> GoldenCaseMeta:
    """Load and validate a case set's required ``meta.yaml``."""
    path = case_dir / "meta.yaml"
    if not path.is_file():
        raise GoldenCaseError(
            "missing_golden_metadata", f"No golden metadata at {path}"
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise GoldenCaseError(
            "invalid_golden_metadata", f"Invalid golden metadata at {path}: {exc}"
        ) from exc
    if not isinstance(data, dict) or not data:
        raise GoldenCaseError(
            "missing_golden_metadata", f"Golden metadata at {path} is empty"
        )
    try:
        return GoldenCaseMeta.model_validate(data)
    except ValidationError as exc:
        kind = (
            "untrusted_golden"
            if data.get("provenance") == "synthesized" and not data.get("sme_sign_off")
            else "invalid_golden_metadata"
        )
        raise GoldenCaseError(
            kind, f"Invalid golden metadata at {path}: {exc}"
        ) from exc


def expected_output_manifest(expected_dir: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    if not expected_dir.is_dir():
        return manifest
    for path in sorted(item for item in expected_dir.rglob("*") if item.is_file()):
        manifest[path.relative_to(expected_dir).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return manifest


def _command_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp_expected_integrity(case_dir: Path) -> GoldenCaseMeta:
    meta = load_golden_case_meta(case_dir)
    manifest = expected_output_manifest(case_dir / "expected")
    if not manifest:
        raise GoldenCaseError(
            "missing_golden_case", f"Golden expected output is empty at {case_dir}"
        )
    path = case_dir / "meta.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data["expected_sha256"] = manifest
    for role in ("legacy", "target"):
        command_path = case_dir / f"{role}.command"
        if not command_path.is_file():
            raise GoldenCaseError(
                "missing_golden_command", f"Missing {role}.command at {case_dir}"
            )
        data[f"{role}_command_sha256"] = _command_digest(command_path)
    data["captured_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return load_golden_case_meta(case_dir)


def validate_expected_integrity(
    case_dir: Path, meta: GoldenCaseMeta | None = None
) -> None:
    profile = meta or load_golden_case_meta(case_dir)
    if not profile.expected_sha256:
        raise GoldenCaseError(
            "missing_golden_integrity",
            f"Golden metadata at {case_dir / 'meta.yaml'} has no expected_sha256",
        )
    current = expected_output_manifest(case_dir / "expected")
    if current != profile.expected_sha256:
        raise GoldenCaseError(
            "stale_golden_integrity",
            f"Golden expected output changed after capture at {case_dir / 'expected'}",
        )
    for role in ("legacy", "target"):
        command_path = case_dir / f"{role}.command"
        recorded = getattr(profile, f"{role}_command_sha256")
        if not command_path.is_file() or not recorded:
            raise GoldenCaseError(
                "missing_golden_command_integrity",
                f"Golden metadata has no valid {role}.command integrity",
            )
        if _command_digest(command_path) != recorded:
            raise GoldenCaseError(
                "stale_golden_command",
                f"{role}.command changed after golden capture at {command_path}",
            )
