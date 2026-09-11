from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest

from app.conductor.client import ConductorClient, ConductorRequestError
from app.conductor.service import ConductorService
from app.core.runtime_settings import ConductorSettings


class MemoryCredentialStore:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def load(self) -> str | None:
        return self.value

    def save(self, credential: str) -> None:
        self.value = credential

    def delete(self) -> None:
        self.value = None


def _sse_body(*frames: tuple[str, str]) -> bytes:
    """Build a raw SSE body from (event, json_data) pairs."""

    body = ""
    for event, data in frames:
        body += f"event: {event}\ndata: {data}\n\n"
    return body.encode("utf-8")


HELLO = (
    "control.hello",
    '{"protocol": "evoflux.realtime.v1", "sequence": "1", '
    '"emitted_at": "2026-08-09T10:30:00Z", '
    '"data": {"connection_id": "c1", "heartbeat_seconds": 20}}',
)


def _frame(event: str, sequence: str, data: dict[str, object]) -> tuple[str, str]:
    import json

    envelope = {
        "protocol": "evoflux.realtime.v1",
        "sequence": sequence,
        "emitted_at": "2026-08-09T10:30:00Z",
        "data": data,
    }
    return event, json.dumps(envelope)


# ---------------------------------------------------------------------------
# ConductorClient.stream_realtime_events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_realtime_events_yields_parsed_frames() -> None:
    store = MemoryCredentialStore("evc_local_secret")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/realtime/events"
        assert request.headers["authorization"] == "Bearer evc_local_secret"
        assert request.headers["accept"] == "text/event-stream"
        return httpx.Response(
            200,
            content=_sse_body(HELLO, _frame("control.heartbeat", "2", {})),
            headers={"content-type": "text/event-stream"},
        )

    client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    try:
        events = [event async for event in client.stream_realtime_events()]
    finally:
        await client.close()

    assert [event.event for event in events] == ["control.hello", "control.heartbeat"]
    assert events[0].data["heartbeat_seconds"] == 20


@pytest.mark.asyncio
async def test_stream_realtime_events_raises_with_retry_after_on_429() -> None:
    store = MemoryCredentialStore("evc_local_secret")

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": "connection limit reached for this secret"},
            headers={"retry-after": "5"},
        )

    client = ConductorClient(
        "https://conductor.example",
        store,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(ConductorRequestError) as raised:
            async for _ in client.stream_realtime_events():
                pass
    finally:
        await client.close()

    assert raised.value.status_code == 429
    assert raised.value.retry_after_seconds == 5.0


# ---------------------------------------------------------------------------
# ConductorService._realtime_loop
# ---------------------------------------------------------------------------


def _connected_service(
    handler: httpx.MockTransport,
) -> tuple[ConductorService, ConductorSettings]:
    store = MemoryCredentialStore("evc_local_secret")
    service = ConductorService(credential_store=store)
    config = ConductorSettings(
        enabled=True,
        url="https://conductor.example",
        installation_id="install-1",
        project_id="project-1",
    )
    service._config = lambda: config  # type: ignore[method-assign]
    service._new_client = lambda cfg: ConductorClient(  # type: ignore[method-assign]
        cfg.url, store, transport=handler
    )
    return service, config


@pytest.mark.asyncio
async def test_realtime_loop_suspends_on_access_revoked() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse_body(
                HELLO, _frame("control.access_revoked", "2", {"reason": "x"})
            ),
            headers={"content-type": "text/event-stream"},
        )

    service, _ = _connected_service(httpx.MockTransport(handler))
    try:
        # Completing rather than timing out is part of the assertion: the
        # loop must return instead of reconnecting forever. It leaves
        # self._stop alone — that is for a real 401/403 handshake failure;
        # the polling lanes find a revoked secret on their own next request.
        await asyncio.wait_for(service._realtime_loop(), timeout=5.0)
    finally:
        if service._client:
            await service._client.close()

    assert service.status.realtime.state == "suspended"


@pytest.mark.asyncio
async def test_realtime_loop_suspends_on_401() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    service, _ = _connected_service(httpx.MockTransport(handler))
    try:
        await asyncio.wait_for(service._realtime_loop(), timeout=5.0)
    finally:
        if service._client:
            await service._client.close()

    assert service.status.realtime.state == "suspended"
    assert service.status.state == "authorization_required"
    assert service._stop.is_set()


@pytest.mark.asyncio
async def test_realtime_loop_triggers_sync_on_resources_head_and_resets_attempts() -> (
    None
):
    calls = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(
                200,
                content=_sse_body(
                    HELLO, _frame("resources.head", "2", {"reason": "initial"})
                ),
                headers={"content-type": "text/event-stream"},
            )
        # Second attempt, after the first stream hit EOF: revoke so the loop
        # terminates deterministically.
        return httpx.Response(
            200,
            content=_sse_body(
                HELLO, _frame("control.access_revoked", "3", {"reason": "done"})
            ),
            headers={"content-type": "text/event-stream"},
        )

    service, _ = _connected_service(httpx.MockTransport(handler))
    sync_now = AsyncMock()

    async def fake_sync_now() -> object:
        service.status.sync.resources.state = "healthy"
        return service.status

    sync_now.side_effect = fake_sync_now
    service.sync_now = cast(AsyncMock, sync_now)  # type: ignore[method-assign]

    try:
        await asyncio.wait_for(service._realtime_loop(), timeout=5.0)
    finally:
        if service._client:
            await service._client.close()

    sync_now.assert_awaited()
    assert service.status.realtime.state == "suspended"


@pytest.mark.asyncio
async def test_realtime_loop_is_disabled_when_conductor_disabled() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must not connect while disabled")

    service, config = _connected_service(httpx.MockTransport(handler))
    config.enabled = False

    task = asyncio.create_task(service._realtime_loop())
    await asyncio.sleep(0.05)
    assert service.status.realtime.state == "disabled"
    service._stop.set()
    await asyncio.wait_for(task, timeout=5.0)
