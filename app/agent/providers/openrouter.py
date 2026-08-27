"""OpenRouter provider with its native normalized reasoning contract."""

from __future__ import annotations

from typing import Any

from pydantic.types import SecretStr

from app.agent.providers.openai import ChatCompletionsOnlyProvider
from app.agent.providers.openai.completions import CompletionsHandler
from app.agent.schemas.chat import ChatMessage


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
            body["cache_control"] = {"type": "ephemeral"}
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
