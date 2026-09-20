from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AppSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=40, ge=1, le=100)


class AppSearchItemResponse(BaseModel):
    id: str
    kind: Literal[
        "session",
        "message",
        "project",
        "workspace",
        "memory",
        "scheduled_task",
        "agent",
        "skill",
    ]
    label: str
    description: str
    session_id: str | None = None
    path: str | None = None
    metadata: dict | None = None


class AppSearchResponse(BaseModel):
    items: list[AppSearchItemResponse]
