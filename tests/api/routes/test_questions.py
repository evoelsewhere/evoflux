"""Tests for /api/team/{session_id}/questions HTTP routes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.agent.ask_user import (
    AskUserService,
    reset_ask_user_service,
    set_ask_user_service,
)
from app.agent.tools.builtin.ask_user import AgentSpawnSpec, QuestionSpec
from app.api.routes.team.questions import router as questions_router


@pytest.fixture
async def client():
    app = FastAPI()
    app.include_router(questions_router, prefix="/api/team")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.fixture
def registered_service():
    service = AskUserService(session_id="lead-sess", stream_session_id="lead-sess")
    token = set_ask_user_service(service)
    yield service
    reset_ask_user_service(token, "lead-sess")


async def _pending_id(svc: AskUserService) -> str:
    for _ in range(100):
        if svc._pending:
            return next(iter(svc._pending))
        await asyncio.sleep(0.005)
    raise AssertionError("no pending ask_user request appeared")


@pytest.mark.asyncio
async def test_reply_unblocks_and_emits_question_replied(client, registered_service):
    task = asyncio.create_task(
        registered_service.ask(
            [QuestionSpec(question="Ship it?", options=["yes", "no"])]
        )
    )
    req_id = await _pending_id(registered_service)

    pushed: list = []

    async def _capture(session_id: str, envelope) -> None:
        pushed.append((session_id, envelope))

    with patch(
        "app.services.memory_stream_store.push_event",
        new=AsyncMock(side_effect=_capture),
    ):
        res = await client.post(
            f"/api/team/lead-sess/questions/{req_id}/reply",
            json={"answers": ["yes"]},
        )
        assert res.status_code == 200
        assert res.json()["answers"] == ["yes"]
        assert await task == ["yes"]
        await asyncio.sleep(0)

    replied = [
        env for _, env in pushed if getattr(env, "event", None) == "question_replied"
    ]
    assert len(replied) == 1
    assert replied[0].data["request_id"] == req_id
    assert replied[0].data["status"] == "answered"


@pytest.mark.asyncio
async def test_reply_unknown_request_404(client, registered_service):
    res = await client.post(
        "/api/team/lead-sess/questions/does-not-exist/reply",
        json={"answers": ["x"]},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_reply_unknown_session_404(client):
    res = await client.post(
        "/api/team/no-such-session/questions/x/reply",
        json={"answers": ["x"]},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_pending_and_reply_via_lead_stream_for_member(client):
    """AIM / lead-session clients must see member-owned ask_user batches."""
    member = AskUserService(session_id="member-sess", stream_session_id="lead-sess")
    token = set_ask_user_service(member)
    try:
        task = asyncio.create_task(
            member.ask([QuestionSpec(question="Gate?", options=["a", "b"])])
        )
        req_id = await _pending_id(member)

        pending = await client.get("/api/team/lead-sess/questions/pending")
        assert pending.status_code == 200
        body = pending.json()
        assert len(body["questions"]) == 1
        assert body["questions"][0]["request_id"] == req_id
        assert body["questions"][0]["session_id"] == "member-sess"
        assert body["questions"][0]["items"][0]["question"] == "Gate?"

        with patch("app.services.memory_stream_store.push_event", new=AsyncMock()):
            res = await client.post(
                f"/api/team/lead-sess/questions/{req_id}/reply",
                json={"answers": ["a"]},
            )
        assert res.status_code == 200
        assert await task == ["a"]
    finally:
        reset_ask_user_service(token, "member-sess")


@pytest.mark.asyncio
async def test_pending_empty_when_no_service(client):
    res = await client.get("/api/team/ghost-sess/questions/pending")
    assert res.status_code == 200
    assert res.json() == {"questions": []}


@pytest.mark.asyncio
async def test_pending_preserves_agent_spawn_metadata(client, registered_service):
    task = asyncio.create_task(
        registered_service.ask(
            [
                QuestionSpec(
                    kind="agent_spawn",
                    question="Choose runtime",
                    agent_spawn=AgentSpawnSpec(
                        blueprint="executor",
                        default_model="openai:gpt-5.6-codex",
                        default_thinking_level="high",
                    ),
                )
            ]
        )
    )
    request_id = await _pending_id(registered_service)
    try:
        pending = await client.get("/api/team/lead-sess/questions/pending")
        item = pending.json()["questions"][0]["items"][0]

        assert item == {
            "question": "Choose runtime",
            "options": [],
            "kind": "agent_spawn",
            "agent_spawn": {
                "blueprint": "executor",
                "default_model": "openai:gpt-5.6-codex",
                "default_thinking_level": "high",
            },
        }
    finally:
        registered_service.reply(request_id, ["__cancel__"])
        await task
