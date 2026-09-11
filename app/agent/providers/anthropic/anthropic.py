from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic.types import SecretStr

from app.agent.providers.base import LLMProviderBase
from app.agent.usage import usage_to_dict
from app.agent.schemas.chat import (
    AssistantMessage,
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionDelta,
    ChatMessage,
    FunctionCall,
    FunctionCallDelta,
    HumanMessage,
    ImageDataBlock,
    ImageUrlBlock,
    SystemMessage,
    TextBlock,
    ToolCall,
    ToolCallDelta,
    ToolMessage,
    Usage,
)

from app.agent.providers.transform import (
    reject_images_for_non_vision,
    strip_empty_parts_anthropic,
)

ANTHROPIC_API_BASE = "https://api.anthropic.com"
ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_MODELS = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]


def _resolve_secret(value: str | SecretStr) -> str:
    return value.get_secret_value() if isinstance(value, SecretStr) else value


def _headers(
    api_key: str,
    extra: dict[str, str] | None = None,
    *,
    use_api_key_header: bool = True,
) -> dict[str, str]:
    headers = {
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
        **(extra or {}),
    }
    if use_api_key_header:
        headers["x-api-key"] = api_key
    return headers


def _anthropic_content_blocks(parts: list[Any]) -> list[dict[str, Any]]:
    """Convert canonical multimodal parts to Anthropic Messages blocks."""
    blocks: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, TextBlock):
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, ImageDataBlock):
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": part.media_type,
                        "data": part.data,
                    },
                }
            )
        elif isinstance(part, ImageUrlBlock):
            blocks.append(
                {
                    "type": "image",
                    "source": {"type": "url", "url": part.url},
                }
            )
    return blocks


def _split_messages(
    messages: list[ChatMessage],
) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            if message.content:
                system_parts.append(message.content)
            continue
        if isinstance(message, HumanMessage):
            content: str | list[dict[str, Any]] = message.content or ""
            if message.parts:
                content = _anthropic_content_blocks(message.parts)
            out.append({"role": "user", "content": content})
        elif isinstance(message, AssistantMessage) and message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for tool_call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.function.name,
                        "input": json.loads(tool_call.function.arguments or "{}"),
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        elif isinstance(message, AssistantMessage):
            out.append({"role": "assistant", "content": message.content or ""})
        elif isinstance(message, ToolMessage):
            tool_content: str | list[dict[str, Any]] = message.content or ""
            if message.parts:
                tool_content = _anthropic_content_blocks(message.parts)
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id,
                            "content": tool_content,
                        }
                    ],
                }
            )
    return "\n\n".join(system_parts) or None, out


def _anthropic_tools(tools: list[dict] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    converted: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            continue
        converted.append(
            {
                "name": str(function.get("name", "")),
                "description": function.get("description", ""),
                "input_schema": function.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return converted or None


def _mark_cache_control(
    block: dict[str, Any], cache_control: dict[str, Any]
) -> dict[str, Any]:
    return {**block, "cache_control": cache_control}


def _system_blocks(
    system: str,
    cache_control: dict[str, Any] | None,
    cache_boundary: int | None,
) -> str | list[dict[str, Any]]:
    """Split *system* at ``cache_boundary`` into a cached head + plain tail.

    ``cache_boundary`` (set via ``agent_loop/streaming.py`` from
    ``CacheBoundaryHook``) marks where per-turn-volatile content — memory
    context, the ranked skill catalog — starts. Caching only the head means
    that content changing every turn no longer invalidates the cache for the
    much larger, actually-stable rest of the system prompt.
    """
    if not cache_control:
        return system
    if not isinstance(cache_boundary, int) or not (0 < cache_boundary < len(system)):
        return [{"type": "text", "text": system, "cache_control": cache_control}]
    head, tail = system[:cache_boundary], system[cache_boundary:]
    return [
        {"type": "text", "text": head, "cache_control": cache_control},
        {"type": "text", "text": tail},
    ]


def _mark_last_message_cache_control(
    message: dict[str, Any], cache_control: dict[str, Any]
) -> None:
    """Add a cache breakpoint to the last content block of *message*, in place.

    Anthropic only recognizes ``cache_control`` on individual content blocks,
    never as a top-level request field. Marking the newest message caches
    everything up to and including it, so the next turn in the same
    conversation reuses the growing prefix instead of paying for it again.
    """
    content = message.get("content")
    if isinstance(content, list) and content:
        content[-1] = _mark_cache_control(content[-1], cache_control)
    elif isinstance(content, str) and content:
        message["content"] = [
            {"type": "text", "text": content, "cache_control": cache_control}
        ]


def _supports_legacy_sampling(model: str) -> bool:
    return not any(marker in model for marker in ("-4-5", "-4-6", "-4-7"))


def _apply_thinking(
    model: str,
    kwargs: dict[str, Any],
    payload: dict[str, Any],
    *,
    provider_id: str = "anthropic",
) -> bool:
    """Translate ``thinking_level`` onto *payload*; return whether it is on.

    The wire shape — adaptive descriptor for the newest Claude generations,
    an explicit token budget for the rest — comes from the shared translator
    in :mod:`app.agent.providers.thinking`, so a third-party endpoint
    speaking Anthropic Messages (MiniMax, Kimi's Anthropic surface) gets the
    same handling from its own catalog metadata.

    The return value gates sampling: Anthropic rejects ``temperature`` and
    ``top_p`` alongside extended thinking on the older models.
    """
    from app.agent.providers.thinking import thinking_request_fields

    requested = kwargs.pop("thinking_level", None)
    fields = thinking_request_fields(
        provider_id,
        model,
        requested,
        max_output=payload.get("max_tokens"),
    )
    if not fields:
        return False

    payload.update(fields)
    thinking = payload.get("thinking")
    return isinstance(thinking, dict) and thinking.get("type") != "disabled"


def _add_sampling(
    model: str, kwargs: dict[str, Any], payload: dict[str, Any], *, thinking: bool
) -> None:
    if not _supports_legacy_sampling(model):
        return
    if not thinking:
        for name in ("temperature", "top_p"):
            if name in kwargs and kwargs[name] is not None:
                payload[name] = kwargs[name]
        return
    top_p = kwargs.get("top_p")
    if (
        isinstance(top_p, (int, float))
        and not isinstance(top_p, bool)
        and 0.95 <= top_p <= 1
    ):
        payload["top_p"] = top_p


def _finish_reason(stop_reason: str | None) -> str | None:
    return "tool_calls" if stop_reason == "tool_use" else stop_reason


def _usage_from_anthropic(raw_usage: dict[str, Any] | None) -> Usage | None:
    """Normalize Anthropic's disjoint input classes into total input tokens."""
    if not raw_usage:
        return None
    ordinary = int(raw_usage.get("input_tokens") or 0)
    cache_read = int(raw_usage.get("cache_read_input_tokens") or 0)
    cache_write = int(raw_usage.get("cache_creation_input_tokens") or 0)
    output = int(raw_usage.get("output_tokens") or 0)
    prompt = ordinary + cache_read + cache_write
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=output,
        total_tokens=prompt + output,
        cached_tokens=cache_read or None,
        cache_write_tokens=cache_write or None,
    )


def _stream_chunk(
    *,
    chunk_id: str,
    model: str,
    delta: ChatCompletionDelta,
    usage: Usage | None = None,
    finish_reason: str | None = None,
) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id=chunk_id,
        created=int(time.time()),
        model=model,
        choices=[
            ChatCompletionChunkChoice(index=0, delta=delta, finish_reason=finish_reason)
        ],
        usage=usage,
    )


class AnthropicProvider(LLMProviderBase):
    """Anthropic Messages API provider.

    Also serves third-party endpoints that speak Anthropic Messages — the
    registry points MiniMax at this handler with its own host and
    credential — so *base_url* and the bound provider ID are both
    parameters rather than constants.
    """

    default_provider_id = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | SecretStr,
        model: str,
        base_url: str = ANTHROPIC_API_BASE,
        headers: dict[str, str] | None = None,
        use_api_key_header: bool = True,
        beta: bool = False,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        timeout: float | httpx.Timeout | None = 120,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )
        resolved_key = _resolve_secret(api_key)
        if not resolved_key:
            raise ValueError("Anthropic API key is required. Set ANTHROPIC_API_KEY.")
        self.api_key = resolved_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.headers = _headers(
            resolved_key, headers, use_api_key_header=use_api_key_header
        )
        self._messages_path = "/v1/messages?beta=true" if beta else "/v1/messages"
        self._timeout = timeout

    def _payload(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        # Strip empty content blocks that Anthropic rejects with 400.
        messages = strip_empty_parts_anthropic(messages)
        # Replace images for non-vision models.
        messages = reject_images_for_non_vision(messages, self.model)
        system, anthropic_messages = _split_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": int(kwargs.pop("max_tokens", 4096) or 4096),
        }
        cache_control = kwargs.pop("cache_control", {"type": "ephemeral"})
        cache_boundary = kwargs.pop("cache_boundary", None)
        if system:
            payload["system"] = _system_blocks(system, cache_control, cache_boundary)
        anthropic_tools = _anthropic_tools(tools)
        if anthropic_tools:
            if cache_control:
                anthropic_tools[-1] = _mark_cache_control(
                    anthropic_tools[-1], cache_control
                )
            payload["tools"] = anthropic_tools
        if cache_control and anthropic_messages:
            _mark_last_message_cache_control(anthropic_messages[-1], cache_control)
        thinking = _apply_thinking(
            self.model,
            kwargs,
            payload,
            provider_id=self.provider_name or "anthropic",
        )
        _add_sampling(self.model, kwargs, payload, thinking=thinking)
        payload.update(self._service_tier(kwargs)[0])
        return payload

    def _service_tier(
        self, kwargs: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Body and headers selecting an alternate service tier.

        Anthropic's fast mode needs both: a ``speed`` field and a beta
        header. Both come from the tier's catalog patch, so neither is
        spelled out here.
        """
        from app.agent.providers.options import service_tier_fields

        return service_tier_fields(
            self.provider_name or "anthropic",
            self.model,
            kwargs.get("service_tier"),
        )

    def _request_headers(self, merged: dict[str, Any]) -> dict[str, str]:
        """Per-call headers. A tier's beta flag cannot live on the shared dict."""
        from app.agent.providers.options import provider_request_headers

        extra = provider_request_headers(self.provider_name or "anthropic")
        extra.update(self._service_tier(merged)[1])
        return {**self.headers, **extra} if extra else self.headers

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AssistantMessage:
        merged = self._merged_kwargs(**kwargs)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self.base_url}{self._messages_path}",
                headers=self._request_headers(merged),
                json=self._payload(messages, tools, merged),
            )
            response.raise_for_status()
        return self._parse_response(response.json())

    def _parse_response(self, data: dict[str, Any]) -> AssistantMessage:
        content_blocks = data.get("content", [])
        text = "".join(
            block.get("text", "")
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        reasoning = "".join(
            block.get("thinking", "")
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "thinking"
        )
        tool_calls = []
        for block in content_blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_calls.append(
                ToolCall(
                    id=str(block.get("id", "")),
                    function=FunctionCall(
                        name=str(block.get("name", "")),
                        arguments=json.dumps(block.get("input") or {}),
                    ),
                )
            )
        usage = _usage_from_anthropic(data.get("usage"))
        return AssistantMessage(
            content=text or None,
            reasoning_content=reasoning or None,
            tool_calls=tool_calls or None,
            extra=(
                {"usage": usage_to_dict(usage, self.qualified_model_id())}
                if usage is not None
                else None
            ),
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatCompletionChunk]:
        merged = self._merged_kwargs(**kwargs)
        payload = self._payload(messages, tools, merged)
        payload["stream"] = True
        chunk_id = f"anthropic-{int(time.time())}"
        usage = Usage()
        tool_call_indexes: dict[int, int] = {}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}{self._messages_path}",
                headers=self._request_headers(merged),
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line.removeprefix("data: ")
                    if raw == "[DONE]":
                        break
                    event = json.loads(raw)
                    event_type = event.get("type") if isinstance(event, dict) else ""
                    if event_type == "message_start":
                        raw_usage = event.get("message", {}).get("usage", {})
                        if isinstance(raw_usage, dict):
                            normalized = _usage_from_anthropic(raw_usage)
                            if normalized is not None:
                                usage = normalized
                    elif event_type == "content_block_start":
                        content_block = event.get("content_block", {})
                        if (
                            not isinstance(content_block, dict)
                            or content_block.get("type") != "tool_use"
                        ):
                            continue
                        raw_index = event.get("index")
                        block_index = (
                            int(raw_index) if isinstance(raw_index, int) else 0
                        )
                        tool_index = tool_call_indexes.setdefault(
                            block_index, len(tool_call_indexes)
                        )
                        yield _stream_chunk(
                            chunk_id=chunk_id,
                            model=self.model,
                            delta=ChatCompletionDelta(
                                tool_calls=[
                                    ToolCallDelta(
                                        index=tool_index,
                                        id=str(content_block.get("id") or ""),
                                        function=FunctionCallDelta(
                                            name=str(content_block.get("name") or ""),
                                            arguments="",
                                        ),
                                    )
                                ]
                            ),
                        )
                    elif event_type == "message_delta":
                        delta = event.get("delta", {})
                        stop_reason = (
                            delta.get("stop_reason")
                            if isinstance(delta, dict)
                            else None
                        )
                        raw_usage = event.get("usage", {})
                        if isinstance(raw_usage, dict):
                            usage.completion_tokens = int(
                                raw_usage.get("output_tokens") or 0
                            )
                            usage.total_tokens = (
                                usage.prompt_tokens + usage.completion_tokens
                            )
                        yield _stream_chunk(
                            chunk_id=chunk_id,
                            model=self.model,
                            delta=ChatCompletionDelta(),
                            usage=usage,
                            finish_reason=_finish_reason(stop_reason),
                        )
                    else:
                        delta = event.get("delta") if isinstance(event, dict) else None
                        if not isinstance(delta, dict):
                            continue
                        delta_type = delta.get("type")
                        if isinstance(delta.get("thinking"), str):
                            yield _stream_chunk(
                                chunk_id=chunk_id,
                                model=self.model,
                                delta=ChatCompletionDelta(
                                    reasoning_content=delta["thinking"]
                                ),
                            )
                        elif isinstance(delta.get("text"), str):
                            yield _stream_chunk(
                                chunk_id=chunk_id,
                                model=self.model,
                                delta=ChatCompletionDelta(content=delta["text"]),
                            )
                        elif delta_type == "input_json_delta" and isinstance(
                            delta.get("partial_json"), str
                        ):
                            raw_index = event.get("index")
                            block_index = (
                                int(raw_index) if isinstance(raw_index, int) else 0
                            )
                            tool_index = tool_call_indexes.setdefault(
                                block_index, len(tool_call_indexes)
                            )
                            yield _stream_chunk(
                                chunk_id=chunk_id,
                                model=self.model,
                                delta=ChatCompletionDelta(
                                    tool_calls=[
                                        ToolCallDelta(
                                            index=tool_index,
                                            function=FunctionCallDelta(
                                                arguments=delta["partial_json"]
                                            ),
                                        )
                                    ]
                                ),
                            )
