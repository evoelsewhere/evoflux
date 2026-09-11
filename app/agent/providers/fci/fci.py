"""FCI provider — FPT AI Marketplace inference gateway.

FPT exposes both OpenAI-compatible Chat Completions and Responses APIs. Agent
work defaults to Responses because that is the FPT-documented interface for
function calling; ``responses_api: false`` remains available for plain-chat
compatibility.

Auth:   Bearer {FCI_API_KEY}
Token resolution order:
    1. ``Settings.FCI_API_KEY`` / ``Settings.FCI_BASE_URL`` (``.env`` or environment)
    2. ``FCI_API_KEY`` / ``FCI_BASE_URL`` environment variables

The public endpoint defaults to ``https://mkp-api.fptcloud.com/v1``. Dedicated
deployments can override it with ``FCI_BASE_URL``.

Usage::

    model: fci:gpt-oss-120b
    model: fci:deepseek-v4-flash
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic.types import SecretStr

from app.agent.providers.openai import OpenAIProvider
from app.agent.providers.openai.completions import CompletionsHandler
from app.agent.providers.openai.responses import ResponsesHandler
from app.agent.schemas.chat import AssistantMessage, ChatMessage

FCI_API_BASE = "https://mkp-api.fptcloud.com/v1"

_FCI_CHAT_EXTRA_FIELDS = frozenset(
    {
        "frequency_penalty",
        "parallel_tool_calls",
        "presence_penalty",
        "response_format",
        "seed",
        "stop",
        "tool_choice",
        "top_k",
    }
)

_FCI_RESPONSES_EXTRA_FIELDS = frozenset(
    {
        "parallel_tool_calls",
        "temperature",
        "top_p",
    }
)


def normalize_fci_base_url(base_url: str | None) -> str:
    """Return a request-safe FCI API base URL.

    Older EvoFlux configurations stored FPT's public host without ``/v1``.
    That host accepts ``/models`` and ``/chat/completions`` aliases, but its
    Responses API exists only below ``/v1``. Normalize that one known public
    host while leaving dedicated/custom gateway paths untouched.
    """
    value = (base_url or "").strip().rstrip("/") or FCI_API_BASE
    parsed = urlsplit(value)
    if parsed.hostname == "mkp-api.fptcloud.com" and parsed.path in ("", "/"):
        return urlunsplit(
            (parsed.scheme, parsed.netloc, "/v1", parsed.query, parsed.fragment)
        )
    return value


def _unwrap_fci_envelope(data: dict[str, Any]) -> dict[str, Any]:
    """Unwrap FPT's documented ``code/message/data`` response envelope."""
    current = data
    for _ in range(2):
        nested = current.get("data")
        if not isinstance(nested, dict):
            break
        if any(key in current for key in ("id", "model", "choices", "content")):
            break
        current = nested
    return current


class _FCICompletionsHandler(CompletionsHandler):
    """Translate FPT Chat Completions differences from native OpenAI."""

    default_provider_id = "fci"

    # FPT's current Marketplace examples document ``max_tokens``.
    uses_max_completion_tokens = False

    def build_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        body = super().build_request(messages, tools, stream, merged)
        # This optional OpenAI extension is not part of FPT's documented chat
        # contract and has caused strict compatible gateways to reject streams.
        body.pop("stream_options", None)
        for field in _FCI_CHAT_EXTRA_FIELDS:
            if merged.get(field) is not None:
                body[field] = merged[field]
        return body

    def customize_thinking(self, merged: dict[str, Any], body: dict[str, Any]) -> None:
        # The live FPT catalog does not advertise reasoning_effort or another
        # request-level thinking control. Models may still reason internally.
        return None

    def normalize_response_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        return _unwrap_fci_envelope(data)

    def normalize_stream_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = _unwrap_fci_envelope(data)
        # Older FPT streaming examples emit ``data: {"content": "..."}``
        # instead of a full OpenAI chunk. Accept both forms.
        if "choices" not in payload and isinstance(payload.get("content"), str):
            return {
                "id": "fci-stream",
                "created": int(time.time()),
                "model": self.model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": payload["content"]},
                        "finish_reason": None,
                    }
                ],
            }
        return payload


class _FCIResponsesHandler(ResponsesHandler):
    """Translate EvoFlux requests to FPT's supported Responses surface."""

    default_provider_id = "fci"

    def convert_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        converted = super().convert_tools(tools)
        if not tools:
            return converted

        # FPT's Responses function-calling contract supports strict schemas.
        source_functions = [
            tool.get("function", {})
            for tool in tools
            if tool.get("type") == "function" and isinstance(tool.get("function"), dict)
        ]
        for target, source in zip(converted, source_functions, strict=True):
            if isinstance(source.get("strict"), bool):
                target["strict"] = source["strict"]
        return converted

    def build_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        body = super().build_request(messages, tools, stream, merged)

        # These OpenAI-only controls are not advertised by FPT and can make
        # otherwise valid agent requests fail schema validation.
        body.pop("prompt_cache_key", None)
        body.pop("reasoning", None)

        for field in _FCI_RESPONSES_EXTRA_FIELDS:
            if merged.get(field) is not None:
                body[field] = merged[field]

        tool_choice = merged.get("tool_choice")
        if tool_choice is not None:
            # FPT's Harmony runtime (gpt-oss) returns 501 for forced function
            # selection and currently accepts only automatic tool routing.
            body["tool_choice"] = (
                "auto"
                if self.model.lower().startswith("gpt-oss-") and tool_choice != "auto"
                else tool_choice
            )

        # Chat-style response_format maps to the Responses API text.format
        # field. Preserve the caller's schema rather than sending an invalid
        # top-level response_format property.
        response_format = merged.get("response_format")
        if isinstance(response_format, dict):
            body["text"] = {"format": response_format}
        return body

    def customize_thinking(self, merged: dict[str, Any], body: dict[str, Any]) -> None:
        # No named effort is currently declared by FPT's live model contract.
        return None

    def parse_response(self, data: dict) -> AssistantMessage:
        return super().parse_response(_unwrap_fci_envelope(data))


class FCIProvider(OpenAIProvider):
    """FCI (FPT inference gateway) provider — OpenAI-compatible.

    Responses API is the default because FPT documents function calling there.
    Pass ``model_kwargs={"responses_api": False}`` to force Chat Completions.

    Args:
        api_key: FCI API key issued by FPT.
        model: Model name, e.g. ``"gpt-oss-120b"``, ``"deepseek-v4-flash"``.
        base_url: FCI gateway endpoint; defaults to the public Marketplace API.
        temperature: Sampling temperature (0-2).
        top_p: Nucleus sampling probability mass cutoff.
        max_tokens: Hard cap on completion tokens.
        model_kwargs: Extra request body fields passed as-is.
    """

    default_provider_id = "fci"

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        base_url: str = FCI_API_BASE,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=normalize_fci_base_url(base_url),
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )

    def _use_responses_for(self, model_kwargs: dict[str, Any]) -> bool:
        return bool(model_kwargs.get("responses_api", True))

    def _make_completions_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> CompletionsHandler:
        return _FCICompletionsHandler(model, base_url, headers)

    def _make_responses_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> ResponsesHandler:
        return _FCIResponsesHandler(model, base_url, headers)
