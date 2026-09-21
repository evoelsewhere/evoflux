"""Agent Spec-Driven (ASDD) Coding-mode endpoints.

Thin by construction: every route resolves a repository, does filesystem work
off the event loop, and maps one ASDD error class to one status code. There is
no transaction to manage and no row to lock, because the catalogue these routes
serve is the repository's own working tree.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.api.deps import DbSessionFactory
from app.api.schemas.asdd import (
    AsddActionRequest,
    AsddApproveRequest,
    AsddArchiveResponse,
    AsddArtifact,
    AsddAutopilotRequest,
    AsddChangeActionResponse,
    AsddChangeCreateRequest,
    AsddChangeDetailResponse,
    AsddChangeListResponse,
    AsddEvidenceCreateRequest,
    AsddInitializeRequest,
    AsddRepositorySetupOut,
    AsddSetupResponse,
    AsddSpecListResponse,
    AsddSpecOut,
)
from app.services import coding_project_service, team_manager
from app.services.asdd_service import (
    AsddActionBlocked,
    archive,
    catalogue_for,
    create_change,
    detail_payload,
    list_changes_across,
    mark_ready,
    prepare_action,
    record_evidence,
    set_autopilot,
    spec_payload,
)
from app.services.asdd_service import approve as approve_artifact
from app.services.asdd_setup_service import (
    AsddRepositoryTarget,
    AsddSetupConflict,
    initialize_repositories,
    inspect_repositories,
)
from app.services.asdd_store import (
    AsddChangeExists,
    AsddChangeNotFound,
    AsddStoreError,
)

router = APIRouter()


def _workspace(raw: str) -> str:
    try:
        return team_manager.validate_workspace(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _raise_asdd(exc: Exception) -> None:
    """Map one ASDD failure to one status code.

    `AsddActionBlocked` carries the blockers the rail already showed, so a client
    that raced the UI gets the same explanation rather than a bare 409.
    """

    if isinstance(exc, AsddChangeNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, AsddChangeExists):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, AsddActionBlocked):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "asdd_action_blocked",
                "message": str(exc),
                "blockers": exc.blockers,
            },
        ) from exc
    if isinstance(exc, AsddStoreError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


async def _repository_targets(
    db_factory: DbSessionFactory,
    *,
    workspace: str,
    project_id: UUID | None,
) -> tuple[str, list[AsddRepositoryTarget]]:
    root = _workspace(workspace)
    if project_id is None:
        return root, [AsddRepositoryTarget(path=root, name=Path(root).name)]

    async with db_factory() as db:
        project = await coding_project_service.get_project(db, project_id)
        if project is None or project.kind != "coding":
            raise HTTPException(status_code=404, detail="Coding project not found")
        pairs = await coding_project_service.get_project_workspaces(db, project_id)

    targets = [
        AsddRepositoryTarget(
            path=_workspace(repository.path),
            name=repository.name or Path(repository.path).name,
            display_name=link.display_name,
        )
        for link, repository in pairs
    ]
    if not targets:
        raise HTTPException(
            status_code=422, detail="Coding project has no repository workspaces."
        )
    if root not in {target.path for target in targets}:
        raise HTTPException(
            status_code=422,
            detail="Workspace does not belong to the selected Coding project.",
        )
    return root, targets


def _setup_response(
    *, workspace: str, project_id: UUID | None, repositories: list[dict]
) -> AsddSetupResponse:
    installed_count = sum(item["installed"] for item in repositories)
    return AsddSetupResponse(
        scope="project" if project_id else "workspace",
        workspace=workspace,
        project_id=project_id,
        workspace_ready=any(
            item["installed"] and item["path"] == workspace for item in repositories
        ),
        ready=installed_count == len(repositories),
        repository_count=len(repositories),
        installed_count=installed_count,
        repositories=[
            AsddRepositorySetupOut.model_validate(item) for item in repositories
        ],
    )


# --- setup ---------------------------------------------------------------


@router.get("/setup", response_model=AsddSetupResponse)
async def get_asdd_setup(
    db_factory: DbSessionFactory,
    workspace: str,
    project_id: UUID | None = None,
) -> AsddSetupResponse:
    root, targets = await _repository_targets(
        db_factory, workspace=workspace, project_id=project_id
    )
    repositories = await asyncio.to_thread(inspect_repositories, targets)
    return _setup_response(
        workspace=root, project_id=project_id, repositories=repositories
    )


@router.post("/setup", response_model=AsddSetupResponse)
async def initialize_asdd_setup(
    body: AsddInitializeRequest,
    db_factory: DbSessionFactory,
) -> AsddSetupResponse:
    root, targets = await _repository_targets(
        db_factory, workspace=body.workspace, project_id=body.project_id
    )
    by_path = {target.path: target for target in targets}
    if body.repository_paths is None:
        selected = targets
    else:
        normalized = [_workspace(path) for path in body.repository_paths]
        unknown = sorted(set(normalized) - set(by_path))
        if unknown:
            raise HTTPException(
                status_code=422,
                detail="Repositories are outside the selected ASDD scope: "
                + ", ".join(unknown),
            )
        selected = [by_path[path] for path in dict.fromkeys(normalized)]
        if not selected:
            raise HTTPException(
                status_code=422, detail="Select at least one repository to initialize."
            )
    try:
        await asyncio.to_thread(
            initialize_repositories,
            selected,
            data_directory=body.data_directory,
            overwrite=body.overwrite,
        )
        repositories = await asyncio.to_thread(inspect_repositories, targets)
    except AsddSetupConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _setup_response(
        workspace=root, project_id=body.project_id, repositories=repositories
    )


# --- changes -------------------------------------------------------------


@router.get("/changes", response_model=AsddChangeListResponse)
async def list_asdd_changes(
    db_factory: DbSessionFactory,
    workspace: str,
    project_id: UUID | None = None,
) -> AsddChangeListResponse:
    """Every change in scope: one repository, or a whole Coding project.

    A project session opens on one of its repositories, and a change filed in
    a sibling used to be invisible from it — the board read the session's
    repository and nothing else, so a project whose work lives next door
    looked like a project with no changes at all.
    """
    root, targets = await _repository_targets(
        db_factory, workspace=workspace, project_id=project_id
    )
    payload = await asyncio.to_thread(
        list_changes_across, [target.path for target in targets], workspace=root
    )
    return AsddChangeListResponse(project_id=project_id, **payload)


@router.post("/changes", response_model=AsddChangeDetailResponse, status_code=201)
async def create_asdd_change(body: AsddChangeCreateRequest) -> AsddChangeDetailResponse:
    catalogue = catalogue_for(_workspace(body.workspace))
    try:
        record = await asyncio.to_thread(
            create_change,
            catalogue,
            title=body.title,
            change_id=body.change_id,
            risk=body.risk,
            capabilities=body.capabilities,
            problem=body.problem,
            outcome=body.outcome,
        )
    except AsddStoreError as exc:
        _raise_asdd(exc)
        raise AssertionError("unreachable")
    return AsddChangeDetailResponse.model_validate(detail_payload(catalogue, record))


@router.get("/changes/{change_id}", response_model=AsddChangeDetailResponse)
async def get_asdd_change(change_id: str, workspace: str) -> AsddChangeDetailResponse:
    catalogue = catalogue_for(_workspace(workspace))
    try:
        record = await asyncio.to_thread(catalogue.read_change, change_id)
    except AsddStoreError as exc:
        _raise_asdd(exc)
        raise AssertionError("unreachable")
    return AsddChangeDetailResponse.model_validate(detail_payload(catalogue, record))


@router.delete("/changes/{change_id}", status_code=204)
async def delete_asdd_change(change_id: str, workspace: str) -> None:
    catalogue = catalogue_for(_workspace(workspace))
    try:
        await asyncio.to_thread(catalogue.delete_change, change_id)
    except AsddStoreError as exc:
        _raise_asdd(exc)


@router.post(
    "/changes/{change_id}/approve/{artifact}",
    response_model=AsddChangeDetailResponse,
)
async def approve_asdd_artifact(
    change_id: str,
    artifact: AsddArtifact,
    body: AsddApproveRequest,
) -> AsddChangeDetailResponse:
    catalogue = catalogue_for(_workspace(body.workspace))
    try:
        record = await asyncio.to_thread(
            approve_artifact, catalogue, change_id, artifact, note=body.note
        )
    except AsddStoreError as exc:
        _raise_asdd(exc)
        raise AssertionError("unreachable")
    return AsddChangeDetailResponse.model_validate(detail_payload(catalogue, record))


@router.post(
    "/changes/{change_id}/actions/{action}",
    response_model=AsddChangeActionResponse,
)
async def start_asdd_action(
    change_id: str,
    action: str,
    body: AsddActionRequest,
) -> AsddChangeActionResponse:
    catalogue = catalogue_for(_workspace(body.workspace))
    try:
        record, prompt, skill = await asyncio.to_thread(
            prepare_action, catalogue, change_id, action
        )
    except AsddStoreError as exc:
        _raise_asdd(exc)
        raise AssertionError("unreachable")
    detail = detail_payload(catalogue, record)
    return AsddChangeActionResponse(
        change=detail["change"], rail=detail["rail"], prompt=prompt, skill=skill
    )


@router.post("/changes/{change_id}/autopilot", response_model=AsddChangeDetailResponse)
async def set_asdd_autopilot(
    change_id: str, body: AsddAutopilotRequest
) -> AsddChangeDetailResponse:
    catalogue = catalogue_for(_workspace(body.workspace))
    try:
        record = await asyncio.to_thread(
            set_autopilot, catalogue, change_id, enabled=body.enabled
        )
    except AsddStoreError as exc:
        _raise_asdd(exc)
        raise AssertionError("unreachable")
    return AsddChangeDetailResponse.model_validate(detail_payload(catalogue, record))


@router.post("/changes/{change_id}/ready", response_model=AsddChangeDetailResponse)
async def mark_asdd_change_ready(
    change_id: str, body: AsddApproveRequest
) -> AsddChangeDetailResponse:
    catalogue = catalogue_for(_workspace(body.workspace))
    try:
        record = await asyncio.to_thread(mark_ready, catalogue, change_id)
    except AsddStoreError as exc:
        _raise_asdd(exc)
        raise AssertionError("unreachable")
    return AsddChangeDetailResponse.model_validate(detail_payload(catalogue, record))


@router.post("/changes/{change_id}/archive", response_model=AsddArchiveResponse)
async def archive_asdd_change(
    change_id: str, body: AsddApproveRequest
) -> AsddArchiveResponse:
    catalogue = catalogue_for(_workspace(body.workspace))
    try:
        result = await asyncio.to_thread(archive, catalogue, change_id)
    except AsddStoreError as exc:
        _raise_asdd(exc)
        raise AssertionError("unreachable")
    return AsddArchiveResponse.model_validate(result)


@router.post(
    "/changes/{change_id}/evidence",
    response_model=AsddChangeDetailResponse,
    status_code=201,
)
async def record_asdd_evidence(
    change_id: str, body: AsddEvidenceCreateRequest
) -> AsddChangeDetailResponse:
    catalogue = catalogue_for(_workspace(body.workspace))
    try:
        record = await asyncio.to_thread(
            record_evidence,
            catalogue,
            change_id,
            evidence_id=body.evidence_id,
            kind=body.kind,
            result=body.result,
            summary=body.summary,
            requirement=body.requirement,
            body=body.body,
        )
    except AsddStoreError as exc:
        _raise_asdd(exc)
        raise AssertionError("unreachable")
    return AsddChangeDetailResponse.model_validate(detail_payload(catalogue, record))


# --- specs ---------------------------------------------------------------


@router.get("/specs", response_model=AsddSpecListResponse)
async def list_asdd_specs(workspace: str) -> AsddSpecListResponse:
    catalogue = catalogue_for(_workspace(workspace))
    capabilities = await asyncio.to_thread(catalogue.list_capabilities)
    return AsddSpecListResponse(
        workspace=str(catalogue.root), capabilities=capabilities
    )


@router.get("/specs/{capability}", response_model=AsddSpecOut)
async def get_asdd_spec(capability: str, workspace: str) -> AsddSpecOut:
    catalogue = catalogue_for(_workspace(workspace))
    try:
        payload = await asyncio.to_thread(spec_payload, catalogue, capability)
    except AsddStoreError as exc:
        _raise_asdd(exc)
        raise AssertionError("unreachable")
    if payload is None:
        raise HTTPException(
            status_code=404, detail=f"No spec for capability '{capability}'"
        )
    return AsddSpecOut.model_validate(payload)
