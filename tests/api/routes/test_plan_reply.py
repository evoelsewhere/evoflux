"""Tests for POST /api/team/{session_id}/plan/reply."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.agent.plan import (
    PlanModeService,
    reset_plan_mode_service,
    set_plan_mode_service,
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
def plan_service():
    service = PlanModeService(session_id="lead-sess", stream_session_id="lead-sess")
    token = set_plan_mode_service(service)
    yield service
    reset_plan_mode_service(token, "lead-sess")


async def _pending_id(svc: PlanModeService) -> str:
    for _ in range(100):
        if svc._pending:
            return next(iter(svc._pending))
        await asyncio.sleep(0.005)
    raise AssertionError("no pending plan request appeared")


@pytest.mark.asyncio
async def test_approve_unblocks_agent(client, plan_service):
    plan_service.enter()
    plan_service.record_step("edit", {}, "edit x")
    task = asyncio.create_task(plan_service.request_approval("# Plan"))
    req_id = await _pending_id(plan_service)

    res = await client.post(
        "/api/team/lead-sess/plan/reply",
        json={"request_id": req_id, "decision": "approved"},
    )
    assert res.status_code == 200
    assert await task == ("approved", "")


@pytest.mark.asyncio
async def test_revise_passes_feedback_through(client, plan_service):
    plan_service.enter()
    task = asyncio.create_task(plan_service.request_approval("# Plan"))
    req_id = await _pending_id(plan_service)

    res = await client.post(
        "/api/team/lead-sess/plan/reply",
        json={
            "request_id": req_id,
            "decision": "revise",
            "feedback": "add rollback steps",
        },
    )
    assert res.status_code == 200
    assert res.json()["decision"] == "revise"
    assert await task == ("revise", "add rollback steps")


@pytest.mark.asyncio
async def test_invalid_decision_422(client, plan_service):
    plan_service.enter()
    task = asyncio.create_task(plan_service.request_approval("# Plan"))
    req_id = await _pending_id(plan_service)

    res = await client.post(
        "/api/team/lead-sess/plan/reply",
        json={"request_id": req_id, "decision": "maybe"},
    )
    assert res.status_code == 422

    plan_service.reply(req_id, "approved")
    await task


@pytest.mark.asyncio
async def test_unknown_request_404(client, plan_service):
    res = await client.post(
        "/api/team/lead-sess/plan/reply",
        json={"request_id": "does-not-exist", "decision": "approved"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_unknown_session_404(client):
    res = await client.post(
        "/api/team/no-such-session/plan/reply",
        json={"request_id": "x", "decision": "approved"},
    )
    assert res.status_code == 404
