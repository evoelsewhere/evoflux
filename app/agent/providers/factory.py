"""Provider factory — resolves a ``"provider:model"`` string to an
:class:`LLMProviderBase` instance.

Resolution order
----------------
1. **Dedicated handler.** The ``match`` in :func:`build_provider` keeps a
   branch only for providers whose auth or wire format needs code, not
   data: Anthropic, Gemini, Vertex, Bedrock, Azure/Foundry, and the two
   OAuth providers.
2. **Registry-driven OpenAI-compatible transport.** Everything else that
   :func:`app.agent.providers.registry.resolve_provider` knows about is a
   base URL plus a bearer token. A dedicated subclass is used when one
   exists (it carries a real wire quirk — DeepSeek's thinking toggle,
   OpenRouter's reasoning object, MiMo's ``reasoning_content`` echo);
   otherwise the generic Chat Completions provider is enough.
3. **models.dev catalog.** A provider ID EvoFlux has no curated entry for
   still resolves if the catalog knows its endpoint and credential name.
   This is what makes the long tail of ~200 catalog providers reachable
   without a code change, the way MiMo-Code's catalog does.
4. **Installed plugin providers.**

Adding an OpenAI-compatible provider is therefore one entry in
:data:`app.agent.providers.registry.PROVIDER_REGISTRY` plus one row in
:mod:`app.agent.providers.catalog` for the settings UI — no branch here.

Usage::

    from app.agent.providers.factory import build_provider

    provider = build_provider(
        "openai:gpt-5",
        model_kwargs={"temperature": 0.2},
    )
"""

from __future__ import annotations

import os
from typing import Protocol, cast

from pydantic import SecretStr

from app.agent.providers.anthropic import AnthropicProvider
from app.agent.providers.base import LLMProviderBase
from app.agent.providers.bedrock import BedrockProvider
from app.agent.providers.codex import CodexProvider
from app.agent.providers.copilot import CopilotProvider
from app.agent.providers.deepseek import DeepSeekProvider  # noqa: F401
from app.agent.providers.fci import FCIProvider  # noqa: F401
from app.agent.providers.foundry import FoundryClaudeProvider, FoundryProvider
from app.agent.providers.googlegenai import GoogleGenAIProvider
from app.agent.providers.kimi import KimiCodeProvider  # noqa: F401
from app.agent.providers.ollama import OllamaProvider  # noqa: F401
from app.agent.providers.openai import ChatCompletionsOnlyProvider, OpenAIProvider
from app.agent.providers.openai.compatible import (
    OPENAI_COMPATIBLE_PROVIDER_SPECS,  # noqa: F401 — re-exported for callers
    is_openai_compatible,
)
from app.agent.providers.openrouter import OpenRouterProvider  # noqa: F401
from app.agent.providers.registry import (
    MIMO_FREE_API_ALIASES,
    MIMO_FREE_API_SUCCESSOR,
    PROVIDER_REGISTRY,
    ProviderConfig,
    Transport,
    mimo_free_api_sunset,
    resolve_base_url,
    resolve_provider,
)
from app.agent.providers.qwencloud import QwenCloudProvider  # noqa: F401
from app.agent.providers.router9 import Router9Provider  # noqa: F401
from app.agent.providers.unconfigured import UnconfiguredProviderError
from app.agent.providers.vertexai import VertexAIProvider
from app.agent.providers.xai import XAIProvider  # noqa: F401
from app.agent.providers.xiaomi import XiaomiProvider  # noqa: F401
from app.agent.providers.zai import ZAIProvider  # noqa: F401

#: Providers reachable without a plugin, sorted for stable error output.
#:
#: Derived from the registry rather than restated, so a new registry entry
#: cannot go missing from the "supported providers" message or from the
#: validation in :mod:`app.api.routes.team.reviews`.
SUPPORTED_PROVIDERS: tuple[str, ...] = tuple(sorted(PROVIDER_REGISTRY))


# ---------------------------------------------------------------------------
# OpenAI-compatible providers with a dedicated subclass
# ---------------------------------------------------------------------------
#
# Each entry below exists because that endpoint diverges from plain Chat
# Completions in a way the generic handler cannot express — a different
# reasoning field, a required message echo, a rejected sampling parameter.
# Everything absent from this table gets ``ChatCompletionsOnlyProvider``,
# which is the whole point: a new OpenAI-compatible provider is data.

_PROVIDER_CLASS_NAMES: dict[str, str] = {
    "deepseek": "DeepSeekProvider",
    "openrouter": "OpenRouterProvider",
    "xai": "XAIProvider",
    "ollama": "OllamaProvider",
    "router9": "Router9Provider",
    "xiaomi": "XiaomiProvider",
    "fci": "FCIProvider",
    "kimi": "KimiCodeProvider",
    "qwencloud": "QwenCloudProvider",
    "zai": "ZAIProvider",
    "zhipuai": "ZAIProvider",
}


def _resolve_compatible_class(name: str) -> type:
    """Resolve the provider class for an OpenAI-compatible provider.

    Uses the dispatch table for providers with dedicated classes, falls
    back to ``ChatCompletionsOnlyProvider`` for generic ones.

    Resolved via module globals so that test-time mocks of the class
    attribute (e.g. ``patch("app.agent.providers.factory.Router9Provider")``)
    take effect at instantiation time.
    """
    cls_name = _PROVIDER_CLASS_NAMES.get(name)
    if cls_name is not None:
        import app.agent.providers.factory as _mod

        resolved = getattr(_mod, cls_name, None)
        if resolved is not None:
            return resolved
    return ChatCompletionsOnlyProvider


def require_api_key(secret: SecretStr | None, env_var: str, label: str) -> str:
    """Resolve an API key from a Pydantic ``SecretStr`` or env var.

    Raises ``ValueError`` with a uniform message when neither is set.
    """
    if secret is not None:
        try:
            value = secret.get_secret_value()
            if value:
                return value
        except AttributeError:
            # Treat plain strings the same as SecretStr in tests.
            if isinstance(secret, str) and secret:
                return secret
    env_value = os.getenv(env_var, "")
    if env_value:
        return env_value
    raise ValueError(f"{label} API key is required. Set {env_var} in your .env file.")


def _with_provider_name(
    provider: LLMProviderBase, provider_name: str
) -> LLMProviderBase:
    provider.bind_provider_name(provider_name)
    return provider


class ProviderFactory(Protocol):
    """Callable that builds a provider from a 'provider:model' string."""

    def __call__(
        self,
        model_str: str | None,
        model_kwargs: dict[str, object] | None = None,
    ) -> LLMProviderBase: ...


def _resolve_config_key_and_url(
    name: str,
    s: object,
    config: ProviderConfig | None = None,
) -> tuple[str | SecretStr, str]:
    """Resolve the API key and base URL for an OpenAI-compatible provider.

    The credential comes from the typed settings field first (which pydantic
    has already populated from ``.env``), then the process environment. The
    base URL is the other way round — the environment wins — because an
    operator pointing a whole process at a proxy sets ``*_BASE_URL`` in the
    environment and expects that to override whatever is on disk.

    Args:
        name: Provider ID.
        s: The settings object.
        config: Pre-resolved provider config; looked up when omitted.

    Raises:
        ValueError: when the provider needs a credential and none is set.
    """
    resolved = config if config is not None else resolve_provider(name)
    if resolved is None:
        raise ValueError(f"Unknown OpenAI-compatible provider: {name}")

    configured_key = getattr(s, resolved.env_var, None) if resolved.env_var else None
    api_key: str | SecretStr | None
    if resolved.default_api_key:
        # Endpoints that require the header but ignore its value (Ollama).
        if not configured_key or (
            isinstance(configured_key, str) and not configured_key.strip()
        ):
            api_key = os.getenv(resolved.env_var) or resolved.default_api_key
        else:
            api_key = configured_key
    else:
        api_key = require_api_key(configured_key, resolved.env_var, resolved.label)

    typed_api_key = cast(str | SecretStr | None, api_key)

    # ``resolve_base_url`` falls back to the endpoint models.dev publishes,
    # so providers whose URL is catalog data rather than a curated constant
    # still resolve here.
    base_url = resolve_base_url(resolved)
    if resolved.base_url_env_var:
        # ``getattr`` carries a falsy default so a MagicMock settings double
        # in tests does not leak an auto-attribute in as a URL.
        env_val = os.getenv(resolved.base_url_env_var)
        if env_val and env_val.strip():
            base_url = env_val.strip()
        else:
            attr_val = getattr(s, resolved.base_url_env_var, "")
            if isinstance(attr_val, str) and attr_val.strip():
                base_url = attr_val.strip()

    return typed_api_key, base_url


# ---------------------------------------------------------------------------
# Main factory
# ---------------------------------------------------------------------------


def build_provider(
    model_str: str | None,
    model_kwargs: dict[str, object] | None = None,
) -> LLMProviderBase:
    """Build a provider instance for ``"<provider>:<model>"``.

    Raises:
        ValueError: when *model_str* is empty, malformed, or names an
            unknown provider, or when the required API key for the
            selected provider is missing.
    """
    if not model_str:
        raise ValueError(
            "No model specified. Set 'model' in the agent's .md frontmatter "
            "(format: 'provider:model', e.g. 'googlegenai:gemini-3.1-flash')."
        )
    # Agents seeded with the placeholder token surface as "not configured"
    # rather than the generic invalid-format error — the caller (loader)
    # catches this specifically to substitute an UnconfiguredProvider stub
    # so the agent loads but defers the failure to LLM-call time.
    from app.cli.seed import PROVIDER_MODEL_TOKEN

    if model_str == PROVIDER_MODEL_TOKEN or PROVIDER_MODEL_TOKEN in model_str:
        raise UnconfiguredProviderError()
    if ":" not in model_str:
        raise ValueError(
            f"Invalid model format '{model_str}'. "
            f"Expected 'provider:model' (e.g. 'zai:glm-5-turbo', "
            f"'googlegenai:gemini-3.1-flash')."
        )

    name, model = model_str.split(":", 1)
    name = name.strip().lower()

    # MiMo's anonymous free channel. It answered ``mimo:auto`` without any
    # credential until 2026-07-26, and MiMo-Code still resolves the alias so
    # it can say what happened instead of "unknown provider". Past the sunset
    # the alias is a configuration error with a fix, not a route.
    if f"{name}:{model}".lower() in MIMO_FREE_API_ALIASES:
        if mimo_free_api_sunset():
            raise UnconfiguredProviderError(
                message=(
                    "MiMo's free API channel ('mimo:auto') shut down on "
                    "2026-07-26. Add a Xiaomi MiMo API key in Settings > "
                    "Providers and use a 'xiaomi:<model>' model instead, or "
                    "pick another provider."
                )
            )
        name = MIMO_FREE_API_SUCCESSOR
        model = "mimo-v2-flash"

    kwargs = model_kwargs or {}
    # Local import so tests can ``patch("app.core.config.settings", ...)`` and
    # so importing this module stays cheap (no env-var validation at import).
    from app.core.config import settings as s

    match name:
        # ── OpenAI (dedicated Responses API support) ────────────────────
        case "openai":
            return _with_provider_name(
                OpenAIProvider(
                    api_key=require_api_key(
                        s.OPENAI_API_KEY, "OPENAI_API_KEY", "OpenAI"
                    ),
                    model=model,
                    base_url=os.getenv("OPENAI_BASE_URL")
                    or s.OPENAI_BASE_URL
                    or "https://api.openai.com/v1",
                    model_kwargs=kwargs,
                ),
                name,
            )

        # ── Anthropic (dedicated Messages API) ──────────────────────────
        case "anthropic":
            return _with_provider_name(
                AnthropicProvider(
                    api_key=require_api_key(
                        s.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY", "Anthropic"
                    ),
                    model=model,
                    base_url=os.getenv("ANTHROPIC_BASE_URL")
                    or s.ANTHROPIC_BASE_URL
                    or "https://api.anthropic.com",
                    model_kwargs=kwargs,
                ),
                name,
            )

        # ── Google GenAI (dedicated Gemini API) ─────────────────────────
        case "googlegenai":
            return _with_provider_name(
                GoogleGenAIProvider(
                    api_key=require_api_key(
                        s.GOOGLE_API_KEY, "GOOGLE_API_KEY", "Google"
                    ),
                    model=model,
                    model_kwargs=kwargs,
                ),
                name,
            )

        # ── Vertex AI (dedicated Google Cloud auth) ─────────────────────
        case "vertexai":
            return _with_provider_name(
                VertexAIProvider(
                    api_key=require_api_key(
                        s.VERTEXAI_API_KEY, "VERTEXAI_API_KEY", "Vertex AI"
                    ),
                    model=model,
                    model_kwargs=kwargs,
                    project=s.GOOGLE_CLOUD_PROJECT,
                    location=s.GOOGLE_CLOUD_LOCATION,
                ),
                name,
            )

        # ── OAuth-only providers ────────────────────────────────────────
        case "copilot":
            return _with_provider_name(
                CopilotProvider(model=model, model_kwargs=kwargs), name
            )
        case "codex":
            return _with_provider_name(
                CodexProvider(model=model, model_kwargs=kwargs), name
            )

        # ── Microsoft Foundry (dedicated Azure Enterprise auth) ─────────
        case "foundry":
            foundry_key = require_api_key(
                s.FOUNDRY_API_KEY, "FOUNDRY_API_KEY", "Microsoft Foundry"
            )
            resource = (
                os.getenv("FOUNDRY_RESOURCE_NAME") or s.FOUNDRY_RESOURCE_NAME or ""
            ).strip()
            if not resource:
                raise ValueError(
                    "Microsoft Foundry resource name is required. "
                    "Set FOUNDRY_RESOURCE_NAME in your .env file."
                )
            use_anthropic = bool(kwargs.get("anthropic_api", "claude" in model.lower()))
            foundry_cls = FoundryClaudeProvider if use_anthropic else FoundryProvider
            return _with_provider_name(
                foundry_cls(
                    api_key=foundry_key,
                    model=model,
                    resource=resource,
                    model_kwargs=kwargs,
                ),
                name,
            )

        # ── Amazon Bedrock (dedicated AWS SDK auth) ────────────────────
        case "bedrock":
            profile_name = s.AWS_BEDROCK_PROFILE or os.getenv("AWS_BEDROCK_PROFILE")
            access_key: str | None = None
            secret_key: str | None = None
            if profile_name is None:
                access_key = os.getenv("AWS_ACCESS_KEY_ID") or None
                secret_key = os.getenv("AWS_SECRET_ACCESS_KEY") or None
            return _with_provider_name(
                BedrockProvider(
                    model=model,
                    region_name=s.AWS_BEDROCK_REGION or os.getenv("AWS_BEDROCK_REGION"),
                    profile_name=profile_name,
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                    model_kwargs=kwargs,
                ),
                name,
            )

        # ── Everything else: registry, then catalog, then plugins ───────
        case _:
            return _build_from_registry(name, model, kwargs, s)


def _build_from_registry(
    name: str,
    model: str,
    kwargs: dict[str, object],
    s: object,
) -> LLMProviderBase:
    """Build a provider that needs no dedicated ``case`` branch.

    Resolves the provider through the curated registry and then the
    models.dev catalog, which is what makes a provider EvoFlux has never
    been taught about reachable from its catalog entry alone. Falls through
    to installed plugins, then reports the ID as unsupported.
    """
    config = resolve_provider(name)
    if config is not None and is_openai_compatible(config):
        typed_api_key, base_url = _resolve_config_key_and_url(name, s, config)
        provider_cls = _resolve_compatible_class(name)
        return _with_provider_name(
            provider_cls(
                api_key=typed_api_key,
                model=model,
                base_url=base_url,
                model_kwargs=kwargs,
            ),
            name,
        )

    if config is not None and config.transport is Transport.ANTHROPIC:
        # A third-party endpoint speaking Anthropic Messages — MiniMax and
        # Kimi's Anthropic surface both land here. Same handler, different
        # host and credential.
        typed_api_key, base_url = _resolve_config_key_and_url(name, s, config)
        return _with_provider_name(
            AnthropicProvider(
                api_key=typed_api_key,
                model=model,
                base_url=base_url,
                model_kwargs=kwargs,
            ),
            name,
        )

    from app.agent.providers.plugin_registry import (
        ProviderCredentialStore,
        find_provider_plugin,
    )

    plugin = find_provider_plugin(name)
    if plugin is not None:
        from app.agent.providers.plugin_api import ProviderBuildContext

        return _with_provider_name(
            plugin.factory(
                ProviderBuildContext(
                    provider_id=name,
                    model=model,
                    model_kwargs=kwargs,
                    credentials=ProviderCredentialStore(name),
                )
            ),
            name,
        )

    raise UnconfiguredProviderError(
        message=(
            f"Unsupported provider '{name}'. "
            f"Supported providers: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    )
