"""Project CRUD and cross-repository code-context endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import select

from app.api.deps import DbSession
from app.api.schemas.code_context import (
    CodeContextIndexRequest,
    CodeContextQueryRequest,
    CodeContextQueryResponse,
    ProjectCodeContextIndexResponse,
)
from app.api.schemas.projects import ProjectResponse, ProjectWorkspaceItem
from app.models.chat import CodingProjectWorkspace, CodingWorkspace
from app.services import coding_project_service as svc
from app.services import team_manager
from app.services.coding_purge_service import purge_project, purge_project_workspace
from app.services.code_index.jobs import project_index_jobs
from app.services.code_index.models import RepositoryScope
from app.services.code_index.pipeline import stable_id
from app.services.code_index.project import repository_indexes
from app.services.code_index.query import snapshot_graph
from app.services.code_index.service import query_code_context

router = APIRouter(prefix="/projects", tags=["projects"])


def _graph_node_id(workspace_id: UUID, repository_symbol_id: str) -> str:
    """Namespace repository-local stable IDs at the project graph boundary."""
    return stable_id(workspace_id, repository_symbol_id)


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


def _validate_path_or_422(path: str) -> str:
    try:
        return team_manager.validate_workspace(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    projects = await svc.list_visible_projects(db, kind=kind)
    output: list[ProjectResponse] = []
    for project in projects:
        pairs = await svc.get_project_workspaces(db, project.id)
        output.append(
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
    return output


async def _project_scopes(
    db: DbSession, project_id: UUID
) -> tuple[RepositoryScope, ...]:
    project = await svc.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    pairs = await svc.get_project_workspaces(db, project_id)
    scopes: list[RepositoryScope] = []
    labels: set[str] = set()
    for link, workspace in pairs:
        base = link.display_name or workspace.name or Path(workspace.path).name
        label = base
        ordinal = 2
        while label.casefold() in labels:
            label = f"{base}-{ordinal}"
            ordinal += 1
        labels.add(label.casefold())
        scopes.append(
            RepositoryScope(
                root=Path(_validate_path_or_422(workspace.path)),
                label=label,
            )
        )
    return tuple(scopes)


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    db: DbSession, kind: str | None = None
) -> list[ProjectResponse]:
    return await list_project_responses(db, kind=kind)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreateRequest, db: DbSession) -> ProjectResponse:
    project = await svc.create_project(
        db,
        name=body.name,
        description=body.description,
        workspace_paths=[_validate_path_or_422(path) for path in body.workspace_paths],
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
    if await purge_project(db, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


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
    workspace = await db.get(CodingWorkspace, link.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    await db.commit()
    return _ws_item(link, workspace)


@router.delete("/{project_id}/workspaces/{workspace_id}", status_code=204)
async def remove_workspace(project_id: UUID, workspace_id: UUID, db: DbSession) -> None:
    if await purge_project_workspace(db, project_id, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not in project")


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
    workspace = await db.get(CodingWorkspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    await db.commit()
    return _ws_item(link, workspace)


@router.get(
    "/{project_id}/code-context/status",
)
async def project_code_context_status(
    project_id: UUID, db: DbSession
) -> list[dict[str, object]]:
    scopes = await _project_scopes(db, project_id)
    pairs = await svc.get_project_workspaces(db, project_id)
    indexes = await asyncio.gather(
        *(repository_indexes.get(scope.root) for scope in scopes)
    )
    stats_values = await asyncio.gather(
        *(asyncio.to_thread(index.stats) for index in indexes)
    )
    job_states = project_index_jobs.snapshot(str(project_id))
    output: list[dict[str, object]] = []
    for scope, (_link, workspace), stats in zip(
        scopes, pairs, stats_values, strict=True
    ):
        job = job_states.get(scope.label)
        output.append(
            {
                "workspace_id": str(workspace.id),
                "path": workspace.path,
                "name": scope.label,
                "indexed": stats.files > 0,
                "files": stats.files,
                "nodes": stats.symbols,
                "edges": stats.relations,
                "indexing": job.indexing if job is not None else False,
                "index_phase": job.phase if job is not None else None,
                "index_progress": job.progress if job is not None else None,
                "index_message": job.message if job is not None else None,
                "index_error": (
                    job.error
                    if job is not None and job.error
                    else f"{stats.errors[0][0]}: {stats.errors[0][1]}"
                    f" (+{len(stats.errors) - 1} more)"
                    if len(stats.errors) > 1
                    else f"{stats.errors[0][0]}: {stats.errors[0][1]}"
                    if stats.errors
                    else None
                ),
            }
        )
    return output


@router.post(
    "/{project_id}/code-context/index",
    response_model=ProjectCodeContextIndexResponse,
    status_code=202,
)
async def index_project_code_context(
    project_id: UUID,
    db: DbSession,
    body: CodeContextIndexRequest | None = None,
) -> ProjectCodeContextIndexResponse:
    scopes = await _project_scopes(db, project_id)
    indexes = await asyncio.gather(
        *(repository_indexes.get(scope.root) for scope in scopes)
    )
    started = project_index_jobs.start(
        str(project_id),
        tuple(zip((scope.label for scope in scopes), indexes, strict=True)),
        full=bool(body and body.full),
    )
    return ProjectCodeContextIndexResponse(
        indexing=started.indexing,
        repo_count=started.repo_count,
        already_running=started.already_running,
        full=started.full,
    )


@router.post(
    "/{project_id}/code-context/query", response_model=CodeContextQueryResponse
)
async def query_project_code_context(
    project_id: UUID,
    db: DbSession,
    body: CodeContextQueryRequest,
) -> CodeContextQueryResponse:
    try:
        result = await query_code_context(
            scopes=await _project_scopes(db, project_id),
            action=body.action,
            query=body.query,
            repository=body.repository,
            paths=body.paths,
            languages=body.languages,
            depth=body.depth,
            limit=body.limit,
            refresh=body.refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CodeContextQueryResponse.model_validate(result, from_attributes=True)


@router.get("/{project_id}/code-context/graph-data")
async def project_code_context_graph_data(
    project_id: UUID,
    db: DbSession,
    node_limit_per_repo: int = Query(500, ge=1, le=5_000),
    edge_limit_per_repo: int = Query(2_000, ge=1, le=10_000),
) -> dict[str, object]:
    """Build the spatial graph from current repository targets, never DB rows."""
    scopes = await _project_scopes(db, project_id)
    pairs = await svc.get_project_workspaces(db, project_id)
    indexes = await asyncio.gather(
        *(repository_indexes.get(scope.root) for scope in scopes)
    )
    stats_values = await asyncio.gather(
        *(asyncio.to_thread(index.stats) for index in indexes)
    )
    snapshot = await snapshot_graph(
        list(
            (scope.label, index)
            for scope, index, stats in zip(scopes, indexes, stats_values, strict=True)
            if stats.files > 0
        ),
        node_limit_per_repository=node_limit_per_repo,
        relation_limit_per_repository=edge_limit_per_repo,
    )
    workspace_by_label = {
        scope.label: workspace
        for scope, (_link, workspace) in zip(scopes, pairs, strict=True)
    }
    global_id = {
        symbol.identity: _graph_node_id(
            workspace_by_label[symbol.repository].id, symbol.id
        )
        for symbol in snapshot.symbols
    }
    repos = await project_code_context_status(project_id, db)
    nodes = [
        {
            "id": global_id[symbol.identity],
            "workspace_id": str(workspace_by_label[symbol.repository].id),
            "kind": symbol.kind,
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "file_path": symbol.file_path,
            "language": symbol.language,
            "line_start": symbol.line_start,
            "line_end": symbol.line_end,
            "signature": symbol.signature,
            "docstring": symbol.docstring,
        }
        for symbol in snapshot.symbols
    ]
    local_edges: list[dict[str, object]] = []
    cross_edges: list[dict[str, object]] = []
    for relation in snapshot.relations:
        relation_id = stable_id(
            relation.source.repository,
            relation.source.id,
            relation.kind,
            relation.target.repository,
            relation.target.id,
            relation.callsite_line,
        )
        if not relation.cross_repo:
            local_edges.append(
                {
                    "id": relation_id,
                    "src_id": global_id[relation.source.identity],
                    "dst_id": global_id[relation.target.identity],
                    "kind": relation.kind,
                    "file_path": relation.callsite_file,
                    "line": relation.callsite_line,
                }
            )
            continue
        source_workspace = workspace_by_label[relation.source.repository]
        target_workspace = workspace_by_label[relation.target.repository]
        cross_edges.append(
            {
                "id": relation_id,
                "src_workspace_id": str(source_workspace.id),
                "src_node_id": global_id[relation.source.identity],
                "src_file_path": relation.callsite_file,
                "src_line": relation.callsite_line,
                "raw_reference": relation.target.qualified_name,
                "dst_name_hint": relation.target.name,
                "kind": relation.kind,
                "status": "resolved",
                "method": "dynamic-symbol-resolution",
                "confidence": 1.0,
                "rationale": "Resolved over the current authorized repository set.",
                "dst_workspace_id": str(target_workspace.id),
                "dst_node_id": global_id[relation.target.identity],
                "dst_qualified_name": relation.target.qualified_name,
            }
        )
    return {
        "repos": repos,
        "nodes": nodes,
        "edges": local_edges,
        "cross_repo_edges": cross_edges,
        "node_limit_per_repo": node_limit_per_repo,
        "edge_limit_per_repo": edge_limit_per_repo,
        "total_node_count": snapshot.total_symbols,
        "total_edge_count": snapshot.total_relations,
    }


__all__ = ["list_project_responses", "router"]
