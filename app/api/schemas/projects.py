"""Shared response schemas for CodingProject — used by both the /projects
CRUD routes and the merged /workspace/tree endpoint (see chat.py)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class ProjectWorkspaceItem(BaseModel):
    workspace_id: UUID
    path: str
    name: str | None
    display_name: str | None
    sort_order: int
    kind: str


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    settings: dict
    workspaces: list[ProjectWorkspaceItem]
    created_at: str
    updated_at: str
