"""The in-memory record of one discovered Skill."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.agent.skills.spec import SkillDiagnostic


SkillSource = Literal["project", "user", "plugin", "builtin"]


@dataclass
class Skill:
    """Level-1 metadata plus the location the model reads for Level 2.

    The body is deliberately not stored: activation reads ``location`` from
    disk, so an edited Skill is picked up without re-discovery.
    """

    name: str
    description: str
    location: Path
    root: Path
    source: SkillSource
    plugin_id: str | None = None
    license: str | None = None
    compatibility: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    allowed_tools: str | None = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    enabled: bool = True
    editable: bool = False
    symlinked: bool = False
    diagnostics: list[SkillDiagnostic] = field(default_factory=list)
    shadowed: list[Path] = field(default_factory=list)

    @property
    def directory(self) -> Path:
        return self.location.parent

    @property
    def valid(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    @property
    def model_visible(self) -> bool:
        """Listed in the model's ``<available_skills>`` catalog."""

        return self.valid and self.enabled and not self.disable_model_invocation

    @property
    def user_visible(self) -> bool:
        """Offered in the ``$`` picker and activated by ``$name``."""

        return self.valid and self.enabled and self.user_invocable


__all__ = ["Skill", "SkillSource"]
