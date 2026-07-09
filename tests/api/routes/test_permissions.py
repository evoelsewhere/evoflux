"""Tests for /api/team/{session_id}/permissions HTTP routes.

The endpoints run in a different async context than the agent task, so they
must resolve services via the module-level session registry — not the
context-var (which would fall back to the default auto-allow service).
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.agent.permission import (
    PermissionRejectedError,
    PermissionService,
    reset_permission_service,
    set_permission_service,
)
from app.api.routes.team.permissions import router as permissions_router


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(permissions_router, prefix="/api/team")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.fixture
def registered_service():
    """A member service registered under a lead stream, like a real team run."""
    service = PermissionService(
        session_id="member-sess",
        mode="ask",
        stream_session_id="lead-sess",
    )
    token = set_permission_service(service)
    yield service
    reset_permission_service(token, "member-sess")


@pytest.mark.asyncio
async def test_list_permissions_empty(client):
    res = await client.get("/api/team/nonexistent/permissions")
    assert res.status_code == 200
    assert res.json() == {"permissions": []}


@pytest.mark.asyncio
async def test_list_permissions_returns_pending_via_lead_session(
    client, registered_service
):
    task = asyncio.create_task(registered_service.ask("shell", ["rm -rf /tmp/x"]))
    await asyncio.sleep(0.01)

    res = await client.get("/api/team/lead-sess/permissions")
    assert res.status_code == 200
    perms = res.json()["permissions"]
    assert len(perms) == 1
    assert perms[0]["tool"] == "shell"
    assert perms[0]["patterns"] == ["rm -rf /tmp/x"]

    registered_service.reply(perms[0]["id"], "once")
    await task


@pytest.mark.asyncio
async def test_reply_unblocks_waiting_ask(client, registered_service):
    """POST reply from the HTTP context resolves the agent-side future."""
    task = asyncio.create_task(registered_service.ask("shell", ["git push"]))
    await asyncio.sleep(0.01)
    req_id = registered_service.list_pending()[0].id

    res = await client.post(
        f"/api/team/lead-sess/permissions/{req_id}/reply",
        json={"reply": "once"},
    )
    assert res.status_code == 200
    assert res.json()["reply"] == "once"

    await task  # ask() returns — the agent proceeds


@pytest.mark.asyncio
async def test_reply_reject_raises_in_agent(client, registered_service):
    task = asyncio.create_task(registered_service.ask("shell", ["rm -rf /"]))
    await asyncio.sleep(0.01)
    req_id = registered_service.list_pending()[0].id

    res = await client.post(
        f"/api/team/lead-sess/permissions/{req_id}/reply",
        json={"reply": "reject"},
    )
    assert res.status_code == 200

    with pytest.raises(PermissionRejectedError):
        await task


@pytest.mark.asyncio
async def test_reply_always_whitelists_pattern(client, registered_service):
    task = asyncio.create_task(
        registered_service.ask(
            "shell", ["git status -sb"], always_patterns=["git status *"]
        )
    )
    await asyncio.sleep(0.01)
    req_id = registered_service.list_pending()[0].id

    res = await client.post(
        f"/api/team/lead-sess/permissions/{req_id}/reply",
        json={"reply": "always"},
    )
    assert res.status_code == 200
    await task

    # Same command family no longer asks
    await registered_service.ask("shell", ["git status --porcelain"])
    assert registered_service.list_pending() == []


@pytest.mark.asyncio
async def test_reply_unknown_request_404(client, registered_service):
    res = await client.post(
        "/api/team/lead-sess/permissions/does-not-exist/reply",
        json={"reply": "once"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_reply_invalid_value_422(client, registered_service):
    task = asyncio.create_task(registered_service.ask("shell", ["ls -la /"]))
    await asyncio.sleep(0.01)
    req_id = registered_service.list_pending()[0].id

    res = await client.post(
        f"/api/team/lead-sess/permissions/{req_id}/reply",
        json={"reply": "yes-please"},
    )
    assert res.status_code == 422

    registered_service.reply(req_id, "once")
    await task
