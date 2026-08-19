"""Review and apply repository-local guarded ChangeSets."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.schemas.change_sets import (
    ChangeSetCreateRequest,
    ChangeSetFileContentResponse,
    ChangeSetResponse,
    ChangeSetSelectionRequest,
)
from app.services import team_manager
from app.services.change_set_service import (
    ChangeFileInput,
    ChangeSetError,
    ChangeSetNotFound,
    ChangeSetStale,
    apply_change_set,
    create_change_set,
    get_change_set,
    get_change_file_contents,
    reject_change_set,
    serialize_change_set,
)

router = APIRouter(prefix="/workspace/change-sets")


def _workspace(raw: str) -> Path:
    try:
        return Path(team_manager.validate_workspace(raw)).resolve()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _response(record) -> ChangeSetResponse:
    return ChangeSetResponse.model_validate(serialize_change_set(record))


@router.post("", response_model=ChangeSetResponse, status_code=201)
async def create_change_set_route(
    workspace: str, body: ChangeSetCreateRequest
) -> ChangeSetResponse:
    root = _workspace(workspace)
    try:
        record = create_change_set(
            root,
            origin=body.origin,
            title=body.title,
            description=body.description,
            files=[
                ChangeFileInput(
                    path=item.path,
                    proposed_content=item.proposed_content,
                    base_hash=item.base_hash,
                    document_version=item.document_version,
                )
                for item in body.files
            ],
            workspace_edit=body.workspace_edit,
            verification_commands=body.verification_commands,
        )
    except ChangeSetStale as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "stale_change_set", "paths": exc.paths},
        ) from exc
    except ChangeSetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response(record)


@router.get("/{change_set_id}", response_model=ChangeSetResponse)
async def get_change_set_route(change_set_id: str, workspace: str) -> ChangeSetResponse:
    try:
        return _response(get_change_set(change_set_id, _workspace(workspace)))
    except ChangeSetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChangeSetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/{change_set_id}/files/{path:path}",
    response_model=ChangeSetFileContentResponse,
)
async def get_change_set_file_route(
    change_set_id: str, path: str, workspace: str
) -> ChangeSetFileContentResponse:
    try:
        return ChangeSetFileContentResponse.model_validate(
            get_change_file_contents(change_set_id, _workspace(workspace), path)
        )
    except ChangeSetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChangeSetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{change_set_id}/apply", response_model=ChangeSetResponse)
async def apply_change_set_route(
    change_set_id: str,
    workspace: str,
    body: ChangeSetSelectionRequest,
) -> ChangeSetResponse:
    root = _workspace(workspace)
    try:
        record = await apply_change_set(
            change_set_id,
            root,
            paths=body.paths,
            session_id=body.session_id,
            verify=body.verify,
        )
    except ChangeSetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChangeSetStale as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "stale_change_set", "paths": exc.paths},
        ) from exc
    except ChangeSetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response(record)


@router.post("/{change_set_id}/reject", response_model=ChangeSetResponse)
async def reject_change_set_route(
    change_set_id: str,
    workspace: str,
    body: ChangeSetSelectionRequest,
) -> ChangeSetResponse:
    try:
        record = reject_change_set(
            change_set_id,
            _workspace(workspace),
            paths=body.paths,
        )
    except ChangeSetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChangeSetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _response(record)
