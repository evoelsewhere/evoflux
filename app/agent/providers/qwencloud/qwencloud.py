"""QwenCloud provider over its documented OpenAI-compatible APIs.

The default is QwenCloud's international pay-as-you-go endpoint. Token Plan
and Coding Plan keys use different API hosts, so callers may override the full
OpenAI-compatible root with ``DASHSCOPE_BASE_URL``.

QwenCloud-specific behavior:

- Chat Completions thinking traces arrive as ``reasoning_content`` and must be
  preserved in assistant history, especially across function-tool turns.
- Explicit ``none``/``off`` maps to ``enable_thinking=false``; omitting the
  control preserves each model's documented default.
- The Responses API is supported. EvoFlux sets ``store=false`` because it sends
  complete conversation context and does not use server-side response IDs.

References:

- https://docs.qwencloud.com/api-reference/chat/openai-chat
- https://docs.qwencloud.com/api-reference/chat/openai-responses
- https://docs.qwencloud.com/developer-guides/text-generation/function-calling
"""

from __future__ import annotations

from typing import Any

from pydantic.types import SecretStr

from app.agent.providers.openai import OpenAIProvider
from app.agent.providers.openai.completions import CompletionsHandler
from app.agent.providers.openai.responses import ResponsesHandler
from app.agent.providers.openai.sanitization import sanitize_openai_tool_pairs
from app.agent.providers.openai.schemas import (
    OpenAIFunctionCall,
    OpenAIStreamOptions,
    OpenAIToolCall,
)
from app.agent.providers.openai.tool_content import flatten_tool_content_for_provider
from app.agent.schemas.chat import (
    AssistantMessage,
    ChatMessage,
    HumanMessage,
    ImageDataBlock,
    ImageUrlBlock,
    SystemMessage,
    TextBlock,
    ToolMessage,
)

from .schemas import QwenCloudChatRequest, QwenCloudMessage

QWENCLOUD_API_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


def _supports_preserved_thinking(model: str) -> bool:
    """Return whether QwenCloud documents ``preserve_thinking`` for a model."""
    normalized = model.lower()
    return normalized.startswith(
        (
            "qwen3.8-max",
            "qwen3.8-flash",
            "qwen3.7-max",
            "qwen3.7-plus",
            "qwen3.7-flash",
            "qwen3.6-max",
            "qwen3.6-plus",
            "qwen3.6-flash",
        )
    )


def _uses_max_completion_tokens(model: str) -> bool:
    """Return whether QwenCloud documents the newer combined token limit."""
    normalized = model.lower()
    return normalized.startswith(
        (
            "qwen3.8-max",
            "qwen3.8-flash",
            "qwen3.7-max",
            "qwen3.7-plus",
            "qwen3.7-flash",
            "qwen3.6-plus",
            "qwen3.6-flash",
            "qwen3.5-plus",
            "qwen3.5-flash",
        )
    )


class _QwenCloudCompletionsHandler(CompletionsHandler):
    """Chat Completions translation for QwenCloud thinking history."""

    def _convert_messages_qwencloud(
        self, messages: list[ChatMessage]
    ) -> list[QwenCloudMessage]:
        result: list[QwenCloudMessage] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append(QwenCloudMessage(role="system", content=msg.content))

            elif isinstance(msg, HumanMessage):
                if msg.parts:
                    parts: list[dict[str, Any]] = []
                    for part in msg.parts:
                        if isinstance(part, TextBlock):
                            parts.append({"type": "text", "text": part.text})
                        elif isinstance(part, ImageUrlBlock):
                            image_url: dict[str, Any] = {"url": part.url}
                            if part.detail:
                                image_url["detail"] = part.detail
                            parts.append({"type": "image_url", "image_url": image_url})
                        elif isinstance(part, ImageDataBlock):
                            parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": (
                                            f"data:{part.media_type};base64,{part.data}"
                                        ),
                                        "detail": "auto",
                                    },
                                }
                            )
                    result.append(QwenCloudMessage(role="user", content=parts))
                else:
                    result.append(QwenCloudMessage(role="user", content=msg.content))

            elif isinstance(msg, AssistantMessage):
                tool_calls = None
                if msg.tool_calls:
                    tool_calls = [
                        OpenAIToolCall(
                            id=tool_call.id,
                            function=OpenAIFunctionCall(
                                name=tool_call.function.name,
                                arguments=(
                                    tool_call.function.arguments
                                    if isinstance(tool_call.function.arguments, str)
                                    else "{}"
                                ),
                            ),
                        )
                        for tool_call in msg.tool_calls
                    ]
                if not msg.content and not tool_calls:
                    continue
                result.append(
                    QwenCloudMessage(
                        role="assistant",
                        content=msg.content,
                        tool_calls=tool_calls,
                        reasoning_content=msg.reasoning_content,
                    )
                )

            elif isinstance(msg, ToolMessage):
                if msg.parts:
                    parts = []
                    for part in msg.parts:
                        if isinstance(part, TextBlock):
                            parts.append({"type": "text", "text": part.text})
                        elif isinstance(part, ImageUrlBlock):
                            image_url = {"url": part.url}
                            if part.detail:
                                image_url["detail"] = part.detail
                            parts.append({"type": "image_url", "image_url": image_url})
                        elif isinstance(part, ImageDataBlock):
                            parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": (
                                            f"data:{part.media_type};base64,{part.data}"
                                        ),
                                        "detail": "auto",
                                    },
                                }
                            )
                    result.append(
                        QwenCloudMessage(
                            role="tool",
                            content=parts,
                            tool_call_id=msg.tool_call_id,
                            name=msg.name,
                        )
                    )
                else:
                    result.append(
                        QwenCloudMessage(
                            role="tool",
                            content=msg.content,
                            tool_call_id=msg.tool_call_id,
                            name=msg.name,
                        )
                    )
        return result

    def build_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        converted = self._convert_messages_qwencloud(
            sanitize_openai_tool_pairs(messages)
        )
        max_tokens = merged.get("max_tokens")
        req = QwenCloudChatRequest(
            model=self.model,
            messages=flatten_tool_content_for_provider(converted, self.model),
            tools=self.convert_tools(tools),
            temperature=merged.get("temperature"),
            top_p=merged.get("top_p"),
            max_tokens=(
                max_tokens if not _uses_max_completion_tokens(self.model) else None
            ),
            max_completion_tokens=(
                max_tokens if _uses_max_completion_tokens(self.model) else None
            ),
            preserve_thinking=(
                True
                if _supports_preserved_thinking(self.model)
                and any(
                    isinstance(message, AssistantMessage)
                    and bool(message.reasoning_content)
                    for message in messages
                )
                else None
            ),
            stream=stream,
            stream_options=OpenAIStreamOptions(include_usage=True) if stream else None,
        )
        body = req.model_dump(exclude_none=True)
        self.customize_thinking(merged, body)
        return body

    def customize_thinking(self, merged: dict[str, Any], body: dict[str, Any]) -> None:
        thinking_level = merged.get("thinking_level", "")
        if thinking_level in {"none", "off"}:
            body["enable_thinking"] = False
        elif thinking_level:
            body["enable_thinking"] = True
            body["reasoning_effort"] = thinking_level


class _QwenCloudResponsesHandler(ResponsesHandler):
    """Responses API translation with explicit retention and thinking policy."""

    def build_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        body = super().build_request(messages, tools, stream, merged)
        body["store"] = False
        return body

    def customize_thinking(self, merged: dict[str, Any], body: dict[str, Any]) -> None:
        thinking_level = merged.get("thinking_level", "")
        if thinking_level in {"none", "off"}:
            body["enable_thinking"] = False
        elif thinking_level:
            body["reasoning"] = {"effort": thinking_level}

    def parse_response(self, data: dict) -> AssistantMessage:
        message = super().parse_response(data)
        if message.reasoning_content:
            return message

        reasoning_parts: list[str] = []
        for item in data.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "reasoning":
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"reasoning_text", "text"} and isinstance(
                    part.get("text"), str
                ):
                    reasoning_parts.append(part["text"])
        if reasoning_parts:
            message.reasoning_content = "\n\n".join(reasoning_parts)
        return message


class QwenCloudProvider(OpenAIProvider):
    """QwenCloud Chat Completions and Responses provider."""

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        base_url: str = QWENCLOUD_API_BASE,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )

    def _make_completions_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> CompletionsHandler:
        return _QwenCloudCompletionsHandler(model, base_url, headers)

    def _make_responses_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> ResponsesHandler:
        return _QwenCloudResponsesHandler(model, base_url, headers)
