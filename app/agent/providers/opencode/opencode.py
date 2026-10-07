"""OpenCode Zen and OpenCode Go providers.

Both are one API key in front of several vendors, reached over three wire
protocols. Which protocol a model needs is a documented per-family fact
(https://opencode.ai/docs/zen/, https://opencode.ai/docs/go/), so — unlike
Xiaomi, where one endpoint has one quirk — the quirk here is *routing*:

    ===================  ============================================  ======================
    Transport            Endpoint                                      Serves
    ===================  ============================================  ======================
    OPENAI_COMPLETIONS   ``{base}/chat/completions``                   GLM, Kimi, DeepSeek,
                                                                       MiMo, Qwen, MiniMax
                                                                       (Zen), free models
    OPENAI_RESPONSES     ``{base}/responses``                          GPT, Grok, Muse Spark
    ANTHROPIC            ``{root}/v1/messages``                        Claude, MiniMax and
                                                                       Qwen (Go)
    GOOGLE_GENAI         ``{base}/models/{model}`` (Zen only)          Gemini
    ===================  ============================================  ======================

``{base}`` is ``https://opencode.ai/zen/v1`` (Zen) or
``https://opencode.ai/zen/go/v1`` (Go). The routing table lives on the
registry entries (:attr:`ProviderConfig.model_transports`) so reasoning
translation and model discovery read the same answer as the factory.

Auth: ``Bearer {key}`` on every endpoint — ``OPENCODE_API_KEY`` for Zen and
``OPENCODE_GO_API_KEY`` for Go, so connecting one never connects the other. The Anthropic and
Gemini surfaces natively read ``x-api-key`` / ``x-goog-api-key``, so those
adapters send the Bearer header alongside their own.

Client headers: OpenCode requires "a stable session ID in ``x-opencode-session``
for each conversation" and a client's own ``User-Agent``
(https://opencode.ai/docs/go/#where-can-i-use-it); without the session header
the gateway answers ``400 MissingSessionID``. Every adapter therefore sends
``x-opencode-session`` / ``x-opencode-session-id`` plus ``x-opencode-request``
(this call) and ``x-opencode-client`` (which app), as OpenCode's own client
does. The session value is EvoFlux's opaque cache-affinity key, never the raw
session ID. Calls with no conversation behind them (title generation, memory
passes) use an id minted once per provider instance, so they are still routed
as one stable session. ``x-opencode-project`` is omitted because a project ID
is local state the gateway has no use for from us.

Anonymous access: OpenCode's client falls back to the public key ``public``
for ``$0`` Zen models when no credential is configured.
:func:`anonymous_api_key` mirrors that for the same models and nothing else.

Chat Completions models (``@ai-sdk/openai-compatible`` upstream) inherit two
divergences from the generic handler:

1. ``max_tokens`` rather than ``max_completion_tokens`` — the field the
   OpenAI-compatible SDK sends, and the one DeepSeek-family backends accept.
2. ``reasoning_content`` is echoed back on assistant turns for models whose
   catalog row says they interleave reasoning there (DeepSeek V4, Kimi, MiMo).
   Those backends reject the next request with a 400 when it is dropped; the
   canonical ``AssistantMessage`` carries it with ``exclude=True``.

Usage::

    model: opencode:claude-sonnet-5
    model: opencode:gpt-5.5
    model: opencode-go:kimi-k3
    model: opencode-go:minimax-m3
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger
from pydantic.types import SecretStr

from app.agent.providers.anthropic import AnthropicProvider
from app.agent.providers.googlegenai import GoogleGenAIProvider
from app.agent.providers.openai import OpenAIProvider
from app.agent.providers.openai.completions import CompletionsHandler
from app.agent.providers.openai.sanitization import sanitize_openai_tool_pairs
from app.agent.providers.registry import Transport
from app.agent.providers.openai.responses import ResponsesHandler
from app.agent.schemas.chat import AssistantMessage, ChatMessage
from app.core.version import VERSION

OPENCODE_PROVIDER_IDS: frozenset[str] = frozenset({"opencode", "opencode-go"})

ZEN_BASE_URL = "https://opencode.ai/zen/v1"
GO_BASE_URL = "https://opencode.ai/zen/go/v1"

#: Model families that need ``reasoning_content`` echoed when the catalog
#: has no row for the model yet (a release newer than the bundled snapshot).
#: Same families the catalog flags today; a catalog answer always wins.
_ECHO_REASONING_FAMILIES: tuple[str, ...] = ("deepseek-", "kimi-", "mimo-")


#: What OpenCode's client sends when a ``$0`` model is used without a key.
PUBLIC_API_KEY = "public"

#: Value of ``x-opencode-client``: which application is calling the gateway.
CLIENT_ID = "evoflux"


def new_session_id() -> str:
    """A session id for calls that belong to no conversation, minted once per owner."""
    return f"evoflux-v1:{uuid.uuid4().hex}"


def opencode_request_headers(
    merged: dict[str, Any] | None, fallback_session: str
) -> dict[str, str]:
    """Per-request client headers OpenCode's gateways require or expect.

    The session is the agent loop's affinity key when there is one and
    *fallback_session* otherwise — never absent, because the gateway rejects a
    request without it. The request id is fresh per call.
    """
    source = merged or {}
    session = source.get("cache_probe_scope") or source.get("prompt_cache_key")
    if not (isinstance(session, str) and session.strip()):
        session = fallback_session
    session = session.strip()
    return {
        "User-Agent": f"EvoFlux/{VERSION}",
        "x-opencode-client": CLIENT_ID,
        "x-opencode-request": uuid.uuid4().hex,
        "x-opencode-session": session,
        "x-opencode-session-id": session,
    }


def anonymous_api_key(provider_id: str, model: str) -> str | None:
    """The public key OpenCode's client uses for a free Zen model, else ``None``.

    Only Zen has a free tier, and only a model the catalog prices at exactly
    ``$0`` input qualifies — an unpriced model is not assumed free.
    """
    if provider_id != "opencode":
        return None
    from app.agent.providers.model_metadata import get_model_metadata

    if get_model_metadata(f"{provider_id}:{model}").cost.input == 0:
        return PUBLIC_API_KEY
    return None


def opencode_transport(provider_id: str, model: str) -> Transport:
    """The wire protocol *model* is served over on this OpenCode plan."""
    from app.agent.providers.thinking import model_transport

    return model_transport(provider_id, model)


def _echoes_reasoning(provider_id: str, model: str) -> bool:
    """Whether *model* needs ``reasoning_content`` sent back on assistant turns."""
    from app.agent.providers.model_metadata import get_model_features

    field = get_model_features(f"{provider_id}:{model}").interleaved_field
    if field:
        return field == "reasoning_content"
    return model.lower().startswith(_ECHO_REASONING_FAMILIES)


def _strip_v1(base_url: str) -> str:
    """``https://host/zen/v1`` → ``https://host/zen``.

    The Anthropic adapter appends ``/v1/messages`` itself, so handing it the
    shared OpenAI-style base would request ``/zen/v1/v1/messages``.
    """
    trimmed = base_url.rstrip("/")
    return trimmed[: -len("/v1")] if trimmed.endswith("/v1") else trimmed


def _secret(value: str | SecretStr) -> str:
    return value.get_secret_value() if isinstance(value, SecretStr) else value


class _OpenCodeCompletionsHandler(CompletionsHandler):
    """Chat Completions for the open-weight models OpenCode hosts."""

    default_provider_id = "opencode"

    uses_max_completion_tokens = False

    def __init__(
        self,
        model: str,
        base_url: str,
        headers: dict[str, str],
        *,
        echo_reasoning: bool = False,
    ) -> None:
        super().__init__(model, base_url, headers)
        self.echo_reasoning = echo_reasoning
        self._fallback_session = new_session_id()

    def _request_headers(self, merged: dict[str, Any]) -> dict[str, str]:
        return {
            **super()._request_headers(merged),
            **opencode_request_headers(merged, self._fallback_session),
        }

    def build_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        body = super().build_request(messages, tools, stream, merged)
        if not self.echo_reasoning:
            return body

        # The base conversion drops ``reasoning_content`` (and any assistant
        # turn with neither content nor tool calls). Re-derive the same
        # surviving turns here and graft the trace back onto the wire body.
        reasoning = [
            msg.reasoning_content
            for msg in sanitize_openai_tool_pairs(messages)
            if isinstance(msg, AssistantMessage) and (msg.content or msg.tool_calls)
        ]
        wire = [m for m in body.get("messages", []) if m.get("role") == "assistant"]
        if len(wire) != len(reasoning):
            logger.warning(
                "opencode_reasoning_echo_skipped model={} wire={} source={}",
                self.model,
                len(wire),
                len(reasoning),
            )
            return body
        for wire_message, trace in zip(wire, reasoning, strict=True):
            if trace:
                wire_message["reasoning_content"] = trace
        return body


class _OpenCodeResponsesHandler(ResponsesHandler):
    """Responses handler that tags requests with OpenCode's client headers."""

    default_provider_id = "opencode"

    def __init__(self, model: str, base_url: str, headers: dict[str, str]) -> None:
        super().__init__(model, base_url, headers)
        self._fallback_session = new_session_id()

    def _request_headers(self, merged: dict[str, Any]) -> dict[str, str]:
        return {
            **super()._request_headers(merged),
            **opencode_request_headers(merged, self._fallback_session),
        }


class OpenCodeProvider(OpenAIProvider):
    """OpenCode models served over Chat Completions or Responses.

    The endpoint is fixed by the model, not by ``thinking_level`` or a
    ``responses_api`` flag: GPT/Grok/Muse Spark only answer ``/responses`` and
    everything else only answers ``/chat/completions``.

    Args:
        api_key: Key from https://opencode.ai/auth (Zen or Go workspace key).
        model: Model ID without the provider prefix, e.g. ``"gpt-5.5"``.
        base_url: Zen or Go base URL (``…/zen/v1``, ``…/zen/go/v1``).
        provider_id: ``"opencode"`` (Zen) or ``"opencode-go"``; selects the
            routing table and the catalog metadata.
    """

    default_provider_id = "opencode"

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        base_url: str = ZEN_BASE_URL,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
        *,
        provider_id: str = "opencode",
    ) -> None:
        # Both hooks run inside ``OpenAIProvider.__init__``, before the
        # factory can bind the ID, so the identity has to exist first.
        self.provider_name = provider_id
        self._echo_reasoning = _echoes_reasoning(provider_id, model)
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )

    def _use_responses_for(self, model_kwargs: dict[str, Any]) -> bool:
        provider_id = self.provider_name or "opencode"
        return opencode_transport(provider_id, self.model) is Transport.OPENAI_RESPONSES

    def _make_completions_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> CompletionsHandler:
        return _OpenCodeCompletionsHandler(
            model, base_url, headers, echo_reasoning=self._echo_reasoning
        )

    def _make_responses_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> ResponsesHandler:
        return _OpenCodeResponsesHandler(model, base_url, headers)


class OpenCodeMessagesProvider(AnthropicProvider):
    """OpenCode models served over Anthropic Messages (Claude, MiniMax, Qwen)."""

    default_provider_id = "opencode"

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        base_url: str = ZEN_BASE_URL,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=_strip_v1(base_url),
            headers={"Authorization": f"Bearer {_secret(api_key)}"},
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )
        self._fallback_session = new_session_id()

    def _request_headers(self, merged: dict[str, Any]) -> dict[str, str]:
        return {
            **super()._request_headers(merged),
            **opencode_request_headers(merged, self._fallback_session),
        }


class OpenCodeGeminiProvider(GoogleGenAIProvider):
    """Gemini models on Zen, reached at ``{base}/models/{model}``."""

    default_provider_id = "opencode"

    #: Call context of the request in flight. The Gemini base class asks for
    #: auth headers without passing it, but the session headers need it.
    _call_context: dict[str, Any] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._fallback_session = new_session_id()

    def _auth_headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            **opencode_request_headers(self._call_context, self._fallback_session),
        }

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AssistantMessage:
        self._call_context = self._merged_kwargs(**kwargs)
        return await super().chat(messages, tools, **kwargs)

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ):
        self._call_context = self._merged_kwargs(**kwargs)
        async for chunk in super().stream(messages, tools, **kwargs):
            yield chunk


def build_opencode_provider(
    provider_id: str,
    model: str,
    api_key: str | SecretStr,
    base_url: str,
    model_kwargs: dict[str, Any] | None = None,
) -> OpenAIProvider | AnthropicProvider | GoogleGenAIProvider:
    """Construct the adapter that speaks *model*'s documented protocol."""
    transport = opencode_transport(provider_id, model)
    if transport is Transport.ANTHROPIC:
        return OpenCodeMessagesProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
            model_kwargs=model_kwargs,
        )
    if transport is Transport.GOOGLE_GENAI:
        return OpenCodeGeminiProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
            model_kwargs=model_kwargs,
        )
    return OpenCodeProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        model_kwargs=model_kwargs,
        provider_id=provider_id,
    )
