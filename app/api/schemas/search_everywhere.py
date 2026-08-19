from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SearchEverywhereRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=50, ge=1, le=100)


class SearchEverywhereItemResponse(BaseModel):
    id: str
    kind: Literal[
        "file",
        "folder",
        "symbol",
        "code",
        "git_branch",
        "git_commit",
        "problem",
        "skill",
        "workflow",
    ]
    label: str
    description: str
    path: str | None = None
    line: int | None = None
    metadata: dict | None = None


class SearchEverywhereResponse(BaseModel):
    items: list[SearchEverywhereItemResponse]
