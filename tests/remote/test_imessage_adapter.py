from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

import pytest

from app.remote.contracts import RemoteConnectionState, RemoteErrorClass
from app.remote.imessage import adapter as adapter_module
from app.remote.imessage.adapter import IMessageRemoteAdapter


class _Provider:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def status(self) -> Mapping[str, object]:
        return {"features": ["messages"]}

    async def query_messages(
        self, *, after: str | None = None
    ) -> list[Mapping[str, object]]:
        return []

    async def send_text(self, *, chat_id: str, text: str) -> Mapping[str, object]:
        return {"chat_id": chat_id, "text": text}


@pytest.mark.asyncio
async def test_adapter_waits_for_pairing_then_starts() -> None:
    adapter = IMessageRemoteAdapter(
        connection_id=uuid4(), credential="ignored", on_action=lambda _: _done()
    )
    await adapter.start()
    assert adapter.status().state is RemoteConnectionState.PAIRING
    adapter.set_pairing(principal_id="+1555", destination_id="chat-1")
    adapter._channel = None  # noqa: SLF001 - avoid spawning a real imsg process
    await adapter.stop()


async def _done() -> None:
    return None


@pytest.mark.asyncio
async def test_adapter_maps_provider_start_failure_to_safe_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = False

    class _FailingChannel:
        def __init__(self, **_: object) -> None:
            pass

        async def start(self) -> frozenset[str]:
            raise RuntimeError("provider payload must not escape")

        async def stop(self) -> None:
            nonlocal stopped
            stopped = True

    monkeypatch.setattr(adapter_module, "IMessageChannel", _FailingChannel)
    adapter = IMessageRemoteAdapter(
        connection_id=uuid4(), credential="ignored", on_action=lambda _: _done()
    )
    await adapter.start()
    adapter.set_pairing(principal_id="+1555", destination_id="chat-1")
    await adapter.start()

    status = adapter.status()
    assert status.state is RemoteConnectionState.ERROR
    assert status.last_error_class is RemoteErrorClass.TRANSPORT
    assert stopped
