from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LanguageServerStatusRequest(BaseModel):
    workspaces: list[str] = Field(default_factory=list, max_length=32)


class DetectedRepositoryResponse(BaseModel):
    workspace: str
    name: str
    file_count: int


class LanguageServerStatusResponse(BaseModel):
    language_id: str
    display_name: str
    extensions: list[str]
    detected: bool
    file_count: int
    repositories: list[DetectedRepositoryResponse]
    state: Literal["ready", "missing", "update_available"]
    source: Literal["managed", "system", "missing"]
    command: str | None
    installed_version: str | None
    expected_version: str | None
    installable: bool
    installer: Literal["npm", "uv"] | None
    installer_available: bool
    install_hint: str


class LanguageServerOverviewResponse(BaseModel):
    workspaces: list[str]
    cache_dir: str
    servers: list[LanguageServerStatusResponse]
