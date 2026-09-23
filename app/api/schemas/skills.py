"""Request and response schemas for ``/api/skills`` endpoints.

See ``documents/architecture/agent-skills.md``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.conductor.models import ManagedResourceProvider


SkillSourceName = Literal["project", "user", "plugin", "builtin"]


class SkillDiagnosticModel(BaseModel):
    code: str
    message: str
    severity: Literal["warning", "error"]


class SkillBundleFile(BaseModel):
    """A file bundled next to ``SKILL.md``."""

    path: str
    size: int = 0
    media_type: str = "application/octet-stream"
    content: str | None = None
    encoding: Literal["utf-8", "base64"] | None = None
    editable: bool = True


class SkillBundleFileWrite(BaseModel):
    """A bundled file to create or replace."""

    path: str
    content: str
    encoding: Literal["utf-8", "base64"] = "utf-8"


class SkillSummary(BaseModel):
    name: str
    description: str = ""
    #: Absolute path of ``SKILL.md`` — the ``location`` the model reads.
    location: str
    source: SkillSourceName
    #: Enabled plugin installation that contributes the Skill, if any.
    plugin_id: str | None = None
    enabled: bool = True
    #: False when ``disable-model-invocation: true`` hides it from the catalog.
    model_invocable: bool = True
    user_invocable: bool = True
    license: str | None = None
    compatibility: str | None = None
    allowed_tools: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    valid: bool = True
    diagnostics: list[SkillDiagnosticModel] = Field(default_factory=list)
    shadowed_paths: list[str] = Field(default_factory=list)
    editable: bool = False
    symlinked: bool = False
    resource_count: int = 0
    provider: ManagedResourceProvider | None = None


class SkillDetail(SkillSummary):
    content: str
    files: list[SkillBundleFile] = Field(default_factory=list)
    bundle_truncated: bool = False


class SkillCreateRequest(BaseModel):
    name: str = Field(description="Skill name; also the directory name.")
    content: str = Field(description="Full SKILL.md contents.")
    files: list[SkillBundleFileWrite] = Field(default_factory=list, max_length=200)


class SkillUpdateRequest(BaseModel):
    content: str = Field(description="Full SKILL.md contents.")
    files: list[SkillBundleFileWrite] = Field(default_factory=list, max_length=200)
    deleted_files: list[str] = Field(default_factory=list, max_length=200)


class SkillEnabledRequest(BaseModel):
    enabled: bool


class SkillListResponse(BaseModel):
    skills: list[SkillSummary]


class SkillDeleteResponse(BaseModel):
    name: str


__all__ = [
    "SkillBundleFile",
    "SkillBundleFileWrite",
    "SkillCreateRequest",
    "SkillDeleteResponse",
    "SkillDetail",
    "SkillDiagnosticModel",
    "SkillEnabledRequest",
    "SkillListResponse",
    "SkillSourceName",
    "SkillSummary",
    "SkillUpdateRequest",
]
