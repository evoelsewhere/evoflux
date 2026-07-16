"""Workflows API (plan §8): list/get/save/delete/approve.

The run/stop/executions endpoints land with the runner (M3) — this module
grows them in place so the router mount stays singular.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from uuid import UUID

from app.api.schemas.workflows import (
    WorkflowApproveRequest,
    WorkflowDetailResponse,
    WorkflowExecutionDetailResponse,
    WorkflowExecutionListResponse,
    WorkflowExecutionOut,
    WorkflowListItem,
    WorkflowListResponse,
    WorkflowNodeRunOut,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowSaveRequest,
)
from app.models.workflow import WorkflowApproval
from app.services import workflows_fs
from app.services.workflows_fs import DiscoveredWorkflow
from app.workflow import registry as wf_registry
from app.workflow.graph import validate_dag
from app.workflow.models import (
    DefinitionError,
    WorkflowDefinition,
    dump_definition_yaml,
    parse_definition,
    validate_environment,
)
from app.workflow.policy import compute_manifest, content_hash, destructive_lint

router = APIRouter()


async def _db() -> AsyncSession:
    from app.core import db as db_module

    async with db_module.async_session_factory() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(_db)]


def _full_errors(found: DiscoveredWorkflow) -> list[str]:
    """File errors + DAG + environment errors for a discovered workflow."""
    errors = list(found.errors)
    if found.definition is not None:
        errors += validate_dag(found.definition)
        errors += validate_environment(
            found.definition,
            known_tools=wf_registry.known_tool_names(),
            known_blueprints=set(wf_registry.member_blueprints(found.definition.scope)),
        )
    return errors


async def _approved_hashes(db: AsyncSession) -> set[str]:
    rows = await db.exec(select(WorkflowApproval.definition_hash))
    return set(rows.all())


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    db: DbSession, workspace: str | None = None
) -> WorkflowListResponse:
    approved = await _approved_hashes(db)
    items: list[WorkflowListItem] = []
    for found in workflows_fs.discover_workflows(workspace):
        file_hash = content_hash(found.raw_yaml.encode("utf-8"))
        errors = _full_errors(found)
        definition = found.definition
        items.append(
            WorkflowListItem(
                name=found.name,
                description=definition.description if definition else "",
                scope=definition.scope if definition else "forge",
                inputs=[
                    inp.model_dump()
                    for inp in (definition.inputs if definition else [])
                ],
                hash=file_hash,
                root=found.root,
                source_path=str(found.path),
                approved=file_hash in approved,
                valid=not errors,
                errors=errors,
                node_count=len(definition.nodes) if definition else 0,
            )
        )
    return WorkflowListResponse(workflows=items)


def _detail(found: DiscoveredWorkflow, approved: set[str]) -> WorkflowDetailResponse:
    file_hash = content_hash(found.raw_yaml.encode("utf-8"))
    errors = _full_errors(found)
    definition = found.definition
    manifest: dict = {}
    lint: list[str] = []
    graph: dict = {}
    if definition is not None:
        blueprint_tools = wf_registry.member_blueprints(definition.scope)
        manifest = compute_manifest(definition, blueprint_tools=blueprint_tools)
        lint = destructive_lint(
            definition,
            blueprint_tools=blueprint_tools,
            lead_tools=wf_registry.lead_tools(definition.scope),
        )
        graph = definition.model_dump(by_alias=True, exclude_none=True)
    return WorkflowDetailResponse(
        name=found.name,
        raw_yaml=found.raw_yaml,
        graph=graph,
        hash=file_hash,
        root=found.root,
        scope=definition.scope if definition else None,
        approved=file_hash in approved,
        manifest=manifest,
        lint_warnings=lint,
        errors=errors,
    )


# NOTE: registered before ``GET /{name}`` so the literal path wins the match.
@router.get("/executions", response_model=WorkflowExecutionListResponse)
async def list_executions_route(
    db: DbSession, session_ids: str = ""
) -> WorkflowExecutionListResponse:
    """Latest-first executions for a comma-separated list of session ids.

    Powers the AIM Pipelines run table: the FE joins its per-run sessions
    with real execution status (running/waiting_gate/completed/failed)
    in one call instead of N polls.
    """
    from app.models.workflow import WorkflowExecution

    ids: list[UUID] = []
    for raw in session_ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            ids.append(UUID(raw))
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid session id: {raw}"
            ) from exc
    if not ids:
        return WorkflowExecutionListResponse(executions=[])
    rows = await db.exec(
        select(WorkflowExecution)
        .where(col(WorkflowExecution.session_id).in_(ids))
        .order_by(
            col(WorkflowExecution.started_at).desc(),
            col(WorkflowExecution.id).desc(),
        )
        .limit(200)
    )
    return WorkflowExecutionListResponse(
        executions=[_execution_out(row) for row in rows.all()]
    )


def _execution_out(row) -> WorkflowExecutionOut:  # noqa: ANN001 — WorkflowExecution
    from app.workflow.runner import runner as workflow_runner

    out = WorkflowExecutionOut.model_validate(row, from_attributes=True)
    out.live = any(
        state.execution_id == row.id for state in workflow_runner.active.values()
    )
    return out


@router.get("/{name}", response_model=WorkflowDetailResponse)
async def get_workflow_detail(
    name: str, db: DbSession, workspace: str | None = None
) -> WorkflowDetailResponse:
    found = workflows_fs.get_workflow(name, workspace)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No workflow named '{name}'.")
    return _detail(found, await _approved_hashes(db))


@router.put("/{name}", response_model=WorkflowDetailResponse)
async def save_workflow_route(
    name: str,
    body: WorkflowSaveRequest,
    db: DbSession,
    workspace: str | None = None,
) -> WorkflowDetailResponse:
    if (body.raw_yaml is None) == (body.graph is None):
        raise HTTPException(
            status_code=422, detail="Provide exactly one of raw_yaml or graph."
        )
    if body.raw_yaml is not None:
        raw_yaml = body.raw_yaml
        try:
            definition = parse_definition(raw_yaml)
        except DefinitionError as exc:
            raise HTTPException(status_code=422, detail=exc.errors)
    else:
        try:
            definition = WorkflowDefinition.model_validate(body.graph)
        except DefinitionError as exc:
            raise HTTPException(status_code=422, detail=exc.errors)
        except Exception as exc:  # pydantic ValidationError
            raise HTTPException(status_code=422, detail=[str(exc)])
        raw_yaml = dump_definition_yaml(definition)

    if definition.name != name:
        raise HTTPException(
            status_code=422,
            detail=[
                f"URL says '{name}' but the definition declares "
                f"'{definition.name}' — they must match."
            ],
        )
    dag_errors = validate_dag(definition)
    if dag_errors:
        raise HTTPException(status_code=422, detail=dag_errors)
    env_errors = validate_environment(
        definition,
        known_tools=wf_registry.known_tool_names(),
        known_blueprints=set(wf_registry.member_blueprints(definition.scope)),
    )
    if env_errors:
        raise HTTPException(status_code=422, detail=env_errors)

    saved = workflows_fs.save_workflow(name, raw_yaml, workspace=workspace)
    return _detail(saved, await _approved_hashes(db))


@router.delete("/{name}", status_code=204)
async def delete_workflow_route(name: str, workspace: str | None = None) -> None:
    if not workflows_fs.delete_workflow(name, workspace=workspace):
        raise HTTPException(
            status_code=404,
            detail=f"No editable workflow named '{name}' (builtin files "
            f"can't be deleted).",
        )


@router.post("/{name}/approve", status_code=204)
async def approve_workflow_route(
    name: str,
    body: WorkflowApproveRequest,
    db: DbSession,
    workspace: str | None = None,
) -> None:
    found = workflows_fs.get_workflow(name, workspace)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No workflow named '{name}'.")
    current_hash = content_hash(found.raw_yaml.encode("utf-8"))
    if body.hash != current_hash:
        raise HTTPException(
            status_code=409,
            detail="The file changed since you reviewed it — reload and "
            "approve the current version.",
        )
    if found.definition is None:
        raise HTTPException(
            status_code=422, detail="An invalid definition can't be approved."
        )
    existing = await db.get(WorkflowApproval, current_hash)
    if existing is None:
        root = found.root
        if root == "workspace":
            root = f"workspace:{found.path.parent.parent.parent}"
        db.add(
            WorkflowApproval(
                definition_hash=current_hash,
                name=name,
                root=root,
                manifest=compute_manifest(
                    found.definition,
                    blueprint_tools=wf_registry.member_blueprints(
                        found.definition.scope
                    ),
                ),
            )
        )
        await db.commit()


async def is_approved(db: AsyncSession, raw_yaml: str) -> bool:
    """Shared with the runner's /run gate (M3)."""
    file_hash = content_hash(raw_yaml.encode("utf-8"))
    row = await db.exec(
        select(WorkflowApproval).where(
            col(WorkflowApproval.definition_hash) == file_hash
        )
    )
    return row.first() is not None


# ── run / stop / executions (M3, plan §6.2, §6.5, §8) ────────────────────────


def _coerce_inputs(definition: WorkflowDefinition, provided: dict) -> dict:
    """Validate + coerce trigger inputs against the declared schema.
    Raises HTTPException 422 listing every problem."""
    errors: list[str] = []
    values: dict = {}
    declared = {inp.name: inp for inp in definition.inputs}
    for name in provided:
        if name not in declared:
            errors.append(f"unknown input '{name}'.")
    for name, spec in declared.items():
        raw = provided.get(name, spec.default)
        if raw is None:
            if spec.required:
                errors.append(f"input '{name}' is required.")
            continue
        try:
            if spec.type == "number":
                values[name] = float(raw) if "." in str(raw) else int(raw)
            elif spec.type == "boolean":
                values[name] = (
                    raw
                    if isinstance(raw, bool)
                    else str(raw).lower() in ("1", "true", "yes")
                )
            elif spec.type == "enum":
                if str(raw) not in (spec.options or []):
                    errors.append(
                        f"input '{name}': '{raw}' not in {spec.options}."
                    )
                    continue
                values[name] = str(raw)
            else:
                values[name] = str(raw)
        except (TypeError, ValueError):
            errors.append(f"input '{name}': can't coerce '{raw}' to {spec.type}.")
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return values


@router.post("/{name}/run", response_model=WorkflowRunResponse)
async def run_workflow_route(
    name: str,
    body: WorkflowRunRequest,
    db: DbSession,
    workspace: str | None = None,
) -> WorkflowRunResponse:
    from uuid import UUID as _UUID

    from app.models.chat import ChatSession
    from app.workflow.runner import runner

    try:
        session_uuid = _UUID(body.session_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="session_id must be a UUID.")
    session = await db.get(ChatSession, session_uuid)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    # Discovery is workspace-relative: prefer the caller's explicit
    # workspace, else the session's own (so coding/aim sessions see their
    # repo-local definitions).
    found = workflows_fs.get_workflow(name, workspace or session.workspace)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No workflow named '{name}'.")
    errors = _full_errors(found)
    if found.definition is None or errors:
        raise HTTPException(status_code=422, detail=errors or ["invalid definition"])
    definition = found.definition

    if definition.has_phase2_nodes():
        raise HTTPException(
            status_code=422, detail="sub-workflows/wait arrive in Phase 2."
        )

    file_hash = content_hash(found.raw_yaml.encode("utf-8"))
    if file_hash not in await _approved_hashes(db):
        raise HTTPException(
            status_code=403,
            detail=f"'{name}' is not approved — review and approve it first.",
        )

    # Scope rules (§6.2 + aim extension): forge runs anywhere; coding/aim
    # definitions require a session of that mode, whose pinned workspace IS
    # the target.
    scope_workspace: str | None = None
    if definition.scope in ("coding", "aim"):
        if session.mode != definition.scope:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"'{name}' is a {definition.scope}-scope workflow — open "
                    f"it in a {definition.scope} session."
                ),
            )
        if not session.workspace:
            raise HTTPException(
                status_code=422, detail="The session has no workspace bound."
            )
        scope_workspace = session.workspace

    if runner.is_driving(body.session_id):
        raise HTTPException(
            status_code=409, detail="An execution is already active in this session."
        )

    inputs = _coerce_inputs(definition, body.inputs)
    state = await runner.start(
        definition,
        definition_hash=file_hash,
        session_id=body.session_id,
        inputs=inputs,
        scope_workspace=scope_workspace,
    )
    return WorkflowRunResponse(
        execution_id=state.execution_id, session_id=body.session_id
    )


@router.post("/executions/{execution_id}/stop", status_code=204)
async def stop_execution_route(execution_id: UUID) -> None:
    from app.workflow.runner import runner

    if not await runner.stop(execution_id):
        raise HTTPException(status_code=404, detail="No active execution with that id.")


@router.get("/executions/{execution_id}", response_model=WorkflowExecutionDetailResponse)
async def get_execution_route(
    execution_id: UUID, db: DbSession
) -> WorkflowExecutionDetailResponse:
    from app.models.workflow import WorkflowExecution, WorkflowNodeRun

    execution = await db.get(WorkflowExecution, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found.")
    rows = await db.exec(
        select(WorkflowNodeRun)
        .where(col(WorkflowNodeRun.execution_id) == execution_id)
        .order_by(col(WorkflowNodeRun.started_at))
    )
    return WorkflowExecutionDetailResponse(
        execution=_execution_out(execution),
        node_runs=[
            WorkflowNodeRunOut.model_validate(row, from_attributes=True)
            for row in rows.all()
        ],
    )
