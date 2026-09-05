"""Response models for chat sessions and their messages."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.api.schemas.base import _ExcludeNoneModel
from app.api.schemas.projects import ProjectResponse
from app.models.chat import normalize_mode
from app.webbridge_tags import WEBBRIDGE_BROWSER_ORIGIN_TAG


class SessionCreate(BaseModel):
    title: str | None = None
    agent_name: str | None = None


class TeamSessionResolveRequest(BaseModel):
    mode: str = "work"
    agent_name: str | None = Field(default=None, min_length=1, max_length=100)
    workspace: str | None = None
    project_id: UUID | None = None
    # Sidebar folder the resolved/created session is filed under. Also scopes
    # the reuse lookup, so "new chat in this folder" cannot hand back a
    # session that lives outside it.
    folder_id: UUID | None = None
    model: str | None = None
    thinking_level: str | None = None
    create: bool = False
    # Look, but do not bring into being. The client opens a chat as a draft
    # and lets the first message create it, so a focus/restore asks only
    # whether there is already a session worth reopening; ``null`` means
    # "nothing here yet", not an error. Mutually exclusive with ``create``.
    existing_only: bool = False
    worktree_from: str | None = None
    worktree_name: str | None = None
    worktree_branch: str | None = None
    # Session tags (e.g. ["webbridge"]) — matched by tag-SET equality: a
    # resolve only reuses an existing session whose stored tag set equals
    # this set, so an untagged resolve never returns a tagged session and
    # vice versa. Persisted on the session when ``create`` (or no match)
    # yields a new row.
    tags: list[str] = []
    # Exact set matching remains the default for capability-scoped sessions.
    # Feature contexts such as a code review can request "contains" so the
    # same session is reused even after another capability tag is added.
    tag_match: Literal["exact", "contains"] = "exact"

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        return normalize_mode(value) if isinstance(value, str) else value

    @field_validator("tags")
    @classmethod
    def _reject_reserved_tags(cls, value: list[str]) -> list[str]:
        reserved_prefixes = (
            WEBBRIDGE_BROWSER_ORIGIN_TAG.partition(":")[0] + ":",
            "webbridge_pairing:",
        )
        if any(tag.startswith(prefix) for tag in value for prefix in reserved_prefixes):
            raise ValueError("WebBridge provenance and pairing tags are server-managed")
        return value


class TeamSessionUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class TeamSessionLeadUpdateRequest(BaseModel):
    lead_name: str = Field(min_length=1, max_length=100)


class TeamLeadMemberResponse(BaseModel):
    name: str
    description: str | None = None
    model: str | None = None


class TeamLeadResponse(BaseModel):
    name: str
    description: str | None = None
    model: str | None = None
    is_default: bool = False
    members: list[TeamLeadMemberResponse] = Field(default_factory=list)


class TeamLeadListResponse(BaseModel):
    mode: Literal["work", "coding"]
    default_lead: str
    leads: list[TeamLeadResponse]


class SessionFolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    mode: str = "work"
    share_context: bool = True

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        return normalize_mode(value) if isinstance(value, str) else value


class SessionFolderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    share_context: bool | None = None
    sort_order: int | None = None


class SessionFolderAssignRequest(BaseModel):
    """Body of ``PATCH /team/sessions/{id}/folder``; ``None`` un-files."""

    folder_id: UUID | None = None


class TeamWorkspaceVisibilityRequest(BaseModel):
    workspace: str
    hidden: bool


class CodingWorkspaceTreeWorktree(BaseModel):
    path: str
    name: str
    managed: bool = False


class CodingWorkspaceTreeRepository(BaseModel):
    # None only for a worktree whose source repo is itself hidden/deleted —
    # see list_coding_workspace_tree's synthesized fallback entry.
    workspace_id: UUID | None = None
    path: str
    name: str
    worktrees: list[CodingWorkspaceTreeWorktree] = Field(default_factory=list)
    # The project this repo belongs to, if any — a real FK lookup (see
    # list_coding_workspace_tree), not something the frontend has to infer
    # by cross-referencing this list against /projects on its own.
    project_id: UUID | None = None


class CodingWorkspaceTreeResponse(BaseModel):
    repositories: list[CodingWorkspaceTreeRepository]
    # Merged in alongside repositories so the sidebar can render both
    # Projects and standalone Workspaces from one fetch/one cache entry,
    # instead of reconciling two independently-fetched lists by path string.
    projects: list[ProjectResponse] = Field(default_factory=list)


class SessionResponse(_ExcludeNoneModel):
    id: UUID
    title: str | None = None
    agent_name: str | None = None
    scheduled_task_name: str | None = None
    mode: str = "work"
    workspace: str | None = None
    project_id: UUID | None = None
    folder_id: UUID | None = None
    permission_mode: str = "auto"
    model: str | None = None
    thinking_level: str | None = None
    revert: dict | None = None
    tags: list[str] = []
    running: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        return normalize_mode(value) if isinstance(value, str) else value

    @field_validator("tags", mode="before")
    @classmethod
    def _none_tags_to_empty(cls, value: object) -> object:
        # Untagged sessions store NULL — the API contract serialises [].
        return [] if value is None else value


class TeamSessionResolveResponse(SessionResponse):
    created: bool


class SessionListResponse(BaseModel):
    data: list[SessionResponse]
    total: int
    offset: int
    limit: int


class SessionPageResponse(BaseModel):
    """Cursor-paginated session list (created_at-based, newest-first).

    ``next_cursor`` is the ISO 8601 ``created_at`` of the last item returned.
    Pass it as ``?before=<next_cursor>`` to fetch the next page.
    ``None`` means this is the last page.
    """

    data: list[SessionResponse]
    next_cursor: str | None = None
    has_more: bool


class SessionFolderResponse(BaseModel):
    """One sidebar folder with the sessions it holds.

    The first page rides along inline so the sidebar renders immediately.
    Larger folders expose a cursor for incrementally loading older chats.
    """

    id: UUID
    name: str
    mode: str = "work"
    share_context: bool = True
    sort_order: int = 0
    session_count: int = 0
    sessions: list[SessionResponse] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionFolderListResponse(BaseModel):
    folders: list[SessionFolderResponse] = Field(default_factory=list)


class MessageResponse(_ExcludeNoneModel):
    id: UUID
    session_id: UUID
    role: str
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    is_summary: bool = False
    exclude_from_context: bool = False
    extra: dict | None = None
    created_at: datetime | None = None
    # Multimodal: attachment metadata (converted_text stripped — see _message_response)
    attachments: list[dict] | None = None
    # True when this message has file attachments — frontend shows file cards
    file_message: bool = False


class SessionDetailResponse(SessionResponse):
    messages: list[MessageResponse]
