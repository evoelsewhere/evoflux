"""Microsoft Foundry (Azure AI Foundry) provider — OpenAI-compatible v1 API.

Foundry serves every deployed model family (OpenAI, DeepSeek, Grok, MAI,
Llama, Mistral, ...) through one OpenAI-compatible surface:

    https://{resource}.services.ai.azure.com/openai/v1

- Auth: the v1 surface accepts both ``api-key: {key}`` and
  ``Authorization: Bearer {key}``; we send both so regional and
  sovereign-cloud variants behave identically.
- ``model`` in requests is the *deployment name* (defaults to the model
  name when deployed via the Foundry portal).
- No ``api-version`` query parameter is needed on the v1 surface.

Claude deployments are the exception: they only answer the Anthropic
Messages API at ``https://{resource}.services.ai.azure.com/anthropic``,
so the factory routes ``claude*`` deployments (or an explicit
``anthropic_api: true`` in model_kwargs) to
:class:`FoundryClaudeProvider` instead.

Usage::

    model: foundry:gpt-5.1            # deployment named after the model
    model: foundry:my-deepseek        # custom deployment name
    model: foundry:claude-sonnet-4-6  # routed to the Anthropic surface
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from pydantic.types import SecretStr

from app.agent.providers.anthropic import AnthropicProvider
from app.agent.providers.openai import OpenAIProvider

FOUNDRY_HOST_SUFFIX = ".services.ai.azure.com"

_RESOURCE_REQUIRED_MSG = (
    "Microsoft Foundry resource name is required. "
    "Set FOUNDRY_RESOURCE_NAME in your .env file."
)


def _normalize_resource(resource: str) -> str:
    cleaned = resource.strip().rstrip("/")
    if not cleaned:
        raise ValueError(_RESOURCE_REQUIRED_MSG)
    return cleaned


def foundry_base_url(resource: str) -> str:
    """Normalise a resource name, hostname, or endpoint URL to the v1 base.

    - ``my-resource`` → ``https://my-resource.services.ai.azure.com/openai/v1``
    - ``my-resource.openai.azure.com`` (bare hostname, covers sovereign
      clouds) → ``https://my-resource.openai.azure.com/openai/v1``
    - Full ``https://`` URLs keep their host and path; ``/openai/v1`` is
      appended unless the path already contains it.
    """
    cleaned = _normalize_resource(resource)
    if "://" in cleaned:
        path = urlsplit(cleaned).path.lower()
        if "/openai/v1" in path:
            return cleaned
        if path.endswith("/openai"):
            return f"{cleaned}/v1"
        return f"{cleaned}/openai/v1"
    if "." in cleaned:
        return f"https://{cleaned}/openai/v1"
    return f"https://{cleaned}{FOUNDRY_HOST_SUFFIX}/openai/v1"


def foundry_anthropic_base_url(resource: str) -> str:
    """Anthropic Messages surface for Claude deployments on the resource.

    Unlike :func:`foundry_base_url`, a full URL is reduced to its origin
    (users typically paste the OpenAI-surface target URI) before the
    ``/anthropic`` path is applied.
    """
    cleaned = _normalize_resource(resource)
    if "://" in cleaned:
        parts = urlsplit(cleaned)
        if "/anthropic" in parts.path.lower():
            return cleaned
        return f"{parts.scheme}://{parts.netloc}/anthropic"
    if "." in cleaned:
        return f"https://{cleaned}/anthropic"
    return f"https://{cleaned}{FOUNDRY_HOST_SUFFIX}/anthropic"


class FoundryProvider(OpenAIProvider):
    """Microsoft Foundry provider (OpenAI-compatible v1 surface).

    Keeps ``OpenAIProvider``'s thinking-level auto-routing: the v1
    surface implements ``/responses`` as well as ``/chat/completions``.

    Args:
        api_key: Foundry resource API key.
        model: Deployment name on the Foundry resource.
        resource: Resource name (``my-resource``), bare hostname, or full
            endpoint URL; normalised by :func:`foundry_base_url`.
        temperature: Sampling temperature (0-2).
        top_p: Nucleus sampling probability mass cutoff.
        max_tokens: Hard cap on completion tokens.
        model_kwargs: Extra request body fields passed as-is.
    """

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        resource: str,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=foundry_base_url(resource),
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )

    def _build_headers(self) -> dict[str, str]:
        return {
            "api-key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


class FoundryClaudeProvider(AnthropicProvider):
    """Claude deployments on a Foundry resource.

    Claude models on Foundry only answer the Anthropic Messages API —
    the OpenAI v1 surface returns 404 for them. Reuses the Anthropic
    handler with the Foundry base URL and adds the Azure ``api-key``
    header alongside the default ``x-api-key``.
    """

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        resource: str,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        resolved = (
            api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        )
        if not resolved:
            raise ValueError(
                "Microsoft Foundry API key is required. "
                "Set FOUNDRY_API_KEY in your .env file."
            )
        super().__init__(
            api_key=resolved,
            model=model,
            base_url=foundry_anthropic_base_url(resource),
            headers={"api-key": resolved},
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )
