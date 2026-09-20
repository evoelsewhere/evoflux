"""Provider adapter for the native ``imsg`` JSON-RPC process."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.remote.contracts import RemoteAttachment
from app.remote.imessage.rpc import IMessageRpcClient


class IMsgProvider:
    def __init__(self, *, client: IMessageRpcClient) -> None:
        self._client = client

    async def start(self) -> None:
        await self._client.start()

    async def stop(self) -> None:
        await self._client.stop()

    async def status(self) -> Mapping[str, Any]:
        return await self._client.request("status")

    async def query_messages(
        self, *, after: str | None = None
    ) -> list[Mapping[str, Any]]:
        params: dict[str, Any] = {}
        if after is not None:
            params["after"] = after
        result = await self._client.request("messages.list", params=params)
        messages = result.get("messages", [])
        return [message for message in messages if isinstance(message, dict)]

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        reply_to_id: str | None = None,
        attachments: Sequence[RemoteAttachment] = (),
    ) -> Mapping[str, Any]:
        params: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_to_id is not None:
            params["reply_to"] = reply_to_id
        if attachments:
            params["attachments"] = [
                {
                    key: value
                    for key, value in {
                        "url": attachment.url,
                        "mime_type": attachment.mime_type,
                        "filename": attachment.filename,
                    }.items()
                    if value is not None
                }
                for attachment in attachments
            ]
        return await self._client.request("send", params=params)
