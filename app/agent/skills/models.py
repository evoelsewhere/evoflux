"""Typed records shared by the skill registry and its consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


SkillDiagnosticSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class SkillDiagnostic:
    """One actionable validation or discovery diagnostic."""

    code: str
    message: str
    severity: SkillDiagnosticSeverity = "warning"

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class SkillRecord:
    """Canonical metadata for one selected skill implementation.

    ``body`` is intentionally absent. Discovery must stay at Tier 1; callers
    read ``skill_file`` only when the skill is activated.
    """

    name: str
    description: str
    skill_file: Path
    root: Path
    source: str
    modes: tuple[str, ...] = ("work", "coding", "aim")
    display_name: str | None = None
    short_description: str | None = None
    default_prompt: str | None = None
    icon_small: str | None = None
    icon_large: str | None = None
    brand_color: str | None = None
    allow_implicit_invocation: bool = True
    user_invocable: bool = True
    settings_id: str = ""
    settings_editable: bool = True
    settings_overridden: bool = False
    valid: bool = True
    editable: bool = False
    symlinked: bool = False
    resource_count: int = 0
    dependencies: tuple[dict, ...] = ()
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)
    shadowed_paths: list[str] = field(default_factory=list)
    alternates: list["SkillRecord"] = field(default_factory=list, repr=False)

    @property
    def skill_dir(self) -> Path:
        return self.skill_file.parent

    def add_diagnostic(
        self,
        code: str,
        message: str,
        *,
        severity: SkillDiagnosticSeverity = "warning",
    ) -> None:
        self.diagnostics.append(
            SkillDiagnostic(code=code, message=message, severity=severity)
        )
        if severity == "error":
            self.valid = False

    def as_legacy_dict(self) -> dict:
        """Return the dict shape used by existing APIs and tests."""

        try:
            relative_file = self.skill_file.relative_to(self.root).as_posix()
        except ValueError:
            relative_file = self.skill_file.name
        first_error = next(
            (item.message for item in self.diagnostics if item.severity == "error"),
            None,
        )
        return {
            "name": self.name,
            "description": self.description,
            "modes": list(self.modes),
            "file": relative_file,
            "dir": str(self.skill_dir),
            "root": str(self.root),
            "source": self.source,
            "display_name": self.display_name or self.name,
            "short_description": self.short_description or self.description,
            "default_prompt": self.default_prompt,
            "icon_small": self.icon_small,
            "icon_large": self.icon_large,
            "brand_color": self.brand_color,
            "allow_implicit_invocation": self.allow_implicit_invocation,
            "user_invocable": self.user_invocable,
            "settings_id": self.settings_id,
            "settings_editable": self.settings_editable,
            "settings_overridden": self.settings_overridden,
            "valid": self.valid,
            "error": first_error,
            "editable": self.editable,
            "symlinked": self.symlinked,
            "resource_count": self.resource_count,
            "dependencies": list(self.dependencies),
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "shadowed_paths": list(self.shadowed_paths),
        }
