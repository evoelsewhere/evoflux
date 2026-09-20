from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import pytest

from app.remote.contracts import RemoteAttachment, RemoteInboundActionKind
from app.remote.imessage.channel import IMessageChannel
from app.remote.imessage.provider import IMessageProviderFactory
from app.remote.imessage.rpc import IMessageRpcClient


class _Provider:
    def __init__(self) -> None:
        self.messages: list[Mapping[str, object]] = []
        self.sent: list[tuple[str, str]] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def status(self) -> Mapping[str, object]:
        return {"features": ["messages", "send"]}

    async def query_messages(
        self, *, after: str | None = None
    ) -> list[Mapping[str, object]]:
        return [item for item in self.messages if str(item["guid"]) > (after or "")]

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        reply_to_id: str | None = None,
        attachments=(),
    ) -> Mapping[str, object]:
        self.sent.append((chat_id, text))
        return {"guid": "outbound-1"}


@pytest.mark.asyncio
async def test_channel_routes_inbound_and_outbound_end_to_end() -> None:
    provider = _Provider()
    actions = []
    saved: list[str] = []

    async def record_action(action: object) -> None:
        actions.append(action)

    channel = IMessageChannel(
        connection_id=uuid4(),
        provider_name="imsg",
        provider=provider,
        paired_principal_id="+1555",
        paired_destination_id="chat-1",
        load_watermark=lambda: _value(None),
        save_watermark=lambda value: _save(saved, value),
        on_action=record_action,
    )

    capabilities = await channel.start()
    provider.messages.append(
        {
            "guid": "m1",
            "sender": "+1555",
            "chat_id": "chat-1",
            "text": "status",
        }
    )
    await asyncio.sleep(2.1)
    outbound = await channel.send_text(text="All good")
    await channel.stop()

    assert capabilities.provider == "imsg"
    assert len(actions) == 1
    assert actions[0].kind is RemoteInboundActionKind.TEXT
    assert outbound == {"guid": "outbound-1"}
    assert provider.sent == [("chat-1", "All good")]


async def _value(value: str | None) -> str | None:
    return value


async def _save(saved: list[str], value: str) -> None:
    saved.append(value)


@pytest.mark.asyncio
async def test_channel_runs_against_protocol_mock_and_delivers_capabilities() -> None:
    fixture = Path(__file__).parent / "fixtures" / "mock_imsg_rpc.py"
    rpc = IMessageRpcClient(command=(sys.executable, str(fixture)), timeout=5)

    async def ignore_action(_action: object) -> None:
        return None

    channel = IMessageChannel(
        connection_id=uuid4(),
        provider_name="imsg",
        provider_factory=IMessageProviderFactory(rpc_client=rpc),
        paired_principal_id="phone:+1555",
        paired_destination_id="chat-1",
        password="mock-secret",
        load_watermark=lambda: _value(None),
        save_watermark=lambda value: _save([], value),
        on_action=ignore_action,
    )

    capabilities = await channel.start()
    sent = await channel.send_text(
        text="hello",
        reply_to_id="msg-1",
        attachments=(RemoteAttachment(url="https://example.test/a.jpg"),),
    )
    await channel.stop()

    assert capabilities.provider == "imsg"
    assert "attachments" in capabilities.features
    assert sent["reply_to"] == "msg-1"

    actions: list[object] = []

    async def record_action(action: object) -> None:
        actions.append(action)

    provider = _Provider()
    provider.messages = [
        {
            "guid": "inbox-1",
            "sender": "phone:+1555",
            "chat_id": "chat-1",
            "text": "ping",
        },
        {
            "guid": "inbox-2",
            "sender": "phone:+1999",
            "chat_id": "chat-1",
            "text": "foreign",
        },
    ]
    inbound_channel = IMessageChannel(
        connection_id=uuid4(),
        provider_name="imsg",
        provider=provider,
        paired_principal_id="phone:+1555",
        paired_destination_id="chat-1",
        load_watermark=lambda: _value(None),
        save_watermark=lambda value: _save([], value),
        on_action=record_action,
    )
    await inbound_channel.start()
    await asyncio.sleep(2.1)
    await inbound_channel.stop()

    assert [getattr(item, "text", None) for item in actions] == ["ping"]
