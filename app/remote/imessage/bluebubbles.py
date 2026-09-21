"""BlueBubbles REST provider kept behind the iMessage provider contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urljoin

import httpx

from app.remote.contracts import RemoteAttachment
from app.remote.imessage.provider import (
    DEFAULT_QUERY_LIMIT,
    IMessageProviderError,
    MessagePage,
)


class BlueBubblesProvider:
    def __init__(
        self,
        *,
        endpoint_url: str,
        password: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        endpoint = endpoint_url.strip()
        if not endpoint.startswith(("https://", "http://")):
            raise IMessageProviderError("BlueBubbles endpoint must use HTTP(S).")
        self._base_url = endpoint.rstrip("/") + "/"
        self._password = password
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None

    async def start(self) -> None:
        await self.status()

    async def stop(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def status(self) -> Mapping[str, Any]:
        return await self._request("api/v1/server")

    async def query_messages(
        self, *, since_cursor: str | None = None, limit: int = DEFAULT_QUERY_LIMIT
    ) -> MessagePage:
        """Catch up via BlueBubbles' own REST cursor.

        Unlike imsg's ``messages.after``, BlueBubbles' query endpoint
        returns no explicit next-cursor or has-more flag, so the highest
        message identifier actually observed becomes the next cursor —
        the same derivation the shared poller used to do itself before the
        cursor contract moved behind this provider boundary.
        """
        params: dict[str, str] = {"password": self._password}
        if since_cursor is not None:
            params["after"] = since_cursor
        payload = await self._request("api/v1/message/query", params=params)
        raw_messages = payload.get("data", payload.get("messages", []))
        messages = [message for message in raw_messages if isinstance(message, dict)]
        next_cursor = since_cursor
        for message in messages:
            candidate = message.get("guid") or message.get("id")
            if isinstance(candidate, str) and (
                next_cursor is None or candidate > next_cursor
            ):
                next_cursor = candidate
        return MessagePage(messages=messages, next_cursor=next_cursor, has_more=False)

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        reply_to_id: str | None = None,
        attachments: Sequence[RemoteAttachment] = (),
    ) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
            "guid": chat_id,
            "text": text,
            "password": self._password,
        }
        if reply_to_id is not None:
            payload["replyTo"] = reply_to_id
        if attachments:
            payload["attachments"] = [
                {
                    key: value
                    for key, value in {
                        "url": attachment.url,
                        "mimeType": attachment.mime_type,
                        "filename": attachment.filename,
                    }.items()
                    if value is not None
                }
                for attachment in attachments
            ]
        return await self._request(
            "api/v1/message/text",
            method="POST",
            json=payload,
        )

    async def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                urljoin(self._base_url, path),
                params=params,
                json=json,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IMessageProviderError(
                f"BlueBubbles request failed ({type(exc).__name__})."
            ) from exc
        if not isinstance(payload, dict):
            raise IMessageProviderError("BlueBubbles returned an invalid response.")
        return payload
