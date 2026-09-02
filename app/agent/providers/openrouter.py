"""OpenRouter provider with its native normalized reasoning contract."""

from __future__ import annotations

from typing import Any

from pydantic.types import SecretStr

from app.agent.providers.openai import ChatCompletionsOnlyProvider
from app.agent.providers.openai.completions import CompletionsHandler
from app.agent.schemas.chat import ChatMessage


_CACHE_CONTROL = {"type": "ephemeral"}


def _mark_message_cache_control(message: dict[str, Any]) -> None:
    """Add a cache breakpoint to the last content block of *message*, in place.

    OpenRouter forwards ``cache_control`` to Anthropic models only when it is
    set on a content block, never as a top-level request field.
    """
    content = message.get("content")
    if isinstance(content, list) and content:
        content[-1] = {**content[-1], "cache_control": _CACHE_CONTROL}
    elif isinstance(content, str) and content:
        message["content"] = [
            {"type": "text", "text": content, "cache_control": _CACHE_CONTROL}
        ]


class _OpenRouterCompletionsHandler(CompletionsHandler):
    """Translate EvoFlux levels to OpenRouter's ``reasoning`` object."""

    def customize_thinking(self, merged: dict[str, Any], body: dict[str, Any]) -> None:
        thinking_level = merged.get("thinking_level")
        if thinking_level == "none":
            body["reasoning"] = {"enabled": False}
        elif thinking_level:
            body["reasoning"] = {"effort": thinking_level}

    def build_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        body = super().build_request(messages, tools, stream, merged)
        if merged.get("session_id") is not None:
            body["session_id"] = merged["session_id"]
        if self.model.startswith(("anthropic/", "~anthropic/")):
            body_messages = body.get("messages")
            if isinstance(body_messages, list) and body_messages:
                if body_messages[0].get("role") == "system":
                    _mark_message_cache_control(body_messages[0])
                _mark_message_cache_control(body_messages[-1])
        return body


class OpenRouterProvider(ChatCompletionsOnlyProvider):
    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        base_url: str,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            model_kwargs=model_kwargs,
        )

    def _make_completions_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> CompletionsHandler:
        return _OpenRouterCompletionsHandler(model, base_url, headers)

    def cache_affinity_kwargs(self, cache_key: str | None) -> dict[str, Any]:
        return {"session_id": cache_key} if cache_key else {}
