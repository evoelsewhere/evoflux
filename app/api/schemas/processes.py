"""Schemas for the unified process manager."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProcessResponse(BaseModel):
    id: str
    kind: Literal["command", "preview", "terminal"]
    label: str
    command: str
    session_id: str | None = None
    session_title: str | None = None
    pid: int | None = None
    cwd: str | None = None
    elapsed_seconds: float
    killable: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProcessListResponse(BaseModel):
    processes: list[ProcessResponse]
