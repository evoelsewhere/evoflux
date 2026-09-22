"""Project CRUD and workspace membership endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    ReadDbSession,
    WriteDbSession,
)
from app.api.schemas.projects import ProjectResponse, ProjectWorkspaceItem
from app.models.chat import CodingProjectWorkspace, CodingWorkspace
from app.services import coding_project_service as svc
from app.services import team_manager
from app.services.coding_purge_service import purge_project, purge_project_workspace

router = APIRouter(prefix="/projects", tags=["projects"])


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


async def _project_response(db: AsyncSession, project_id: UUID) -> ProjectResponse:
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
    db: AsyncSession, *, kind: str | None = None
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


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    db: ReadDbSession, kind: str | None = None
) -> list[ProjectResponse]:
    return await list_project_responses(db, kind=kind)


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreateRequest, db: WriteDbSession
) -> ProjectResponse:
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
async def get_project(project_id: UUID, db: ReadDbSession) -> ProjectResponse:
    return await _project_response(db, project_id)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID, body: ProjectUpdateRequest, db: WriteDbSession
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
async def delete_project(project_id: UUID, db: WriteDbSession) -> None:
    if await purge_project(db, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")


@router.post(
    "/{project_id}/workspaces", response_model=ProjectWorkspaceItem, status_code=201
)
async def add_workspace(
    project_id: UUID, body: AddWorkspaceRequest, db: WriteDbSession
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
async def remove_workspace(
    project_id: UUID, workspace_id: UUID, db: WriteDbSession
) -> None:
    if await purge_project_workspace(db, project_id, workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not in project")


@router.put(
    "/{project_id}/workspaces/{workspace_id}", response_model=ProjectWorkspaceItem
)
async def update_workspace_in_project(
    project_id: UUID,
    workspace_id: UUID,
    body: UpdateWorkspaceRequest,
    db: WriteDbSession,
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


__all__ = ["list_project_responses", "router"]
