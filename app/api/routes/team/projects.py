"""Project CRUD endpoints — GET/POST/PUT/DELETE /team/projects."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import DbSession
from app.api.schemas.code_graph import (
    CodeEdgeOut,
    CodeNodeOut,
    ProjectCodeGraphDataOut,
    ProjectCodeSearchResponse,
    ProjectCodeSearchResultOut,
    ProjectRepoStatus,
)
from app.api.schemas.cross_repo import (
    CrossRepoEdgeOut,
    CrossRepoResolveJobOut,
    CrossRepoResolveRequest,
    CrossRepoResolveStatsOut,
    CrossRepoResolveStatusResponse,
)
from app.models.chat import CodingProjectWorkspace, CodingWorkspace
from app.models.code_graph import CrossRepoEdge
from app.services import code_graph_service as cg_svc
from app.services import coding_project_service as svc
from app.services import team_manager
from app.services.code_graph.cross_repo import METHOD_MANUAL_REJECT, resolve_project
from app.services.code_graph.cross_repo_jobs import cross_repo_jobs
from app.services.code_graph.jobs import index_jobs

router = APIRouter(prefix="/projects", tags=["projects"])


def _validate_path_or_422(path: str) -> str:
    """Resolve + verify a workspace path, mapping failures to a 422.

    Gives project repos the same existence guarantee as single-workspace
    coding sessions, so a project can't be created pointing at a missing dir.
    """
    try:
        return team_manager.validate_workspace(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Schemas ───────────────────────────────────────────────────────────────────


class ProjectWorkspaceItem(BaseModel):
    workspace_id: UUID
    path: str
    name: str | None
    display_name: str | None
    sort_order: int
    kind: str


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    settings: dict
    workspaces: list[ProjectWorkspaceItem]
    created_at: str
    updated_at: str


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    workspace_paths: list[str] = Field(min_length=1)
    settings: dict = Field(default_factory=dict)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    settings: dict | None = None


class AddWorkspaceRequest(BaseModel):
    workspace_path: str
    display_name: str | None = None


class UpdateWorkspaceRequest(BaseModel):
    display_name: str | None = None
    sort_order: int | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ws_item(link: CodingProjectWorkspace, ws: CodingWorkspace) -> ProjectWorkspaceItem:
    return ProjectWorkspaceItem(
        workspace_id=ws.id,
        path=ws.path,
        name=ws.name,
        display_name=link.display_name,
        sort_order=link.sort_order,
        kind=ws.kind,
    )


async def _project_response(db: DbSession, project_id: UUID) -> ProjectResponse:
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    pairs = await svc.get_project_workspaces(db, project_id)
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        settings=project.settings,
        workspaces=[_ws_item(link, ws) for link, ws in pairs],
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ProjectResponse])
async def list_projects(db: DbSession) -> list[ProjectResponse]:
    projects = await svc.list_visible_projects(db)
    result = []
    for project in projects:
        pairs = await svc.get_project_workspaces(db, project.id)
        result.append(
            ProjectResponse(
                id=project.id,
                name=project.name,
                description=project.description,
                settings=project.settings,
                workspaces=[_ws_item(link, ws) for link, ws in pairs],
                created_at=project.created_at.isoformat(),
                updated_at=project.updated_at.isoformat(),
            )
        )
    return result


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreateRequest, db: DbSession) -> ProjectResponse:
    validated_paths = [_validate_path_or_422(p) for p in body.workspace_paths]
    project = await svc.create_project(
        db,
        name=body.name,
        description=body.description,
        workspace_paths=validated_paths,
        settings=body.settings,
    )
    await db.commit()
    return await _project_response(db, project.id)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: UUID, db: DbSession) -> ProjectResponse:
    return await _project_response(db, project_id)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID, body: ProjectUpdateRequest, db: DbSession
) -> ProjectResponse:
    project = await svc.update_project(
        db,
        project_id,
        name=body.name,
        # Only touch description when the client actually sent the field, so an
        # explicit null clears it and an omitted field leaves it unchanged.
        description=(
            body.description if "description" in body.model_fields_set else svc.UNSET
        ),
        settings=body.settings,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.commit()
    return await _project_response(db, project_id)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: UUID, db: DbSession) -> None:
    deleted = await svc.soft_delete_project(db, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.commit()


@router.post("/{project_id}/workspaces", response_model=ProjectWorkspaceItem, status_code=201)
async def add_workspace(
    project_id: UUID, body: AddWorkspaceRequest, db: DbSession
) -> ProjectWorkspaceItem:
    link = await svc.add_workspace_to_project(
        db,
        project_id,
        _validate_path_or_422(body.workspace_path),
        display_name=body.display_name,
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Project not found")
    ws = await db.get(CodingWorkspace, link.workspace_id)
    await db.commit()
    return _ws_item(link, ws)


@router.delete("/{project_id}/workspaces/{workspace_id}", status_code=204)
async def remove_workspace(
    project_id: UUID, workspace_id: UUID, db: DbSession
) -> None:
    removed = await svc.remove_workspace_from_project(db, project_id, workspace_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Workspace not in project")
    await db.commit()


@router.put("/{project_id}/workspaces/{workspace_id}", response_model=ProjectWorkspaceItem)
async def update_workspace_in_project(
    project_id: UUID,
    workspace_id: UUID,
    body: UpdateWorkspaceRequest,
    db: DbSession,
) -> ProjectWorkspaceItem:
    link = (
        await db.exec(
            select(CodingProjectWorkspace).where(
                CodingProjectWorkspace.project_id == project_id,
                CodingProjectWorkspace.workspace_id == workspace_id,
            )
        )
    ).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Workspace not in project")
    if body.display_name is not None:
        link.display_name = body.display_name
    if body.sort_order is not None:
        link.sort_order = body.sort_order
    db.add(link)
    ws = await db.get(CodingWorkspace, workspace_id)
    await db.commit()
    return _ws_item(link, ws)


# ── Cross-repo reference resolution ──────────────────────────────────────────


def _cross_repo_job_out(job) -> CrossRepoResolveJobOut:
    return CrossRepoResolveJobOut(
        project_id=UUID(job.project_id),
        use_llm=job.use_llm,
        llm_model=job.llm_model,
        status=job.status,
        phase=job.phase,
        progress=job.progress,
        message=job.message,
        error=job.error,
        stats=CrossRepoResolveStatsOut(**job.stats) if job.stats else None,
    )


@router.post("/{project_id}/cross-repo/resolve")
async def resolve_cross_repo(
    project_id: UUID,
    body: CrossRepoResolveRequest,
    db: DbSession,
    response: Response,
) -> CrossRepoResolveStatsOut | CrossRepoResolveJobOut:
    """Resolve unresolved cross-repo references for a project.

    ``use_llm=False`` (default) resolves synchronously — Tier A (static
    matching) is cheap regardless of project size, so the request just
    returns the resulting counts. ``use_llm=True`` always starts a
    background job instead: Tier B's cost is dominated by LLM latency, which
    doesn't shrink just because a project has few repos.
    """
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not body.use_llm:
        stats = await resolve_project(db, project_id=project_id)
        return CrossRepoResolveStatsOut(
            reattached=stats.reattached,
            static_resolved=stats.static_resolved,
            lexical_resolved=stats.lexical_resolved,
            llm_resolved=stats.llm_resolved,
            still_unresolved=stats.still_unresolved,
        )

    job, started = await cross_repo_jobs.start(
        project_id=project_id, use_llm=True, llm_model=body.llm_model
    )
    response.status_code = 202 if started else 200
    return _cross_repo_job_out(job)


@router.get("/{project_id}/cross-repo/status", response_model=CrossRepoResolveStatusResponse)
async def get_cross_repo_status(
    project_id: UUID, db: DbSession
) -> CrossRepoResolveStatusResponse:
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    job = cross_repo_jobs.snapshot(project_id)
    if job is None:
        return CrossRepoResolveStatusResponse(running=False)
    return CrossRepoResolveStatusResponse(
        running=job.status == "running", job=_cross_repo_job_out(job)
    )


@router.get("/{project_id}/cross-repo/edges", response_model=list[CrossRepoEdgeOut])
async def list_cross_repo_edges(
    project_id: UUID,
    db: DbSession,
    status: str | None = None,
) -> list[CrossRepoEdgeOut]:
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    stmt = select(CrossRepoEdge).where(col(CrossRepoEdge.project_id) == project_id)
    if status is not None:
        stmt = stmt.where(col(CrossRepoEdge.status) == status)
    rows = (await db.exec(stmt)).all()
    return [_cross_repo_edge_out(row) for row in rows]


def _cross_repo_edge_out(row: CrossRepoEdge) -> CrossRepoEdgeOut:
    return CrossRepoEdgeOut(
        id=row.id,
        src_workspace_id=row.src_workspace_id,
        src_node_id=row.src_node_id,
        src_file_path=row.src_file_path,
        src_line=row.src_line,
        raw_reference=row.raw_reference,
        dst_name_hint=row.dst_name_hint,
        kind=row.kind,
        status=row.status,
        method=row.method,
        confidence=row.confidence,
        rationale=row.rationale,
        dst_workspace_id=row.dst_workspace_id,
        dst_node_id=row.dst_node_id,
        dst_qualified_name=row.dst_qualified_name,
    )


@router.post(
    "/{project_id}/cross-repo/edges/{edge_id}/reject",
    response_model=CrossRepoEdgeOut,
)
async def reject_cross_repo_edge(
    project_id: UUID, edge_id: UUID, db: DbSession
) -> CrossRepoEdgeOut:
    """Permanently dismiss a candidate reference.

    For a false match (a resolved link that's actually wrong) or noise the
    automatic external-dependency filter missed (``is_likely_external`` is a
    best-effort heuristic, not exhaustive) — once rejected, no future
    resolution pass re-suggests it: Tier A/B only ever touch
    ``status="unresolved"`` rows, and the reindex hot path only replaces rows
    with ``method IS NULL``, which a rejected row never has (see
    ``METHOD_MANUAL_REJECT``).
    """
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    edge = (
        await db.exec(
            select(CrossRepoEdge).where(
                col(CrossRepoEdge.id) == edge_id,
                col(CrossRepoEdge.project_id) == project_id,
            )
        )
    ).first()
    if edge is None:
        raise HTTPException(status_code=404, detail="Cross-repo edge not found")

    edge.status = "rejected"
    edge.method = edge.method or METHOD_MANUAL_REJECT
    edge.dst_workspace_id = None
    edge.dst_node_id = None
    edge.dst_qualified_name = None
    db.add(edge)
    await db.commit()
    await db.refresh(edge)

    return _cross_repo_edge_out(edge)


@router.get("/{project_id}/code-graph/status", response_model=list[ProjectRepoStatus])
async def get_project_code_graph_status(
    project_id: UUID, db: DbSession
) -> list[ProjectRepoStatus]:
    """Per-repo index status for every workspace in the project.

    One entry per repo (not an aggregate) — the UI needs to know which
    specific repos still need a "Build index" click, not just a total count.
    """
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    pairs = await svc.get_project_workspaces(db, project_id)
    statuses: list[ProjectRepoStatus] = []
    for _link, ws in pairs:
        workspace_id = await cg_svc.resolve_workspace_id(db, path=ws.path)
        if workspace_id is None:
            statuses.append(
                ProjectRepoStatus(
                    workspace_id=str(ws.id), path=ws.path, name=ws.name or ws.path, indexed=False
                )
            )
            continue
        counts = await cg_svc.get_index_status(db, workspace_id=workspace_id)
        job = index_jobs.snapshot(workspace_id)
        indexing = job is not None and job.status == "running"
        index_error = job.error if job is not None and job.status == "error" else None
        statuses.append(
            ProjectRepoStatus(
                workspace_id=str(ws.id),
                path=ws.path,
                name=ws.name or ws.path,
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
        )
    return statuses


@router.get("/{project_id}/code-graph/search", response_model=ProjectCodeSearchResponse)
async def search_project_code_graph(
    project_id: UUID,
    db: DbSession,
    query: str,
    kind: str | None = None,
    limit_per_repo: int = 10,
) -> ProjectCodeSearchResponse:
    """Search for a symbol across every repo in the project at once.

    Fans out via ``search_across_workspaces`` (already used by the agent
    tool ``code_cross_repo_search``) so the frontend never has to make the
    user pick one repo before searching.
    """
    if not query.strip():
        raise HTTPException(status_code=422, detail="query must not be empty")
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    paths = await svc.get_project_workspace_paths(db, project_id)
    capped = max(1, min(limit_per_repo, 20))
    results = await cg_svc.search_across_workspaces(
        db, workspace_paths=paths, query=query, kind=kind, limit_per_workspace=capped
    )
    return ProjectCodeSearchResponse(
        results=[
            ProjectCodeSearchResultOut(path=path, node=CodeNodeOut.from_model(node))
            for path, node in results
        ]
    )


@router.get("/{project_id}/code-graph/graph-data", response_model=ProjectCodeGraphDataOut)
async def get_project_code_graph_data(
    project_id: UUID,
    db: DbSession,
    node_limit_per_repo: int = Query(500, ge=1, le=5000),
    edge_limit_per_repo: int = Query(2000, ge=1, le=10000),
) -> ProjectCodeGraphDataOut:
    """Project-wide graph payload for the spatial neuron view.

    Returns repo statuses, a capped set of symbol nodes and intra-repo
    edges per repo, plus all cross-repo edges. The caps keep the frontend
    renderer responsive for monorepos with tens of thousands of symbols.
    """
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    pairs = await svc.get_project_workspaces(db, project_id)
    repos: list[ProjectRepoStatus] = []
    nodes: list[CodeNodeOut] = []
    edges: list[CodeEdgeOut] = []
    total_node_count = 0
    total_edge_count = 0

    for _link, ws in pairs:
        workspace_id = await cg_svc.resolve_workspace_id(db, path=ws.path)
        if workspace_id is None:
            repos.append(
                ProjectRepoStatus(
                    workspace_id=str(ws.id),
                    path=ws.path,
                    name=ws.name or ws.path,
                    indexed=False,
                )
            )
            continue

        counts = await cg_svc.get_index_status(db, workspace_id=workspace_id)
        job = index_jobs.snapshot(workspace_id)
        indexing = job is not None and job.status == "running"
        index_error = job.error if job is not None and job.status == "error" else None
        repos.append(
            ProjectRepoStatus(
                workspace_id=str(ws.id),
                path=ws.path,
                name=ws.name or ws.path,
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
        )

        if counts["files"] == 0:
            continue

        repo_nodes, repo_edges, repo_total_nodes, repo_total_edges = (
            await cg_svc.get_workspace_graph_data(
                db,
                workspace_id=workspace_id,
                node_limit=node_limit_per_repo,
                edge_limit=edge_limit_per_repo,
            )
        )
        total_node_count += repo_total_nodes
        total_edge_count += repo_total_edges
        nodes.extend(CodeNodeOut.from_model(n) for n in repo_nodes)
        edges.extend(
            CodeEdgeOut(
                id=str(e.id),
                src_id=str(e.src_id),
                dst_id=str(e.dst_id),
                kind=e.kind,
                file_path=e.file_path,
                line=e.line,
            )
            for e in repo_edges
        )

    cross_stmt = select(CrossRepoEdge).where(col(CrossRepoEdge.project_id) == project_id)
    cross_rows = (await db.exec(cross_stmt)).all()

    return ProjectCodeGraphDataOut(
        repos=repos,
        nodes=nodes,
        edges=edges,
        cross_repo_edges=[_cross_repo_edge_out(row) for row in cross_rows],
        node_limit_per_repo=node_limit_per_repo,
        edge_limit_per_repo=edge_limit_per_repo,
        total_node_count=total_node_count,
        total_edge_count=total_edge_count,
    )
