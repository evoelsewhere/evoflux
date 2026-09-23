"""``/api/skills``: the Settings view of discovered Agent Skills.

Lists every discovered Skill (valid or not), returns bundle content, creates
Skills in the user skills root, edits and deletes editable Skills, and toggles
any Skill on or off. Behavior lives in :mod:`app.services.skills_service`; see
``documents/architecture/agent-skills.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn, Sequence

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas.skills import (
    SkillCreateRequest,
    SkillDeleteResponse,
    SkillDetail,
    SkillEnabledRequest,
    SkillListResponse,
    SkillUpdateRequest,
)
from app.services import skills_service
from app.services.skills_service import (
    SkillBundleError,
    SkillConflictError,
    SkillInvalidError,
    SkillNotFoundError,
    SkillReadOnlyError,
    SkillServiceError,
    SkillTooLargeError,
)

router = APIRouter()

_WORKSPACE_DESCRIPTION = "Repeat for every repository in the active workspace/project."

_STATUS_BY_ERROR: tuple[tuple[type[SkillServiceError], int], ...] = (
    (SkillNotFoundError, 404),
    (SkillReadOnlyError, 403),
    (SkillConflictError, 409),
    (SkillInvalidError, 422),
    (SkillTooLargeError, 413),
    (SkillBundleError, 400),
)


def _raise_http(exc: SkillServiceError) -> NoReturn:
    status = next(
        (code for kind, code in _STATUS_BY_ERROR if isinstance(exc, kind)), 400
    )
    raise HTTPException(status_code=status, detail=exc.message) from exc


def _workspace_paths(workspaces: Sequence[str] | None) -> list[Path]:
    """Resolve explicit API workspace roots without guessing a repository."""

    resolved: list[Path] = []
    seen: set[str] = set()
    for workspace in workspaces or ():
        path = Path(workspace).expanduser().resolve()
        if not path.is_dir():
            raise HTTPException(
                status_code=422,
                detail=f"Workspace does not exist or is not a directory: {path}",
            )
        key = str(path)
        if key not in seen:
            seen.add(key)
            resolved.append(path)
    return resolved


@router.get("")
async def list_skills(
    workspace: list[str] | None = Query(None, description=_WORKSPACE_DESCRIPTION),
) -> SkillListResponse:
    return SkillListResponse(
        skills=skills_service.list_skills(_workspace_paths(workspace))
    )


@router.get("/{name}")
async def get_skill(
    name: str,
    workspace: list[str] | None = Query(None, description=_WORKSPACE_DESCRIPTION),
) -> SkillDetail:
    try:
        return skills_service.get_skill(name, _workspace_paths(workspace))
    except SkillServiceError as exc:
        _raise_http(exc)


@router.post("", status_code=201)
async def create_skill(
    body: SkillCreateRequest,
    workspace: list[str] | None = Query(None, description=_WORKSPACE_DESCRIPTION),
) -> SkillDetail:
    workspaces = _workspace_paths(workspace)
    try:
        return skills_service.create_skill(
            body.name, body.content, body.files, workspaces
        )
    except SkillServiceError as exc:
        _raise_http(exc)


@router.put("/{name}")
async def update_skill(
    name: str,
    body: SkillUpdateRequest,
    workspace: list[str] | None = Query(None, description=_WORKSPACE_DESCRIPTION),
) -> SkillDetail:
    workspaces = _workspace_paths(workspace)
    try:
        return skills_service.update_skill(
            name, body.content, body.files, body.deleted_files, workspaces
        )
    except SkillServiceError as exc:
        _raise_http(exc)


@router.patch("/{name}")
async def set_skill_enabled(
    name: str,
    body: SkillEnabledRequest,
    workspace: list[str] | None = Query(None, description=_WORKSPACE_DESCRIPTION),
) -> SkillDetail:
    workspaces = _workspace_paths(workspace)
    try:
        return skills_service.set_enabled(name, body.enabled, workspaces)
    except SkillServiceError as exc:
        _raise_http(exc)


@router.delete("/{name}")
async def delete_skill(
    name: str,
    workspace: list[str] | None = Query(None, description=_WORKSPACE_DESCRIPTION),
) -> SkillDeleteResponse:
    workspaces = _workspace_paths(workspace)
    try:
        skills_service.delete_skill(name, workspaces)
    except SkillServiceError as exc:
        _raise_http(exc)
    return SkillDeleteResponse(name=name)
