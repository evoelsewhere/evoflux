"""HTTP API for the code knowledge graph (``/api/code-graph``).

Endpoints are workspace-scoped via a ``workspace`` query param (the coding
workspace directory). Reindexing registers the workspace if needed, then
rebuilds its stored graph; the read endpoints serve search, neighbours, and
overview for the UI panel.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import col, select

from app.api.deps import DbSession
from app.api.schemas.code_graph import (
    CodeGraphStatusResponse,
    CodeGraphFreshnessResponse,
    CodeNodeOut,
    CodeOverviewResponse,
    CodeSearchResponse,
    CodeQueryCandidateOut,
    CodeQueryRequest,
    CodeQueryResponse,
    LanguageCapabilityOut,
    NeighborOut,
    NeighborsResponse,
    ReindexRequest,
    ReindexStartedResponse,
)
from app.services.code_graph.jobs import index_jobs
from app.models.chat import CodingWorkspace
from app.services.coding_workspace_service import upsert_coding_workspace

router = APIRouter()


def _service():  # noqa: ANN202 - lazy module boundary
    from app.services import code_graph_service

    return code_graph_service


def _workspace_path(workspace: str | None) -> Path:
    if workspace is None:
        raise HTTPException(status_code=422, detail="Workspace is required.")
    path = Path(workspace).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(
            status_code=422,
            detail=f"Workspace does not exist or is not a directory: {path}",
        )
    return path


async def _require_workspace_id(db: DbSession, workspace: str | None) -> UUID:
    path = _workspace_path(workspace)
    svc = _service()
    workspace_id = await svc.resolve_workspace_id(db, path=str(path))
    if workspace_id is None:
        raise HTTPException(
            status_code=404,
            detail="Workspace has no code index yet. Reindex it first.",
        )
    return workspace_id


async def _require_registered_workspace(
    db: DbSession, workspace: str | None
) -> tuple[Path, UUID]:
    """Authorize endpoints that read live source, even without an index."""
    path = _workspace_path(workspace)
    row = (
        await db.exec(
            select(CodingWorkspace).where(
                CodingWorkspace.path == str(path),
                ~col(CodingWorkspace.hidden),
                col(CodingWorkspace.deleted_at).is_(None),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Workspace is not registered or is no longer active.",
        )
    return path, row.id


@router.get("/status")
async def get_status(
    db: DbSession,
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> CodeGraphStatusResponse:
    path = _workspace_path(workspace)
    svc = _service()
    workspace_id = await svc.resolve_workspace_id(db, path=str(path))
    if workspace_id is None:
        return CodeGraphStatusResponse(indexed=False)
    counts = await svc.get_index_status(db, workspace_id=workspace_id)
    job = index_jobs.snapshot(workspace_id)
    indexing = job is not None and job.status == "running"
    index_error = job.error if job is not None and job.status == "error" else None
    return CodeGraphStatusResponse(
        indexed=counts["files"] > 0,
        files=counts["files"],
        nodes=counts["nodes"],
        edges=counts["edges"],
        indexing=indexing,
        index_phase=job.phase if indexing else None,
        index_progress=job.progress if indexing else None,
        index_message=job.message if indexing else None,
        index_error=index_error,
    )


@router.post("/reindex", status_code=202)
async def reindex(
    db: DbSession,
    body: ReindexRequest | None = None,
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> ReindexStartedResponse:
    path = _workspace_path(workspace)
    row = await upsert_coding_workspace(db, path=str(path))
    # Commit the workspace row before launching the detached job: the job runs
    # in its own session and inserts CodeNode rows that FK to this workspace,
    # so the row must be visible outside the request session first.
    await db.commit()
    _, started = await index_jobs.start(
        workspace_id=row.id,
        root_path=str(path),
        languages=body.languages if body else None,
        full=body.full if body else False,
    )
    return ReindexStartedResponse(indexing=True, already_running=not started)


@router.get("/search")
async def search(
    db: DbSession,
    workspace: str | None = Query(None, description="Coding workspace directory."),
    query: str = Query(..., min_length=1, description="Symbol name or fragment."),
    kind: str | None = Query(None, description="Restrict to a single symbol kind."),
    limit: int = Query(20, ge=1, le=100),
) -> CodeSearchResponse:
    svc = _service()
    workspace_id = await _require_workspace_id(db, workspace)
    nodes = await svc.search_nodes(
        db, workspace_id=workspace_id, query=query, kind=kind, limit=limit
    )
    return CodeSearchResponse(nodes=[CodeNodeOut.from_model(n) for n in nodes])


@router.post("/query")
async def code_query(
    db: DbSession,
    body: CodeQueryRequest,
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> CodeQueryResponse:
    """Return one freshness-aware code context pack with automatic fallback."""
    from app.services.code_query_service import query_code

    path, workspace_id = await _require_registered_workspace(db, workspace)
    result = await query_code(
        db,
        root_path=str(path),
        workspace_id=workspace_id,
        query=body.query,
        intent=body.intent,
        paths=body.paths,
        languages=body.languages,
        kinds=body.kinds,
        budget_tokens=body.budget_tokens,
        freshness_policy=body.freshness,
        limit=body.limit,
        enable_lsp=body.enable_lsp,
    )
    return CodeQueryResponse(
        query=result.query,
        intent=result.intent,
        strategy=result.strategy,
        graph_version=result.graph_version,
        working_tree_revision=result.working_tree_revision,
        freshness=result.freshness,
        coverage=result.coverage,
        confidence=result.confidence,
        dirty_files=result.dirty_files,
        pending_edges=result.pending_edges,
        results=[
            CodeQueryCandidateOut(
                handle=item.handle,
                file_path=item.file_path,
                line_start=item.line_start,
                line_end=item.line_end,
                symbol=item.symbol,
                kind=item.kind,
                language=item.language,
                signature=item.signature,
                snippet=item.snippet,
                score=item.score,
                confidence=item.confidence,
                provenance=item.provenance,
                match_reasons=item.match_reasons,
                callers=item.callers,
                callees=item.callees,
                tests=item.tests,
                repository=item.repository,
            )
            for item in result.results
        ],
        capabilities=[
            LanguageCapabilityOut(
                language=item.language,
                extensions=list(item.extensions),
                graph=item.graph,
                lsp=item.lsp,
                indexed_files=item.indexed_files,
                workspace_files=item.workspace_files,
                coverage=item.coverage,
            )
            for item in result.capabilities
        ],
        limitations=result.limitations,
        next_read_ranges=result.next_read_ranges,
        truncated=result.truncated,
        cache_hit=result.cache_hit,
    )


@router.get("/capabilities")
async def capabilities(
    db: DbSession,
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> list[LanguageCapabilityOut]:
    from app.services.code_query_service import get_capabilities

    path, workspace_id = await _require_registered_workspace(db, workspace)
    values = await get_capabilities(db, root_path=str(path), workspace_id=workspace_id)
    return [
        LanguageCapabilityOut(
            language=item.language,
            extensions=list(item.extensions),
            graph=item.graph,
            lsp=item.lsp,
            indexed_files=item.indexed_files,
            workspace_files=item.workspace_files,
            coverage=item.coverage,
        )
        for item in values
    ]


@router.get("/freshness")
async def freshness(
    db: DbSession,
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> CodeGraphFreshnessResponse:
    from app.services.code_query_service import get_freshness

    path, workspace_id = await _require_registered_workspace(db, workspace)
    value = await get_freshness(db, root_path=str(path), workspace_id=workspace_id)
    return CodeGraphFreshnessResponse(
        graph_version=value.graph_version,
        working_tree_revision=value.working_tree_revision,
        freshness=value.freshness,
        indexed_files=value.indexed_files,
        dirty_files=value.dirty_files,
        change_source=value.change_source,
    )


@router.get("/neighbors")
async def neighbors(
    db: DbSession,
    workspace: str | None = Query(None, description="Coding workspace directory."),
    node_id: UUID = Query(..., description="Node id to expand."),
    direction: str = Query("both", pattern="^(out|in|both)$"),
    edge_kind: str | None = Query(None, description="Restrict to one relation kind."),
) -> NeighborsResponse:
    svc = _service()
    workspace_id = await _require_workspace_id(db, workspace)
    node = await svc.get_node(db, workspace_id=workspace_id, node_id=node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found.")
    adjacent = await svc.get_neighbors(
        db,
        workspace_id=workspace_id,
        node_id=node_id,
        direction=direction,
        edge_kind=edge_kind,
    )
    return NeighborsResponse(
        node=CodeNodeOut.from_model(node),
        neighbors=[
            NeighborOut(edge_kind=kind, node=CodeNodeOut.from_model(n))
            for kind, n in adjacent
        ],
    )


@router.get("/overview")
async def overview(
    db: DbSession,
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> CodeOverviewResponse:
    svc = _service()
    workspace_id = await _require_workspace_id(db, workspace)
    ov = await svc.get_overview(db, workspace_id=workspace_id)
    return CodeOverviewResponse.from_overview(ov)
