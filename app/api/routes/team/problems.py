"""Unified coding Problems endpoint."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.schemas.problems import ProblemResponse, ProblemsResponse
from app.plugin_platform import inspect_plugin, list_effective_installations
from app.plugin_platform.registry import plugin_data_root
from app.services import team_manager
from app.services.problems_service import (
    ProblemError,
    ProblemInput,
    dismiss_problem,
    list_problems,
    publish_problems,
    serialize_problem,
    suppress_problem,
)

router = APIRouter(prefix="/workspace/problems")
_plugin_sync_at: dict[str, float] = {}
_plugin_scopes: dict[str, set[str]] = {}


def _workspace(raw: str) -> Path:
    try:
        return Path(team_manager.validate_workspace(raw)).resolve()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _response(workspace: Path, *, include_resolved: bool) -> ProblemsResponse:
    rows = list_problems(workspace, include_resolved=include_resolved)
    counts = {key: 0 for key in ("error", "warning", "info", "hint", "total")}
    for row in rows:
        counts[row.severity] += 1
        counts["total"] += 1
    return ProblemsResponse(
        problems=[
            ProblemResponse.model_validate(serialize_problem(row)) for row in rows
        ],
        counts=counts,
    )


@router.get("", response_model=ProblemsResponse)
async def list_workspace_problems(
    workspace: str,
    include_resolved: bool = False,
    refresh_plugins: bool = True,
) -> ProblemsResponse:
    root = _workspace(workspace)
    if refresh_plugins:
        await _sync_plugin_problems(root)
    return _response(root, include_resolved=include_resolved)


@router.post("/{problem_id}/dismiss", response_model=ProblemResponse)
async def dismiss_workspace_problem(problem_id: str, workspace: str) -> ProblemResponse:
    try:
        problem = dismiss_problem(_workspace(workspace), problem_id)
    except ProblemError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProblemResponse.model_validate(serialize_problem(problem))


@router.post("/{problem_id}/suppress", response_model=ProblemResponse)
async def suppress_workspace_problem(
    problem_id: str, workspace: str
) -> ProblemResponse:
    try:
        problem = suppress_problem(_workspace(workspace), problem_id)
    except ProblemError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProblemResponse.model_validate(serialize_problem(problem))


async def _sync_plugin_problems(workspace: Path) -> None:
    root = str(workspace)
    now = time.monotonic()
    if now - _plugin_sync_at.get(root, 0.0) < 30.0:
        return
    _plugin_sync_at[root] = now
    installations = await asyncio.to_thread(list_effective_installations)
    current_scopes: set[str] = set()
    for installation in installations:
        scope = f"plugin:{installation.id}"
        current_scopes.add(scope)
        try:
            inspection = await asyncio.to_thread(
                inspect_plugin,
                installation.root,
                data_root=plugin_data_root(installation.id),
            )
            diagnostics = list(inspection.diagnostics)
            for component in [*inspection.skills, *inspection.mcp_servers]:
                diagnostics.extend(component.diagnostics)
            inputs = [
                ProblemInput(
                    title=f"{installation.name}: {item.code}",
                    message=item.message,
                    severity="error" if item.severity == "error" else "warning",
                    code=item.code,
                    details=f"Plugin scope: {item.scope}",
                    suppression_key=f"plugin:{installation.name}:{item.code}",
                    provenance={
                        "installation_id": installation.id,
                        "plugin": installation.name,
                        "component_scope": item.scope,
                    },
                )
                for item in diagnostics
            ]
        except (OSError, ValueError) as exc:
            inputs = [
                ProblemInput(
                    title=f"{installation.name}: inspection failed",
                    message=str(exc),
                    severity="error",
                    code="plugin-inspection-failed",
                    provenance={"installation_id": installation.id},
                )
            ]
        publish_problems(workspace, source="plugin", scope=scope, problems=inputs)

    for stale_scope in _plugin_scopes.get(root, set()) - current_scopes:
        publish_problems(workspace, source="plugin", scope=stale_scope, problems=[])
    _plugin_scopes[root] = current_scopes
