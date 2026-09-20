"""BlueBubbles REST provider kept behind the iMessage provider contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urljoin

import httpx

from app.remote.contracts import RemoteAttachment
from app.remote.imessage.provider import IMessageProviderError


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
        self, *, after: str | None = None
    ) -> list[Mapping[str, Any]]:
        params: dict[str, str] = {"password": self._password}
        if after is not None:
            params["after"] = after
        payload = await self._request("api/v1/message/query", params=params)
        messages = payload.get("data", payload.get("messages", []))
        return [message for message in messages if isinstance(message, dict)]

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
