from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from app.remote.contracts import RemoteAttachment

from app.remote.imessage.capabilities import IMessageHealth, probe_provider
from app.remote.imessage.poller import IMessagePoller


class _Provider:
    def __init__(self, messages: list[Mapping[str, Any]]) -> None:
        self.messages = messages
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def status(self) -> Mapping[str, Any]:
        return {"features": ["messages", "send"]}

    async def query_messages(
        self, *, after: str | None = None
    ) -> list[Mapping[str, Any]]:
        return [message for message in self.messages if message["guid"] > (after or "")]

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        reply_to_id: str | None = None,
        attachments: Sequence[RemoteAttachment] = (),
    ) -> Mapping[str, Any]:
        return {"chat_id": chat_id, "text": text}


@pytest.mark.asyncio
async def test_probe_returns_only_safe_capabilities() -> None:
    result = await probe_provider(_Provider([]), provider_name="imsg")
    assert result.health is IMessageHealth.HEALTHY
    assert result.features == frozenset({"messages", "send"})


@pytest.mark.asyncio
async def test_poller_advances_and_persists_watermark() -> None:
    provider = _Provider([{"guid": "1", "text": "one"}, {"guid": "2", "text": "two"}])
    seen: list[str] = []
    saved: list[str] = []
    poller = IMessagePoller(
        provider,
        interval=0.01,
        on_message=lambda message: _record(seen, message),
        load_watermark=lambda: _value(None),
        save_watermark=lambda value: _save(saved, value),
    )

    await poller.start()
    await asyncio.sleep(0.04)
    await poller.stop()

    assert seen == ["1", "2"]
    assert saved == ["1", "2"]
    assert provider.started is True
    assert provider.stopped is True


@pytest.mark.asyncio
async def test_poller_restart_resumes_after_persisted_watermark() -> None:
    provider = _Provider([{"guid": "1", "text": "old"}, {"guid": "2", "text": "new"}])
    seen: list[str] = []
    saved: list[str] = []
    poller = IMessagePoller(
        provider,
        interval=0.01,
        on_message=lambda message: _record(seen, message),
        load_watermark=lambda: _value("1"),
        save_watermark=lambda value: _save(saved, value),
    )

    await poller.start()
    await asyncio.sleep(0.03)
    await poller.stop()

    assert seen == ["2"]
    assert saved == ["2"]


async def _record(seen: list[str], message: Mapping[str, Any]) -> None:
    seen.append(str(message["guid"]))


async def _value(value: str | None) -> str | None:
    return value


async def _save(saved: list[str], value: str) -> None:
    saved.append(value)
