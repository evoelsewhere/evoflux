from __future__ import annotations

import pytest

from app.remote.contracts import RemoteAttachment, RemoteOutboundMessage
from tests.remote.telegram.test_adapter import ScriptedTransport, _make_adapter, _ok


@pytest.mark.asyncio
async def test_adapter_sends_https_image_and_falls_back_to_text() -> None:
    transport = ScriptedTransport()
    transport.queue(
        "sendPhoto",
        _ok({"message_id": 1, "date": 1, "chat": {"id": 100, "type": "private"}}),
    )
    transport.queue(
        "sendMessage",
        _ok({"message_id": 2, "date": 1, "chat": {"id": 100, "type": "private"}}),
    )
    adapter = _make_adapter(transport)

    await adapter.send(
        RemoteOutboundMessage(
            connection_id=adapter._connection_id,
            destination_id="100",
            text="Image result",
            attachments=(
                RemoteAttachment(
                    url="https://cdn.example.test/result.png",
                    mime_type="image/png",
                    size_bytes=1024,
                ),
            ),
        )
    )

    assert transport.call_count("sendPhoto") == 1
    assert transport.call_count("sendMessage") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "mime_type", "size_bytes"),
    [
        ("http://cdn.example.test/result.png", "image/png", 1024),
        ("https://cdn.example.test/result.exe", "application/octet-stream", 1024),
        ("https://cdn.example.test/result.png", "image/png", 11 * 1024 * 1024),
    ],
)
async def test_adapter_rejects_unsafe_images_but_sends_text(
    url: str, mime_type: str, size_bytes: int
) -> None:
    transport = ScriptedTransport()
    transport.queue(
        "sendMessage",
        _ok({"message_id": 2, "date": 1, "chat": {"id": 100, "type": "private"}}),
    )
    adapter = _make_adapter(transport)

    await adapter.send(
        RemoteOutboundMessage(
            connection_id=adapter._connection_id,
            destination_id="100",
            text="Image unavailable",
            attachments=(
                RemoteAttachment(
                    url=url,
                    mime_type=mime_type,
                    size_bytes=size_bytes,
                ),
            ),
        )
    )

    assert transport.call_count("sendPhoto") == 0
    assert transport.call_count("sendMessage") == 1
