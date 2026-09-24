from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.remote.imessage.rpc import IMessageRpcClient, IMessageRpcError


class _FakeWriter:
    def __init__(
        self, stdout: asyncio.StreamReader, *, auto_response: bool = True
    ) -> None:
        self.stdout = stdout
        self.auto_response = auto_response
        self.payloads: list[dict[str, object]] = []

    def write(self, data: bytes) -> None:
        payload = json.loads(data)
        self.payloads.append(payload)
        if not self.auto_response:
            return
        self.stdout.feed_data(
            (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": payload["id"],
                        "result": {"ready": True},
                    }
                )
                + "\n"
            ).encode()
        )

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, *, auto_response: bool = True) -> None:
        self.stdout = asyncio.StreamReader()
        self.stdin = _FakeWriter(self.stdout, auto_response=auto_response)
        self.returncode: int | None = None

    async def wait(self) -> int:
        self.returncode = 0
        self.stdout.feed_eof()
        return 0

    def kill(self) -> None:
        self.returncode = -9
        self.stdout.feed_eof()


@pytest.mark.asyncio
async def test_request_correlates_json_rpc_response() -> None:
    process = _FakeProcess()
    client = IMessageRpcClient(timeout=1)
    client._process = process  # noqa: SLF001 - deterministic protocol test
    client._closed = False  # noqa: SLF001
    client._reader_task = asyncio.create_task(client._read_responses())  # noqa: SLF001

    result = await client.request("status")

    assert result == {"ready": True}
    assert process.stdin.payloads[0]["method"] == "status"
    await client.stop()


@pytest.mark.asyncio
async def test_request_raises_provider_error() -> None:
    process = _FakeProcess(auto_response=False)
    client = IMessageRpcClient(timeout=1)
    client._process = process  # noqa: SLF001
    client._closed = False  # noqa: SLF001

    async def respond() -> None:
        await asyncio.sleep(0)
        while not process.stdin.payloads:
            await asyncio.sleep(0)
        request_id = process.stdin.payloads[0]["id"]
        process.stdout.feed_data(
            (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32000, "message": "not ready"},
                    }
                )
                + "\n"
            ).encode()
        )

    client._reader_task = asyncio.create_task(client._read_responses())  # noqa: SLF001
    responder = asyncio.create_task(respond())
    with pytest.raises(IMessageRpcError, match="not ready"):
        await client.request("status")
    await responder
    await client.stop()


@pytest.mark.asyncio
async def test_rpc_client_runs_protocol_mock_process() -> None:
    fixture = Path(__file__).parent / "fixtures" / "mock_imsg_rpc.py"
    client = IMessageRpcClient(command=(sys.executable, str(fixture)), timeout=5)

    await client.start()
    status = await client.request("status")
    sent = await client.request(
        "send",
        params={
            "chat_identifier": "chat-1",
            "text": "hello",
            "reply_to": "msg-1",
            "attachments": [{"url": "https://example.test/a.jpg"}],
        },
    )
    messages = await client.request("messages.after", params={"since_rowid": 0})
    await client.stop()

    assert status["ready"] is True
    assert "attachments" in status["features"]
    assert sent["reply_to"] == "msg-1"
    assert messages["messages"][0]["chat_identifier"] == "chat-1"


@pytest.mark.asyncio
async def test_rpc_mock_state_survives_process_restart_and_filters_watermark() -> None:
    fixture = Path(__file__).parent / "fixtures" / "mock_imsg_rpc.py"
    with TemporaryDirectory() as temporary_directory:
        state = str(Path(temporary_directory) / "state.json")
        command = (sys.executable, str(fixture))
        first = IMessageRpcClient(
            command=command, timeout=5, env={"MOCK_IMSG_STATE": state}
        )
        await first.start()
        await first.request(
            "send", params={"chat_identifier": "chat-1", "text": "old"}
        )
        await first.stop()

        second = IMessageRpcClient(
            command=command, timeout=5, env={"MOCK_IMSG_STATE": state}
        )
        await second.start()
        await second.request(
            "send", params={"chat_identifier": "chat-1", "text": "new"}
        )
        resumed = await second.request(
            "messages.after", params={"since_rowid": 1}
        )
        await second.stop()

    assert [item["text"] for item in resumed["messages"]] == ["new"]
