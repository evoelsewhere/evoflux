"""Response/request schemas for /team/projects/{id}/cross-repo/*."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class CrossRepoEdgeOut(BaseModel):
    id: UUID
    src_workspace_id: UUID
    src_node_id: UUID | None
    src_file_path: str
    src_line: int | None
    raw_reference: str
    dst_name_hint: str | None
    kind: str
    status: str
    method: str | None
    confidence: float | None
    rationale: str | None
    dst_workspace_id: UUID | None
    dst_node_id: UUID | None
    dst_qualified_name: str | None


class CrossRepoResolveRequest(BaseModel):
    pass


class CrossRepoResolveStatsOut(BaseModel):
    reattached: int
    static_resolved: int
    lexical_resolved: int
    still_unresolved: int
    capped: int = 0


class CrossRepoResolveJobOut(BaseModel):
    project_id: UUID
    status: str
    phase: str
    progress: float
    message: str
    error: str | None
    stats: CrossRepoResolveStatsOut | None


class CrossRepoResolveStatusResponse(BaseModel):
    """Job snapshot for GET /cross-repo/status — ``running=False`` and every
    other field ``None`` when no resolution pass has ever been started."""

    running: bool
    job: CrossRepoResolveJobOut | None = None
