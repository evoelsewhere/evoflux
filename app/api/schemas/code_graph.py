"""Request and response schemas for ``/api/code-graph`` endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.code_graph_service import (
    ReindexStats,
    WorkspaceOverview,
)
from app.models.code_graph import CodeNode


class CodeNodeOut(BaseModel):
    id: str
    kind: str
    name: str
    qualified_name: str
    file_path: str
    language: str
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None

    @classmethod
    def from_model(cls, node: CodeNode) -> "CodeNodeOut":
        return cls(
            id=str(node.id),
            kind=node.kind,
            name=node.name,
            qualified_name=node.qualified_name,
            file_path=node.file_path,
            language=node.language,
            line_start=node.line_start,
            line_end=node.line_end,
            signature=node.signature,
            docstring=node.docstring,
        )


class CodeGraphStatusResponse(BaseModel):
    indexed: bool = Field(description="Whether this workspace has a stored graph.")
    files: int = 0
    nodes: int = 0
    edges: int = 0
    semantic_enabled: bool = False
    embedding_model: str | None = None
    vector_count: int = 0
    indexing: bool = Field(
        default=False,
        description="Whether a background reindex is currently running.",
    )
    index_phase: str | None = Field(
        default=None,
        description="Current indexing phase: parsing | saving | embedding.",
    )
    index_progress: float | None = Field(
        default=None,
        description="Indexing progress from 0.0 to 1.0.",
    )
    index_message: str | None = Field(
        default=None,
        description="Human-readable progress message.",
    )
    index_error: str | None = Field(
        default=None,
        description="Error message from the last reindex, if it failed.",
    )


class CodeSearchResponse(BaseModel):
    nodes: list[CodeNodeOut]


class NeighborOut(BaseModel):
    edge_kind: str
    node: CodeNodeOut


class NeighborsResponse(BaseModel):
    node: CodeNodeOut
    neighbors: list[NeighborOut]


class CodeOverviewResponse(BaseModel):
    node_count: int
    edge_count: int
    file_count: int
    languages: list[str]
    kind_counts: dict[str, int]
    top_files: list[tuple[str, int]]

    @classmethod
    def from_overview(cls, ov: WorkspaceOverview) -> "CodeOverviewResponse":
        return cls(
            node_count=ov.node_count,
            edge_count=ov.edge_count,
            file_count=ov.file_count,
            languages=ov.languages,
            kind_counts=ov.kind_counts,
            top_files=ov.top_files,
        )


class ReindexRequest(BaseModel):
    languages: list[str] | None = Field(
        default=None,
        description="Restrict indexing to these languages; omit for all supported.",
    )
    full: bool = Field(
        default=False,
        description="Force a full rebuild instead of an incremental update.",
    )


class ReindexStartedResponse(BaseModel):
    indexing: bool = Field(description="Always true — an index run is now active.")
    already_running: bool = Field(
        description="True when a reindex was already in progress for this workspace.",
    )


class ReindexResponse(BaseModel):
    node_count: int
    edge_count: int
    file_count: int
    error_count: int
    errors: list[str]
    embedded_count: int = 0
    changed_files: int = 0
    deleted_files: int = 0

    @classmethod
    def from_stats(cls, stats: ReindexStats) -> "ReindexResponse":
        return cls(
            node_count=stats.node_count,
            edge_count=stats.edge_count,
            file_count=stats.file_count,
            error_count=stats.error_count,
            errors=stats.errors,
            embedded_count=stats.embedded_count,
            changed_files=stats.changed_files,
            deleted_files=stats.deleted_files,
        )
