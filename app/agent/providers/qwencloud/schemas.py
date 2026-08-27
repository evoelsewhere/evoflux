"""QwenCloud Chat Completions request schemas.

QwenCloud is OpenAI-compatible, but thinking-mode conversation history adds
``reasoning_content`` to assistant messages. Qwen's function-calling guide
requires callers to send that field back on subsequent requests.

Reference: https://docs.qwencloud.com/api-reference/chat/openai-chat
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from app.agent.providers.openai.schemas import (
    OpenAIStreamOptions,
    OpenAITool,
    OpenAIToolCall,
)


class QwenCloudMessage(BaseModel):
    """One OpenAI-compatible QwenCloud conversation message."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[OpenAIToolCall] | None = None
    reasoning_content: str | None = None
    tool_call_id: str | None = None
    name: str | None = None


class QwenCloudChatRequest(BaseModel):
    """QwenCloud ``/chat/completions`` request body."""

    model: str
    messages: list[QwenCloudMessage]
    tools: list[OpenAITool] | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    preserve_thinking: bool | None = None
    stream: bool = False
    stream_options: OpenAIStreamOptions | None = None
