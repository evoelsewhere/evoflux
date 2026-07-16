"""Workflows API (plan §8): list/get/save/delete/approve.

The run/stop/executions endpoints land with the runner (M3) — this module
grows them in place so the router mount stays singular.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.schemas.workflows import (
    WorkflowApproveRequest,
    WorkflowDetailResponse,
    WorkflowListItem,
    WorkflowListResponse,
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
