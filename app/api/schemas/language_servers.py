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
    installer: Literal["npm", "uv", "go", "rustup", "gem", "dotnet"] | None
    installer_available: bool
    install_hint: str
    blocked_reason: str | None
    install_phase: Literal["idle", "running", "failed"]
    install_started_at: str | None
    install_error: str | None


class LanguageServerOverviewResponse(BaseModel):
    workspaces: list[str]
    cache_dir: str
    servers: list[LanguageServerStatusResponse]
    scan_truncated: bool
    scan_limit: int


class LanguageServerInstallResponse(BaseModel):
    """State of the install that was just started, not its outcome."""

    language_id: str
    phase: Literal["idle", "running", "failed"]
    started_at: str
    finished_at: str | None
    error: str | None
