from __future__ import annotations

import httpx
import pytest

from app.remote.telegram.client import TelegramApiError, TelegramClient


@pytest.mark.asyncio
async def test_download_file_uses_get_file_and_streams_bounded_body() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/getFile"):
            return httpx.Response(
                200, json={"ok": True, "result": {"file_path": "docs/a.txt"}}
            )
        return httpx.Response(200, headers={"content-length": "5"}, content=b"hello")

    client = TelegramClient(
        "token", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    assert await client.download_file("file-1", max_bytes=5) == b"hello"
    assert calls[0].endswith("/getFile")
    assert "/file/bottoken/docs/a.txt" in calls[1]
    await client.aclose()


@pytest.mark.asyncio
async def test_download_file_rejects_content_length_before_reading_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            return httpx.Response(
                200, json={"ok": True, "result": {"file_path": "large.bin"}}
            )
        return httpx.Response(
            200, headers={"content-length": "11"}, content=b"0123456789a"
        )

    client = TelegramClient(
        "token", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(TelegramApiError) as error:
        await client.download_file("file-1", max_bytes=10)
    assert error.value.error_code == 413
    await client.aclose()
