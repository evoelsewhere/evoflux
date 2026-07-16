"""Response/request models for /team endpoints.

Covers: history, workspace files, todos, and permission requests.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.api.schemas.sessions import MessageResponse, SessionDetailResponse


# ── History ──────────────────────────────────────────────────────────────────


class TeamHistoryMember(BaseModel):
    name: str
    session_id: str
    messages: list[MessageResponse]


class TeamHistoryResponse(BaseModel):
    lead: SessionDetailResponse
    members: list[TeamHistoryMember]
    loop_status: dict[str, object] | None = None
    # Live workflow execution snapshot from the runner's in-memory state —
    # gone after restart, consistent with the no-durability posture (plan
    # v5 §6.5). Same live-state semantics as loop_status.
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


class CodingWorkspaceFilesResponse(BaseModel):
    """Flat recursive listing of a coding workspace."""

    workspace: str
    files: list[WorkspaceFileInfo]
    truncated: bool = False


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
