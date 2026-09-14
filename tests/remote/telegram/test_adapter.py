"""Tests for app/remote/telegram/adapter.py — poll lifecycle, Telegram error
taxonomy -> connection-state translation, and normalized inbound delivery.

``ScriptedTransport`` is a small in-process fake Bot API: it queues one
response (or exception) per method name and records every call, so tests
can script conflict/rate-limit/transport sequences and assert on offsets,
state, and timing without any real network or real sleeping.
"""

from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

import httpx
import pytest

from app.remote.contracts import (
    RemoteConnectionState,
    RemoteErrorClass,
    RemoteInboundActionKind,
    RemoteOutboundMessage,
)
from app.remote.telegram.adapter import TelegramAdapter

TOKEN = "123456:AAFakeTokenValueThatMustNeverAppearInLogs"


def _ok(result) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def _err(status: int, error_code: int, description: str, *, retry_after: int | None = None):
    body: dict[str, object] = {"ok": False, "error_code": error_code, "description": description}
    if retry_after is not None:
        body["parameters"] = {"retry_after": retry_after}
    return httpx.Response(status, json=body)


class ScriptedTransport:
    """Queues responses/exceptions per Bot API method name.

    ``queue(method, *items)`` appends; each call to that method pops the
    next item (a response is returned, an exception instance is raised).
    Once a method's queue is empty, a default response is served forever
    (empty ``getUpdates``, ``ok: true`` for everything else) so a test only
    needs to script the calls it cares about.
    """

    def __init__(self) -> None:
        self.responses: dict[str, list[object]] = {}
        self._forever: dict[str, object] = {}
        self.calls: list[tuple[str, dict]] = []

    def queue(self, method: str, *items: object) -> None:
        self.responses.setdefault(method, []).extend(items)

    def fail_forever(self, method: str, item: object) -> None:
        """Always serve *item* for *method* once its one-shot queue (if any)
        is drained — for tests that must observe a state persisting across
        a wall-clock window without racing a scripted recovery."""
        self._forever[method] = item

    async def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content) if request.content else {}
        self.calls.append((method, payload))
        pending = self.responses.get(method)
        if pending:
            item = pending.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        forever = self._forever.get(method)
        if forever is not None:
            if isinstance(forever, Exception):
                raise forever
            return forever
        if method == "getUpdates":
            # Real Telegram blocks for up to `timeout` seconds before
            # returning an empty result, which naturally throttles the poll
            # loop. A mock transport resolves instantly, so without a small
            # real yield here a scripted-empty poll loop would spin as a
            # tight, non-yielding busy loop and starve the event loop
            # (including the test's own `asyncio.sleep` deadlines).
            await asyncio.sleep(0.01)
            return _ok([])
        return _ok(True)

    def call_count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)


def _make_adapter(
    transport: ScriptedTransport,
    *,
    on_action=None,
    backoff_base_seconds: float = 0.01,
    backoff_max_seconds: float = 0.05,
    jitter=lambda lo, hi: hi,
    **kwargs,
) -> TelegramAdapter:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport.handler))
    calls: list[object] = []

    async def default_on_action(action):
        calls.append(action)
        return None

    adapter = TelegramAdapter(
        connection_id=uuid4(),
        token=TOKEN,
        on_action=on_action or default_on_action,
        http_client=http_client,
        backoff_base_seconds=backoff_base_seconds,
        backoff_max_seconds=backoff_max_seconds,
        jitter=jitter,
        **kwargs,
    )
    adapter.received = calls  # type: ignore[attr-defined]
    return adapter


async def _run_briefly(adapter: TelegramAdapter, seconds: float = 0.1) -> None:
    await adapter.start()
    await asyncio.sleep(seconds)
    await adapter.stop()


# ---------------------------------------------------------------------------
# Startup sequence (AC-11)
# ---------------------------------------------------------------------------


class TestStartupSequence:
    @pytest.mark.asyncio
    async def test_deletes_webhook_with_drop_pending_updates_before_first_poll(self):
        transport = ScriptedTransport()
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        method_order = [name for name, _ in transport.calls]
        assert "deleteWebhook" in method_order
        assert method_order.index("deleteWebhook") < method_order.index("getUpdates")
        _, payload = next(c for c in transport.calls if c[0] == "deleteWebhook")
        assert payload["drop_pending_updates"] is True

    @pytest.mark.asyncio
    async def test_requests_only_message_and_callback_query_updates(self):
        transport = ScriptedTransport()
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        _, payload = next(c for c in transport.calls if c[0] == "getUpdates")
        assert payload["allowed_updates"] == ["message", "callback_query"]


# ---------------------------------------------------------------------------
# Update classification, ordering, and offset advancement
# ---------------------------------------------------------------------------


def _text_update(update_id: int, *, chat_id: int = 100, user_id: int = 200, text: str = "hi"):
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "username": "alice"},
            "text": text,
        },
    }


class TestClassificationAndOffsets:
    @pytest.mark.asyncio
    async def test_out_of_order_updates_are_processed_in_update_id_order(self):
        transport = ScriptedTransport()
        transport.queue(
            "getUpdates",
            _ok([_text_update(2, text="second"), _text_update(1, text="first")]),
        )
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        assert [action.text for action in adapter.received] == ["first", "second"]

    @pytest.mark.asyncio
    async def test_accepted_offsets_advance_the_next_getupdates_call(self):
        transport = ScriptedTransport()
        transport.queue("getUpdates", _ok([_text_update(5)]))
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        get_updates_payloads = [p for name, p in transport.calls if name == "getUpdates"]
        assert "offset" not in get_updates_payloads[0]
        assert get_updates_payloads[1]["offset"] == 6

    @pytest.mark.asyncio
    async def test_handler_failure_does_not_advance_past_the_failed_update(self):
        transport = ScriptedTransport()
        transport.queue("getUpdates", _ok([_text_update(9)]))

        async def failing_on_action(action):
            raise RuntimeError("boom")

        adapter = _make_adapter(transport, on_action=failing_on_action)
        await _run_briefly(adapter)

        get_updates_payloads = [p for name, p in transport.calls if name == "getUpdates"]
        # Second call must not have advanced past update 9 — it stays
        # unacknowledged so it is safely redelivered.
        assert "offset" not in get_updates_payloads[1]

    @pytest.mark.asyncio
    async def test_private_text_message_classified_as_text_action(self):
        transport = ScriptedTransport()
        transport.queue("getUpdates", _ok([_text_update(1, text="hello there")]))
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        (action,) = adapter.received
        assert action.kind == RemoteInboundActionKind.TEXT
        assert action.text == "hello there"
        assert action.principal.principal_id == "200"
        assert action.principal.destination_id == "100"
        assert action.source_key.endswith(":1")

    @pytest.mark.asyncio
    async def test_start_command_with_payload_classified_as_pairing_start(self):
        transport = ScriptedTransport()
        transport.queue("getUpdates", _ok([_text_update(1, text="/start abc123token")]))
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        (action,) = adapter.received
        assert action.kind == RemoteInboundActionKind.PAIRING_START
        assert action.pairing_token == "abc123token"

    @pytest.mark.asyncio
    async def test_bare_start_command_classified_as_pairing_start_with_no_token(self):
        transport = ScriptedTransport()
        transport.queue("getUpdates", _ok([_text_update(1, text="/start")]))
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        (action,) = adapter.received
        assert action.kind == RemoteInboundActionKind.PAIRING_START
        assert action.pairing_token is None

    @pytest.mark.asyncio
    async def test_group_chat_message_is_ignored(self):
        transport = ScriptedTransport()
        update = _text_update(1)
        update["message"]["chat"]["type"] = "group"
        transport.queue("getUpdates", _ok([update]))
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        assert adapter.received == []

    @pytest.mark.asyncio
    async def test_bot_authored_message_is_ignored(self):
        transport = ScriptedTransport()
        update = _text_update(1)
        update["message"]["from"]["is_bot"] = True
        transport.queue("getUpdates", _ok([update]))
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        assert adapter.received == []

    @pytest.mark.asyncio
    async def test_media_only_message_with_no_text_is_ignored(self):
        transport = ScriptedTransport()
        update = _text_update(1)
        update["message"]["text"] = None
        transport.queue("getUpdates", _ok([update]))
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        assert adapter.received == []

    @pytest.mark.asyncio
    async def test_callback_query_classified_with_opaque_token(self):
        transport = ScriptedTransport()
        transport.queue(
            "getUpdates",
            _ok(
                [
                    {
                        "update_id": 1,
                        "callback_query": {
                            "id": "raw-cbq-id-1",
                            "from": {"id": 200, "is_bot": False, "username": "alice"},
                            "message": {
                                "message_id": 42,
                                "date": 1,
                                "chat": {"id": 100, "type": "private"},
                            },
                            "data": "opaque-token-1",
                        },
                    }
                ]
            ),
        )
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)

        (action,) = adapter.received
        assert action.kind == RemoteInboundActionKind.CALLBACK
        assert action.callback_token == "opaque-token-1"
        assert action.principal.destination_id == "100"

    @pytest.mark.asyncio
    async def test_callback_query_without_data_is_ignored(self):
        transport = ScriptedTransport()
        transport.queue(
            "getUpdates",
            _ok(
                [
                    {
                        "update_id": 1,
                        "callback_query": {
                            "id": "raw-cbq-id-1",
                            "from": {"id": 200, "is_bot": False},
                            "data": None,
                        },
                    }
                ]
            ),
        )
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)
        assert adapter.received == []


# ---------------------------------------------------------------------------
# answer_callback: opaque token -> raw callback_query id
# ---------------------------------------------------------------------------


class TestAnswerCallback:
    @pytest.mark.asyncio
    async def test_answer_callback_resolves_opaque_token_to_raw_callback_id(self):
        transport = ScriptedTransport()
        transport.queue(
            "getUpdates",
            _ok(
                [
                    {
                        "update_id": 1,
                        "callback_query": {
                            "id": "raw-cbq-id-42",
                            "from": {"id": 200, "is_bot": False},
                            "message": {
                                "message_id": 1,
                                "date": 1,
                                "chat": {"id": 100, "type": "private"},
                            },
                            "data": "opaque-token-42",
                        },
                    }
                ]
            ),
        )
        adapter = _make_adapter(transport)
        await adapter.start()
        await asyncio.sleep(0.1)
        await adapter.answer_callback("opaque-token-42")
        await adapter.stop()

        _, payload = next(c for c in transport.calls if c[0] == "answerCallbackQuery")
        assert payload["callback_query_id"] == "raw-cbq-id-42"

    @pytest.mark.asyncio
    async def test_answer_callback_for_unknown_token_is_a_safe_noop(self):
        transport = ScriptedTransport()
        adapter = _make_adapter(transport)
        await adapter.answer_callback("never-seen-token")  # must not raise
        assert transport.call_count("answerCallbackQuery") == 0


# ---------------------------------------------------------------------------
# Telegram error taxonomy -> connection state (AC-12)
# ---------------------------------------------------------------------------


class TestErrorTaxonomy:
    @pytest.mark.asyncio
    async def test_webhook_conflict_is_cleared_once_and_retried_immediately(self):
        transport = ScriptedTransport()
        transport.queue(
            "getUpdates",
            _err(409, 409, "Conflict: can't use getUpdates method while webhook is active"),
        )
        adapter = _make_adapter(transport)
        start = time.monotonic()
        await _run_briefly(adapter, seconds=0.1)
        elapsed = time.monotonic() - start

        # Cleared once: deleteWebhook is called again (startup + recovery).
        assert transport.call_count("deleteWebhook") >= 2
        # Not a backoff state: recovers to polling promptly.
        assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_used_elsewhere_conflict_sets_state_and_backs_off(self):
        transport = ScriptedTransport()
        transport.fail_forever(
            "getUpdates",
            _err(
                409,
                409,
                "Conflict: terminated by other getUpdates request; make sure "
                "only one bot instance is running",
            ),
        )
        adapter = _make_adapter(transport, backoff_max_seconds=0.02)

        await adapter.start()
        await asyncio.sleep(0.05)
        status = adapter.status()
        await adapter.stop()

        assert status.state == RemoteConnectionState.USED_ELSEWHERE
        assert status.last_error_class == RemoteErrorClass.USED_ELSEWHERE

    @pytest.mark.asyncio
    async def test_invalid_token_stops_polling_permanently_for_this_start(self):
        transport = ScriptedTransport()
        transport.queue("getUpdates", _err(401, 401, "Unauthorized"))
        adapter = _make_adapter(transport)

        await adapter.start()
        await asyncio.sleep(0.1)
        status = adapter.status()
        calls_after_first_wait = transport.call_count("getUpdates")
        await asyncio.sleep(0.1)
        calls_after_second_wait = transport.call_count("getUpdates")
        await adapter.stop()

        assert status.state == RemoteConnectionState.INVALID_TOKEN
        assert status.last_error_class == RemoteErrorClass.INVALID_TOKEN
        # Terminal: no further getUpdates attempts, ever, for this start().
        assert calls_after_first_wait == calls_after_second_wait == 1

    @pytest.mark.asyncio
    async def test_rate_limit_honors_retry_after_verbatim(self):
        transport = ScriptedTransport()
        transport.fail_forever(
            "getUpdates", _err(429, 429, "Too Many Requests", retry_after=7)
        )
        adapter = _make_adapter(transport)

        sleeps: list[float] = []

        async def spy(seconds: float) -> None:
            sleeps.append(seconds)
            # Yield control without a real delay so the loop can retry
            # (still forever-429) without the test waiting out real seconds.
            await asyncio.sleep(0)

        adapter._interruptible_sleep = spy  # type: ignore[method-assign]

        await adapter.start()
        await asyncio.sleep(0.05)
        status = adapter.status()
        await adapter.stop()

        assert status.state == RemoteConnectionState.RATE_LIMITED
        assert sleeps and all(seconds == 7.0 for seconds in sleeps)

    @pytest.mark.asyncio
    async def test_transport_failure_backs_off(self):
        transport = ScriptedTransport()
        transport.fail_forever("getUpdates", httpx.ConnectError("boom"))
        adapter = _make_adapter(transport)

        await adapter.start()
        await asyncio.sleep(0.05)
        status = adapter.status()
        await adapter.stop()

        assert status.state == RemoteConnectionState.BACKOFF
        assert status.last_error_class == RemoteErrorClass.TRANSPORT

    @pytest.mark.asyncio
    async def test_successful_poll_after_backoff_recovers_to_polling(self):
        transport = ScriptedTransport()
        transport.queue("getUpdates", httpx.ConnectError("boom"))
        adapter = _make_adapter(transport)

        await adapter.start()
        await asyncio.sleep(0.15)
        status = adapter.status()
        await adapter.stop()

        assert status.state == RemoteConnectionState.POLLING
        assert status.last_error_class == RemoteErrorClass.NONE
        assert status.last_successful_poll_at is not None


# ---------------------------------------------------------------------------
# Delivery: phone_unreachable is independent of inbound polling (AC-12)
# ---------------------------------------------------------------------------


class TestDeliveryIndependentOfPolling:
    @pytest.mark.asyncio
    async def test_send_failure_sets_phone_unreachable_without_crashing_poll_loop(self):
        transport = ScriptedTransport()
        transport.queue(
            "sendMessage", _err(403, 403, "Forbidden: bot was blocked by the user")
        )
        adapter = _make_adapter(transport)

        await adapter.start()
        await asyncio.sleep(0.05)

        from app.remote.telegram.client import TelegramApiError

        with pytest.raises(TelegramApiError):
            await adapter.send(
                RemoteOutboundMessage(
                    connection_id=uuid4(), destination_id="100", text="hi"
                )
            )

        status = adapter.status()
        await adapter.stop()

        assert status.phone_reachable is False
        assert status.last_error_class == RemoteErrorClass.PHONE_UNREACHABLE
        # Inbound polling is unaffected — still healthy.
        assert status.state == RemoteConnectionState.PHONE_UNREACHABLE

    @pytest.mark.asyncio
    async def test_successful_send_marks_phone_reachable(self):
        transport = ScriptedTransport()
        transport.queue(
            "sendMessage",
            _ok({"message_id": 1, "date": 1, "chat": {"id": 100, "type": "private"}}),
        )
        adapter = _make_adapter(transport)
        await adapter.start()
        await asyncio.sleep(0.02)

        await adapter.send(
            RemoteOutboundMessage(connection_id=uuid4(), destination_id="100", text="hi")
        )
        status = adapter.status()
        await adapter.stop()

        assert status.phone_reachable is True
        assert status.state == RemoteConnectionState.POLLING


# ---------------------------------------------------------------------------
# Prompt shutdown (AC-13)
# ---------------------------------------------------------------------------


class TestPromptShutdown:
    @pytest.mark.asyncio
    async def test_stop_interrupts_backoff_promptly(self):
        transport = ScriptedTransport()
        transport.queue("getUpdates", httpx.ConnectError("boom"))
        adapter = _make_adapter(
            transport, backoff_base_seconds=30.0, backoff_max_seconds=30.0
        )

        await adapter.start()
        await asyncio.sleep(0.05)  # let it enter the (real) 30s backoff sleep

        start = time.monotonic()
        await adapter.stop()
        elapsed = time.monotonic() - start

        assert elapsed < 2.0

    @pytest.mark.asyncio
    async def test_stop_interrupts_an_in_flight_long_poll_promptly(self):
        transport = ScriptedTransport()

        async def slow_get_updates(request: httpx.Request) -> httpx.Response:
            method = request.url.path.rsplit("/", 1)[-1]
            transport.calls.append((method, {}))
            if method == "getUpdates":
                await asyncio.sleep(100)  # never resolves within test time
            return _ok(True)

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(slow_get_updates))
        adapter = TelegramAdapter(
            connection_id=uuid4(),
            token=TOKEN,
            on_action=lambda action: _noop(),
            http_client=http_client,
        )

        await adapter.start()
        await asyncio.sleep(0.05)  # let it enter the in-flight getUpdates call

        start = time.monotonic()
        await adapter.stop()
        elapsed = time.monotonic() - start

        assert elapsed < 2.0

    @pytest.mark.asyncio
    async def test_duplicate_start_is_a_noop(self):
        transport = ScriptedTransport()
        adapter = _make_adapter(transport)
        await adapter.start()
        first_task = adapter._task
        await adapter.start()
        assert adapter._task is first_task
        await adapter.stop()

    @pytest.mark.asyncio
    async def test_duplicate_stop_is_safe(self):
        transport = ScriptedTransport()
        adapter = _make_adapter(transport)
        await adapter.start()
        await asyncio.sleep(0.02)
        await adapter.stop()
        await adapter.stop()  # must not raise

    @pytest.mark.asyncio
    async def test_stop_before_start_is_safe(self):
        transport = ScriptedTransport()
        adapter = _make_adapter(transport)
        await adapter.stop()  # must not raise


async def _noop() -> None:
    return None


# ---------------------------------------------------------------------------
# status() never leaks provider payloads or the token
# ---------------------------------------------------------------------------


class TestStatusIsSafe:
    @pytest.mark.asyncio
    async def test_status_never_contains_the_token(self):
        transport = ScriptedTransport()
        transport.queue("getUpdates", _err(401, 401, "Unauthorized"))
        adapter = _make_adapter(transport)
        await _run_briefly(adapter)
        status = adapter.status()
        assert TOKEN not in repr(status)
        assert TOKEN not in str(status)
