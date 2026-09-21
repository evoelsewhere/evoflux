"""Provider adapter for the native ``imsg`` JSON-RPC process."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.remote.contracts import RemoteAttachment
from app.remote.imessage.provider import DEFAULT_QUERY_LIMIT, MessagePage
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
        self, *, since_cursor: str | None = None, limit: int = DEFAULT_QUERY_LIMIT
    ) -> MessagePage:
        """Catch up in stable ROWID order using the RPC's ``messages.after``.

        Not ``messages.list``, which does not exist in the ``imsg`` RPC
        surface and always fails with a JSON-RPC "Method not found" error
        that a poller's generic retry/backoff handler swallows silently,
        looking exactly like "no messages ever arrive" rather than a wrong
        method name.

        The shared cursor contract is an opaque string; this provider is
        the only place that knows it encodes imsg's own exclusive integer
        ``since_rowid``, so the string<->int conversion stays local to it.
        """
        since_rowid = 0
        if since_cursor is not None:
            try:
                since_rowid = int(since_cursor)
            except ValueError:
                since_rowid = 0
        result = await self._client.request(
            "messages.after",
            params={"since_rowid": since_rowid, "limit": limit},
        )
        raw_messages = result.get("messages", [])
        messages = [message for message in raw_messages if isinstance(message, dict)]
        next_rowid = result.get("next_rowid")
        if not isinstance(next_rowid, int):
            next_rowid = since_rowid
        return MessagePage(
            messages=messages,
            next_cursor=str(next_rowid),
            has_more=bool(result.get("has_more", False)),
        )

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        reply_to_id: str | None = None,
        attachments: Sequence[RemoteAttachment] = (),
    ) -> Mapping[str, Any]:
        # `chat_id` here is EvoFlux's own generic "destination" parameter
        # name; it always carries imsg's *string* `chat_identifier` (see
        # `app/remote/imessage/inbound.py`), never the numeric `chat_id`
        # `messages.after` reports — `send`'s `chat_id` selector wants that
        # integer database rowid instead, so passing our string through
        # under that key would resolve to the wrong (or no) chat.
        params: dict[str, Any] = {"chat_identifier": chat_id, "text": text}
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
