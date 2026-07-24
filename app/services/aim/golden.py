"""Validation for AIM golden-master case metadata."""

from __future__ import annotations

from pathlib import Path

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
