"""Common registry for provider-neutral remote adapter construction."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from app.models.remote import RemoteConnection
from app.remote.contracts import (
    RemoteAdapter,
    RemoteAdapterKind,
    RemoteInboundAction,
    RemoteProviderKind,
    ValidatedRemoteIdentity,
)
from app.remote.imessage.adapter import IMessageRemoteAdapter
from app.remote.imessage.provider import IMessageProviderError, IMessageProviderFactory
from app.remote.imessage.rpc import IMessageRpcError, IMessageRpcProtocolError

RemoteActionHandler = Callable[[RemoteInboundAction], Awaitable[object]]
AdapterConstructor = Callable[[UUID, str, RemoteActionHandler], RemoteAdapter]
IdentityValidator = Callable[[str], Awaitable[ValidatedRemoteIdentity]]


class RemoteAdapterRegistry(Protocol):
    async def validate(
        self,
        connection: RemoteConnection,
        credential: str,
    ) -> ValidatedRemoteIdentity: ...

    def create(
        self,
        connection: RemoteConnection,
        credential: str,
        on_action: RemoteActionHandler,
    ) -> RemoteAdapter: ...


class DefaultRemoteAdapterRegistry:
    def __init__(
        self,
        *,
        telegram_constructor: AdapterConstructor | None = None,
        telegram_validator: IdentityValidator | None = None,
        imessage_provider_factory: IMessageProviderFactory | None = None,
    ) -> None:
        self._telegram_constructor = telegram_constructor
        self._telegram_validator = telegram_validator
        self._imessage_provider_factory = (
            imessage_provider_factory or IMessageProviderFactory()
        )

    async def validate(
        self,
        connection: RemoteConnection,
        credential: str,
    ) -> ValidatedRemoteIdentity:
        adapter = RemoteAdapterKind(connection.adapter)
        if adapter is RemoteAdapterKind.TELEGRAM:
            if self._telegram_validator is None:
                raise ValueError("Telegram validation is not configured")
            return await self._telegram_validator(credential)
        if adapter is RemoteAdapterKind.IMESSAGE:
            provider = RemoteProviderKind(
                connection.provider or RemoteProviderKind.IMSG
            )
            try:
                transport = self._imessage_provider_factory.create(
                    provider,
                    endpoint_url=connection.endpoint_url,
                    password=credential,
                )
                try:
                    await transport.start()
                finally:
                    await transport.stop()
            except (
                IMessageProviderError,
                IMessageRpcError,
                IMessageRpcProtocolError,
                OSError,
            ) as exc:
                raise ValueError(f"iMessage provider validation failed: {exc}") from exc
            return ValidatedRemoteIdentity(
                adapter=RemoteAdapterKind.IMESSAGE,
                principal_id=f"imessage:{provider.value}",
                username=provider.value,
            )
        raise ValueError(f"Unsupported remote adapter: {connection.adapter}")

    def create(
        self,
        connection: RemoteConnection,
        credential: str,
        on_action: RemoteActionHandler,
    ) -> RemoteAdapter:
        adapter = RemoteAdapterKind(connection.adapter)
        if adapter is RemoteAdapterKind.TELEGRAM:
            if self._telegram_constructor is None:
                raise ValueError("Telegram construction is not configured")
            return self._telegram_constructor(connection.id, credential, on_action)
        if adapter is RemoteAdapterKind.IMESSAGE:
            provider = RemoteProviderKind(
                connection.provider or RemoteProviderKind.IMSG
            )
            return IMessageRemoteAdapter(
                connection_id=connection.id,
                credential=credential,
                on_action=on_action,
                provider_name=provider,
                endpoint_url=connection.endpoint_url,
            )
        raise ValueError(f"Unsupported remote adapter: {connection.adapter}")
