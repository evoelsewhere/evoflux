"""OpenAI Chat Completions API handler (/v1/chat/completions)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator

import httpx
from loguru import logger

from app.agent.usage import usage_to_dict
from app.agent.providers.streaming import iter_sse_data
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

from .schemas import (
    OpenAIChatRequest,
    OpenAIChatResponse,
    OpenAIFunction,
    OpenAIFunctionCall,
    OpenAIMessage,
    OpenAIStreamChunk,
    OpenAIStreamOptions,
    OpenAITool,
    OpenAIToolCall,
)
from .sanitization import sanitize_openai_tool_pairs
from .tool_content import flatten_tool_content_for_provider
from app.agent.providers.registry import Transport
from app.agent.providers.transform import apply_model_sampling_defaults

if TYPE_CHECKING:
    pass


def _positive_token_count(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else None
    )


#: Tier values that mean "serve this the normal way".
_NO_SERVICE_TIER = frozenset({"", "auto", "default", "none", "off", "standard"})


class CompletionsHandler:
    """Handles all interaction with /v1/chat/completions."""

    # OpenAI's reasoning-capable models (o-series, gpt-5*, gpt-5.4*) reject
    # the legacy ``max_tokens`` field — they require ``max_completion_tokens``.
    # The Chat Completions API accepts ``max_completion_tokens`` on every
    # current OpenAI model (including legacy gpt-4o/gpt-3.5), so we default
    # to the new field for the native OpenAI provider.
    #
    # OpenAI-compatible endpoints that still require the legacy field
    # (xAI Grok, Deepseek as of 2026-Q2) flip this to ``False`` in their
    # provider subclass — see ``providers/xai`` and ``providers/deepseek``.
    #
    # Class-level flag rather than per-instance so subclassing remains
    # the single override point; callers don't toggle field names ad-hoc.
    uses_max_completion_tokens: bool = True

    #: Registry ID this handler subclass serves, when it serves exactly one.
    #:
    #: A handler subclass exists precisely because its endpoint diverges, so
    #: it knows its own identity. Declaring it here means a handler built
    #: directly — in a test, or by a provider constructed outside the
    #: factory — still resolves the right reasoning dialect. The factory
    #: overwrites ``provider_id`` with the ID the user actually chose, which
    #: is what one handler serving two registry entries needs.
    default_provider_id: str | None = None

    def __init__(self, model: str, base_url: str, headers: dict[str, str]) -> None:
        self.model = model
        self.usage_model_id = model
        self.base_url = base_url
        self.headers = headers
        # Bound by ``LLMProviderBase.bind_provider_name`` once the factory
        # knows which registry entry produced this handler. Reasoning
        # translation needs it: the same model ID means different wire
        # fields behind OpenRouter than behind its first-party vendor.
        self.provider_id: str | None = type(self).default_provider_id

    @property
    def qualified_model(self) -> str:
        """``"provider:model"`` when the provider is known, else the model."""
        if self.provider_id and ":" not in self.model:
            return f"{self.provider_id}:{self.model}"
        return self.model

    # ------------------------------------------------------------------
    # Message / tool conversion
    # ------------------------------------------------------------------

    def convert_messages(self, messages: list[ChatMessage]) -> list[OpenAIMessage]:
        result: list[OpenAIMessage] = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append(OpenAIMessage(role="system", content=msg.content))

            elif isinstance(msg, HumanMessage):
                if msg.parts:
                    oai_parts: list[dict] = []
                    for part in msg.parts:
                        if isinstance(part, TextBlock):
                            oai_parts.append({"type": "text", "text": part.text})
                        elif isinstance(part, ImageUrlBlock):
                            img_url: dict = {"url": part.url}
                            if part.detail:
                                img_url["detail"] = part.detail
                            oai_parts.append(
                                {"type": "image_url", "image_url": img_url}
                            )
                        elif isinstance(part, ImageDataBlock):
                            data_url = f"data:{part.media_type};base64,{part.data}"
                            oai_parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": data_url, "detail": "auto"},
                                }
                            )
                    result.append(OpenAIMessage(role="user", content=oai_parts))
                else:
                    result.append(OpenAIMessage(role="user", content=msg.content))

            elif isinstance(msg, AssistantMessage):
                openai_tool_calls = None
                if msg.tool_calls:
                    openai_tool_calls = [
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
                # Some providers (e.g. Xiaomi mimo) reject assistant turns
                # with neither content nor tool_calls (HTTP 400).
                if not msg.content and not openai_tool_calls:
                    continue
                result.append(
                    OpenAIMessage(
                        role="assistant",
                        content=msg.content,
                        tool_calls=openai_tool_calls,
                    )
                )

            elif isinstance(msg, ToolMessage):
                if msg.parts:
                    oai_parts = []
                    for part in msg.parts:
                        if isinstance(part, TextBlock):
                            oai_parts.append({"type": "text", "text": part.text})
                        elif isinstance(part, ImageUrlBlock):
                            img_url = {"url": part.url}
                            if part.detail:
                                img_url["detail"] = part.detail
                            oai_parts.append(
                                {"type": "image_url", "image_url": img_url}
                            )
                        elif isinstance(part, ImageDataBlock):
                            data_url = f"data:{part.media_type};base64,{part.data}"
                            oai_parts.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": data_url, "detail": "auto"},
                                }
                            )
                    result.append(
                        OpenAIMessage(
                            role="tool",
                            content=oai_parts,
                            tool_call_id=msg.tool_call_id,
                            name=msg.name,
                        )
                    )
                else:
                    result.append(
                        OpenAIMessage(
                            role="tool",
                            content=msg.content,
                            tool_call_id=msg.tool_call_id,
                            name=msg.name,
                        )
                    )
        return result

    def convert_tools(
        self, tools: list[dict[str, Any]] | None
    ) -> list[OpenAITool] | None:
        if not tools:
            return None
        result = []
        for t in tools:
            if t.get("type") == "function":
                f = t["function"]
                result.append(
                    OpenAITool(
                        function=OpenAIFunction(
                            name=f["name"],
                            description=f.get("description", ""),
                            parameters=f.get("parameters"),
                        )
                    )
                )
        return result or None

    # ------------------------------------------------------------------
    # Request builder
    # ------------------------------------------------------------------

    def build_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        # Route the caller's ``max_tokens`` to whichever field name the
        # downstream API expects.  Callers up the stack use the canonical
        # ``max_tokens`` name (defined on ``LLMProviderBase.chat``); the
        # handler is the *only* layer that knows whether the wire field
        # should be ``max_tokens`` (legacy) or ``max_completion_tokens``
        # (reasoning-capable OpenAI models — see class docstring).
        max_tokens_value = merged.get("max_tokens")
        req = OpenAIChatRequest(
            model=self.model,
            messages=flatten_tool_content_for_provider(
                self.convert_messages(sanitize_openai_tool_pairs(messages)),
                self.model,
            ),
            tools=self.convert_tools(tools),
            temperature=merged.get("temperature"),
            top_p=merged.get("top_p"),
            max_tokens=(
                max_tokens_value if not self.uses_max_completion_tokens else None
            ),
            max_completion_tokens=(
                max_tokens_value if self.uses_max_completion_tokens else None
            ),
            stream=stream,
            stream_options=OpenAIStreamOptions(include_usage=True) if stream else None,
        )
        body = req.model_dump(exclude_none=True)
        if merged.get("prompt_cache_key") is not None:
            body["prompt_cache_key"] = merged["prompt_cache_key"]
        self.customize_thinking(merged, body)
        body.update(self._service_tier_body(merged))
        # Apply per-model sampling defaults (temperature/topP/topK).
        apply_model_sampling_defaults(
            body,
            self.model,
            explicitly_set={k for k in ("temperature", "top_p", "top_k") if k in body},
        )
        return body

    def customize_thinking(self, merged: dict[str, Any], body: dict[str, Any]) -> None:
        """Apply provider-specific reasoning/thinking translation.

        Delegates to :func:`app.agent.providers.thinking.thinking_request_fields`,
        which resolves the caller's ``thinking_level`` against what the
        catalog says this model accepts and emits the wire fields for this
        provider's dialect. That covers ``reasoning_effort``, OpenRouter's
        ``reasoning`` object, DeepSeek's thinking toggle, GLM's
        ``clear_thinking``, DashScope's ``enable_thinking`` and MiMo's token
        budget without a subclass per provider.

        Subclasses still override when the endpoint needs something the
        dialect table cannot express — a per-model allowlist, or a level
        vocabulary of its own.

        Mutates ``body`` in place.
        """
        from app.agent.providers.thinking import thinking_request_fields

        if not self.provider_id:
            # No registry identity (a bare handler in a test, or a provider
            # built outside the factory). Fall back to the OpenAI-shaped
            # default rather than guessing a dialect.
            level = merged.get("thinking_level")
            if level and level not in ("none", "off"):
                body["reasoning_effort"] = level
            return

        body.update(
            thinking_request_fields(
                self.provider_id,
                self.model,
                merged.get("thinking_level"),
                transport=Transport.OPENAI_COMPLETIONS,
            )
        )

    def _service_tier_body(self, merged: dict[str, Any]) -> dict[str, Any]:
        """Body fields selecting an alternate service tier.

        A tier the catalog (or the provider table) describes is applied from
        its own patch. Anything else the caller names is forwarded verbatim
        as ``service_tier``, because that is a real field on this endpoint —
        OpenAI documents ``flex`` and ``priority`` alongside the tiers a
        model advertises, and dropping an explicit one would silently ignore
        the caller.
        """
        tier = merged.get("service_tier")
        if not isinstance(tier, str) or not tier.strip():
            return {}
        if self.provider_id:
            from app.agent.providers.options import service_tier_fields

            body, _headers = service_tier_fields(self.provider_id, self.model, tier)
            if body:
                return body
        normalized = tier.strip().lower()
        if normalized in _NO_SERVICE_TIER:
            return {}
        return {"service_tier": normalized}

    def _service_tier_headers(self, merged: dict[str, Any]) -> dict[str, str]:
        """Headers selecting an alternate service tier, if one was asked for."""
        if not self.provider_id:
            return {}
        from app.agent.providers.options import service_tier_fields

        _body, headers = service_tier_fields(
            self.provider_id, self.model, merged.get("service_tier")
        )
        return headers

    def _request_headers(self, merged: dict[str, Any]) -> dict[str, str]:
        """Return per-call headers without mutating the shared handler state."""
        extra = self._provider_headers()
        extra.update(self._service_tier_headers(merged))
        return {**self.headers, **extra} if extra else self.headers

    def _provider_headers(self) -> dict[str, str]:
        """Static headers this provider always needs — gateway attribution."""
        if not self.provider_id:
            return {}
        from app.agent.providers.options import provider_request_headers

        return provider_request_headers(self.provider_id)

    # ------------------------------------------------------------------
    # Response parsing — non-streaming
    # ------------------------------------------------------------------

    def normalize_response_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize a provider-specific non-streaming response envelope.

        The native OpenAI wire format is already flat, so the default is an
        identity transform. Compatible gateways can override this hook without
        duplicating the HTTP and canonical-message conversion code.
        """
        return data

    def normalize_stream_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize one provider-specific SSE JSON payload."""
        return data

    def parse_response(self, data: dict) -> AssistantMessage:
        data = self.normalize_response_payload(data)
        parsed = OpenAIChatResponse.model_validate(data)
        if not parsed.choices:
            return AssistantMessage(content=None)

        msg = parsed.choices[0].message
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        function=FunctionCall(
                            name=tc.function.name,
                            arguments=tc.function.arguments,
                        ),
                    )
                )
        usage_dict = None
        if parsed.usage is not None:
            usage_dict = usage_to_dict(
                self._usage_from_openai(parsed.usage), self.usage_model_id
            )
        return AssistantMessage(
            content=msg.content or None,
            reasoning_content=msg.reasoning_content or None,
            tool_calls=tool_calls if tool_calls else None,
            extra={"usage": usage_dict} if usage_dict is not None else None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        merged: dict[str, Any],
    ) -> AssistantMessage:
        body = self.build_request(messages, tools, stream=False, merged=merged)
        url = f"{self.base_url}/chat/completions"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, headers=self._request_headers(merged), json=body, timeout=120.0
            )
            if response.status_code >= 400:
                logger.error(
                    "openai_chat_error status={} body={}",
                    response.status_code,
                    response.text[:500],
                )
            response.raise_for_status()
            return self.parse_response(response.json())

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        merged: dict[str, Any],
    ) -> AsyncIterator[ChatCompletionChunk]:
        body = self.build_request(messages, tools, stream=True, merged=merged)
        url = f"{self.base_url}/chat/completions"

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                url,
                headers=self._request_headers(merged),
                json=body,
                timeout=120.0,
            ) as response:
                if response.status_code >= 400:
                    err_body = await response.aread()
                    logger.error(
                        "openai_stream_error status={} body={}",
                        response.status_code,
                        err_body[:500],
                    )
                    response.raise_for_status()

                async for data in iter_sse_data(response, sentinel="[DONE]"):
                    data = self.normalize_stream_payload(data)
                    chunk = OpenAIStreamChunk.model_validate(data)

                    if not chunk.choices:
                        if chunk.usage:
                            yield self._usage_chunk(chunk)
                        continue

                    choice = chunk.choices[0]
                    delta = choice.delta

                    delta_tool_calls: list[ToolCallDelta] = []
                    for tc in delta.tool_calls or []:
                        delta_tool_calls.append(
                            ToolCallDelta(
                                index=tc.index,
                                id=tc.id,
                                function=FunctionCallDelta(
                                    name=tc.function.name if tc.function else None,
                                    arguments=tc.function.arguments
                                    if tc.function
                                    else None,
                                ),
                            )
                        )

                    usage = (
                        self._usage_from_openai(chunk.usage) if chunk.usage else None
                    )

                    yield ChatCompletionChunk(
                        id=chunk.id,
                        created=chunk.created,
                        model=chunk.model,
                        choices=[
                            ChatCompletionChunkChoice(
                                index=choice.index or 0,
                                delta=ChatCompletionDelta(
                                    content=delta.content,
                                    reasoning_content=delta.reasoning_content
                                    or delta.reasoning_text,
                                    tool_calls=delta_tool_calls or None,
                                ),
                                finish_reason=choice.finish_reason,
                            )
                        ],
                        usage=usage,
                    )

    # ------------------------------------------------------------------
    # Usage helpers
    # ------------------------------------------------------------------

    def _usage_from_openai(self, u: Any) -> Usage:
        cached = None
        cache_write = None
        if u.prompt_tokens_details:
            cached = _positive_token_count(u.prompt_tokens_details.cached_tokens)
            cache_write = _positive_token_count(
                u.prompt_tokens_details.cache_write_tokens
            ) or _positive_token_count(
                u.prompt_tokens_details.cache_creation_input_tokens
            )
        if cached is None:
            cached = _positive_token_count(getattr(u, "prompt_cache_hit_tokens", None))
        thoughts = None
        if u.completion_tokens_details:
            thoughts = _positive_token_count(
                u.completion_tokens_details.reasoning_tokens
            )
        return Usage(
            prompt_tokens=u.prompt_tokens,
            completion_tokens=u.completion_tokens,
            total_tokens=u.total_tokens,
            cached_tokens=cached,
            cache_write_tokens=cache_write,
            thoughts_tokens=thoughts,
        )

    def _usage_chunk(self, chunk: OpenAIStreamChunk) -> ChatCompletionChunk:
        return ChatCompletionChunk(
            id=chunk.id,
            created=chunk.created,
            model=chunk.model,
            choices=[],
            usage=self._usage_from_openai(chunk.usage),
        )
