"""Format-neutral lifecycle types for Artifact Fabric.

Document content deliberately stays out of this module. Each driver owns its
native project schema; only lifecycle, QA, provenance, and byte publication are
shared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

ArtifactFormat = Literal["docx", "xlsx", "pptx", "pdf"]
ArtifactSeverity = Literal["error", "warning", "info"]


class ArtifactIssue(BaseModel):
    model_config = ConfigDict(extra="allow")

    severity: ArtifactSeverity
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1)
    location: dict[str, Any] | None = None
    details: dict[str, Any] = Field(default_factory=dict)


def normalize_issues(values: list[Any]) -> list[ArtifactIssue]:
    """Normalize driver issue shapes without discarding evidence."""

    normalized: list[ArtifactIssue] = []
    for index, value in enumerate(values):
        if isinstance(value, ArtifactIssue):
            normalized.append(value)
            continue
        if hasattr(value, "to_dict"):
            value = value.to_dict()
        if not isinstance(value, dict):
            value = {
                "severity": "error",
                "code": "invalid-driver-issue",
                "message": str(value),
            }
        severity = str(value.get("severity", "error")).lower()
        if severity not in {"error", "warning", "info"}:
            severity = "error"
        message = value.get("message") or value.get("detail") or str(value)
        code = value.get("code") or f"driver-issue-{index + 1}"
        location = value.get("location")
        if location is None:
            location_keys = ("page", "slide", "sheet", "cell", "targetId", "element")
            compact = {key: value[key] for key in location_keys if key in value}
            location = compact or None
        normalized.append(
            ArtifactIssue(
                severity=cast(ArtifactSeverity, severity),
                code=str(code),
                message=str(message),
                location=location if isinstance(location, dict) else None,
                details={
                    key: item
                    for key, item in value.items()
                    if key not in {"severity", "code", "message", "location"}
                },
            )
        )
    return normalized


@dataclass(frozen=True, slots=True)
class ArtifactDriverContext:
    workspace_root: Path
    work_dir: Path
    project_path: Path | None = None
    source_path: Path | None = None
    manifest_path: Path | None = None
    session_id: str | None = None


@dataclass(slots=True)
class ArtifactDriverResult:
    candidate_path: Path | None = None
    previews: list[Path] = field(default_factory=list)
    issues: list[ArtifactIssue] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "candidate_path": str(self.candidate_path) if self.candidate_path else None,
            "previews": [str(path) for path in self.previews],
            "issues": [issue.model_dump(exclude_none=True) for issue in self.issues],
            "manifest": self.manifest,
            "metadata": self.metadata,
            "provenance": self.provenance,
        }


__all__ = [
    "ArtifactDriverContext",
    "ArtifactDriverResult",
    "ArtifactFormat",
    "ArtifactIssue",
    "ArtifactSeverity",
    "normalize_issues",
]
