"""Response/request schemas for /team/projects/{id}/cross-repo/*."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class CrossRepoEdgeOut(BaseModel):
    id: UUID
    src_workspace_id: UUID
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
    dst_qualified_name: str | None


class CrossRepoResolveRequest(BaseModel):
    use_llm: bool = False
    # Overrides the persisted CrossRepoSettings.llm_model for this call.
    # There's no "current session" to default to here (this is a
    # project-level operation, not an agent turn) — pass it explicitly.
    llm_model: str | None = None


class CrossRepoResolveStatsOut(BaseModel):
    reattached: int
    static_resolved: int
    lexical_resolved: int
    llm_resolved: int
    still_unresolved: int


class CrossRepoResolveJobOut(BaseModel):
    project_id: UUID
    use_llm: bool
    llm_model: str | None
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
