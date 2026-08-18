from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChangeSetFileProposal(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    proposed_content: str = Field(max_length=2_000_000)
    base_hash: str | None = Field(default=None, min_length=64, max_length=64)
    document_version: int | None = Field(default=None, ge=0)


class ChangeSetCreateRequest(BaseModel):
    origin: Literal["lsp", "ai", "agent", "review", "git"]
    title: str = Field(min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=4000)
    files: list[ChangeSetFileProposal] = Field(default_factory=list, max_length=100)
    workspace_edit: dict | None = None
    verification_commands: list[str] = Field(default_factory=list, max_length=10)


class ChangeSetSelectionRequest(BaseModel):
    paths: list[str] | None = Field(default=None, max_length=100)
    session_id: str | None = Field(default=None, max_length=128)
    verify: bool = True


class ChangeSetFileResponse(BaseModel):
    path: str
    base_hash: str | None
    proposed_hash: str
    document_version: int | None
    diff: str
    additions: int
    deletions: int
    status: Literal["pending", "applied", "rejected"]


class ChangeSetResponse(BaseModel):
    id: str
    workspace: str
    origin: Literal["lsp", "ai", "agent", "review", "git"]
    title: str
    description: str | None
    status: Literal["pending", "applied", "rejected", "partial"]
    snapshot_hash: str | None
    verification_commands: list[str] = Field(default_factory=list)
    verification: list[dict] = Field(default_factory=list)
    created_at: float
    updated_at: float
    files: list[ChangeSetFileResponse]
