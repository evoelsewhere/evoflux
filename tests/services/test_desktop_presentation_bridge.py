from __future__ import annotations

import json

import pytest

from app.services.desktop_presentation_bridge import (
    DesktopPresentationBridge,
    DesktopPresentationRendererUnavailable,
    _Connection,
)


@pytest.mark.asyncio
async def test_render_requires_matching_desktop_task() -> None:
    bridge = DesktopPresentationBridge()

    with pytest.raises(
        DesktopPresentationRendererUnavailable,
        match="active EvoFlux Desktop task",
    ):
        await bridge.render(
            "missing-session",
            document="<html></html>",
            inspection_script="() => ({})",
            inspection_params={},
            canvas={},
        )


@pytest.mark.asyncio
async def test_large_render_request_is_chunked_and_reconstructable() -> None:
    class Socket:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.messages: list[dict] = []

        async def send_text(self, value: str) -> None:
            self.texts.append(value)

        async def send_json(self, value: dict) -> None:
            self.messages.append(value)

    socket = Socket()
    message = {"id": "job", "document": "x" * 600_000}

    await DesktopPresentationBridge._send_request(socket, message)  # type: ignore[arg-type]

    assert socket.texts == []
    assert len(socket.messages) == 3
    raw = "".join(item["data"] for item in socket.messages)
    assert json.loads(raw) == message


def test_large_render_response_chunks_are_reassembled() -> None:
    connection = _Connection(websocket=object())  # type: ignore[arg-type]
    raw = json.dumps({"id": "job", "ok": True, "result": {"data": "abc"}})
    pieces = [raw[:12], raw[12:]]

    first = DesktopPresentationBridge._accept_response_chunk(
        connection,
        {
            "type": "response_chunk",
            "id": "job",
            "index": 0,
            "total": 2,
            "data": pieces[0],
        },
    )
    result = DesktopPresentationBridge._accept_response_chunk(
        connection,
        {
            "type": "response_chunk",
            "id": "job",
            "index": 1,
            "total": 2,
            "data": pieces[1],
        },
    )

    assert first is None
    assert result == json.loads(raw)
