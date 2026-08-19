"""Response/request models for /team endpoints.

Covers: history, workspace files, todos, and permission requests.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.api.schemas.sessions import MessageResponse, SessionDetailResponse


# ── History ──────────────────────────────────────────────────────────────────


class TeamHistoryMember(BaseModel):
    name: str
    session_id: str
    messages: list[MessageResponse]


class GoalResponse(BaseModel):
    session_id: UUID
    objective: str
    status: Literal["active", "paused", "complete", "blocked"]
    token_budget: int | None = None
    tokens_used: int
    time_used_seconds: float
    pause_reason: str | None = None
    blocker_streak: int
    status_details: dict | None = None
    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class TeamHistoryResponse(BaseModel):
    lead: SessionDetailResponse
    members: list[TeamHistoryMember]
    goal: GoalResponse | None = None
    # Live workflow execution snapshot from the runner's in-memory state —
    # gone after restart, consistent with the no-durability posture (plan
    # v5 §6.5).
    workflow_execution: dict[str, object] | None = None
    has_more: bool = False
    next_cursor: str | None = None


# ── Workspace files ──────────────────────────────────────────────────────────


class WorkspaceFileInfo(BaseModel):
    """One file in the agent workspace."""

    path: str  # Relative, POSIX-separated (e.g. "output/chart.png")
    name: str  # Basename (e.g. "chart.png")
    size: int  # Bytes
    mtime: float  # Seconds since epoch
    mime: str  # Guessed MIME type


class WorkspaceFilesResponse(BaseModel):
    """Flat recursive listing of a session's agent workspace."""

    session_id: str
    files: list[WorkspaceFileInfo]
    truncated: bool = False  # True when the walk hit the max-files cap
    workspace_root: str | None = (
        None  # Absolute OS path to the workspace root (None for empty/new sessions)
    )


class WorkspaceRootResponse(BaseModel):
    """Resolved workspace root without an accompanying directory scan."""

    session_id: str
    workspace_root: str


class CodingWorkspaceFilesResponse(BaseModel):
    """Flat recursive listing of a coding workspace."""

    workspace: str
    files: list[WorkspaceFileInfo]
    truncated: bool = False


class CodingDiagnosticsRequest(BaseModel):
    """Current editor buffer sent to the coding LSP."""

    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=2_000_000)


class CodingDiagnosticsResponse(BaseModel):
    """LSP diagnostics for one coding-editor buffer."""

    workspace: str
    path: str
    language: str | None = None
    status: Literal["ready", "unavailable", "unsupported"]
    diagnostics: list[dict] = Field(default_factory=list)
    message: str | None = None


CodingSemanticAction = Literal[
    "hover",
    "code_actions",
    "rename",
    "format",
    "organize_imports",
    "document_symbols",
    "workspace_symbols",
]


class CodingSemanticRequest(BaseModel):
    """Repository-local semantic request from the coding editor."""

    action: CodingSemanticAction
    path: str = Field(min_length=1, max_length=4096)
    content: str | None = Field(default=None, max_length=2_000_000)
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    end_column: int | None = Field(default=None, ge=1)
    new_name: str | None = Field(default=None, min_length=1, max_length=512)
    query: str | None = Field(default=None, max_length=512)
    diagnostics: list[dict] = Field(default_factory=list, max_length=200)
    tab_size: int = Field(default=4, ge=1, le=16)
    insert_spaces: bool = True


class CodingSemanticResponse(BaseModel):
    """Semantic result; WorkspaceEdits are proposed and never applied here."""

    workspace: str
    path: str
    action: CodingSemanticAction
    language: str | None = None
    status: Literal["ready", "unavailable", "unsupported"]
    result: object | None = None
    capabilities: dict = Field(default_factory=dict)
    message: str | None = None


# ── Todos ────────────────────────────────────────────────────────────────────


class TodoItemResponse(BaseModel):
    task_id: str
    content: str
    status: str
    priority: str
    tier: str = "simple"
    dependencies: list[str] = Field(default_factory=list)
    assigned_to: str | None = None
    claimed_by: str | None = None


class TodosResponse(BaseModel):
    todos: list[TodoItemResponse]


# ── Permissions ──────────────────────────────────────────────────────────────


class PermissionReplyRequest(BaseModel):
    """Body for replying to a pending permission request."""

    reply: str = Field(description="'once', 'always', or 'reject'")
    message: str | None = Field(
        default=None, description="Optional feedback message when rejecting."
    )


class PermissionRequestResponse(BaseModel):
    """Serialised form of a pending PermissionRequest."""

    id: str
    session_id: str
    tool: str
    patterns: list[str]
    metadata: dict


# ── Plan mode ─────────────────────────────────────────────────────────────────


class PlanReplyRequest(BaseModel):
    """Body for replying to a pending plan-approval request."""

    request_id: str = Field(
        description="ID returned in the plan_approval_requested event."
    )
    decision: str = Field(description="'approved', 'rejected' or 'revise'")
    feedback: str | None = Field(
        default=None,
        description=(
            "Free-text notes returned to the agent — the requested changes "
            "for 'revise', or an optional reason for 'rejected'."
        ),
    )


# ── Ask user ─────────────────────────────────────────────────────────────────


class AskUserReplyRequest(BaseModel):
    """Body for replying to a pending ask_user question batch."""

    answers: list[str] = Field(
        description="One answer per question, in the same order as asked."
    )
