"""Capability probing and safe provider health classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.remote.imessage.provider import IMessageProvider
from app.remote.imessage.rpc import IMessageRpcError, IMessageRpcProtocolError


class IMessageHealth(StrEnum):
    HEALTHY = "healthy"
    ENDPOINT_UNREACHABLE = "endpoint_unreachable"
    AUTHENTICATION_FAILED = "authentication_failed"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True)
class IMessageCapabilities:
    provider: str
    health: IMessageHealth
    features: frozenset[str]
    detail: str | None = None


async def probe_provider(
    provider: IMessageProvider, *, provider_name: str
) -> IMessageCapabilities:
    """Probe without returning provider payloads or secrets."""
    try:
        status: Any = await provider.status()
    except IMessageRpcError as exc:
        health = (
            IMessageHealth.AUTHENTICATION_FAILED
            if exc.code in {-32001, 401, 403}
            else IMessageHealth.PROVIDER_ERROR
        )
        return IMessageCapabilities(provider_name, health, frozenset())
    except (IMessageRpcProtocolError, OSError, TimeoutError):
        return IMessageCapabilities(
            provider_name, IMessageHealth.ENDPOINT_UNREACHABLE, frozenset()
        )
    if not isinstance(status, dict):
        return IMessageCapabilities(
            provider_name, IMessageHealth.PROVIDER_ERROR, frozenset()
        )
    features = status.get("features", [])
    safe_features = frozenset(str(item) for item in features if isinstance(item, str))
    return IMessageCapabilities(provider_name, IMessageHealth.HEALTHY, safe_features)
