"""Request and response schemas for ``/api/skills`` endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.skill_scope import ALL_SKILL_MODES, SkillMode, default_skill_modes


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
    display_name: str | None = None
    short_description: str | None = None
    default_prompt: str | None = None
    allow_implicit_invocation: bool = True
    user_invocable: bool = True
    settings_id: str = ""
    settings_editable: bool = True
    settings_overridden: bool = False
    resource_count: int = 0
    dependencies: list[dict] = Field(default_factory=list)
    symlinked: bool = False
    diagnostics: list[dict[str, str]] = Field(default_factory=list)
    shadowed_paths: list[str] = Field(default_factory=list)
    valid: bool = True
    error: str | None = None
    built_in: bool = False
    editable: bool = True
    source: str = "global-EvoFlux"
    modes: list[SkillMode] = Field(default_factory=default_skill_modes)


class SkillDetail(BaseModel):
    name: str
    path: str
    content: str
    description: str = ""
    display_name: str | None = None
    short_description: str | None = None
    default_prompt: str | None = None
    allow_implicit_invocation: bool = True
    user_invocable: bool = True
    settings_id: str = ""
    settings_editable: bool = True
    settings_overridden: bool = False
    resource_count: int = 0
    dependencies: list[dict] = Field(default_factory=list)
    symlinked: bool = False
    diagnostics: list[dict[str, str]] = Field(default_factory=list)
    shadowed_paths: list[str] = Field(default_factory=list)
    error: str | None = None
    built_in: bool = False
    editable: bool = True
    source: str = "global-EvoFlux"
    modes: list[SkillMode] = Field(default_factory=default_skill_modes)
    files: list[SkillBundleFile] = Field(default_factory=list)
    bundle_truncated: bool = False


class SkillWriteRequest(BaseModel):
    name: str = Field(description="Skill name (directory name).")
    content: str = Field(description="Full SKILL.md contents.")
    modes: list[SkillMode] = Field(
        default_factory=default_skill_modes,
        min_length=1,
        max_length=2,
        description="Application modes where the skill is available.",
    )
    files: list[SkillBundleFileWrite] = Field(
        default_factory=list,
        max_length=200,
        description="Bundled resources to create or replace.",
    )
    deleted_files: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="Bundled resource paths to remove on update.",
    )

    @field_validator("modes")
    @classmethod
    def canonicalize_modes(cls, value: list[SkillMode]) -> list[SkillMode]:
        if len(set(value)) != len(value):
            raise ValueError("Skill modes must not contain duplicates.")
        selected = set(value)
        return [mode for mode in ALL_SKILL_MODES if mode in selected]


class SkillUpdateRequest(BaseModel):
    """Mutable bundle fields; omitted modes preserve the source sidecar."""

    name: str = Field(description="Skill name (directory name).")
    content: str = Field(description="Full SKILL.md contents.")
    modes: list[SkillMode] | None = Field(
        default=None,
        min_length=1,
        max_length=2,
        description=(
            "Optional source mode scope. Omit for normal bundle edits so user "
            "runtime overrides are never baked into the bundle sidecar."
        ),
    )
    files: list[SkillBundleFileWrite] = Field(default_factory=list, max_length=200)
    deleted_files: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("modes")
    @classmethod
    def canonicalize_modes(
        cls, value: list[SkillMode] | None
    ) -> list[SkillMode] | None:
        if value is None:
            return None
        if len(set(value)) != len(value):
            raise ValueError("Skill modes must not contain duplicates.")
        selected = set(value)
        return [mode for mode in ALL_SKILL_MODES if mode in selected]


class SkillRuntimeSettingsRequest(BaseModel):
    """User-owned runtime switches for one exact discovered bundle variant."""

    settings_id: str = Field(
        min_length=38,
        max_length=38,
        pattern=r"^skill_[0-9a-f]{32}$",
    )
    modes: list[SkillMode] = Field(min_length=1, max_length=2)
    allow_implicit_invocation: bool
    user_invocable: bool

    @field_validator("modes")
    @classmethod
    def canonicalize_modes(cls, value: list[SkillMode]) -> list[SkillMode]:
        if len(set(value)) != len(value):
            raise ValueError("Skill modes must not contain duplicates.")
        selected = set(value)
        return [mode for mode in ALL_SKILL_MODES if mode in selected]


class SkillListResponse(BaseModel):
    skills: list[SkillSummary]


class SkillDeleteResponse(BaseModel):
    name: str
