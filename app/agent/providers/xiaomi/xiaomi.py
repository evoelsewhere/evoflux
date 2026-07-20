"""Xiaomi MiMo provider — OpenAI-compatible API.

Thin wrapper around ``ChatCompletionsOnlyProvider`` with MiMo-specific
request quirks. Base URL is configurable (``XIAOMI_BASE_URL``) since MiMo
is also commonly reached through self-hosted or third-party gateways in
addition to Xiaomi's own Token Plan API.

Endpoint:  https://api.xiaomi.com/v1 (override via ``XIAOMI_BASE_URL``)
Auth:      Bearer {XIAOMI_API_KEY}
Docs:      https://mimo.mi.com/docs/en-US/api/chat/openai-api

MiMo thinking-mode quirks (vs plain OpenAI):
    1. Thinking mode is toggled with ``thinking: {"type": ...}``, not
       OpenAI's ``reasoning_effort`` field — the latter is not part of
       MiMo's documented request shape and is rejected by some deployments.
    2. When an assistant message contains tool calls AND thinking was
       active, the ``reasoning_content`` field MUST be echoed back in the
       next request or the API returns 400 "Param Incorrect" — this is
       documented by Xiaomi itself and matches multiple real-world reports
       (see https://github.com/XiaomiMiMo/MiMo/issues/44). The canonical
       ``AssistantMessage`` carries ``reasoning_content`` with
       ``exclude=True`` (other providers don't want it), so this handler
       uses its own ``XiaomiMessage`` schema that includes the field.

Token resolution order:
    1. ``Settings.XIAOMI_API_KEY`` (from ``.env`` or environment)
    2. ``XIAOMI_API_KEY`` environment variable

Usage::

    model: xiaomi:mimo-v2.5
    model: xiaomi:mimo-v2.5-pro
"""

from __future__ import annotations

from typing import Any

from app.agent.providers.openai import ChatCompletionsOnlyProvider
from app.agent.providers.openai.completions import CompletionsHandler
from app.agent.providers.openai.sanitization import sanitize_openai_tool_pairs
from app.agent.providers.openai.tool_content import flatten_tool_content_for_provider
from app.agent.providers.openai.schemas import (
    OpenAIFunctionCall,
    OpenAIStreamOptions,
    OpenAIToolCall,
)
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

from .schemas import XiaomiChatRequest, XiaomiMessage, XiaomiThinking

_NO_THINKING = frozenset({"none", "off"})


class _XiaomiCompletionsHandler(CompletionsHandler):
    """MiMo-specific completions handler.

    Differences from the base ``CompletionsHandler``:

    1. Uses ``XiaomiMessage`` instead of ``OpenAIMessage`` so that
       ``reasoning_content`` on assistant messages is a proper schema
       field and survives ``model_dump``.
    2. ``build_request`` uses ``XiaomiChatRequest``, which carries the
       ``thinking`` field instead of ``reasoning_effort``.
    3. ``customize_thinking`` sends ``thinking: {type: disabled}`` only
       when thinking is explicitly turned off; MiMo reasons by default
       and does not accept ``reasoning_effort``.
    """

    def _convert_messages_xiaomi(
        self, messages: list[ChatMessage]
    ) -> list[XiaomiMessage]:
        """Convert canonical chat messages to MiMo wire messages.

        Identical to the base ``convert_messages`` but produces
        ``XiaomiMessage`` objects and echoes ``reasoning_content`` on
        assistant messages that had tool calls — required by MiMo when
        thinking mode was active for that turn.
        """
        result: list[XiaomiMessage] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append(XiaomiMessage(role="system", content=msg.content))

            elif isinstance(msg, HumanMessage):
                if msg.parts:
                    parts: list[dict] = []
                    for part in msg.parts:
                        if isinstance(part, TextBlock):
                            parts.append({"type": "text", "text": part.text})
                        elif isinstance(part, ImageUrlBlock):
                            img: dict = {"url": part.url}
                            if part.detail:
                                img["detail"] = part.detail
                            parts.append({"type": "image_url", "image_url": img})
                        elif isinstance(part, ImageDataBlock):
                            data_url = f"data:{part.media_type};base64,{part.data}"
                            parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": data_url, "detail": "auto"},
                                }
                            )
                    result.append(XiaomiMessage(role="user", content=parts))
                else:
                    result.append(XiaomiMessage(role="user", content=msg.content))

            elif isinstance(msg, AssistantMessage):
                tool_calls = None
                if msg.tool_calls:
                    tool_calls = [
                        OpenAIToolCall(
                            id=tc.id,
                            function=OpenAIFunctionCall(
                                name=tc.function.name,
                                arguments=tc.function.arguments
                                if isinstance(tc.function.arguments, str)
                                else "{}",
                            ),
                        )
                        for tc in msg.tool_calls
                    ]
                # Echo reasoning_content whenever present. Not gated on
                # ``tool_calls`` being non-empty here: sanitize_openai_tool_pairs
                # (called before this method — see build_request) strips
                # tool_calls from a message whose tool turn was interrupted
                # before the tool ever ran, leaving no matching tool result.
                # Gating on (post-strip) tool_calls would silently drop real
                # reasoning_content for exactly the messages most likely to
                # otherwise end up with nothing to send at all.
                echoed_reasoning = msg.reasoning_content or None
                content = msg.content
                # MiMo rejects an assistant message with none of content,
                # reasoning_content, or tool_calls ("must provide content,
                # reasoning_content or tool_calls") — a genuinely empty LLM
                # turn (e.g. an empty reply that doesn't immediately follow a
                # tool result, so core.py's empty-response retry guard never
                # sees it) would otherwise serialize to a bare
                # {"role": "assistant"} and get a 400 on every future request
                # in this conversation, since history is resent every turn.
                if not content and not tool_calls and not echoed_reasoning:
                    content = " "
                result.append(
                    XiaomiMessage(
                        role="assistant",
                        content=content,
                        tool_calls=tool_calls,
                        reasoning_content=echoed_reasoning,
                    )
                )

            elif isinstance(msg, ToolMessage):
                if msg.parts:
                    parts = []
                    for part in msg.parts:
                        if isinstance(part, TextBlock):
                            parts.append({"type": "text", "text": part.text})
                        elif isinstance(part, ImageUrlBlock):
                            img = {"url": part.url}
                            if part.detail:
                                img["detail"] = part.detail
                            parts.append({"type": "image_url", "image_url": img})
                        elif isinstance(part, ImageDataBlock):
                            data_url = f"data:{part.media_type};base64,{part.data}"
                            parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": data_url, "detail": "auto"},
                                }
                            )
                    result.append(
                        XiaomiMessage(
                            role="tool",
                            content=parts,
                            tool_call_id=msg.tool_call_id,
                            name=msg.name,
                        )
                    )
                else:
                    result.append(
                        XiaomiMessage(
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
        req = XiaomiChatRequest(
            model=self.model,
            messages=flatten_tool_content_for_provider(
                self._convert_messages_xiaomi(sanitize_openai_tool_pairs(messages)),
                self.model,
            ),
            tools=self.convert_tools(tools),
            temperature=merged.get("temperature"),
            top_p=merged.get("top_p"),
            max_completion_tokens=merged.get("max_tokens"),
            stream=stream,
            stream_options=OpenAIStreamOptions(include_usage=True) if stream else None,
        )
        body = req.model_dump(exclude_none=True)
        self.customize_thinking(merged, body)
        return body

    def customize_thinking(self, merged: dict[str, Any], body: dict[str, Any]) -> None:
        """Map ``thinking_level`` to MiMo's ``thinking`` toggle.

        MiMo does not accept OpenAI's ``reasoning_effort`` field. Reasoning
        is on by default for thinking-capable models; the only override is
        to disable it via ``thinking: {"type": "disabled"}``.
        """
        if merged.get("thinking_level") in _NO_THINKING:
            body["thinking"] = XiaomiThinking(type="disabled").model_dump()


class XiaomiProvider(ChatCompletionsOnlyProvider):
    """Xiaomi MiMo provider (OpenAI-compatible).

    Args:
        api_key: MiMo API key from https://mimo.mi.com.
        model: Model name, e.g. ``"mimo-v2.5"``, ``"mimo-v2.5-pro"``.
        base_url: API base URL — defaults to Xiaomi's hosted endpoint,
            overridable via ``XIAOMI_BASE_URL`` for alternate gateways.
        temperature: Sampling temperature (0-2).
        top_p: Nucleus sampling probability mass cutoff.
        max_tokens: Hard cap on completion tokens.
        model_kwargs: Extra request body fields passed as-is.
    """

    def _make_completions_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> CompletionsHandler:
        return _XiaomiCompletionsHandler(model, base_url, headers)
