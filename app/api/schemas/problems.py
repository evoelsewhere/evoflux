from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProblemResponse(BaseModel):
    id: str
    workspace: str
    source: Literal[
        "lsp", "static", "build", "test", "ai_review", "security", "plugin", "browser"
    ]
    scope: str
    message: str
    severity: Literal["error", "warning", "info", "hint"]
    path: str | None
    line: int | None
    column: int | None
    end_line: int | None
    end_column: int | None
    code: str | None
    title: str | None
    details: str | None
    fix: dict | None
    suppression_key: str
    #: How many rows suppressing this one would hide. Suppression is
    #: workspace-wide, so the button's reach is never just this row.
    suppression_count: int = 1
    provenance: dict = Field(default_factory=dict)
    session_id: str | None
    status: Literal["open", "dismissed", "suppressed"]
    created_at: float
    updated_at: float


class ProblemsResponse(BaseModel):
    problems: list[ProblemResponse]
    counts: dict[str, int]
