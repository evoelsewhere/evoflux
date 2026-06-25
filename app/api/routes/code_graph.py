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

from app.api.deps import DbSession
from app.api.schemas.code_graph import (
    CodeGraphStatusResponse,
    CodeNodeOut,
    CodeOverviewResponse,
    CodeSearchResponse,
    NeighborOut,
    NeighborsResponse,
    ReindexRequest,
    ReindexStartedResponse,
)
from app.services import code_graph_service as svc
from app.services.code_graph.jobs import index_jobs
from app.services.coding_workspace_service import upsert_coding_workspace

router = APIRouter()


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
    workspace_id = await svc.resolve_workspace_id(db, path=str(path))
    if workspace_id is None:
        raise HTTPException(
            status_code=404,
            detail="Workspace has no code index yet. Reindex it first.",
        )
    return workspace_id


@router.get("/status")
async def get_status(
    db: DbSession,
    workspace: str | None = Query(None, description="Coding workspace directory."),
) -> CodeGraphStatusResponse:
    path = _workspace_path(workspace)
    workspace_id = await svc.resolve_workspace_id(db, path=str(path))
    if workspace_id is None:
        return CodeGraphStatusResponse(indexed=False)
    counts = await svc.get_index_status(db, workspace_id=workspace_id)
    semantic = await svc.get_semantic_status(workspace_id=workspace_id)
    job = index_jobs.snapshot(workspace_id)
    indexing = job is not None and job.status == "running"
    index_error = job.error if job is not None and job.status == "error" else None
    return CodeGraphStatusResponse(
        indexed=counts["files"] > 0,
        files=counts["files"],
        nodes=counts["nodes"],
        edges=counts["edges"],
        semantic_enabled=semantic.enabled,
        embedding_model=semantic.model,
        vector_count=semantic.vector_count,
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
    workspace_id = await _require_workspace_id(db, workspace)
    nodes = await svc.search_nodes(
        db, workspace_id=workspace_id, query=query, kind=kind, limit=limit
    )
    return CodeSearchResponse(nodes=[CodeNodeOut.from_model(n) for n in nodes])


@router.get("/neighbors")
async def neighbors(
    db: DbSession,
    workspace: str | None = Query(None, description="Coding workspace directory."),
    node_id: UUID = Query(..., description="Node id to expand."),
    direction: str = Query("both", pattern="^(out|in|both)$"),
    edge_kind: str | None = Query(None, description="Restrict to one relation kind."),
) -> NeighborsResponse:
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
    workspace_id = await _require_workspace_id(db, workspace)
    ov = await svc.get_overview(db, workspace_id=workspace_id)
    return CodeOverviewResponse.from_overview(ov)
