"""Request and response schemas for ``/api/code-graph`` endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from app.api.schemas.cross_repo import CrossRepoEdgeOut
from app.models.code_graph import CodeNode

if TYPE_CHECKING:
    from app.services.code_graph_service import ReindexStats, WorkspaceOverview


class CodeNodeOut(BaseModel):
    id: str
    workspace_id: str
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
            workspace_id=str(node.workspace_id),
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
    indexing: bool = Field(
        default=False,
        description="Whether a background reindex is currently running.",
    )
    index_phase: str | None = Field(
        default=None,
        description="Current indexing phase: parsing | saving.",
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


class CodeQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    intent: Literal["locate", "explain", "impact", "trace", "change"] = "locate"
    paths: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)
    budget_tokens: int = Field(default=2500, ge=500, le=12000)
    freshness: Literal["fast", "balanced", "strict"] = "balanced"
    limit: int = Field(default=10, ge=1, le=30)


class CodeQueryCandidateOut(BaseModel):
    handle: str
    file_path: str
    line_start: int
    line_end: int
    symbol: str | None = None
    kind: str | None = None
    language: str | None = None
    signature: str | None = None
    snippet: str | None = None
    score: float
    confidence: float
    provenance: str
    match_reasons: list[str]
    callers: list[str]
    callees: list[str]
    tests: list[str]
    repository: str | None = None


class LanguageCapabilityOut(BaseModel):
    language: str
    extensions: list[str]
    graph: bool
    lsp: bool
    indexed_files: int
    workspace_files: int
    coverage: float


class CodeQueryResponse(BaseModel):
    query: str
    intent: str
    strategy: str
    graph_version: str | None
    working_tree_revision: str
    freshness: str
    coverage: float
    confidence: float
    dirty_files: int
    pending_edges: int
    results: list[CodeQueryCandidateOut]
    capabilities: list[LanguageCapabilityOut]
    limitations: list[str]
    next_read_ranges: list[str]
    truncated: bool
    cache_hit: bool


class CodeGraphFreshnessResponse(BaseModel):
    graph_version: str | None
    working_tree_revision: str
    freshness: str
    indexed_files: int
    dirty_files: int
    change_source: str


class CodeEdgeOut(BaseModel):
    id: str
    src_id: str
    dst_id: str
    kind: str
    file_path: str | None = None
    line: int | None = None


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


class ProjectReindexStartedResponse(BaseModel):
    """Result of triggering a project-wide reindex with a single call."""

    indexing: bool = Field(
        description="True when at least one repo's index run is now active."
    )
    repo_count: int = Field(description="Number of repos in the project targeted.")
    already_running: int = Field(
        description="How many of those repos already had an index job running.",
    )
    will_resolve: bool = Field(
        description=(
            "Whether a cross-repo resolve pass will auto-run once every repo "
            "finishes indexing (projects with more than one repo only)."
        ),
    )


class ProjectRepoStatus(BaseModel):
    """Per-repo index status, one entry per workspace in a CodingProject."""

    workspace_id: str
    path: str
    name: str
    indexed: bool
    files: int = 0
    nodes: int = 0
    edges: int = 0
    indexing: bool = False
    index_phase: str | None = None
    index_progress: float | None = None
    index_message: str | None = None
    index_error: str | None = None


class ProjectCodeSearchResultOut(BaseModel):
    path: str = Field(description="Absolute path of the repo the match was found in.")
    node: CodeNodeOut


class ProjectCodeSearchResponse(BaseModel):
    results: list[ProjectCodeSearchResultOut]


class ProjectCodeGraphDataOut(BaseModel):
    """Project-wide code-graph payload for the spatial neuron graph UI.

    Nodes and intra-repo edges are capped per repo so the frontend can
    render large monorepos without choking. Cross-repo edges are the
    project's resolved/unresolved inter-repo references.
    """

    repos: list[ProjectRepoStatus]
    nodes: list[CodeNodeOut]
    edges: list[CodeEdgeOut]
    cross_repo_edges: list[CrossRepoEdgeOut]
    node_limit_per_repo: int
    edge_limit_per_repo: int
    total_node_count: int
    total_edge_count: int


class ProjectCodeGraphOverviewResponse(BaseModel):
    """Per-repo workspace overview aggregated for an entire CodingProject."""

    overviews: dict[str, CodeOverviewResponse]


class ReindexResponse(BaseModel):
    node_count: int
    edge_count: int
    file_count: int
    error_count: int
    errors: list[str]
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
            changed_files=stats.changed_files,
            deleted_files=stats.deleted_files,
        )
