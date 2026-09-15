"""Tests for app/remote/telegram/client.py — Bot API translation and safe
error classification.

Uses ``httpx.MockTransport`` (the established pattern in this repo, see
``tests/agent/providers/codex/test_oauth.py``) so every test runs against a
fake transport instead of the network. The bot token is embedded in every
request URL by Telegram's own wire shape
(``https://api.telegram.org/bot<TOKEN>/<method>``); several tests exist
purely to prove that URL — and the token inside it — never leaks into an
exception message.
"""

from __future__ import annotations

import httpx
import pytest

from app.remote.contracts import RemoteButton
from app.remote.telegram.client import (
    TelegramApiError,
    TelegramCallbackDataError,
    TelegramClient,
    TelegramMalformedResponseError,
    TelegramTransportError,
)
from app.remote.telegram.models import TelegramMessage, TelegramUpdate, TelegramUser

TOKEN = "123456:AAFakeTokenValueThatMustNeverAppearInLogs"


def _client(handler) -> TelegramClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return TelegramClient(TOKEN, http_client=http_client)


def _ok(result) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def _err(
    status: int, error_code: int, description: str, *, retry_after: int | None = None
) -> httpx.Response:
    body: dict[str, object] = {
        "ok": False,
        "error_code": error_code,
        "description": description,
    }
    if retry_after is not None:
        body["parameters"] = {"retry_after": retry_after}
    return httpx.Response(status, json=body)


# ---------------------------------------------------------------------------
# Successful calls
# ---------------------------------------------------------------------------


class TestGetMe:
    @pytest.mark.asyncio
    async def test_returns_bot_identity(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/getMe")
            return _ok({"id": 42, "is_bot": True, "username": "my_bot"})

        client = _client(handler)
        user = await client.get_me()
        assert isinstance(user, TelegramUser)
        assert user.id == 42
        assert user.username == "my_bot"
        await client.aclose()


class TestDeleteWebhook:
    @pytest.mark.asyncio
    async def test_sends_drop_pending_updates_true_by_default(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content
            return _ok(True)

        client = _client(handler)
        await client.delete_webhook()
        assert b'"drop_pending_updates": true' in captured["body"] or (
            b'"drop_pending_updates":true' in captured["body"]
        )
        await client.aclose()

    @pytest.mark.asyncio
    async def test_can_send_drop_pending_updates_false(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content
            return _ok(True)

        client = _client(handler)
        await client.delete_webhook(drop_pending_updates=False)
        assert b"false" in captured["body"]
        await client.aclose()


class TestGetUpdates:
    @pytest.mark.asyncio
    async def test_requests_only_message_and_callback_query(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            return _ok([])

        client = _client(handler)
        await client.get_updates(offset=None, timeout=50)
        assert captured["payload"]["allowed_updates"] == ["message", "callback_query"]
        await client.aclose()

    @pytest.mark.asyncio
    async def test_passes_offset_and_timeout(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            return _ok([])

        client = _client(handler)
        await client.get_updates(offset=99, timeout=5)
        assert captured["payload"]["offset"] == 99
        assert captured["payload"]["timeout"] == 5
        await client.aclose()

    @pytest.mark.asyncio
    async def test_omits_offset_when_none(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            return _ok([])

        client = _client(handler)
        await client.get_updates(offset=None, timeout=5)
        assert "offset" not in captured["payload"]
        await client.aclose()

    @pytest.mark.asyncio
    async def test_parses_updates_in_response_order(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok(
                [
                    {
                        "update_id": 1,
                        "message": {
                            "message_id": 10,
                            "date": 1,
                            "chat": {"id": 555, "type": "private"},
                            "from": {"id": 777, "is_bot": False},
                            "text": "hello",
                        },
                    },
                    {"update_id": 2, "message": None},
                ]
            )

        client = _client(handler)
        updates = await client.get_updates(offset=None, timeout=1)
        assert [u.update_id for u in updates] == [1, 2]
        assert isinstance(updates[0], TelegramUpdate)
        assert updates[0].message.text == "hello"
        assert updates[0].message.chat.id == 555
        assert updates[0].message.from_user.id == 777
        await client.aclose()


class TestSendEditAnswer:
    @pytest.mark.asyncio
    async def test_send_text_sends_html_parse_mode(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            return _ok(
                {
                    "message_id": 5,
                    "date": 1,
                    "chat": {"id": 1, "type": "private"},
                }
            )

        client = _client(handler)
        message = await client.send_text(chat_id=1, text="hello <b>world</b>")
        assert captured["payload"]["parse_mode"] == "HTML"
        assert captured["payload"]["text"] == "hello <b>world</b>"
        assert isinstance(message, TelegramMessage)
        assert message.message_id == 5
        await client.aclose()

    @pytest.mark.asyncio
    async def test_send_text_with_buttons_builds_inline_keyboard(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            return _ok(
                {"message_id": 6, "date": 1, "chat": {"id": 1, "type": "private"}}
            )

        client = _client(handler)
        await client.send_text(
            chat_id=1,
            text="Approve?",
            buttons=[
                RemoteButton(text="Allow", token="tok-1"),
                RemoteButton(text="Deny", token="tok-2"),
            ],
        )
        markup = captured["payload"]["reply_markup"]
        assert markup["inline_keyboard"] == [
            [{"text": "Allow", "callback_data": "tok-1"}],
            [{"text": "Deny", "callback_data": "tok-2"}],
        ]
        await client.aclose()

    @pytest.mark.asyncio
    async def test_send_text_rejects_callback_data_over_64_bytes_before_sending(self):
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return _ok({})

        client = _client(handler)
        with pytest.raises(TelegramCallbackDataError):
            await client.send_text(
                chat_id=1,
                text="hi",
                buttons=[RemoteButton(text="x", token="a" * 65)],
            )
        assert called is False
        await client.aclose()

    @pytest.mark.asyncio
    async def test_send_text_rejects_empty_callback_data_before_sending(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok({})

        client = _client(handler)
        with pytest.raises(TelegramCallbackDataError):
            await client.send_text(
                chat_id=1, text="hi", buttons=[RemoteButton(text="x", token="")]
            )
        await client.aclose()

    @pytest.mark.asyncio
    async def test_send_text_accepts_exactly_64_byte_callback_data(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _ok(
                {"message_id": 1, "date": 1, "chat": {"id": 1, "type": "private"}}
            )

        client = _client(handler)
        await client.send_text(
            chat_id=1, text="hi", buttons=[RemoteButton(text="x", token="a" * 64)]
        )
        await client.aclose()

    @pytest.mark.asyncio
    async def test_edit_text_targets_chat_and_message_id(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            assert request.url.path.endswith("/editMessageText")
            return _ok(
                {"message_id": 5, "date": 1, "chat": {"id": 1, "type": "private"}}
            )

        client = _client(handler)
        await client.edit_text(chat_id=1, message_id=5, text="updated")
        assert captured["payload"]["chat_id"] == 1
        assert captured["payload"]["message_id"] == 5
        assert captured["payload"]["text"] == "updated"
        assert captured["payload"]["parse_mode"] == "HTML"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_answer_callback_posts_callback_query_id(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            assert request.url.path.endswith("/answerCallbackQuery")
            return _ok(True)

        client = _client(handler)
        await client.answer_callback("cbq-1")
        assert captured["payload"]["callback_query_id"] == "cbq-1"
        assert "text" not in captured["payload"]
        await client.aclose()

    @pytest.mark.asyncio
    async def test_send_chat_action_calls_send_chat_action_endpoint(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            assert request.url.path.endswith("/sendChatAction")
            return _ok(True)

        client = _client(handler)
        await client.send_chat_action(chat_id="1")
        assert captured["payload"] == {"chat_id": "1", "action": "typing"}
        await client.aclose()

    @pytest.mark.asyncio
    async def test_send_chat_action_accepts_a_custom_action(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            return _ok(True)

        client = _client(handler)
        await client.send_chat_action(chat_id="1", action="upload_document")
        assert captured["payload"]["action"] == "upload_document"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_set_commands_sends_command_description_pairs(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            assert request.url.path.endswith("/setMyCommands")
            return _ok(True)

        client = _client(handler)
        await client.set_commands([("start", "Start"), ("help", "Help")])
        assert captured["payload"]["commands"] == [
            {"command": "start", "description": "Start"},
            {"command": "help", "description": "Help"},
        ]
        await client.aclose()

    @pytest.mark.asyncio
    async def test_delete_message_sends_chat_id_and_message_id(self):
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["payload"] = json.loads(request.content)
            assert request.url.path.endswith("/deleteMessage")
            return _ok(True)

        client = _client(handler)
        await client.delete_message(chat_id="1", message_id=42)
        assert captured["payload"] == {"chat_id": "1", "message_id": 42}
        await client.aclose()


# ---------------------------------------------------------------------------
# Safe error classification
# ---------------------------------------------------------------------------


class TestApiErrors:
    @pytest.mark.asyncio
    async def test_invalid_token_401(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _err(401, 401, "Unauthorized")

        client = _client(handler)
        with pytest.raises(TelegramApiError) as excinfo:
            await client.get_me()
        assert excinfo.value.error_code == 401
        assert TOKEN not in str(excinfo.value)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_conflict_409_webhook_active(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _err(
                409,
                409,
                "Conflict: can't use getUpdates method while webhook is active",
            )

        client = _client(handler)
        with pytest.raises(TelegramApiError) as excinfo:
            await client.get_updates(offset=None, timeout=1)
        assert excinfo.value.error_code == 409
        assert "webhook" in excinfo.value.description.lower()
        assert TOKEN not in str(excinfo.value)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_conflict_409_used_elsewhere(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _err(
                409,
                409,
                "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running",
            )

        client = _client(handler)
        with pytest.raises(TelegramApiError) as excinfo:
            await client.get_updates(offset=None, timeout=1)
        assert excinfo.value.error_code == 409
        assert TOKEN not in str(excinfo.value)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_rate_limited_429_carries_retry_after(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _err(429, 429, "Too Many Requests: retry later", retry_after=17)

        client = _client(handler)
        with pytest.raises(TelegramApiError) as excinfo:
            await client.get_updates(offset=None, timeout=1)
        assert excinfo.value.retry_after == 17
        assert TOKEN not in str(excinfo.value)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_chat_unreachable_403(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return _err(403, 403, "Forbidden: bot was blocked by the user")

        client = _client(handler)
        with pytest.raises(TelegramApiError) as excinfo:
            await client.send_text(chat_id=1, text="hi")
        assert excinfo.value.error_code == 403
        assert TOKEN not in str(excinfo.value)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_malformed_json_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json at all")

        client = _client(handler)
        with pytest.raises(TelegramMalformedResponseError) as excinfo:
            await client.get_me()
        assert TOKEN not in str(excinfo.value)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_malformed_shape_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            # Valid JSON, but missing the required "ok" field entirely.
            return httpx.Response(200, json={"surprise": True})

        client = _client(handler)
        with pytest.raises(TelegramMalformedResponseError) as excinfo:
            await client.get_me()
        assert TOKEN not in str(excinfo.value)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_transport_failure_never_leaks_url(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        client = _client(handler)
        with pytest.raises(TelegramTransportError) as excinfo:
            await client.get_me()
        assert TOKEN not in str(excinfo.value)
        assert "api.telegram.org" not in str(excinfo.value)
        await client.aclose()

    @pytest.mark.asyncio
    async def test_no_exception_message_ever_contains_the_bot_token(self):
        # Belt-and-suspenders sweep across every error path this client
        # defines — the token must never leak, regardless of failure mode.
        scenarios = [
            _err(401, 401, "Unauthorized"),
            _err(409, 409, "Conflict: webhook is active"),
            _err(429, 429, "Too Many Requests", retry_after=3),
            _err(403, 403, "Forbidden: bot was blocked by the user"),
        ]
        for response in scenarios:

            def handler(request: httpx.Request, _response=response) -> httpx.Response:
                return _response

            client = _client(handler)
            with pytest.raises(TelegramApiError) as excinfo:
                await client.get_me()
            assert TOKEN not in str(excinfo.value)
            assert "api.telegram.org" not in str(excinfo.value)
            await client.aclose()
