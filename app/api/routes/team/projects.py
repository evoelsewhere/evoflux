"""Project CRUD endpoints — GET/POST/PUT/DELETE /team/projects."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import DbSession
from app.api.schemas.code_graph import (
    CodeEdgeOut,
    CodeNodeOut,
    CodeOverviewResponse,
    ProjectCodeGraphDataOut,
    ProjectCodeGraphOverviewResponse,
    ProjectCodeSearchResponse,
    ProjectCodeSearchResultOut,
    ProjectReindexStartedResponse,
    ProjectRepoStatus,
    ReindexRequest,
)
from app.api.schemas.cross_repo import (
    CrossRepoEdgeOut,
    CrossRepoResolveJobOut,
    CrossRepoResolveRequest,
    CrossRepoResolveStatsOut,
    CrossRepoResolveStatusResponse,
)
from app.api.schemas.aim import (
    AimApprovalOut,
    AimCutoverChecklistOut,
    AimCutoverChecklistUpdate,
    AimLayoutDetectionResponse,
    AimManifestPreviewResponse,
    AimMetaResponse,
    AimPhaseCounts,
    AimProjectCreateRequest,
    AimProjectHealthOut,
    AimProjectJoinRequest,
    AimProjectSummaryOut,
    AimReadinessResponse,
    AimReindexResponse,
    AimRulebookFile,
    AimRulebookResponse,
    AimRunListItem,
    AimRunOut,
    AimStateReconcileRequest,
    AimStateReconcileResponse,
    AimUnitOut,
    AimUnitActionOut,
    AimUnitClaimOut,
)
from app.api.schemas.projects import ProjectResponse, ProjectWorkspaceItem
from app.models.aim import AimClaim, AimRun, AimUnit
from app.models.chat import CodingProjectWorkspace, CodingWorkspace
from app.models.code_graph import CrossRepoEdge
from app.services import code_graph_service as cg_svc
from app.services import coding_project_service as svc
from app.services import team_manager
from app.services.aim import project_setup as aim_project_setup
from app.services.code_graph.cross_repo import METHOD_MANUAL_REJECT
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
# ProjectWorkspaceItem / ProjectResponse live in app.api.schemas.projects —
# chat.py's merged /workspace/tree endpoint needs them too.


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
        kind=project.kind,
        workspaces=[_ws_item(link, ws) for link, ws in pairs],
        created_at=project.created_at.isoformat(),
        updated_at=project.updated_at.isoformat(),
    )


async def list_project_responses(
    db: DbSession, *, kind: str | None = None
) -> list[ProjectResponse]:
    """All visible projects with their member workspaces, as ProjectResponse.

    Shared with chat.py's merged /workspace/tree endpoint so both surfaces
    build the Projects list the same way instead of maintaining two copies.
    ``kind`` (optional) filters to "coding" or "aim" — see
    ``svc.list_visible_projects``. Left unfiltered by default so existing
    callers are unaffected; the Coding sidebar and AIM Board should each
    pass their own ``kind`` explicitly.
    """
    projects = await svc.list_visible_projects(db, kind=kind)
    result = []
    for project in projects:
        pairs = await svc.get_project_workspaces(db, project.id)
        result.append(
            ProjectResponse(
                id=project.id,
                name=project.name,
                description=project.description,
                settings=project.settings,
                kind=project.kind,
                workspaces=[_ws_item(link, ws) for link, ws in pairs],
                created_at=project.created_at.isoformat(),
                updated_at=project.updated_at.isoformat(),
            )
        )
    return result


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    db: DbSession, kind: str | None = None
) -> list[ProjectResponse]:
    return await list_project_responses(db, kind=kind)


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


@router.post(
    "/{project_id}/workspaces", response_model=ProjectWorkspaceItem, status_code=201
)
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
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    await db.commit()
    return _ws_item(link, ws)


@router.delete("/{project_id}/workspaces/{workspace_id}", status_code=204)
async def remove_workspace(project_id: UUID, workspace_id: UUID, db: DbSession) -> None:
    removed = await svc.remove_workspace_from_project(db, project_id, workspace_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Workspace not in project")
    await db.commit()


@router.put(
    "/{project_id}/workspaces/{workspace_id}", response_model=ProjectWorkspaceItem
)
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
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    await db.commit()
    return _ws_item(link, ws)


# ── Cross-repo reference resolution ──────────────────────────────────────────


def _cross_repo_job_out(job) -> CrossRepoResolveJobOut:
    return CrossRepoResolveJobOut(
        project_id=UUID(job.project_id),
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
) -> CrossRepoResolveJobOut:
    """Resolve unresolved cross-repo references for a project.

    Always starts a background job that runs Tier 0 (reattach) + Tier A
    (static matching) + Tier B (FTS5 lexical matching).
    """
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    job, started = await cross_repo_jobs.start(project_id=project_id)
    response.status_code = 202 if started else 200
    return _cross_repo_job_out(job)


@router.get(
    "/{project_id}/cross-repo/status", response_model=CrossRepoResolveStatusResponse
)
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


# ── Code graph indexing ──────────────────────────────────────────────────────


@router.post("/{project_id}/code-graph/reindex", status_code=202)
async def reindex_project_code_graph(
    project_id: UUID,
    db: DbSession,
    body: ReindexRequest | None = None,
) -> ProjectReindexStartedResponse:
    """Reindex every repo in a project with a single call.

    Starts (or joins) a background index job per repo. Projects with more
    than one repo also start the cross-repo resolve job immediately —
    ``cross_repo_jobs`` internally waits for these workspaces to settle
    before it touches the database — so ``GET .../cross-repo/status`` reads
    ``running`` continuously from this call through to "done" instead of
    dipping back to "not running" while indexing is still in progress.
    Callers never sequence "index" then "resolve" by hand.

    Repos are indexed in parallel for better performance on multi-repo projects.
    """
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    pairs = await svc.get_project_workspaces(db, project_id)

    # Start all index jobs in parallel
    async def start_index_job(ws):
        _, started = await index_jobs.start(
            workspace_id=ws.id,
            root_path=ws.path,
            languages=body.languages if body else None,
            full=body.full if body else False,
        )
        return ws.id, started

    # Run all index job starts concurrently
    import asyncio

    results = await asyncio.gather(*[start_index_job(ws) for _, ws in pairs])

    workspace_ids: list[UUID] = []
    already_running = 0
    for ws_id, started in results:
        workspace_ids.append(ws_id)
        if not started:
            already_running += 1

    # For incremental resolution, track which workspaces actually need re-indexing
    # If full=True, all workspaces are considered changed
    changed_workspaces = set(workspace_ids) if (body and body.full) else None

    will_resolve = len(workspace_ids) > 1
    if will_resolve:
        await cross_repo_jobs.start(
            project_id=project_id,
            wait_for_workspaces=workspace_ids,
            changed_workspaces=changed_workspaces,
        )

    return ProjectReindexStartedResponse(
        indexing=bool(workspace_ids),
        repo_count=len(workspace_ids),
        already_running=already_running,
        will_resolve=will_resolve,
    )


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
    tool ``code_search`` with ``scope='project'``) so the frontend never has
    to make the user pick one repo before searching.
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
            for path, _ws_id, node in results
        ]
    )


@router.get(
    "/{project_id}/code-graph/overview", response_model=ProjectCodeGraphOverviewResponse
)
async def get_project_code_graph_overview(
    project_id: UUID, db: DbSession
) -> ProjectCodeGraphOverviewResponse:
    """Aggregated workspace overview for every repo in the project."""
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    overviews = await cg_svc.get_project_overview(db, project_id=project_id)
    return ProjectCodeGraphOverviewResponse(
        overviews={
            path: CodeOverviewResponse.from_overview(overview)
            for path, overview in overviews.items()
        }
    )


@router.get(
    "/{project_id}/code-graph/graph-data", response_model=ProjectCodeGraphDataOut
)
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

        (
            repo_nodes,
            repo_edges,
            repo_total_nodes,
            repo_total_edges,
        ) = await cg_svc.get_workspace_graph_data(
            db,
            workspace_id=workspace_id,
            node_limit=node_limit_per_repo,
            edge_limit=edge_limit_per_repo,
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

    cross_stmt = select(CrossRepoEdge).where(
        col(CrossRepoEdge.project_id) == project_id
    )
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


# ── AIM (documents/research/aim-framework.md §3.8(e), §3.12) ────────────────
#
# /aim/create, /aim/preview, /aim/join are the AimSetupWizard's backend
# (§3.12) — the only routes in this section that write. Everything else
# here is read-only: they serve the `aim_units`/`aim_runs` local index for
# a dashboard. Every write to THAT index goes through the aim_units/
# aim_compare tools (app/agent/tools/builtin/aim.py), never through this
# router.


@router.get("/aim/meta", response_model=AimMetaResponse)
async def get_aim_meta() -> AimMetaResponse:
    """Backend-authoritative AIM vocabulary — phase lists, labels, and the
    phase→next-pipeline map. The frontend reads this instead of duplicating
    the phase set (kept in sync with the backend ``VALID_PHASES``)."""
    from app.services.aim.models import (
        UNIT_PHASE_LABELS,
        UNIT_PHASE_NEXT_PIPELINE,
        VALID_PHASES,
        VALID_PROJECT_PHASES,
    )

    return AimMetaResponse(
        unit_phases=list(VALID_PHASES),
        project_phases=list(VALID_PROJECT_PHASES),
        phase_labels=dict(UNIT_PHASE_LABELS),
        phase_next_pipeline=dict(UNIT_PHASE_NEXT_PIPELINE),
    )


@router.post("/aim/detect", response_model=AimLayoutDetectionResponse)
async def detect_aim_layout_route(root_path: str) -> AimLayoutDetectionResponse:
    """Inspect one folder for the AIM layout convention
    (``<name>/{aim_source_base/*, aim_<name>_document, aim_target_source}``)
    — the wizard's single-folder-pick path. ``has_manifest`` tells the
    caller whether the follow-up is a join (aim.yaml already in the
    document repo) or a create.
    """
    from app.services.aim.layout import detect_aim_layout

    try:
        detection = detect_aim_layout(root_path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return AimLayoutDetectionResponse(
        root=detection.root,
        project_name=detection.project_name,
        source_paths=detection.source_paths,
        kb_path=detection.kb_path,
        target_path=detection.target_path,
        has_manifest=detection.has_manifest,
        source_identity_map=detection.source_identity_map,
        target_identity_map=detection.target_identity_map,
        warnings=detection.warnings,
    )


@router.post("/aim/preview", response_model=AimManifestPreviewResponse)
async def preview_aim_project(kb_path: str) -> AimManifestPreviewResponse:
    """Read an existing KB repo's aim.yaml — the "Join existing" wizard
    step's preview, before asking the user for local repo path mappings.
    """
    try:
        manifest = await aim_project_setup.preview_aim_manifest(kb_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=422, detail=f"No aim.yaml found at '{kb_path}'."
        )
    return AimManifestPreviewResponse(
        rulebook_id=manifest.rulebook.id,
        rulebook_version=manifest.rulebook.version,
        source_identities=manifest.roles.source,
        target_identities=manifest.roles.target,
        phase=manifest.phase,
    )


@router.post("/aim", response_model=ProjectResponse, status_code=201)
async def create_aim_project_route(
    body: AimProjectCreateRequest, db: DbSession
) -> ProjectResponse:
    source_paths = [_validate_path_or_422(p) for p in body.source_paths]
    target_path = _validate_path_or_422(body.target_path)
    kb_root = Path(body.kb_path).expanduser().resolve()
    # The KB dir may legitimately pre-exist (the aim_<name>_document repo of
    # the folder convention is created/cloned before the project — see
    # app/services/aim/layout.py) and scaffolding is gap-fill-only. The one
    # thing create must refuse is a dir that is ALREADY an AIM KB.
    if (kb_root / "aim.yaml").is_file():
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{kb_root}' already contains an aim.yaml — this is an "
                f"existing AIM project; join it instead of creating."
            ),
        )
    project = await aim_project_setup.create_aim_project(
        db,
        name=body.name,
        source_paths=source_paths,
        target_path=target_path,
        kb_path=str(kb_root),
    )
    await db.commit()
    from app.services.aim.watcher import _global_aim_watcher

    if _global_aim_watcher is not None:
        await _global_aim_watcher.watch_project(project.id, str(kb_root))
    return await _project_response(db, project.id)


@router.post("/aim/join", response_model=ProjectResponse, status_code=201)
async def join_aim_project_route(
    body: AimProjectJoinRequest, db: DbSession
) -> ProjectResponse:
    kb_path = _validate_path_or_422(body.kb_path)
    try:
        project = await aim_project_setup.join_aim_project(
            db,
            name=body.name,
            kb_path=kb_path,
            source_paths=[_validate_path_or_422(p) for p in body.source_paths],
            target_path=_validate_path_or_422(body.target_path),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"AIM KB manifest or local rulebook is invalid: {exc}",
        )
    await db.commit()
    from app.services.aim.watcher import _global_aim_watcher

    if _global_aim_watcher is not None:
        await _global_aim_watcher.watch_project(project.id, kb_path)
    return await _project_response(db, project.id)


async def _get_aim_project_or_404(db: DbSession, project_id: UUID):
    project = await svc.get_project(db, project_id)
    if project is None or project.kind != "aim":
        raise HTTPException(status_code=404, detail="AIM project not found")
    return project


def _aim_unit_out(
    row: AimUnit,
    *,
    state_verified: bool = False,
    state_error: str | None = None,
    next_action: AimUnitActionOut | None = None,
    claim: AimUnitClaimOut | None = None,
) -> AimUnitOut:
    return AimUnitOut(
        id=row.id,
        module=row.module,
        name=row.name,
        kind=row.kind,
        phase=row.phase,
        wave=row.wave,
        assignee=row.assignee,
        depends_on=row.depends_on,
        complexity=row.complexity,
        revision=row.revision,
        last_transition_id=row.last_transition_id,
        state_verified=state_verified,
        state_error=state_error,
        next_action=next_action,
        claim=claim,
        kb_doc_path=row.kb_doc_path,
        updated_at=row.updated_at,
    )


@router.get("/{project_id}/aim/summary", response_model=AimProjectSummaryOut)
async def get_aim_project_summary(
    project_id: UUID, db: DbSession
) -> AimProjectSummaryOut:
    await _get_aim_project_or_404(db, project_id)

    units = (
        await db.exec(select(AimUnit).where(AimUnit.project_id == project_id))
    ).all()
    counts = AimPhaseCounts()
    for unit in units:
        if hasattr(counts, unit.phase):
            setattr(counts, unit.phase, getattr(counts, unit.phase) + 1)
    total = len(units)
    equivalent_pct = (
        round(100 * (counts.equivalent + counts.cutover) / total, 1) if total else 0.0
    )

    latest_run = (
        await db.exec(
            select(AimRun)
            .join(AimUnit, col(AimRun.unit_id) == col(AimUnit.id))
            .where(AimUnit.project_id == project_id)
            .order_by(col(AimRun.created_at).desc())
            .limit(1)
        )
    ).first()

    return AimProjectSummaryOut(
        project_id=project_id,
        total_units=total,
        phase_counts=counts,
        equivalent_pct=equivalent_pct,
        latest_run_at=latest_run.created_at if latest_run else None,
    )


@router.get("/{project_id}/aim/units", response_model=list[AimUnitOut])
async def list_aim_units(
    project_id: UUID,
    db: DbSession,
    phase: str | None = None,
    wave: int | None = None,
) -> list[AimUnitOut]:
    from app.services.aim import kb_store
    from app.services.aim.business_rules import business_rule_review_ready
    from app.services.aim.models import UNIT_PHASE_NEXT_PIPELINE, next_unit_phase
    from app.services.aim.project import resolve_kb_workspace_path
    from app.services.aim.readiness import evaluate_pipeline

    project = await _get_aim_project_or_404(db, project_id)

    stmt = select(AimUnit).where(AimUnit.project_id == project_id)
    if phase is not None:
        stmt = stmt.where(AimUnit.phase == phase)
    if wave is not None:
        stmt = stmt.where(AimUnit.wave == wave)
    rows = (await db.exec(stmt.order_by(AimUnit.module, AimUnit.name))).all()
    now = datetime.now(timezone.utc)
    claims = (
        await db.exec(
            select(AimClaim).where(
                AimClaim.project_id == project_id,
                AimClaim.lease_expires_at > now,
            )
        )
    ).all()
    claims_by_unit = {claim.unit_id: claim for claim in claims}
    kb_path = await resolve_kb_workspace_path(db, project)
    kb_root = Path(kb_path) if kb_path and Path(kb_path).is_dir() else None
    state_schema = 1
    if kb_root is not None:
        try:
            state_schema = kb_store.read_manifest(kb_root).state_schema
        except (FileNotFoundError, ValueError):
            state_schema = 1

    output: list[AimUnitOut] = []
    for row in rows:
        state_error: str | None = "KB repo is not available on this machine"
        action: AimUnitActionOut | None = None
        if kb_root is not None:
            unit_state = kb_store.read_unit(kb_root, row.module, row.name)
            if unit_state is None:
                state_error = "unit document is missing from the KB"
            elif state_schema < 2:
                state_error = (
                    "legacy state schema: reconcile this unit before running "
                    "lifecycle actions"
                )
            else:
                state_error = kb_store.validate_unit_state(
                    kb_root,
                    row.module,
                    row.name,
                    unit_state[0],
                    state_schema=state_schema,
                )
            pipeline = UNIT_PHASE_NEXT_PIPELINE.get(row.phase)
            target_phase = next_unit_phase(row.phase)
            if row.phase == "understood":
                rules_ready, _rules_blocker = business_rule_review_ready(
                    kb_root, f"{row.module}/{row.name}"
                )
                if not rules_ready:
                    pipeline = "aim-review-rules"
                    target_phase = "understood"
            if pipeline and target_phase:
                readiness = evaluate_pipeline(
                    kb_root,
                    pipeline,
                    unit=f"{row.module}/{row.name}",
                    wave=row.wave,
                    case_set="smoke",
                )
                action = AimUnitActionOut(
                    pipeline=pipeline,
                    target_phase=target_phase,
                    allowed=readiness.allowed and state_error is None,
                    blockers=[
                        *([state_error] if state_error else []),
                        *readiness.blockers,
                    ],
                    warnings=list(readiness.warnings),
                )
        claim_row = claims_by_unit.get(row.id)
        claim = (
            AimUnitClaimOut(
                workflow_execution_id=claim_row.workflow_execution_id,
                workflow_name=claim_row.workflow_name,
                session_id=claim_row.session_id,
                lease_expires_at=claim_row.lease_expires_at,
            )
            if claim_row is not None
            else None
        )
        output.append(
            _aim_unit_out(
                row,
                state_verified=state_error is None,
                state_error=state_error,
                next_action=action,
                claim=claim,
            )
        )
    return output


@router.get(
    "/{project_id}/aim/readiness",
    response_model=AimReadinessResponse,
)
async def get_aim_readiness(
    project_id: UUID,
    db: DbSession,
    pipeline: str,
    unit: str | None = None,
    wave: int | None = None,
    case_set: str | None = None,
    overwrite: bool = False,
) -> AimReadinessResponse:
    from app.services.aim.project import resolve_kb_workspace_path
    from app.services.aim.readiness import evaluate_pipeline
    from app.models.workflow import WorkflowExecution

    project = await _get_aim_project_or_404(db, project_id)
    kb_path = await resolve_kb_workspace_path(db, project)
    if not kb_path or not Path(kb_path).is_dir():
        raise HTTPException(
            status_code=422, detail="Project has no KB repo on this machine."
        )
    result = evaluate_pipeline(
        Path(kb_path),
        pipeline,
        unit=unit,
        wave=wave,
        case_set=case_set,
        overwrite=overwrite,
    )
    data = result.to_dict()
    dependencies: list[dict] = []
    selected_keys = set(result.selected_units)
    if selected_keys:
        unit_rows = (
            await db.exec(select(AimUnit).where(AimUnit.project_id == project_id))
        ).all()
        selected_by_id = {
            row.id: f"{row.module}/{row.name}"
            for row in unit_rows
            if f"{row.module}/{row.name}" in selected_keys
        }
        if selected_by_id:
            now = datetime.now(timezone.utc)
            claims = (
                await db.exec(
                    select(AimClaim).where(
                        AimClaim.project_id == project_id,
                        AimClaim.lease_expires_at > now,
                    )
                )
            ).all()
            claims = [claim for claim in claims if claim.unit_id in selected_by_id]
            grouped: dict[UUID, dict] = {}
            for claim in claims:
                dependency = grouped.setdefault(
                    claim.workflow_execution_id,
                    {
                        "workflow_execution_id": claim.workflow_execution_id,
                        "workflow_name": claim.workflow_name,
                        "execution_status": "unknown",
                        "session_id": claim.session_id,
                        "lease_expires_at": claim.lease_expires_at,
                        "units": [],
                    },
                )
                dependency["units"].append(selected_by_id[claim.unit_id])
                if claim.lease_expires_at > dependency["lease_expires_at"]:
                    dependency["lease_expires_at"] = claim.lease_expires_at
            for execution_id, dependency in grouped.items():
                execution = await db.get(WorkflowExecution, execution_id)
                if execution is not None:
                    dependency["execution_status"] = execution.status
                    dependency["session_id"] = execution.session_id
                dependency["units"].sort()
                dependencies.append(dependency)
            dependencies.sort(
                key=lambda item: (
                    item["workflow_name"],
                    str(item["workflow_execution_id"]),
                )
            )

    if dependencies:
        data["status"] = "blocked"
        data["allowed"] = False
        data["blockers"] = [
            *data["blockers"],
            *[
                (
                    f"{len(dependency['units'])} selected unit(s) are owned by "
                    f"{dependency['workflow_name']} execution "
                    f"{dependency['workflow_execution_id']} until "
                    f"{dependency['lease_expires_at'].isoformat()}"
                )
                for dependency in dependencies
            ],
        ]
    data["claim_dependencies"] = dependencies
    return AimReadinessResponse(**data)


@router.get("/{project_id}/aim/health", response_model=AimProjectHealthOut)
async def get_aim_project_health(
    project_id: UUID, db: DbSession
) -> AimProjectHealthOut:
    from app.services.aim.health import evaluate_project_health

    project = await _get_aim_project_or_404(db, project_id)
    health = await evaluate_project_health(db, project)
    return AimProjectHealthOut(**health.to_dict())


@router.get("/{project_id}/aim/approvals", response_model=list[AimApprovalOut])
async def list_aim_approvals(project_id: UUID, db: DbSession) -> list[AimApprovalOut]:
    from app.agent.ask_user import get_service_for_session
    from app.models.chat import ChatSession
    from app.models.workflow import WorkflowExecution

    await _get_aim_project_or_404(db, project_id)
    rows = (
        await db.exec(
            select(WorkflowExecution, ChatSession)
            .join(ChatSession, col(WorkflowExecution.session_id) == col(ChatSession.id))
            .where(
                ChatSession.project_id == project_id,
                WorkflowExecution.status == "waiting_gate",
            )
            .order_by(col(WorkflowExecution.started_at))
        )
    ).all()
    approvals: list[AimApprovalOut] = []
    for execution, session in rows:
        service = get_service_for_session(str(session.id))
        if service is None:
            continue
        for request_id, request in service._pending.items():
            for question in request.questions:
                approvals.append(
                    AimApprovalOut(
                        execution_id=execution.id,
                        session_id=session.id,
                        session_title=session.title,
                        workflow=execution.definition_name,
                        request_id=request_id,
                        question=question.question,
                        options=question.options,
                    )
                )
    return approvals


@router.post(
    "/{project_id}/aim/reconcile-state",
    response_model=AimStateReconcileResponse,
)
async def reconcile_aim_state(
    project_id: UUID,
    body: AimStateReconcileRequest,
    db: DbSession,
) -> AimStateReconcileResponse:
    from app.services.aim import kb_store
    from app.services.aim.project import resolve_kb_workspace_path
    from app.services.aim.reindex import reindex_project

    project = await _get_aim_project_or_404(db, project_id)
    kb_path = await resolve_kb_workspace_path(db, project)
    if not kb_path or not Path(kb_path).is_dir():
        raise HTTPException(
            status_code=422, detail="Project has no KB repo on this machine."
        )
    kb_root = Path(kb_path)
    manifest = kb_store.read_manifest(kb_root)
    if manifest.state_schema >= 2:
        return AimStateReconcileResponse(
            reconciliation_id="already-current",
            reconciled=0,
            state_schema=manifest.state_schema,
        )
    reconciliation_id, reconciled = kb_store.reconcile_legacy_state(kb_root)
    await reindex_project(db, project_id, kb_root)
    await db.commit()
    return AimStateReconcileResponse(
        reconciliation_id=reconciliation_id,
        reconciled=reconciled,
        state_schema=2,
    )


async def _aim_kb_root_or_422(db: DbSession, project_id: UUID) -> tuple[object, Path]:
    from app.services.aim.project import resolve_kb_workspace_path

    project = await _get_aim_project_or_404(db, project_id)
    kb_path = await resolve_kb_workspace_path(db, project)
    if not kb_path or not Path(kb_path).is_dir():
        raise HTTPException(
            status_code=422, detail="Project has no KB repo on this machine."
        )
    return project, Path(kb_path)


@router.get(
    "/{project_id}/aim/waves/{wave}/cutover",
    response_model=AimCutoverChecklistOut,
)
async def get_aim_cutover_checklist(
    project_id: UUID, wave: int, db: DbSession
) -> AimCutoverChecklistOut:
    from app.services.aim import kb_store
    from app.services.aim.models import CutoverChecklist

    _project, kb_root = await _aim_kb_root_or_422(db, project_id)
    checklist = kb_store.read_cutover_checklist(kb_root, wave) or CutoverChecklist(
        wave=wave
    )
    return AimCutoverChecklistOut(**checklist.model_dump())


@router.put(
    "/{project_id}/aim/waves/{wave}/cutover",
    response_model=AimCutoverChecklistOut,
)
async def update_aim_cutover_checklist(
    project_id: UUID,
    wave: int,
    body: AimCutoverChecklistUpdate,
    db: DbSession,
) -> AimCutoverChecklistOut:
    from app.services.aim import kb_store
    from app.services.aim.models import CutoverChecklist

    _project, kb_root = await _aim_kb_root_or_422(db, project_id)
    checklist = CutoverChecklist(wave=wave, **body.model_dump())
    kb_store.write_cutover_checklist(kb_root, checklist)
    return AimCutoverChecklistOut(**checklist.model_dump())


@router.get("/{project_id}/aim/runs", response_model=list[AimRunListItem])
async def list_aim_runs(
    project_id: UUID, db: DbSession, limit: int = 50
) -> list[AimRunListItem]:
    """Newest-first compare/run history across the project's units — the
    Runs & Reports table (spec v2.2 §5.3)."""
    await _get_aim_project_or_404(db, project_id)
    rows = (
        await db.exec(
            select(AimRun, AimUnit)
            .join(AimUnit, col(AimRun.unit_id) == col(AimUnit.id))
            .where(AimUnit.project_id == project_id)
            .order_by(col(AimRun.created_at).desc())
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    return [
        AimRunListItem(
            id=run.id,
            unit_id=run.unit_id,
            unit=f"{unit.module}/{unit.name}",
            kind=run.kind,
            verdict=run.verdict,
            case_set=run.case_set,
            report_path=run.report_path,
            session_id=run.session_id,
            workflow_execution_id=run.workflow_execution_id,
            created_at=run.created_at,
        )
        for run, unit in rows
    ]


@router.post("/{project_id}/aim/reindex", response_model=AimReindexResponse)
async def reindex_aim_project(project_id: UUID, db: DbSession) -> AimReindexResponse:
    """Rebuild the local aim_units index from the KB repo's frontmatter —
    the KB screen's Reindex button, for after a manual ``git pull`` (the
    KB is the system of record; this table is only a local projection)."""
    from app.services.aim.project import resolve_kb_workspace_path
    from app.services.aim.reindex import reindex_project

    project = await _get_aim_project_or_404(db, project_id)
    kb_path = await resolve_kb_workspace_path(db, project)
    if not kb_path or not Path(kb_path).is_dir():
        raise HTTPException(
            status_code=422, detail="Project has no KB repo on this machine."
        )
    result = await reindex_project(db, project_id, Path(kb_path))
    await db.commit()
    return AimReindexResponse(
        created=result.created,
        updated=result.updated,
        unchanged=result.unchanged,
        invalid=result.invalid,
        errors=result.errors,
        runs_created=result.runs_created,
        runs_updated=result.runs_updated,
        links_created=result.links_created,
        links_updated=result.links_updated,
    )


_RULEBOOK_TEXT_SUFFIXES = {".yaml", ".yml", ".md", ".sh"}
_RULEBOOK_MAX_FILE_BYTES = 64 * 1024
_RULEBOOK_MAX_FILES = 60


@router.get("/{project_id}/aim/rulebook", response_model=AimRulebookResponse)
async def get_aim_rulebook(project_id: UUID, db: DbSession) -> AimRulebookResponse:
    """The project's KB-local rulebook, read-only — answers "what rules does
    this line convert by?" without opening the EvoFlux repo (spec v2.2 J5).
    The rulebook is always read from this project's KB repository.
    """
    from app.services.aim.project import resolve_kb_workspace_path
    from app.services.aim.rulebook import rulebook_dir, validate_rulebook_identity

    project = await _get_aim_project_or_404(db, project_id)
    kb_path = await resolve_kb_workspace_path(db, project)
    kb_root = Path(kb_path) if kb_path else None
    try:
        local_manifest = (
            validate_rulebook_identity(kb_root) if kb_root is not None else None
        )
    except (FileNotFoundError, ValueError):
        local_manifest = None
    if local_manifest is None or kb_root is None:
        raise HTTPException(
            status_code=404,
            detail="KB-local rulebook is missing, invalid, or does not match aim.yaml.",
        )
    local_rulebook_dir = rulebook_dir(kb_root)
    manifest = local_manifest.model_dump()

    files: list[AimRulebookFile] = []
    for path in sorted(local_rulebook_dir.rglob("*")):
        if len(files) >= _RULEBOOK_MAX_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in _RULEBOOK_TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > _RULEBOOK_MAX_FILE_BYTES:
                continue
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        files.append(
            AimRulebookFile(
                path=str(path.relative_to(local_rulebook_dir)), content=content
            )
        )
    return AimRulebookResponse(id=local_manifest.id, manifest=manifest, files=files)


@router.get("/{project_id}/aim/runs/{run_id}", response_model=AimRunOut)
async def get_aim_run(project_id: UUID, run_id: UUID, db: DbSession) -> AimRunOut:
    from app.services.aim.project import resolve_kb_workspace_path

    project = await _get_aim_project_or_404(db, project_id)

    run = (
        await db.exec(
            select(AimRun)
            .join(AimUnit, col(AimRun.unit_id) == col(AimUnit.id))
            .where(AimRun.id == run_id, AimUnit.project_id == project_id)
        )
    ).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    report: dict | None = None
    if run.report_path:
        report_file = Path(run.report_path)
        # report_path is stored KB-relative (see aim_compare) — resolve
        # against the project's current KB checkout. Older rows recorded
        # an absolute path; still honor those as-is.
        if not report_file.is_absolute():
            kb_path = await resolve_kb_workspace_path(db, project)
            if kb_path:
                report_file = Path(kb_path) / report_file
        if report_file.is_file():
            try:
                report = json.loads(report_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                report = None

    return AimRunOut(
        id=run.id,
        unit_id=run.unit_id,
        kind=run.kind,
        verdict=run.verdict,
        case_set=run.case_set,
        stats=run.stats,
        report_path=run.report_path,
        session_id=run.session_id,
        workflow_execution_id=run.workflow_execution_id,
        created_at=run.created_at,
        report=report,
    )
