"""Provider registry — the declarative provider table.

Why this exists
---------------
EvoFlux used to answer "how do I talk to provider X?" with a ``match``
branch in :mod:`app.agent.providers.factory` plus a bespoke Python class
per provider. That couples two unrelated facts: the *wire protocol* (of
which there are five) and the *endpoint identity* (of which there are
hundreds). MiMo-Code splits the two — it keeps one adapter per wire
protocol and lets the model catalog name which adapter a provider needs,
via the ``npm`` field on every https://models.dev entry.

This module is EvoFlux's version of that split:

- :class:`Transport` enumerates the wire protocols EvoFlux implements.
- :data:`NPM_TRANSPORTS` maps models.dev's ``npm`` adapter names onto them,
  so any of the ~200 catalog providers can be resolved without new code.
- :data:`PROVIDER_REGISTRY` curates the providers EvoFlux ships with
  first-class metadata (label, endpoint, credential env var, attribution
  headers).
- :func:`resolve_provider` falls back to synthesizing a config straight
  from the models.dev entry, and :func:`custom_provider` covers a
  user-supplied OpenAI-compatible endpoint that no catalog knows about.

Endpoint and credential facts below were read out of the models.dev
catalog (its ``env`` and ``api`` fields), not from memory. Where models.dev
leaves ``api`` null because its adapter is a native SDK, the value here is
that vendor's documented OpenAI-compatible base URL.

Deliberately *not* here
-----------------------
Per-model facts — context window, output cap, pricing, which reasoning
efforts a model accepts — belong to
:mod:`app.agent.providers.model_metadata`, which already merges the bundled
models.dev snapshot, a live refresh, and the user overlay. Reasoning wire
translation belongs to :mod:`app.agent.providers.thinking`; always-on
request options belong to :mod:`app.agent.providers.options`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------


class Transport(StrEnum):
    """A wire protocol EvoFlux can speak.

    One transport is one request/response serialization plus one reasoning
    dialect. Everything else about a provider (URL, credential, headers) is
    data, not code.
    """

    OPENAI_COMPLETIONS = "openai-completions"
    """``POST {base}/chat/completions`` — the OpenAI Chat Completions shape."""

    OPENAI_RESPONSES = "openai-responses"
    """``POST {base}/responses`` — OpenAI's Responses API."""

    ANTHROPIC = "anthropic"
    """``POST {base}/v1/messages`` — the Anthropic Messages shape."""

    GOOGLE_GENAI = "google-genai"
    """``POST {base}/models/{model}:streamGenerateContent`` — Gemini API."""

    GOOGLE_VERTEX = "google-vertex"
    """Vertex AI: the Gemini shape behind Google Cloud credentials."""

    BEDROCK = "bedrock"
    """AWS Bedrock Converse, reached through the AWS SDK rather than a URL."""

    AZURE = "azure"
    """Azure OpenAI deployments — OpenAI shape, Azure-specific routing."""


#: models.dev ``npm`` adapter name -> the EvoFlux transport that speaks it.
#:
#: models.dev names the *ai-sdk package* a provider needs, which is exactly
#: the "which wire format?" question a transport answers. Anything absent
#: falls through to :data:`DEFAULT_TRANSPORT`, correct for the 172 of ~212
#: catalog providers that are plain OpenAI-compatible endpoints.
NPM_TRANSPORTS: dict[str, Transport] = {
    "@ai-sdk/openai-compatible": Transport.OPENAI_COMPLETIONS,
    "@ai-sdk/openai": Transport.OPENAI_RESPONSES,
    "@ai-sdk/azure": Transport.AZURE,
    "@ai-sdk/anthropic": Transport.ANTHROPIC,
    "@ai-sdk/google-vertex/anthropic": Transport.ANTHROPIC,
    "@ai-sdk/google": Transport.GOOGLE_GENAI,
    "@ai-sdk/google-vertex": Transport.GOOGLE_VERTEX,
    "@ai-sdk/amazon-bedrock": Transport.BEDROCK,
    # Native SDKs whose HTTP surface is OpenAI-compatible.
    "@ai-sdk/cerebras": Transport.OPENAI_COMPLETIONS,
    "@ai-sdk/cohere": Transport.OPENAI_COMPLETIONS,
    "@ai-sdk/deepinfra": Transport.OPENAI_COMPLETIONS,
    "@ai-sdk/gateway": Transport.OPENAI_COMPLETIONS,
    "@ai-sdk/groq": Transport.OPENAI_COMPLETIONS,
    "@ai-sdk/mistral": Transport.OPENAI_COMPLETIONS,
    "@ai-sdk/perplexity": Transport.OPENAI_COMPLETIONS,
    "@ai-sdk/togetherai": Transport.OPENAI_COMPLETIONS,
    "@ai-sdk/vercel": Transport.OPENAI_COMPLETIONS,
    "@ai-sdk/xai": Transport.OPENAI_COMPLETIONS,
    "@openrouter/ai-sdk-provider": Transport.OPENAI_COMPLETIONS,
    "venice-ai-sdk-provider": Transport.OPENAI_COMPLETIONS,
}

DEFAULT_TRANSPORT = Transport.OPENAI_COMPLETIONS

#: How the settings UI must collect credentials for a provider.
AuthKind = Literal["api_key", "oauth", "cloud", "local"]


# ---------------------------------------------------------------------------
# Provider config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderConfig:
    """Everything needed to open a connection to one provider.

    Attributes:
        id: EvoFlux's provider ID — the part before ``:`` in a
            ``"provider:model"`` string.
        label: Human-readable name for the settings UI.
        transport: Which wire protocol to speak.
        env_var: Primary credential environment variable / settings field.
        base_url: Default endpoint. Empty when the transport reaches the
            provider through an SDK instead of a URL (Bedrock, Vertex).
        base_url_env_var: Environment variable / settings field that
            overrides *base_url*.
        models_dev_id: The provider's ID in the models.dev catalog when it
            differs from :attr:`id`. Drives model-metadata aliasing.
        attribution_headers: Static headers identifying EvoFlux to
            aggregators that rank or bill by referrer. MiMo-Code sends the
            same class of header to OpenRouter, Vercel, NVIDIA and friends;
            omitting them makes a client invisible to the gateway's own
            analytics and, on OpenRouter, forfeits app-level attribution.
        extra_headers: Other always-on headers (protocol pins, beta flags).
        default_api_key: Placeholder credential for endpoints that require
            the header but ignore its value (Ollama).
        responses_models: Model-ID substrings that must use
            :attr:`Transport.OPENAI_RESPONSES` even though the provider's
            default transport is Chat Completions. MiMo-Code carries the
            same per-provider routing in its ``getModel`` custom loaders.
        auth: How credentials are obtained.
        docs_url: Where a user gets a key.
    """

    id: str
    label: str
    transport: Transport = DEFAULT_TRANSPORT
    env_var: str = ""
    base_url: str = ""
    base_url_env_var: str | None = None
    models_dev_id: str | None = None
    attribution_headers: dict[str, str] = field(default_factory=dict)
    extra_headers: dict[str, str] = field(default_factory=dict)
    default_api_key: str = ""
    responses_models: tuple[str, ...] = ()
    auth: AuthKind = "api_key"
    docs_url: str = ""
    #: Protocols this provider's adapters speak *besides* :attr:`transport`.
    #:
    #: Most providers have one adapter, so a model the catalog flags as
    #: needing a different protocol is one EvoFlux cannot serve. A few have
    #: more: Foundry hosts Claude on the same resource as its OpenAI
    #: deployments and the factory routes those to an Anthropic adapter.
    #: Declaring it here is what keeps those models listed.
    extra_transports: tuple[Transport, ...] = ()

    #: Whether this provider can mint its own key through a browser sign-in
    #: (``evoflux auth <id>`` / the Settings button), instead of the user
    #: creating one in a console and pasting it. Orthogonal to :attr:`auth`:
    #: the flow ends in an ordinary API key, so the provider stays
    #: ``api_key`` and the key field keeps working for anyone who has one.
    browser_login: bool = False

    def speaks(self, transport: Transport) -> bool:
        """Whether one of this provider's adapters speaks *transport*."""
        return transport is self.transport or transport in self.extra_transports

    @property
    def models_dev_provider_id(self) -> str:
        """The catalog ID to read this provider's model metadata under."""
        return self.models_dev_id or self.id

    def uses_responses_api(self, model: str) -> bool:
        """Whether *model* must be sent to ``/responses``.

        True when the provider's transport *is* Responses, or when the model
        matches one of :attr:`responses_models`.
        """
        if self.transport is Transport.OPENAI_RESPONSES:
            return True
        if not self.responses_models:
            return False
        lowered = model.lower()
        return any(marker in lowered for marker in self.responses_models)


# EvoFlux identifies itself to aggregating gateways the way MiMo-Code does:
# a referrer plus a product name, so the gateway can attribute the traffic.
_ATTRIBUTION = {
    "HTTP-Referer": "https://github.com/khuonghung/evoflux",
    "X-Title": "EvoFlux",
}


# ---------------------------------------------------------------------------
# Curated registry
# ---------------------------------------------------------------------------

PROVIDER_REGISTRY: dict[str, ProviderConfig] = {
    # -- First-party model vendors --------------------------------------
    "openai": ProviderConfig(
        id="openai",
        label="OpenAI",
        transport=Transport.OPENAI_RESPONSES,
        env_var="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        base_url_env_var="OPENAI_BASE_URL",
        docs_url="https://platform.openai.com/api-keys",
    ),
    "anthropic": ProviderConfig(
        id="anthropic",
        label="Anthropic Claude",
        transport=Transport.ANTHROPIC,
        env_var="ANTHROPIC_API_KEY",
        base_url="https://api.anthropic.com",
        base_url_env_var="ANTHROPIC_BASE_URL",
        docs_url="https://console.anthropic.com/settings/keys",
    ),
    "googlegenai": ProviderConfig(
        id="googlegenai",
        label="Google Gemini",
        transport=Transport.GOOGLE_GENAI,
        env_var="GOOGLE_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        models_dev_id="google",
        docs_url="https://aistudio.google.com/apikey",
    ),
    "xai": ProviderConfig(
        id="xai",
        label="xAI Grok",
        env_var="XAI_API_KEY",
        base_url="https://api.x.ai/v1",
        base_url_env_var="XAI_BASE_URL",
        docs_url="https://console.x.ai",
    ),
    "deepseek": ProviderConfig(
        id="deepseek",
        label="DeepSeek",
        env_var="DEEPSEEK_API_KEY",
        base_url_env_var="DEEPSEEK_BASE_URL",
        docs_url="https://platform.deepseek.com/api_keys",
    ),
    "mistral": ProviderConfig(
        id="mistral",
        label="Mistral AI",
        env_var="MISTRAL_API_KEY",
        base_url="https://api.mistral.ai/v1",
        base_url_env_var="MISTRAL_BASE_URL",
        docs_url="https://console.mistral.ai/api-keys/",
    ),
    "cohere": ProviderConfig(
        id="cohere",
        label="Cohere",
        env_var="COHERE_API_KEY",
        # Cohere's native v2 API is not OpenAI-shaped; its compatibility
        # endpoint is.
        base_url="https://api.cohere.ai/compatibility/v1",
        base_url_env_var="COHERE_BASE_URL",
        docs_url="https://dashboard.cohere.com/api-keys",
    ),
    "minimax": ProviderConfig(
        id="minimax",
        label="MiniMax",
        # models.dev routes MiniMax through @ai-sdk/anthropic: the endpoint
        # speaks Anthropic Messages, not an OpenAI-compatible shape.
        transport=Transport.ANTHROPIC,
        env_var="MINIMAX_API_KEY",
        base_url="https://api.minimax.io/anthropic",
        base_url_env_var="MINIMAX_BASE_URL",
        docs_url="https://platform.minimax.io/user-center/basic-information/interface-key",
    ),
    "xiaomi": ProviderConfig(
        id="xiaomi",
        label="Xiaomi MiMo",
        env_var="XIAOMI_API_KEY",
        base_url_env_var="XIAOMI_BASE_URL",
        docs_url="https://xiaomimimo.com",
        browser_login=True,
    ),
    "zai": ProviderConfig(
        id="zai",
        label="Z.AI GLM",
        env_var="ZAI_API_KEY",
        base_url_env_var="ZAI_BASE_URL",
        docs_url="https://z.ai/manage-apikey/apikey-list",
    ),
    "zhipuai": ProviderConfig(
        id="zhipuai",
        label="Zhipu AI (China)",
        env_var="ZHIPU_API_KEY",
        base_url_env_var="ZHIPU_BASE_URL",
        docs_url="https://open.bigmodel.cn/usercenter/apikeys",
    ),
    "kimi": ProviderConfig(
        id="kimi",
        label="Kimi Code",
        env_var="MOONSHOT_API_KEY",
        base_url_env_var="MOONSHOT_BASE_URL",
        models_dev_id="kimi-for-coding",
        docs_url="https://platform.moonshot.ai/console/api-keys",
    ),
    "moonshot": ProviderConfig(
        id="moonshot",
        label="Moonshot AI",
        env_var="MOONSHOT_PLATFORM_API_KEY",
        base_url_env_var="MOONSHOT_PLATFORM_BASE_URL",
        models_dev_id="moonshotai",
        docs_url="https://platform.moonshot.ai/console/api-keys",
    ),
    "qwencloud": ProviderConfig(
        id="qwencloud",
        label="Qwen Cloud (DashScope)",
        env_var="DASHSCOPE_API_KEY",
        base_url_env_var="DASHSCOPE_BASE_URL",
        models_dev_id="alibaba",
        docs_url="https://bailian.console.alibabacloud.com/?tab=model#/api-key",
    ),
    # -- Fast-inference hosts -------------------------------------------
    "groq": ProviderConfig(
        id="groq",
        label="Groq",
        env_var="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        base_url_env_var="GROQ_BASE_URL",
        docs_url="https://console.groq.com/keys",
    ),
    "cerebras": ProviderConfig(
        id="cerebras",
        label="Cerebras",
        env_var="CEREBRAS_API_KEY",
        base_url="https://api.cerebras.ai/v1",
        base_url_env_var="CEREBRAS_BASE_URL",
        docs_url="https://cloud.cerebras.ai",
    ),
    "together": ProviderConfig(
        id="together",
        label="Together AI",
        env_var="TOGETHER_API_KEY",
        base_url="https://api.together.xyz/v1",
        base_url_env_var="TOGETHER_BASE_URL",
        models_dev_id="togetherai",
        docs_url="https://api.together.xyz/settings/api-keys",
    ),
    "fireworks": ProviderConfig(
        id="fireworks",
        label="Fireworks AI",
        env_var="FIREWORKS_API_KEY",
        base_url_env_var="FIREWORKS_BASE_URL",
        models_dev_id="fireworks-ai",
        docs_url="https://fireworks.ai/account/api-keys",
    ),
    "deepinfra": ProviderConfig(
        id="deepinfra",
        label="Deep Infra",
        env_var="DEEPINFRA_API_KEY",
        base_url="https://api.deepinfra.com/v1/openai",
        base_url_env_var="DEEPINFRA_BASE_URL",
        docs_url="https://deepinfra.com/dash/api_keys",
    ),
    "baseten": ProviderConfig(
        id="baseten",
        label="Baseten",
        env_var="BASETEN_API_KEY",
        base_url_env_var="BASETEN_BASE_URL",
        docs_url="https://app.baseten.co/settings/api_keys",
    ),
    "sambanova": ProviderConfig(
        id="sambanova",
        label="SambaNova",
        env_var="SAMBANOVA_API_KEY",
        base_url="https://api.sambanova.ai/v1",
        base_url_env_var="SAMBANOVA_BASE_URL",
        # Absent from models.dev; model metadata comes from live discovery.
        docs_url="https://cloud.sambanova.ai/apis",
    ),
    "nvidia": ProviderConfig(
        id="nvidia",
        label="NVIDIA NIM",
        env_var="NVIDIA_API_KEY",
        base_url_env_var="NVIDIA_BASE_URL",
        attribution_headers=dict(_ATTRIBUTION),
        docs_url="https://build.nvidia.com",
    ),
    "huggingface": ProviderConfig(
        id="huggingface",
        label="Hugging Face",
        env_var="HF_TOKEN",
        base_url_env_var="HF_BASE_URL",
        docs_url="https://huggingface.co/settings/tokens",
    ),
    # -- Search-augmented -----------------------------------------------
    "perplexity": ProviderConfig(
        id="perplexity",
        label="Perplexity",
        env_var="PERPLEXITY_API_KEY",
        base_url="https://api.perplexity.ai",
        base_url_env_var="PERPLEXITY_BASE_URL",
        docs_url="https://www.perplexity.ai/account/api/keys",
    ),
    # -- Aggregating gateways (attribution headers matter here) ---------
    "openrouter": ProviderConfig(
        id="openrouter",
        label="OpenRouter",
        env_var="OPENROUTER_API_KEY",
        base_url_env_var="OPENROUTER_BASE_URL",
        attribution_headers={
            **_ATTRIBUTION,
            "X-OpenRouter-Categories": "programming,programming-app,cli-agent",
        },
        docs_url="https://openrouter.ai/keys",
    ),
    "vercel": ProviderConfig(
        id="vercel",
        label="Vercel AI Gateway",
        env_var="AI_GATEWAY_API_KEY",
        base_url="https://ai-gateway.vercel.sh/v1",
        base_url_env_var="AI_GATEWAY_BASE_URL",
        # Vercel's gateway reads these lower-cased.
        attribution_headers={
            "http-referer": _ATTRIBUTION["HTTP-Referer"],
            "x-title": _ATTRIBUTION["X-Title"],
        },
        docs_url="https://vercel.com/dashboard/ai-gateway/api-keys",
    ),
    "llmgateway": ProviderConfig(
        id="llmgateway",
        label="LLM Gateway",
        env_var="LLMGATEWAY_API_KEY",
        base_url_env_var="LLMGATEWAY_BASE_URL",
        attribution_headers={**_ATTRIBUTION, "X-Source": "evoflux"},
        docs_url="https://llmgateway.io/dashboard",
    ),
    "zenmux": ProviderConfig(
        id="zenmux",
        label="ZenMux",
        env_var="ZENMUX_API_KEY",
        base_url_env_var="ZENMUX_BASE_URL",
        attribution_headers=dict(_ATTRIBUTION),
        docs_url="https://zenmux.ai/settings/keys",
    ),
    # -- Cloud platforms (credentials are not a single API key) ---------
    "bedrock": ProviderConfig(
        id="bedrock",
        label="Amazon Bedrock",
        transport=Transport.BEDROCK,
        env_var="AWS_BEARER_TOKEN_BEDROCK",
        models_dev_id="amazon-bedrock",
        auth="cloud",
        docs_url="https://console.aws.amazon.com/bedrock",
    ),
    "vertexai": ProviderConfig(
        id="vertexai",
        label="Google Vertex AI",
        transport=Transport.GOOGLE_VERTEX,
        env_var="VERTEXAI_API_KEY",
        models_dev_id="google-vertex",
        auth="cloud",
        docs_url="https://console.cloud.google.com/vertex-ai",
    ),
    "foundry": ProviderConfig(
        id="foundry",
        label="Microsoft Foundry",
        transport=Transport.AZURE,
        # Claude models on a Foundry resource are reached over Anthropic
        # Messages; ``build_provider`` routes them to a second adapter.
        extra_transports=(Transport.ANTHROPIC,),
        env_var="FOUNDRY_API_KEY",
        models_dev_id="azure-cognitive-services",
        auth="cloud",
        docs_url="https://ai.azure.com",
    ),
    # -- OAuth (credentials come from a device/browser flow) ------------
    "copilot": ProviderConfig(
        id="copilot",
        label="GitHub Copilot",
        models_dev_id="github-copilot",
        auth="oauth",
        docs_url="https://github.com/settings/copilot",
    ),
    "codex": ProviderConfig(
        id="codex",
        label="OpenAI Codex",
        transport=Transport.OPENAI_RESPONSES,
        base_url="https://chatgpt.com/backend-api/codex",
        models_dev_id="openai",
        auth="oauth",
        docs_url="https://chatgpt.com/codex",
    ),
    # -- Local / self-hosted --------------------------------------------
    "ollama": ProviderConfig(
        id="ollama",
        label="Ollama",
        env_var="OLLAMA_API_KEY",
        base_url="http://localhost:11434/v1",
        base_url_env_var="OLLAMA_BASE_URL",
        default_api_key="ollama",
        auth="local",
        docs_url="https://ollama.com",
    ),
    "router9": ProviderConfig(
        id="router9",
        label="9Router",
        env_var="ROUTER9_API_KEY",
        base_url="http://localhost:20128/v1",
        base_url_env_var="ROUTER9_BASE_URL",
        auth="local",
    ),
    "cliproxy": ProviderConfig(
        id="cliproxy",
        label="CLIProxyAPI",
        env_var="CLIPROXY_API_KEY",
        base_url="http://localhost:8317/v1",
        base_url_env_var="CLIPROXY_BASE_URL",
        auth="local",
    ),
    "fci": ProviderConfig(
        id="fci",
        label="FPT Cloud AI",
        env_var="FCI_API_KEY",
        base_url="https://mkp-api.fptcloud.com/v1",
        base_url_env_var="FCI_BASE_URL",
        docs_url="https://marketplace.fptcloud.com/en/my-account?tab=my-api-key",
    ),
}


# ---------------------------------------------------------------------------
# Presentation order
# ---------------------------------------------------------------------------

#: Providers to offer first, strongest recommendation first.
#:
#: With ~200 providers reachable, a flat alphabetical list makes the choice
#: harder rather than easier. This is the short answer to "which one should
#: I connect?", and it is a product judgement rather than a fact about the
#: catalog — which is why it is a plain list here and not inferred from
#: model counts or pricing.
#:
#: The order reflects three things: the frontier vendors most agents are
#: written against, the subscriptions a user may already be paying for
#: (Codex, Copilot), and MiMo — Xiaomi's API is the one EvoFlux tracks most
#: closely, and MiMo-Code marks it recommended for the same reason.
RECOMMENDED_PROVIDERS: tuple[str, ...] = (
    "xiaomi",
    "anthropic",
    "openai",
    "googlegenai",
    "codex",
    "copilot",
    "openrouter",
    "deepseek",
    "zai",
    "qwencloud",
)


def provider_rank(provider_id: str) -> int:
    """Sort key for the settings list: recommended first, then the rest.

    Returns the provider's position in :data:`RECOMMENDED_PROVIDERS`, or a
    value past the end for everything else, so callers can sort by
    ``(rank, label)`` and get a stable order without restating the list.
    """
    normalized = (provider_id or "").strip().lower()
    try:
        return RECOMMENDED_PROVIDERS.index(normalized)
    except ValueError:
        return len(RECOMMENDED_PROVIDERS)


def is_recommended(provider_id: str) -> bool:
    """Whether this provider is one EvoFlux suggests connecting first."""
    return (provider_id or "").strip().lower() in RECOMMENDED_PROVIDERS


# ---------------------------------------------------------------------------
# Provider-implemented service tiers
# ---------------------------------------------------------------------------

#: Alternate service tiers EvoFlux's own integration implements, keyed by
#: provider then tier name, in the same ``{"body": …, "headers": …}`` shape
#: the catalog uses for ``experimental.modes``.
#:
#: The catalog covers tiers that belong to a *model's* public API — OpenAI's
#: ``service_tier: priority``, Anthropic's fast-mode beta — and those need no
#: entry here. This table is for tiers that belong to a *plan* instead:
#: Codex's fast lane is a ChatGPT-subscription feature reached through the
#: backend API, so no model catalog publishes it and only the client that
#: speaks to that endpoint can know it exists.
#:
#: Merging the two means every consumer — the request builder, the model
#: catalog endpoint, the composer's Fast toggle — asks one question ("does
#: this model offer a ``fast`` tier?") instead of matching a provider prefix.
PROVIDER_MODES: dict[str, dict[str, dict[str, Any]]] = {
    # Codex's own config file spells this tier "fast"; the wire field it
    # maps to is OpenAI's ``service_tier: priority``. The patch carries the
    # wire value, so nothing downstream has to translate it again.
    "codex": {"fast": {"body": {"service_tier": "priority"}}},
}


def provider_modes(provider_id: str) -> dict[str, dict[str, Any]]:
    """Service tiers *provider_id*'s integration implements itself."""
    return PROVIDER_MODES.get((provider_id or "").strip().lower(), {})


# ---------------------------------------------------------------------------
# Free-tier lifecycle
# ---------------------------------------------------------------------------

#: MiMo-Code's anonymous free channel (``mimo/mimo-auto``) stopped serving
#: requests at this instant; upstream encodes the same constant in
#: ``src/util/free-api-sunset.ts``. EvoFlux keeps the alias resolvable so an
#: agent still pinned to it fails with a message that says what to do,
#: rather than a bare "unknown provider".
MIMO_FREE_API_SUNSET_ISO = "2026-07-26T10:00:00+00:00"

#: ``"provider:model"`` strings that used to route to the free channel.
MIMO_FREE_API_ALIASES = frozenset({"mimo:auto", "mimo:mimo-auto"})

#: Where the free channel routed once a user has their own credential.
MIMO_FREE_API_SUCCESSOR = "xiaomi"


def mimo_free_api_sunset() -> bool:
    """Whether MiMo's anonymous free channel has already shut down."""
    from datetime import UTC, datetime

    return datetime.now(UTC) >= datetime.fromisoformat(MIMO_FREE_API_SUNSET_ISO)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def provider_ids() -> tuple[str, ...]:
    """Curated provider IDs, sorted for stable error messages and menus."""
    return tuple(sorted(PROVIDER_REGISTRY))


def get_provider_config(provider_id: str) -> ProviderConfig | None:
    """Look up a curated provider config by ID, case-insensitively."""
    return PROVIDER_REGISTRY.get((provider_id or "").strip().lower())


def transport_for_npm(npm: str | None) -> Transport:
    """Map a models.dev ``npm`` adapter name to an EvoFlux transport."""
    if not npm:
        return DEFAULT_TRANSPORT
    return NPM_TRANSPORTS.get(npm, DEFAULT_TRANSPORT)


def config_from_models_dev(
    provider_id: str, entry: dict[str, Any]
) -> ProviderConfig | None:
    """Synthesize a config from one models.dev provider entry.

    This is what lets EvoFlux reach a catalog provider it has never heard
    of: models.dev already states the adapter (``npm``), the endpoint
    (``api``) and the credential names (``env``), which is the whole of a
    :class:`ProviderConfig` for an OpenAI-compatible host.

    Returns ``None`` when the entry names something EvoFlux cannot connect
    to from a URL and a key alone — a native-SDK-only provider whose
    endpoint models.dev leaves null, or one whose URL is templated on other
    credentials (Databricks, Cloudflare) and so needs a real credential
    form rather than a guess.
    """
    npm = entry.get("npm")
    transport = transport_for_npm(npm if isinstance(npm, str) else None)
    api = entry.get("api")
    base_url = api.strip() if isinstance(api, str) else ""
    if not base_url:
        return None
    if "${" in base_url:
        return None

    env = entry.get("env")
    env_var = ""
    if isinstance(env, list) and env and isinstance(env[0], str):
        env_var = env[0]
    if not env_var:
        return None

    name = entry.get("name")
    normalized = provider_id.strip().lower()
    return ProviderConfig(
        id=normalized,
        label=name if isinstance(name, str) and name else provider_id,
        transport=transport,
        env_var=env_var,
        base_url=base_url,
        base_url_env_var=_derived_base_url_env_var(normalized),
        models_dev_id=normalized,
    )


def _derived_base_url_env_var(provider_id: str) -> str:
    """The conventional ``<PROVIDER>_BASE_URL`` override name."""
    slug = provider_id.upper().replace("-", "_").replace(".", "_")
    return f"{slug}_BASE_URL"


def custom_provider(
    provider_id: str,
    *,
    label: str | None = None,
    base_url: str,
    env_var: str | None = None,
    transport: Transport = DEFAULT_TRANSPORT,
) -> ProviderConfig:
    """Build a config for a user-declared endpoint.

    Mirrors MiMo-Code's "Custom Provider": any OpenAI-compatible base URL
    plus a key is enough, no catalog entry required. The base URL is used
    verbatim — no ``/v1`` is appended or stripped, because whether that path
    belongs there is the endpoint's business, not ours.
    """
    normalized = provider_id.strip().lower()
    slug = normalized.upper().replace("-", "_").replace(".", "_")
    return ProviderConfig(
        id=normalized,
        label=label or provider_id,
        transport=transport,
        env_var=env_var or f"{slug}_API_KEY",
        base_url=base_url,
        base_url_env_var=f"{slug}_BASE_URL",
    )


def resolve_provider(provider_id: str) -> ProviderConfig | None:
    """Resolve *provider_id* against the curated registry, then models.dev.

    Curated entries win: they carry the label, attribution headers and
    credential wiring the settings UI needs. Catalog entries fill in for
    the long tail.
    """
    normalized = (provider_id or "").strip().lower()
    if not normalized:
        return None
    curated = PROVIDER_REGISTRY.get(normalized)
    if curated is not None:
        return curated

    from app.agent.providers.model_registry import models_dev_provider_entry

    entry = models_dev_provider_entry(normalized)
    if entry is None:
        return None
    return config_from_models_dev(normalized, entry)


def catalog_entry(config: ProviderConfig) -> dict[str, Any]:
    """The models.dev envelope backing *config*, or empty when unlisted."""
    from app.agent.providers.model_registry import models_dev_provider_entry

    return models_dev_provider_entry(config.models_dev_provider_id) or {}


def catalog_base_url(config: ProviderConfig) -> str:
    """The endpoint models.dev publishes for this provider, if any.

    Empty for the ~26 first-party providers whose endpoint the catalog
    leaves null because their SDK hardcodes it (OpenAI, Anthropic, Google,
    Groq, Mistral…), and for any URL templated on other credentials
    (``https://${AZURE_RESOURCE_NAME}.…``), which is not an endpoint until
    those credentials are known.
    """
    api = catalog_entry(config).get("api")
    if not isinstance(api, str):
        return ""
    url = api.strip()
    return "" if not url or "${" in url else url


def catalog_env_vars(config: ProviderConfig) -> tuple[str, ...]:
    """Credential variable names models.dev lists for this provider."""
    env = catalog_entry(config).get("env")
    if not isinstance(env, list):
        return ()
    return tuple(name for name in env if isinstance(name, str) and name)


def catalog_docs_url(config: ProviderConfig) -> str:
    """The provider's model documentation, per models.dev.

    Distinct from :attr:`ProviderConfig.docs_url`, which points at the page
    where a user creates an API key. The settings UI wants both: one to get
    connected, one to read what the models do.
    """
    doc = catalog_entry(config).get("doc")
    return doc.strip() if isinstance(doc, str) else ""


def provider_label(config: ProviderConfig) -> str:
    """Display name: EvoFlux's own when set, else the catalog's."""
    if config.label:
        return config.label
    name = catalog_entry(config).get("name")
    if isinstance(name, str) and name:
        return name
    return config.id


def resolve_api_key(
    config: ProviderConfig, *, explicit: str | None = None
) -> str | None:
    """Resolve a credential: explicit value -> environment -> placeholder.

    The environment is searched under EvoFlux's own variable name first and
    then under every name models.dev lists for the provider. Those differ
    more often than they look: EvoFlux calls Kimi's key ``MOONSHOT_API_KEY``
    to keep it apart from the Moonshot platform's, while the catalog (and
    every other tool a user has installed) calls it ``KIMI_API_KEY``.
    Reading both means an existing environment works untouched.
    """
    if explicit:
        return explicit
    for name in (config.env_var, *catalog_env_vars(config)):
        if not name:
            continue
        from_env = os.environ.get(name)
        if from_env:
            return from_env
    return config.default_api_key or None


def resolve_base_url(config: ProviderConfig, *, explicit: str | None = None) -> str:
    """Resolve an endpoint: explicit -> override env var -> config -> catalog.

    :attr:`ProviderConfig.base_url` is an *override*, not a restatement: it
    is set only where EvoFlux deliberately differs from the catalog (Cohere's
    OpenAI-compatibility endpoint rather than its native v2 surface) or where
    the catalog publishes no endpoint at all. Everywhere else this reads
    models.dev, so a provider that moves its API moves EvoFlux with it on the
    next catalog refresh.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    if config.base_url_env_var:
        from_env = os.environ.get(config.base_url_env_var)
        if from_env and from_env.strip():
            return from_env.strip()
    return config.base_url or catalog_base_url(config)


def with_overrides(
    config: ProviderConfig,
    *,
    base_url: str | None = None,
    transport: Transport | None = None,
) -> ProviderConfig:
    """Return a copy of *config* with per-session overrides applied."""
    changes: dict[str, Any] = {}
    if base_url is not None and base_url.strip():
        changes["base_url"] = base_url.strip()
    if transport is not None:
        changes["transport"] = transport
    return replace(config, **changes) if changes else config


def request_headers(config: ProviderConfig) -> dict[str, str]:
    """Static headers every request to this provider should carry."""
    return {**config.attribution_headers, **config.extra_headers}


# ---------------------------------------------------------------------------
# Thinking-level vocabulary
# ---------------------------------------------------------------------------

#: Every active level name, ordered weakest -> strongest. These mirror
#: models.dev's ``reasoning_options.values`` vocabulary, which is also what
#: MiMo-Code's ``variants()`` keys its per-model effort maps on.
THINKING_ORDER: tuple[str, ...] = (
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

NO_THINKING_LEVELS = frozenset({"none", "off", "disabled"})
ACTIVE_THINKING_LEVELS = frozenset(THINKING_ORDER)
THINKING_LEVELS = ACTIVE_THINKING_LEVELS | NO_THINKING_LEVELS

#: Level names other tools and agent frontmatter use for the same efforts.
_LEVEL_ALIASES: dict[str, str] = {
    "ultra": "max",
    "maximum": "max",
    "very-high": "xhigh",
    "veryhigh": "xhigh",
    "x-high": "xhigh",
    "extra-high": "xhigh",
    "min": "minimal",
    "minimum": "minimal",
    "light": "low",
}


def normalize_thinking_level(value: object) -> str:
    """Normalize a caller-supplied thinking level to registry vocabulary.

    Returns ``"none"`` for any spelling of "do not reason", one of
    :data:`THINKING_ORDER` for an active effort, and ``""`` for "the caller
    expressed no preference". A typo lands in that last bucket rather than
    silently selecting an effort the model never advertised.
    """
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    if not normalized:
        return ""
    if normalized in NO_THINKING_LEVELS:
        return "none"
    if normalized in ACTIVE_THINKING_LEVELS:
        return normalized
    return _LEVEL_ALIASES.get(normalized, "")


def clamp_thinking_level(level: str, supported: tuple[str, ...]) -> str:
    """Snap *level* down to the strongest level *supported* allows.

    A model that tops out at ``high`` should serve a request for ``max`` at
    ``high`` rather than erroring or silently reasoning at its default —
    MiMo-Code clamps the same way when a variant map has no entry for the
    requested effort. Returns ``""`` when nothing is supported.
    """
    if not supported:
        return ""
    if level in supported:
        return level
    if level not in ACTIVE_THINKING_LEVELS:
        return ""
    ranked = [name for name in THINKING_ORDER if name in supported]
    if not ranked:
        return ""
    requested_rank = THINKING_ORDER.index(level)
    weaker = [name for name in ranked if THINKING_ORDER.index(name) <= requested_rank]
    return weaker[-1] if weaker else ranked[0]
