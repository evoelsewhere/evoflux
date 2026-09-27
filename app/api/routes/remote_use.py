"""Remote use over Tailscale Serve: status, serve control, lock release."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core.config import settings
from app.services import remote_use_service as remote_use

router = APIRouter()


async def _status_payload() -> dict[str, Any]:
    """The uniform remote-use response: tailscale, serve, and lock."""
    status = await remote_use.get_status()
    holder = await remote_use.get_lock_holder()
    status["lock"] = remote_use.session_lock_payload(holder)
    return status


async def _with_lock(status: dict[str, Any]) -> dict[str, Any]:
    """Attach the lock section to an enable/disable payload."""
    holder = await remote_use.get_lock_holder()
    status["lock"] = remote_use.session_lock_payload(holder)
    return status


def _backend_port(request: Request) -> int | None:
    """The sidecar's own listen port: ASGI server scope, else settings."""
    server = request.scope.get("server")
    if server and server[1]:
        return int(server[1])
    return settings.API_PORT


@router.get("/status")
async def remote_use_status() -> dict[str, Any]:
    """Tailscale state, serve state, and the current lock holder."""
    return await _status_payload()


@router.post("/enable")
async def remote_use_enable(request: Request) -> dict[str, Any]:
    """Enable ``tailscale serve`` toward this sidecar over loopback."""
    return await _with_lock(await remote_use.enable_serve(_backend_port(request)))


@router.post("/disable")
async def remote_use_disable() -> dict[str, Any]:
    """Disable tailscale serve (``tailscale serve reset``)."""
    return await _with_lock(await remote_use.disable_serve())


@router.post("/release")
async def remote_use_release() -> dict[str, Any]:
    """Desktop force-release: retire every live remote session."""
    await remote_use.force_release()
    return await _status_payload()
