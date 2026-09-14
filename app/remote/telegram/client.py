"""Telegram Bot API HTTP client.

Owns the ``httpx.AsyncClient``, the ``https://api.telegram.org/bot<TOKEN>/``
request shape, and translation of Bot API responses into safe internal
types. No exception this module raises — and no log line a caller should
ever write from one — includes the request URL, because the URL embeds the
bot token as a path segment. Every error carries only Telegram's
``error_code``/``description`` (already token-free — the token lives in the
URL, never the body) or the *type name* of a transport failure.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

import httpx
from pydantic import TypeAdapter, ValidationError

from app.remote.contracts import RemoteButton
from app.remote.telegram.models import (
    TelegramMessage,
    TelegramResponse,
    TelegramUpdate,
    TelegramUser,
)

TELEGRAM_API_BASE = "https://api.telegram.org"

#: Telegram's inclusive byte-length contract for one button's callback_data.
CALLBACK_DATA_MIN_BYTES = 1
CALLBACK_DATA_MAX_BYTES = 64

#: Only these update kinds are ever requested (spec: "Telegram update
#: contract") — no edited messages, channel posts, or other update kinds.
ALLOWED_UPDATE_KINDS: tuple[str, ...] = ("message", "callback_query")

#: Extra seconds of HTTP read-timeout headroom over the server-side
#: long-poll `timeout` so the client never times out before Telegram does.
_LONG_POLL_TIMEOUT_MARGIN_SECONDS = 10.0
_DEFAULT_TIMEOUT_SECONDS = 30.0

T = TypeVar("T")


class TelegramClientError(Exception):
    """Base class for every error this client raises.

    Never carries the request URL (which embeds the bot token) or the bot
    token itself.
    """


class TelegramApiError(TelegramClientError):
    """The Bot API responded with ``ok: false``.

    Carries only Telegram's own ``error_code``/``description`` (safe — the
    token lives in the URL, never the response body) and any ``retry_after``
    Telegram supplied in ``parameters``. Adapter-level code classifies this
    into the spec's error taxonomy (webhook conflict, used-elsewhere,
    invalid token, rate limit, ...).
    """

    def __init__(
        self,
        *,
        error_code: int | None,
        description: str | None,
        retry_after: int | None = None,
    ) -> None:
        self.error_code = error_code
        self.description = description or ""
        self.retry_after = retry_after
        message = "Telegram API error"
        if error_code is not None:
            message += f" {error_code}"
        if self.description:
            message += f": {self.description}"
        super().__init__(message)


class TelegramTransportError(TelegramClientError):
    """A network-level failure talking to the Bot API.

    Carries only the underlying exception's type name — never the
    exception's own message, which for some httpx errors includes the
    request URL.
    """

    def __init__(self, *, cause_type: str) -> None:
        self.cause_type = cause_type
        super().__init__(f"Telegram request failed ({cause_type}).")


class TelegramMalformedResponseError(TelegramClientError):
    """The Bot API response body was not valid JSON, or did not match the
    expected envelope shape. Never echoes the raw response body, which
    could (in principle) reflect request content back."""


class TelegramCallbackDataError(TelegramClientError, ValueError):
    """A ``callback_data`` payload violates Telegram's 1-64 byte contract.

    Raised before any request is sent, so a caller never has to distinguish
    "rejected locally" from "rejected by Telegram after the fact".
    """


def _validate_callback_data(token: str) -> None:
    size = len(token.encode("utf-8"))
    if not (CALLBACK_DATA_MIN_BYTES <= size <= CALLBACK_DATA_MAX_BYTES):
        raise TelegramCallbackDataError(
            "callback_data must be "
            f"{CALLBACK_DATA_MIN_BYTES}-{CALLBACK_DATA_MAX_BYTES} bytes; got {size}."
        )


def _build_reply_markup(buttons: Sequence[RemoteButton]) -> dict[str, Any] | None:
    if not buttons:
        return None
    for button in buttons:
        _validate_callback_data(button.token)
    return {
        "inline_keyboard": [
            [{"text": button.text, "callback_data": button.token}] for button in buttons
        ]
    }


class TelegramClient:
    """Thin, provider-specific translation over the Telegram Bot API.

    Constructed from a bot token; an ``httpx.AsyncClient`` can be injected
    (tests use ``httpx.MockTransport``) or is otherwise created and owned —
    and closed — by this client.
    """

    def __init__(
        self, token: str, *, http_client: httpx.AsyncClient | None = None
    ) -> None:
        if not token:
            raise ValueError("A Telegram bot token is required.")
        self._token = token
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(_DEFAULT_TIMEOUT_SECONDS)
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _url(self, method: str) -> str:
        return f"{TELEGRAM_API_BASE}/bot{self._token}/{method}"

    async def _call(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        result_model: type[T],
        timeout: float | None = None,
    ) -> T:
        try:
            response = await self._http.post(
                self._url(method),
                json=payload,
                timeout=(
                    httpx.Timeout(timeout)
                    if timeout is not None
                    else httpx.USE_CLIENT_DEFAULT
                ),
            )
        except httpx.HTTPError as exc:
            raise TelegramTransportError(cause_type=type(exc).__name__) from None

        try:
            body = response.json()
        except ValueError:
            raise TelegramMalformedResponseError(
                f"Telegram {method} response was not valid JSON."
            ) from None

        # Validated generically first (``Any`` is a real type expression, so
        # this subscript is fine for a static checker); the payload-specific
        # shape is validated separately below via ``TypeAdapter``, which
        # takes a plain runtime value rather than a static subscript.
        try:
            envelope = TelegramResponse[Any].model_validate(body)
        except ValidationError:
            raise TelegramMalformedResponseError(
                f"Telegram {method} response did not match the expected shape."
            ) from None

        if not envelope.ok:
            retry_after = (
                envelope.parameters.retry_after if envelope.parameters else None
            )
            raise TelegramApiError(
                error_code=envelope.error_code,
                description=envelope.description,
                retry_after=retry_after,
            )

        if envelope.result is None:
            raise TelegramMalformedResponseError(
                f"Telegram {method} response had no result."
            )
        try:
            return TypeAdapter(result_model).validate_python(envelope.result)
        except ValidationError:
            raise TelegramMalformedResponseError(
                f"Telegram {method} response did not match the expected shape."
            ) from None

    # -- Bot API methods --------------------------------------------------

    async def get_me(self) -> TelegramUser:
        return await self._call("getMe", {}, result_model=TelegramUser)

    async def delete_webhook(self, *, drop_pending_updates: bool = True) -> None:
        await self._call(
            "deleteWebhook",
            {"drop_pending_updates": drop_pending_updates},
            result_model=bool,
        )

    async def get_updates(
        self,
        *,
        offset: int | None,
        timeout: int,
        allowed_updates: Sequence[str] = ALLOWED_UPDATE_KINDS,
    ) -> list[TelegramUpdate]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": list(allowed_updates),
        }
        if offset is not None:
            payload["offset"] = offset
        return await self._call(
            "getUpdates",
            payload,
            result_model=list[TelegramUpdate],
            timeout=float(timeout) + _LONG_POLL_TIMEOUT_MARGIN_SECONDS,
        )

    async def send_text(
        self,
        *,
        chat_id: str | int,
        text: str,
        buttons: Sequence[RemoteButton] = (),
    ) -> TelegramMessage:
        # No parse_mode, ever (AC-24): model/agent text must never be
        # interpreted as Telegram markup.
        markup = _build_reply_markup(buttons)
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if markup is not None:
            payload["reply_markup"] = markup
        return await self._call("sendMessage", payload, result_model=TelegramMessage)

    async def edit_text(
        self,
        *,
        chat_id: str | int,
        message_id: int,
        text: str,
        buttons: Sequence[RemoteButton] = (),
    ) -> TelegramMessage:
        markup = _build_reply_markup(buttons)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if markup is not None:
            payload["reply_markup"] = markup
        return await self._call(
            "editMessageText", payload, result_model=TelegramMessage
        )

    async def answer_callback(
        self, callback_query_id: str, *, text: str | None = None
    ) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
        await self._call("answerCallbackQuery", payload, result_model=bool)

    async def set_commands(self, commands: Sequence[tuple[str, str]]) -> None:
        payload = {
            "commands": [
                {"command": command, "description": description}
                for command, description in commands
            ]
        }
        await self._call("setMyCommands", payload, result_model=bool)


__all__ = [
    "ALLOWED_UPDATE_KINDS",
    "CALLBACK_DATA_MAX_BYTES",
    "CALLBACK_DATA_MIN_BYTES",
    "TelegramApiError",
    "TelegramCallbackDataError",
    "TelegramClient",
    "TelegramClientError",
    "TelegramMalformedResponseError",
    "TelegramTransportError",
]
