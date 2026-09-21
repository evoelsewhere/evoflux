"""RemoteAdapter compatibility wrapper for the iMessage channel."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from loguru import logger

from app.remote.contracts import (
    RemoteAdapterStatus,
    RemoteConnectionState,
    RemoteErrorClass,
    RemoteOutboundMessage,
    RemoteProviderKind,
)
from app.remote.imessage.channel import IMessageChannel


class IMessageRemoteAdapter:
    def __init__(
        self,
        *,
        connection_id: UUID,
        credential: str,
        on_action,
        provider_name: RemoteProviderKind | str = RemoteProviderKind.IMSG,
        endpoint_url: str | None = None,
    ) -> None:
        self.connection_id = connection_id
        self._credential = credential
        self._provider_name = RemoteProviderKind(provider_name)
        self._endpoint_url = endpoint_url
        self._on_action = on_action
        self._channel: IMessageChannel | None = None
        self._status = RemoteAdapterStatus(
            connection_id=connection_id,
            state=RemoteConnectionState.DISABLED,
        )
        self._paired_principal_id: str | None = None
        self._paired_destination_id: str | None = None

    def set_pairing(self, *, principal_id: str, destination_id: str) -> None:
        self._paired_principal_id = principal_id
        self._paired_destination_id = destination_id

    def clear_pairing(self) -> None:
        self._paired_principal_id = None
        self._paired_destination_id = None

    async def start(self) -> None:
        """Start (or restart) the channel.

        Runs in discovery mode when no contact is bound yet — the poller is
        live and reachable, but ``IMessageChannel``/``normalize_inbound``
        recognize nothing from an unrecognized sender except a ``/pair
        <code>`` attempt (see ``app/remote/imessage/inbound.py``). Reported
        state stays ``PAIRING`` until a caller supplies a contact via
        :meth:`set_pairing` and calls ``start`` again, which is idempotent:
        an already-running channel (discovery or previously paired) is
        stopped first so it is never leaked.
        """
        if self._channel is not None:
            await self._channel.stop()
            self._channel = None

        from app.remote.imessage.provider import IMessageProviderFactory

        self._channel = IMessageChannel(
            connection_id=self.connection_id,
            provider_name=self._provider_name,
            provider_factory=IMessageProviderFactory(),
            endpoint_url=self._endpoint_url,
            password=self._credential,
            paired_principal_id=self._paired_principal_id,
            paired_destination_id=self._paired_destination_id,
            load_watermark=self._load_watermark,
            save_watermark=self._save_watermark,
            on_action=self._on_action,
        )
        try:
            capabilities = await self._channel.start()
        except Exception as exc:
            logger.warning(
                "imessage_adapter_start_failed connection_id={} error_type={}",
                self.connection_id,
                type(exc).__name__,
            )
            try:
                await self._channel.stop()
            except Exception as cleanup_exc:
                logger.warning(
                    "imessage_adapter_start_cleanup_failed connection_id={} error_type={}",
                    self.connection_id,
                    type(cleanup_exc).__name__,
                )
            self._channel = None
            is_paired = (
                self._paired_principal_id is not None
                and self._paired_destination_id is not None
            )
            self._status = RemoteAdapterStatus(
                connection_id=self.connection_id,
                state=RemoteConnectionState.ERROR,
                last_error_class=RemoteErrorClass.TRANSPORT,
                paired=is_paired,
            )
            return
        is_paired = (
            self._paired_principal_id is not None
            and self._paired_destination_id is not None
        )
        healthy = capabilities.health.value == "healthy"
        if not healthy:
            state = RemoteConnectionState.ERROR
        elif is_paired:
            state = RemoteConnectionState.POLLING
        else:
            state = RemoteConnectionState.PAIRING
        self._status = RemoteAdapterStatus(
            connection_id=self.connection_id,
            state=state,
            last_successful_poll_at=datetime.now(UTC) if healthy else None,
            last_error_class=(
                RemoteErrorClass.NONE if healthy else RemoteErrorClass.UNKNOWN
            ),
            paired=is_paired,
            capabilities=capabilities.features,
        )

    async def stop(self) -> None:
        if self._channel is not None:
            await self._channel.stop()
            self._channel = None
        self._status = RemoteAdapterStatus(
            connection_id=self.connection_id,
            state=RemoteConnectionState.DISABLED,
        )

    async def send(self, message: RemoteOutboundMessage) -> None:
        if self._channel is None:
            return
        await self._channel.send_text(
            text=message.text,
            reply_to_id=message.reply_to_id,
            attachments=message.attachments,
        )

    async def edit(self, message: RemoteOutboundMessage) -> None:
        await self.send(message)

    async def answer_callback(self, callback_token: str) -> None:
        return None

    async def indicate_typing(self, destination_id: str) -> None:
        return None

    def status(self) -> RemoteAdapterStatus:
        return self._status

    async def _load_watermark(self) -> str | None:
        """Load the connection's durable, provider-opaque inbound cursor."""
        from sqlmodel import select

        from app.core.db import read_session_factory
        from app.models.remote import RemoteConnection

        async with read_session_factory() as session:
            connection = await session.scalar(
                select(RemoteConnection).where(
                    RemoteConnection.id == self.connection_id
                )
            )
        if connection is None:
            return None
        return connection.inbound_watermark_cursor

    async def _save_watermark(self, value: str) -> None:
        """Persist the latest provider cursor without storing message
        content. Opaque here by design — see `app/remote/imessage/provider.py`."""
        from app.core.db import async_session_factory
        from app.models.remote import RemoteConnection

        async with async_session_factory() as session:
            connection = await session.get(RemoteConnection, self.connection_id)
            if connection is None:
                return
            connection.inbound_watermark_cursor = value
            session.add(connection)
            await session.commit()
