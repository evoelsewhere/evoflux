"""End-to-end iMessage channel orchestration seam."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from uuid import UUID

from app.remote.contracts import RemoteAttachment, RemoteInboundAction
from app.remote.imessage.capabilities import IMessageCapabilities, probe_provider
from app.remote.imessage.inbound import normalize_inbound
from app.remote.imessage.poller import IMessagePoller
from app.remote.imessage.provider import IMessageProvider, IMessageProviderFactory
from app.remote.imessage.redaction import redact

ActionSink = Callable[[RemoteInboundAction], Awaitable[None]]


class IMessageChannel:
    """Connect one configured provider to normalized remote actions."""

    def __init__(
        self,
        *,
        connection_id: UUID,
        provider_name: str,
        provider: IMessageProvider | None = None,
        provider_factory: IMessageProviderFactory | None = None,
        endpoint_url: str | None = None,
        password: str | None = None,
        paired_principal_id: str,
        paired_destination_id: str,
        load_watermark: Callable[[], Awaitable[str | None]],
        save_watermark: Callable[[str], Awaitable[None]],
        on_action: ActionSink,
    ) -> None:
        self.connection_id = connection_id
        self.provider_name = provider_name
        self._provider = provider or (
            provider_factory or IMessageProviderFactory()
        ).create(provider_name, endpoint_url=endpoint_url, password=password)
        self._paired_principal_id = paired_principal_id
        self._paired_destination_id = paired_destination_id
        self._on_action = on_action
        self._poller = IMessagePoller(
            self._provider,
            on_message=self._handle_message,
            load_watermark=load_watermark,
            save_watermark=save_watermark,
        )
        self.capabilities: IMessageCapabilities | None = None

    async def start(self) -> IMessageCapabilities:
        await self._provider.start()
        self.capabilities = await probe_provider(
            self._provider, provider_name=self.provider_name
        )
        if self.capabilities.health.value != "healthy":
            return self.capabilities
        await self._poller.start()
        return self.capabilities

    async def stop(self) -> None:
        await self._poller.stop()

    async def send_text(
        self,
        *,
        text: str,
        reply_to_id: str | None = None,
        attachments: Sequence[RemoteAttachment] = (),
    ) -> Mapping[str, object]:
        """Send only to the configured paired destination."""
        return await self._provider.send_text(
            chat_id=self._paired_destination_id,
            text=redact(text),
            reply_to_id=reply_to_id,
            attachments=attachments,
        )

    async def _handle_message(self, message: dict[str, object]) -> None:
        action = normalize_inbound(
            message,
            connection_id=self.connection_id,
            paired_principal_id=self._paired_principal_id,
            paired_destination_id=self._paired_destination_id,
        )
        if action is not None:
            await self._on_action(action)
