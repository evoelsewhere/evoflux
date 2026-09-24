from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DocumentVersionResponse(BaseModel):
    id: str
    size: int
    created_at: float
    label: str
    source: str


class DocumentHistoryResponse(BaseModel):
    path: str
    head: str | None
    can_undo: bool
    can_redo: bool
    versions: list[DocumentVersionResponse]


class DocumentVersionActionRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    action: Literal["checkpoint", "restore", "undo", "redo"]
    version_id: str | None = Field(default=None, max_length=64)
    label: str = Field(default="", max_length=2000)
