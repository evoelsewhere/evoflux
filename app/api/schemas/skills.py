"""Request and response schemas for ``/api/skills`` endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    valid: bool = True
    error: str | None = None
    built_in: bool = False
    editable: bool = True
    source: str = "global-EvoFlux"


class SkillDetail(BaseModel):
    name: str
    path: str
    content: str
    description: str = ""
    error: str | None = None
    built_in: bool = False
    editable: bool = True
    source: str = "global-EvoFlux"
    files: list[SkillBundleFile] = Field(default_factory=list)


class SkillWriteRequest(BaseModel):
    name: str = Field(description="Skill name (directory name).")
    content: str = Field(description="Full SKILL.md contents.")
    files: list[SkillBundleFileWrite] = Field(
        default_factory=list,
        max_length=100,
        description="Bundled resources to create or replace.",
    )
    deleted_files: list[str] = Field(
        default_factory=list,
        max_length=100,
        description="Bundled resource paths to remove on update.",
    )


class SkillListResponse(BaseModel):
    skills: list[SkillSummary]


class SkillDeleteResponse(BaseModel):
    name: str
