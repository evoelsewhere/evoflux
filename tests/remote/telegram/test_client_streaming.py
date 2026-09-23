from __future__ import annotations

import json

import httpx
import pytest

from app.remote.telegram.client import TelegramApiError, TelegramClient


TOKEN = "123456:AAFakeTokenValueThatMustNeverAppearInLogs"


def _client(handler) -> TelegramClient:
    return TelegramClient(
        TOKEN, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


@pytest.mark.asyncio
async def test_send_photo_uses_bot_api_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 9,
                    "date": 1700000000,
                    "chat": {"id": 42, "type": "private"},
                },
            },
        )

    client = _client(handler)
    message = await client.send_photo(
        chat_id=42,
        photo="https://cdn.example.test/result.png",
        caption="Result",
    )
    await client.aclose()

    assert str(captured["path"]).endswith("/sendPhoto")
    assert captured["body"] == {
        "chat_id": 42,
        "photo": "https://cdn.example.test/result.png",
        "caption": "Result",
        "parse_mode": "HTML",
    }
    assert message.message_id == 9


@pytest.mark.asyncio
async def test_send_message_draft_uses_bot_api_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": True})

    client = _client(handler)
    await client.send_message_draft(chat_id=42, draft_id=7, text="<b>partial</b>")
    await client.aclose()

    assert str(captured["path"]).endswith("/sendMessageDraft")
    assert captured["body"] == {
        "chat_id": 42,
        "draft_id": 7,
        "text": "<b>partial</b>",
        "parse_mode": "HTML",
    }


@pytest.mark.asyncio
async def test_send_message_draft_rejects_non_positive_id() -> None:
    client = _client(
        lambda request: httpx.Response(200, json={"ok": True, "result": True})
    )
    with pytest.raises(ValueError, match="draft_id must be positive"):
        await client.send_message_draft(chat_id=42, draft_id=0, text="partial")
    await client.aclose()


@pytest.mark.asyncio
async def test_send_message_draft_preserves_rate_limit_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 4},
            },
        )

    client = _client(handler)
    with pytest.raises(TelegramApiError) as exc_info:
        await client.send_message_draft(chat_id=42, draft_id=7, text="partial")
    await client.aclose()

    assert exc_info.value.error_code == 429
    assert exc_info.value.retry_after == 4
