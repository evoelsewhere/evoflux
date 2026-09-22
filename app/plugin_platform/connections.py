"""Host-side connection approval and outbound data controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import urlparse

from app.plugin_platform.models import PluginConnectionProfile, PluginRunContext


class ConnectionDeniedError(PermissionError):
    """A connection request failed a host-controlled guard."""


@dataclass(frozen=True, slots=True)
class ConnectionDecision:
    allowed: bool
    reason: str
    endpoint: str
    operation: str
    resource: str


def _active(profile: PluginConnectionProfile, now: datetime) -> bool:
    if not profile.enabled or profile.approval != "approved":
        return False
    if profile.revoked_at is not None:
        return False
    if profile.expires_at is not None:
        try:
            return datetime.fromisoformat(profile.expires_at) > now
        except ValueError:
            return False
    return True


def _host_allowed(profile: PluginConnectionProfile, endpoint: str) -> bool:
    requested = urlparse(endpoint)
    configured = urlparse(profile.endpoint)
    if requested.scheme != "https" or not requested.hostname:
        return False
    if (
        configured.hostname
        and requested.hostname.casefold() == configured.hostname.casefold()
    ):
        return True
    return requested.hostname.casefold() in {
        domain.casefold().lstrip(".") for domain in profile.allowed_domains
    }


def authorize_connection(
    profile: PluginConnectionProfile,
    context: PluginRunContext,
    *,
    endpoint: str,
    operation: str,
    resource: str,
    usage: dict[str, int] | None = None,
) -> ConnectionDecision:
    """Apply approval, ownership, allowlist, lifecycle, and budget checks."""

    if profile.installation_id != context.installation_id:
        raise ConnectionDeniedError("connection installation ownership mismatch")
    if profile.package_digest != context.content_sha256:
        raise ConnectionDeniedError("connection package provenance mismatch")
    if (
        profile.workspace_id is not None
        and profile.workspace_id != context.workspace_id
    ):
        raise ConnectionDeniedError("connection workspace ownership mismatch")
    if profile.project_id is not None and profile.project_id != context.project_id:
        raise ConnectionDeniedError("connection project ownership mismatch")
    if profile.tenant is not None and profile.tenant != context.tenant:
        raise ConnectionDeniedError("connection tenant ownership mismatch")
    if profile.environment is not None and profile.environment != context.environment:
        raise ConnectionDeniedError("connection environment ownership mismatch")
    if (
        context.connection_profile_id is not None
        and context.connection_profile_id != profile.id
    ):
        raise ConnectionDeniedError("connection profile ownership mismatch")
    if not context.policy_allowed:
        raise ConnectionDeniedError("plugin policy denied connection")
    if not _active(profile, datetime.now(UTC)):
        raise ConnectionDeniedError(
            "connection is disabled, unapproved, expired, or revoked"
        )
    if operation not in profile.operations:
        raise ConnectionDeniedError("connection operation is not approved")
    if not profile.resources or not any(
        fnmatchcase(resource, pattern) for pattern in profile.resources
    ):
        raise ConnectionDeniedError("connection resource is not allowlisted")
    if not _host_allowed(profile, endpoint):
        raise ConnectionDeniedError("connection endpoint is not allowlisted")

    current = usage or {}
    if profile.rate_limit is not None and current.get("rate", 0) >= profile.rate_limit:
        raise ConnectionDeniedError("connection rate limit exceeded")
    if profile.quota is not None and current.get("quota", 0) >= profile.quota:
        raise ConnectionDeniedError("connection quota exceeded")
    return ConnectionDecision(
        True, "connection approved", endpoint, operation, resource
    )


def redact_outbound(payload: Any, fields: list[str]) -> Any:
    """Return a redacted copy before payloads cross an approved connection."""

    redacted = {field.casefold() for field in fields}
    if isinstance(payload, dict):
        return {
            key: "[redacted]"
            if key.casefold() in redacted
            else redact_outbound(value, fields)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [redact_outbound(value, fields) for value in payload]
    return payload


__all__ = [
    "ConnectionDecision",
    "ConnectionDeniedError",
    "authorize_connection",
    "redact_outbound",
]
