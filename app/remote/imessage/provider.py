"""Provider-neutral iMessage transport contracts and provider selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.remote.contracts import RemoteAttachment, RemoteProviderKind
from app.remote.imessage.rpc import IMessageRpcClient

#: Default bounded page size for one catchup call.
DEFAULT_QUERY_LIMIT = 200


@dataclass(frozen=True)
class MessagePage:
    """One page of new messages plus an opaque forward cursor.

    ``since_cursor``/``next_cursor`` are deliberately opaque strings at this
    shared boundary: each concrete provider owns what the string actually
    means (imsg encodes its numeric, exclusive ``since_rowid``; BlueBubbles
    keeps its own native cursor) so the poller and the durable watermark
    column never need to know which provider produced it.
    """

    messages: Sequence[Mapping[str, Any]]
    next_cursor: str | None
    has_more: bool


class IMessageProvider(Protocol):
    """Transport contract consumed by the remote runtime."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def status(self) -> Mapping[str, Any]: ...

    async def query_messages(
        self, *, since_cursor: str | None = None, limit: int = DEFAULT_QUERY_LIMIT
    ) -> MessagePage: ...

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        reply_to_id: str | None = None,
        attachments: Sequence[RemoteAttachment] = (),
    ) -> Mapping[str, Any]: ...


class IMessageProviderError(Exception):
    """Safe provider failure without raw payloads."""


class IMessageProviderFactory:
    """Construct the configured provider without leaking provider DTOs."""

    def __init__(self, *, rpc_client: IMessageRpcClient | None = None) -> None:
        self._rpc_client = rpc_client

    def create(
        self,
        provider: RemoteProviderKind | str,
        *,
        endpoint_url: str | None = None,
        password: str | None = None,
    ) -> IMessageProvider:
        try:
            normalized = RemoteProviderKind(provider).value
        except ValueError as exc:
            raise IMessageProviderError(
                f"Unsupported iMessage provider: {provider}"
            ) from exc
        if normalized == "imsg":
            from app.remote.imessage.imsg_provider import IMsgProvider

            return IMsgProvider(client=self._rpc_client or IMessageRpcClient())
        if normalized == "bluebubbles":
            from app.remote.imessage.bluebubbles import BlueBubblesProvider

            if endpoint_url is None or password is None:
                raise IMessageProviderError(
                    "BlueBubbles provider requires endpoint and credential."
                )
            return BlueBubblesProvider(endpoint_url=endpoint_url, password=password)
        raise IMessageProviderError(f"Unsupported iMessage provider: {normalized}")
