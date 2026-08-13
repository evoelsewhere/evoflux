from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from app.agent.builtin_plugins.documents.engines.html_slide_broker import (
    HtmlSlideRenderBroker,
)


@pytest.mark.asyncio
async def test_render_broker_correlates_session_request_and_result() -> None:
    broker = HtmlSlideRenderBroker()
    await broker.heartbeat("session-a")
    waiting = asyncio.create_task(
        broker.request("session-a", {"slide_id": "one"}, timeout_seconds=1)
    )
    await asyncio.sleep(0)

    assert await broker.claim("session-b") is None
    claimed = await broker.claim("session-a")
    assert claimed is not None
    assert claimed["slide_id"] == "one"
    accepted = await broker.complete(
        "session-a", UUID(claimed["request_id"]), {"ok": True}
    )

    assert accepted is True
    assert await waiting == {"ok": True}


@pytest.mark.asyncio
async def test_render_broker_fails_closed_without_webview_response() -> None:
    broker = HtmlSlideRenderBroker()
    await broker.heartbeat("session-a")

    with pytest.raises(RuntimeError, match="renderer is unavailable"):
        await broker.request("session-a", {"slide_id": "one"}, timeout_seconds=0.01)


@pytest.mark.asyncio
async def test_render_broker_allows_renderer_to_connect_after_request() -> None:
    broker = HtmlSlideRenderBroker()
    waiting = asyncio.create_task(
        broker.request("session-a", {"slide_id": "one"}, timeout_seconds=1)
    )
    await asyncio.sleep(0)

    await broker.heartbeat_renderer("renderer-a")
    claimed = await broker.claim_next("renderer-a")

    assert claimed is not None
    assert claimed["session_id"] == "session-a"
    assert claimed["slide_id"] == "one"
    assert await broker.complete_claim(UUID(claimed["request_id"]), {"ok": True})
    assert await waiting == {"ok": True}


@pytest.mark.asyncio
async def test_global_renderer_claims_background_session() -> None:
    broker = HtmlSlideRenderBroker()
    await broker.heartbeat_renderer("renderer-a")
    waiting = asyncio.create_task(
        broker.request("background-session", {"slide_id": "two"}, timeout_seconds=1)
    )
    await asyncio.sleep(0)

    claimed = await broker.claim_next("renderer-a")

    assert claimed is not None
    assert claimed["session_id"] == "background-session"
    assert await broker.complete_claim(UUID(claimed["request_id"]), {"rendered": True})
    assert await waiting == {"rendered": True}


@pytest.mark.asyncio
async def test_render_broker_requires_session() -> None:
    broker = HtmlSlideRenderBroker()

    with pytest.raises(RuntimeError, match="active desktop session"):
        await broker.request(None, {"slide_id": "one"})
