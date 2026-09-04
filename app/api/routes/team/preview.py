"""Dev-server (preview) endpoints backing the browser pane's launcher.

These share one registry with the agent's ``preview`` tool: a server the
user starts from the browser pane is the one the agent later reuses, and
neither side spawns a second copy on a port the other owns.

Requests carry the coding workspace explicitly — the agent path has a
request-local sandbox, this one is initiated by the UI and must establish
an equivalent context so servers are keyed under the right root.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.tools.builtin.preview import (
    launch_targets,
    start_launch_target,
    stop_launch_target,
)
from app.services import team_manager

router = APIRouter()


class PreviewTargetResponse(BaseModel):
    name: str
    port: int
    url: str
    command: str
    cwd: str | None = None
    depends_on: str | None = None
    configured: bool
    running: bool
    reused: bool
    pid: int | None = None


class PreviewTargetListResponse(BaseModel):
    workspace: str
    # Absolute path of the launch config that was read, or None when the
    # workspace has none yet.
    source: str | None = None
    # Where the UI tells the user to create one.
    suggested_source: str = ".evoflux/launch.json"
    error: str | None = None
    targets: list[PreviewTargetResponse] = []


class PreviewActionRequest(BaseModel):
    workspace: str
    name: str


class PreviewActionResponse(BaseModel):
    ok: bool
    message: str
    url: str | None = None


def _resolve_workspace(workspace: str) -> Path:
    try:
        resolved = team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Path(resolved).resolve(strict=False)


@router.get("/preview/targets", response_model=PreviewTargetListResponse)
async def list_preview_targets(workspace: str) -> PreviewTargetListResponse:
    root = _resolve_workspace(workspace)
    targets, source, error = await launch_targets(root)
    return PreviewTargetListResponse(
        workspace=str(root),
        source=source,
        error=error,
        targets=[PreviewTargetResponse(**asdict(target)) for target in targets],
    )


@router.post("/preview/start", response_model=PreviewActionResponse)
async def start_preview_target(body: PreviewActionRequest) -> PreviewActionResponse:
    root = _resolve_workspace(body.workspace)
    # The tool resolves cwd, env, and the server key from the active sandbox.
    sandbox_token = set_sandbox(SandboxConfig(workspace=str(root)))
    try:
        ok, message = await start_launch_target(body.name, root)
    except ValueError as exc:
        # Unknown name or unreadable launch config — the message names both
        # the problem and the configurations that do exist.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(sandbox_token)

    targets, _source, _error = await launch_targets(root)
    url = next(
        (
            target.url
            for target in targets
            if target.name == body.name and target.running
        ),
        None,
    )
    return PreviewActionResponse(ok=ok, message=message, url=url)


@router.post("/preview/stop", response_model=PreviewActionResponse)
async def stop_preview_target(body: PreviewActionRequest) -> PreviewActionResponse:
    root = _resolve_workspace(body.workspace)
    sandbox_token = set_sandbox(SandboxConfig(workspace=str(root)))
    try:
        message = await stop_launch_target(body.name, root)
    finally:
        from app.agent.sandbox import _sandbox_ctx

        _sandbox_ctx.reset(sandbox_token)
    return PreviewActionResponse(ok=True, message=message)
