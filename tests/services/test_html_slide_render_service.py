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
async def test_render_broker_rejects_session_without_active_renderer() -> None:
    broker = HtmlSlideRenderBroker()

    with pytest.raises(RuntimeError, match="renderer is unavailable"):
        await broker.request("session-a", {"slide_id": "one"})


@pytest.mark.asyncio
async def test_render_broker_requires_session() -> None:
    broker = HtmlSlideRenderBroker()

    with pytest.raises(RuntimeError, match="active desktop session"):
        await broker.request(None, {"slide_id": "one"})
