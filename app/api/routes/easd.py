"""Evo Agent Specs (EASD) Coding-mode endpoints."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import DbSessionFactory, WriteDbSession
from app.api.schemas.easd import (
    EasdConvergenceResponse,
    EasdDeviationCreateRequest,
    EasdDeviationOut,
    EasdDeviationResolveRequest,
    EasdEvidenceCreateRequest,
    EasdEvidenceOut,
    EasdGenerateRequest,
    EasdGenerateResponse,
    EasdInitializeRequest,
    EasdPlanRevisionCreateRequest,
    EasdPlanRevisionOut,
    EasdRepositorySetupOut,
    EasdRecoveryExecuteRequest,
    EasdRecoveryExecuteResponse,
    EasdRecoveryPreviewResponse,
    EasdRevisionAcceptRequest,
    EasdRevisionCreateRequest,
    EasdRunCreateRequest,
    EasdRunStartRequest,
    EasdRunDetailResponse,
    EasdRunListResponse,
    EasdRunOut,
    EasdRunTraceResponse,
    EasdSetupResponse,
    EasdSpecRevisionOut,
)
from app.agent.sandbox import SandboxConfig, set_sandbox
from app.models.chat import ChatSession
from app.services import coding_project_service, team_manager
from app.services.easd_generation_service import (
    GenerationRepository,
    generate_scope_and_proof,
)
from app.services.easd_setup_service import (
    EasdRepositoryTarget,
    EasdSetupConflict,
    initialize_repositories,
    inspect_repositories,
)
from app.services.trace_service import (
    TraceConflict,
    TraceConvergenceError,
    TraceNotFound,
    TraceValidationError,
    accept_revision,
    accept_plan_revision,
    build_run_trace,
    converge_run,
    create_deviation,
    create_evidence,
    create_revision,
    create_run,
    create_intent_run,
    create_plan_revision,
    get_run,
    list_runs,
    retry_plan_authoring_in_session,
    retry_spec_authoring_in_session,
    read_run_trace_events,
    read_run_repository_state,
    recover_run_in_session,
    recovery_preview,
    register_run_repository_state,
    resolve_deviation,
    run_detail,
    serialize_deviation,
    serialize_evidence,
    serialize_plan_revision,
    serialize_revision,
    serialize_run,
    start_run_in_session,
    start_plan_authoring_in_session,
    start_review_in_session,
    start_spec_authoring_in_session,
    start_verification_in_session,
)
from app.services import memory_stream_store as stream_store

router = APIRouter()
_RECOVERY_RESULTS: OrderedDict[tuple[UUID, UUID], dict] = OrderedDict()


def _workspace(raw: str) -> str:
    try:
        return team_manager.validate_workspace(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _raise_easd(exc: Exception) -> None:
    if isinstance(exc, TraceNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, TraceConvergenceError):
        raise HTTPException(
            status_code=409,
            detail={"code": "easd_not_converged", "reasons": exc.reasons},
        ) from exc
    if isinstance(exc, TraceConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, TraceValidationError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


async def _repository_targets(
    db_factory: DbSessionFactory,
    *,
    workspace: str,
    project_id: UUID | None,
) -> tuple[str, list[EasdRepositoryTarget]]:
    root = _workspace(workspace)
    if project_id is None:
        path = Path(root)
        return root, [EasdRepositoryTarget(path=root, name=path.name)]

    async with db_factory() as db:
        project = await coding_project_service.get_project(db, project_id)
        if project is None or project.kind != "coding":
            raise HTTPException(status_code=404, detail="Coding project not found")
        pairs = await coding_project_service.get_project_workspaces(db, project_id)

    targets = [
        EasdRepositoryTarget(
            path=_workspace(repository.path),
            name=repository.name or Path(repository.path).name,
            display_name=link.display_name,
        )
        for link, repository in pairs
    ]
    if not targets:
        raise HTTPException(
            status_code=422,
            detail="Coding project has no repository workspaces.",
        )
    if root not in {target.path for target in targets}:
        raise HTTPException(
            status_code=422,
            detail="Workspace does not belong to the selected Coding project.",
        )
    return root, targets


def _setup_response(
    *,
    workspace: str,
    project_id: UUID | None,
    repositories: list[dict],
) -> EasdSetupResponse:
    installed_count = sum(item["installed"] for item in repositories)
    return EasdSetupResponse(
        scope="project" if project_id else "workspace",
        workspace=workspace,
        project_id=project_id,
        ready=installed_count == len(repositories),
        repository_count=len(repositories),
        installed_count=installed_count,
        repositories=[
            EasdRepositorySetupOut.model_validate(item) for item in repositories
        ],
    )


@router.get("/setup", response_model=EasdSetupResponse)
async def get_easd_setup(
    db_factory: DbSessionFactory,
    workspace: str,
    project_id: UUID | None = None,
) -> EasdSetupResponse:
    root, targets = await _repository_targets(
        db_factory,
        workspace=workspace,
        project_id=project_id,
    )
    repositories = await asyncio.to_thread(inspect_repositories, targets)
    return _setup_response(
        workspace=root,
        project_id=project_id,
        repositories=repositories,
    )


@router.post("/setup", response_model=EasdSetupResponse)
async def initialize_easd_setup(
    body: EasdInitializeRequest,
    db_factory: DbSessionFactory,
) -> EasdSetupResponse:
    root, targets = await _repository_targets(
        db_factory,
        workspace=body.workspace,
        project_id=body.project_id,
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
                detail="Repositories are outside the selected EASD scope: "
                + ", ".join(unknown),
            )
        selected = [by_path[path] for path in dict.fromkeys(normalized)]
        if not selected:
            raise HTTPException(
                status_code=422,
                detail="Select at least one repository to initialize.",
            )
    try:
        await asyncio.to_thread(
            initialize_repositories,
            selected,
            data_directory=body.data_directory,
            overwrite=body.overwrite,
        )
        repositories = await asyncio.to_thread(inspect_repositories, targets)
    except EasdSetupConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _setup_response(
        workspace=root,
        project_id=body.project_id,
        repositories=repositories,
    )


@router.post("/generate", response_model=EasdGenerateResponse)
async def generate_easd_scope_and_proof(
    body: EasdGenerateRequest,
    db_factory: DbSessionFactory,
) -> EasdGenerateResponse:
    """Generate a read-only Scope/Proof proposal from authorized code context."""
    root, targets = await _repository_targets(
        db_factory,
        workspace=body.workspace,
        project_id=body.project_id,
    )
    setup = await asyncio.to_thread(inspect_repositories, targets)
    if any(not item["installed"] for item in setup):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "easd_setup_required",
                "repositories": [
                    item["path"] for item in setup if not item["installed"]
                ],
            },
        )
    async with db_factory() as db:
        session = await db.get(ChatSession, body.session_id)
        if session is None or session.mode != "coding":
            raise HTTPException(status_code=404, detail="Coding session not found.")
        if body.project_id is not None:
            if session.project_id != body.project_id:
                raise HTTPException(
                    status_code=409,
                    detail="Coding session belongs to another project.",
                )
        elif not session.workspace or Path(session.workspace).resolve() != Path(root):
            raise HTTPException(
                status_code=409,
                detail="Coding session belongs to another workspace.",
            )
        session_workspace = session.workspace
        session_model = session.model
        session_thinking = session.thinking_level
    if not session_workspace:
        raise HTTPException(status_code=409, detail="Coding session has no workspace.")

    session_id = str(body.session_id)
    team = team_manager.find_team_for_session(session_id)
    if team is None:
        team = await team_manager.get_or_start_coding_team(
            str(Path(session_workspace).resolve()), session_id, mode="coding"
        )
    provider = team.lead.agent.llm_provider
    provider_factory = getattr(team, "_provider_factory", None)
    if session_model and provider_factory is not None:
        model_kwargs: dict[str, object] = {}
        if session_thinking:
            model_kwargs["thinking_level"] = session_thinking
        provider = provider_factory(session_model, model_kwargs=model_kwargs)

    sandbox_token = set_sandbox(SandboxConfig(workspace=root, session_id=session_id))
    try:
        result = await generate_scope_and_proof(
            provider=provider,
            repositories=[
                GenerationRepository(
                    path=Path(target.path),
                    name=target.display_name or target.name,
                )
                for target in targets
            ],
            intent=body.intent,
            target=body.target,
            current_draft=body.current_draft.model_dump(mode="json"),
            clarifications=body.clarifications,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(sandbox_token)
    return EasdGenerateResponse.model_validate(result.model_dump(mode="json"))


@router.get("/runs", response_model=EasdRunListResponse)
async def list_easd_runs(
    db: WriteDbSession,
    workspace: str | None = None,
    project_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
) -> EasdRunListResponse:
    if workspace is None and project_id is None:
        raise HTTPException(
            status_code=422, detail="Provide workspace or project_id for EASD runs."
        )
    rows = await list_runs(
        db,
        workspace=_workspace(workspace) if workspace else None,
        project_id=project_id,
        limit=limit,
    )
    return EasdRunListResponse(
        runs=[EasdRunOut.model_validate(serialize_run(item)) for item in rows]
    )


@router.post(
    "/runs",
    response_model=EasdRunDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_easd_run(
    body: EasdRunCreateRequest,
    db_factory: DbSessionFactory,
) -> EasdRunDetailResponse:
    root, targets = await _repository_targets(
        db_factory,
        workspace=body.workspace,
        project_id=body.project_id,
    )
    repositories = await asyncio.to_thread(inspect_repositories, targets)
    if any(not item["installed"] for item in repositories):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "easd_setup_required",
                "repositories": [
                    item["path"] for item in repositories if not item["installed"]
                ],
            },
        )
    if body.specification is not None:
        allowed_repository_names = {
            target.display_name or target.name for target in targets
        }
        unknown_impact_repositories = sorted(
            {
                item.repository
                for item in body.specification.impact_targets
                if item.repository not in allowed_repository_names
            }
        )
        if unknown_impact_repositories:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Impact targets reference repositories outside the EASD scope: "
                    + ", ".join(unknown_impact_repositories)
                ),
            )
    try:
        async with db_factory() as db:
            if body.specification is not None:
                run = await create_run(
                    db,
                    workspace=root,
                    title=body.specification.title,
                    risk_tier=body.specification.risk_tier,
                    specification=body.specification,
                    authoring=(
                        body.authoring.model_dump(mode="json")
                        if body.authoring
                        else None
                    ),
                    project_id=body.project_id,
                    session_id=body.session_id,
                )
            else:
                assert body.intent is not None
                run = await create_intent_run(
                    db,
                    workspace=root,
                    title=body.intent.title,
                    problem=body.intent.problem,
                    outcome=body.intent.outcome,
                    project_id=body.project_id,
                    session_id=body.session_id,
                )
            response = EasdRunDetailResponse.model_validate(
                await run_detail(db, run.id)
            )
            await db.commit()
        return response
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.get("/runs/{run_id}", response_model=EasdRunDetailResponse)
async def get_easd_run(
    run_id: UUID,
    db: WriteDbSession,
) -> EasdRunDetailResponse:
    try:
        return EasdRunDetailResponse.model_validate(await run_detail(db, run_id))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.get("/runs/{run_id}/trace", response_model=EasdRunTraceResponse)
async def get_easd_run_trace(
    run_id: UUID,
    db_factory: DbSessionFactory,
) -> EasdRunTraceResponse:
    try:
        async with db_factory() as db:
            detail = await run_detail(db, run_id)
        events, diagnostics = await asyncio.to_thread(
            read_run_trace_events,
            detail["run"]["workspace"],
            run_id,
        )
        return EasdRunTraceResponse.model_validate(
            build_run_trace(detail, events=events, diagnostics=diagnostics)
        )
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.get(
    "/runs/{run_id}/recovery",
    response_model=EasdRecoveryPreviewResponse,
)
async def get_easd_recovery(
    run_id: UUID,
    db_factory: DbSessionFactory,
) -> EasdRecoveryPreviewResponse:
    try:
        async with db_factory() as db:
            run = await get_run(db, run_id)
            preview = await recovery_preview(db, run_id)
        repository_state = await asyncio.to_thread(
            read_run_repository_state,
            run.workspace,
            run_id,
        )
        register_run_repository_state(run_id, repository_state)
        preview["store_generation"] = repository_state["store_generation"]
        return EasdRecoveryPreviewResponse.model_validate(preview)
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post(
    "/runs/{run_id}/recovery",
    response_model=EasdRecoveryExecuteResponse,
)
async def execute_easd_recovery(
    run_id: UUID,
    body: EasdRecoveryExecuteRequest,
    db_factory: DbSessionFactory,
) -> EasdRecoveryExecuteResponse:
    cache_key = (run_id, body.idempotency_key)
    cached = _RECOVERY_RESULTS.get(cache_key)
    if cached is not None:
        _RECOVERY_RESULTS.move_to_end(cache_key)
        if cached["recovery"]["id"] != body.action_id:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key belongs to another recovery action",
            )
        return EasdRecoveryExecuteResponse.model_validate(cached)
    try:
        async with db_factory() as db:
            existing_run = await get_run(db, run_id)
        repository_state = await asyncio.to_thread(
            read_run_repository_state,
            existing_run.workspace,
            run_id,
        )
        register_run_repository_state(run_id, repository_state)
        if body.expected_generation != repository_state["store_generation"]:
            raise TraceConflict(
                "EASD repository generation changed; refresh Recovery before retrying"
            )
        async with db_factory() as db:
            run, recovery = await recover_run_in_session(
                db,
                run_id=run_id,
                action_id=body.action_id,
                session_id=body.session_id,
                expected_generation=body.expected_generation,
            )
            response = EasdRecoveryExecuteResponse.model_validate(
                {"run": serialize_run(run), "recovery": recovery}
            )
            await db.commit()
        payload = response.model_dump(mode="json")
        _RECOVERY_RESULTS[cache_key] = payload
        if len(_RECOVERY_RESULTS) > 512:
            _RECOVERY_RESULTS.popitem(last=False)
        return response
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post(
    "/runs/{run_id}/revisions",
    response_model=EasdSpecRevisionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_easd_revision(
    run_id: UUID,
    body: EasdRevisionCreateRequest,
    db: WriteDbSession,
) -> EasdSpecRevisionOut:
    try:
        revision = await create_revision(
            db,
            run_id=run_id,
            specification=body.specification,
            authoring=(
                body.authoring.model_dump(mode="json") if body.authoring else None
            ),
        )
        return EasdSpecRevisionOut.model_validate(serialize_revision(revision))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post(
    "/runs/{run_id}/revisions/{revision_id}/accept",
    response_model=EasdSpecRevisionOut,
)
async def accept_easd_revision(
    run_id: UUID,
    revision_id: UUID,
    body: EasdRevisionAcceptRequest,
    db: WriteDbSession,
) -> EasdSpecRevisionOut:
    try:
        revision = await accept_revision(
            db,
            run_id=run_id,
            revision_id=revision_id,
            expected_hash=body.expected_hash,
        )
        return EasdSpecRevisionOut.model_validate(serialize_revision(revision))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post(
    "/runs/{run_id}/plans",
    response_model=EasdPlanRevisionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_easd_plan_revision(
    run_id: UUID,
    body: EasdPlanRevisionCreateRequest,
    db: WriteDbSession,
) -> EasdPlanRevisionOut:
    try:
        revision = await create_plan_revision(db, run_id=run_id, plan=body.plan)
        return EasdPlanRevisionOut.model_validate(serialize_plan_revision(revision))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post(
    "/runs/{run_id}/plans/{revision_id}/accept",
    response_model=EasdPlanRevisionOut,
)
async def accept_easd_plan_revision(
    run_id: UUID,
    revision_id: UUID,
    body: EasdRevisionAcceptRequest,
    db: WriteDbSession,
) -> EasdPlanRevisionOut:
    try:
        revision = await accept_plan_revision(
            db,
            run_id=run_id,
            revision_id=revision_id,
            expected_hash=body.expected_hash,
        )
        return EasdPlanRevisionOut.model_validate(serialize_plan_revision(revision))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


def _require_idle_chat(session_id: UUID) -> None:
    if str(session_id) in stream_store.running_session_ids():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "easd_chat_busy",
                "message": "Wait for the Coding chat's current turn to finish.",
            },
        )


@router.post("/runs/{run_id}/planning/start", response_model=EasdRunOut)
async def start_easd_planning(
    run_id: UUID,
    body: EasdRunStartRequest,
    db: WriteDbSession,
) -> EasdRunOut:
    _require_idle_chat(body.session_id)
    try:
        run = await start_plan_authoring_in_session(
            db,
            run_id=run_id,
            session_id=body.session_id,
        )
        return EasdRunOut.model_validate(serialize_run(run))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post("/runs/{run_id}/planning/retry", response_model=EasdRunOut)
async def retry_easd_planning(
    run_id: UUID,
    body: EasdRunStartRequest,
    db: WriteDbSession,
) -> EasdRunOut:
    _require_idle_chat(body.session_id)
    try:
        run = await retry_plan_authoring_in_session(
            db,
            run_id=run_id,
            session_id=body.session_id,
        )
        return EasdRunOut.model_validate(serialize_run(run))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post("/runs/{run_id}/start", response_model=EasdRunOut)
async def start_easd_run_in_chat(
    run_id: UUID,
    body: EasdRunStartRequest,
    db: WriteDbSession,
) -> EasdRunOut:
    _require_idle_chat(body.session_id)
    try:
        run = await start_run_in_session(db, run_id=run_id, session_id=body.session_id)
        return EasdRunOut.model_validate(serialize_run(run))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post("/runs/{run_id}/authoring/start", response_model=EasdRunOut)
async def start_easd_spec_authoring(
    run_id: UUID,
    body: EasdRunStartRequest,
    db: WriteDbSession,
) -> EasdRunOut:
    _require_idle_chat(body.session_id)
    try:
        run = await start_spec_authoring_in_session(
            db,
            run_id=run_id,
            session_id=body.session_id,
        )
        return EasdRunOut.model_validate(serialize_run(run))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post("/runs/{run_id}/authoring/retry", response_model=EasdRunOut)
async def retry_easd_spec_authoring(
    run_id: UUID,
    body: EasdRunStartRequest,
    db: WriteDbSession,
) -> EasdRunOut:
    _require_idle_chat(body.session_id)
    try:
        run = await retry_spec_authoring_in_session(
            db,
            run_id=run_id,
            session_id=body.session_id,
        )
        return EasdRunOut.model_validate(serialize_run(run))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post("/runs/{run_id}/review/start", response_model=EasdRunOut)
async def start_easd_review(
    run_id: UUID,
    body: EasdRunStartRequest,
    db: WriteDbSession,
) -> EasdRunOut:
    _require_idle_chat(body.session_id)
    try:
        run = await start_review_in_session(
            db,
            run_id=run_id,
            session_id=body.session_id,
        )
        return EasdRunOut.model_validate(serialize_run(run))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post("/runs/{run_id}/verification/start", response_model=EasdRunOut)
async def start_easd_verification(
    run_id: UUID,
    body: EasdRunStartRequest,
    db: WriteDbSession,
) -> EasdRunOut:
    _require_idle_chat(body.session_id)
    try:
        run = await start_verification_in_session(
            db,
            run_id=run_id,
            session_id=body.session_id,
        )
        return EasdRunOut.model_validate(serialize_run(run))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post(
    "/runs/{run_id}/evidence",
    response_model=EasdEvidenceOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_easd_evidence(
    run_id: UUID,
    body: EasdEvidenceCreateRequest,
    db: WriteDbSession,
) -> EasdEvidenceOut:
    payload = dict(body.payload)
    if body.kind == "review":
        for reserved in (
            "runtime_reviewer_identity",
            "reviewer_role",
            "independent",
        ):
            payload.pop(reserved, None)
    try:
        evidence = await create_evidence(
            db,
            run_id=run_id,
            spec_hash=body.spec_hash,
            criterion_ids=body.criterion_ids,
            producer=body.producer,
            kind=body.kind,
            result=body.result,
            summary=body.summary,
            delegation_task_id=body.delegation_task_id,
            revision=body.revision,
            artifact_hash=body.artifact_hash,
            payload=payload,
            source_key=body.source_key,
        )
        return EasdEvidenceOut.model_validate(serialize_evidence(evidence))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.post(
    "/runs/{run_id}/deviations",
    response_model=EasdDeviationOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_easd_deviation(
    run_id: UUID,
    body: EasdDeviationCreateRequest,
    db: WriteDbSession,
) -> EasdDeviationOut:
    try:
        deviation = await create_deviation(
            db,
            run_id=run_id,
            description=body.description,
            blocking=body.blocking,
            criterion_id=body.criterion_id,
            delegation_task_id=body.delegation_task_id,
            proposed_change=body.proposed_change,
        )
        return EasdDeviationOut.model_validate(serialize_deviation(deviation))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


@router.patch(
    "/runs/{run_id}/deviations/{deviation_id}",
    response_model=EasdDeviationOut,
)
async def resolve_easd_deviation(
    run_id: UUID,
    deviation_id: UUID,
    body: EasdDeviationResolveRequest,
    db: WriteDbSession,
) -> EasdDeviationOut:
    try:
        deviation = await resolve_deviation(
            db,
            run_id=run_id,
            deviation_id=deviation_id,
            status=body.status,
            resolution=body.resolution,
            resolved_spec_hash=body.resolved_spec_hash,
        )
        return EasdDeviationOut.model_validate(serialize_deviation(deviation))
    except (TraceNotFound, TraceConflict, TraceValidationError) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


async def _git_revision(workspace: str) -> str | None:
    root = Path(workspace)
    if not (root / ".git").exists():
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(root),
            "rev-parse",
            "HEAD",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except (OSError, TimeoutError):
        return None
    if proc.returncode != 0:
        return None
    value = stdout.decode("utf-8", errors="replace").strip()
    return value or None


@router.post(
    "/runs/{run_id}/converge",
    response_model=EasdConvergenceResponse,
)
async def converge_easd_run(
    run_id: UUID,
    db_factory: DbSessionFactory,
) -> EasdConvergenceResponse:
    try:
        async with db_factory() as read_db:
            run = await get_run(read_db, run_id)
            workspace = run.workspace
        git_revision = await _git_revision(workspace)
        async with db_factory() as write_db:
            report = await converge_run(
                write_db,
                run_id=run_id,
                git_revision=git_revision,
            )
            await write_db.commit()
        return EasdConvergenceResponse(report=report)
    except (
        TraceNotFound,
        TraceConflict,
        TraceValidationError,
        TraceConvergenceError,
    ) as exc:
        _raise_easd(exc)
        raise AssertionError("unreachable")


__all__ = ["router"]
