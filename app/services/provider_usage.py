"""Provider usage dispatcher for Settings -> Providers."""

from __future__ import annotations

from app.agent.providers.codex.usage import (
    CodexUsageCredentialsError,
    CodexUsageUnavailableError,
    get_usage as get_codex_usage,
)
from app.agent.providers.copilot.usage import (
    CopilotUsageCredentialsError,
    CopilotUsageUnavailableError,
    get_usage as get_copilot_usage,
)
from app.agent.providers.plugin_registry import (
    ProviderCredentialStore,
    find_provider_plugin,
)
from app.api.schemas.settings import ProviderUsageResponse


class ProviderUsageUnsupportedError(ValueError):
    """Raised when a provider has no usage endpoint integration."""


class ProviderUsageCredentialsError(ValueError):
    """Raised when usage support needs missing OAuth credentials."""


class ProviderUsageUnavailableError(RuntimeError):
    """Raised when the upstream usage endpoint cannot be reached or parsed."""


async def get_provider_usage(provider_id: str) -> ProviderUsageResponse:
    try:
        if provider_id == "codex":
            return await get_codex_usage()
        if provider_id == "copilot":
            return await get_copilot_usage()
    except (CodexUsageCredentialsError, CopilotUsageCredentialsError) as exc:
        raise ProviderUsageCredentialsError(str(exc)) from exc
    except (CodexUsageUnavailableError, CopilotUsageUnavailableError) as exc:
        raise ProviderUsageUnavailableError(str(exc)) from exc

    plugin = find_provider_plugin(provider_id)
    if plugin is not None and plugin.get_usage is not None:
        try:
            return await plugin.get_usage(ProviderCredentialStore(provider_id))
        except ValueError as exc:
            raise ProviderUsageCredentialsError(str(exc)) from exc
        except Exception as exc:
            raise ProviderUsageUnavailableError(str(exc)) from exc
    raise ProviderUsageUnsupportedError(provider_id)
