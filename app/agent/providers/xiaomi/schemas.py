"""Xiaomi MiMo Chat Completions API request schemas.

MiMo is OpenAI-compatible but has one documented wire difference:

- Thinking mode is controlled by a ``thinking`` object, not OpenAI's
  ``reasoning_effort`` field.
- Assistant messages that contained tool calls in a thinking-mode turn
  MUST echo ``reasoning_content`` back; omitting it returns
  400 ``Param Incorrect`` on the *next* turn.

Reference:  https://mimo.mi.com/docs/en-US/api/chat/openai-api
Reported:   https://github.com/XiaomiMiMo/MiMo/issues/44
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.agent.providers.openai.schemas import (
    OpenAIStreamOptions,
    OpenAITool,
    OpenAIToolCall,
)


class XiaomiMessage(BaseModel):
    """A single message in the MiMo conversation history (request).

    Extends the OpenAI message shape with ``reasoning_content`` on the
    assistant role. MiMo requires this field to be present when an
    assistant turn contained tool calls and thinking mode was active —
    omitting it produces a 400 ``Param Incorrect`` on the next turn.
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = None
    # assistant role only
    tool_calls: list[OpenAIToolCall] | None = None
    # assistant role only — must be echoed back when tool_calls were present
    # during a thinking-mode turn (MiMo returns 400 on the next turn if omitted).
    reasoning_content: str | None = None
    # tool role only
    tool_call_id: str | None = None
    name: str | None = None


class XiaomiThinking(BaseModel):
    """Controls thinking mode with budget-based token allocation.

    MiMo-Code wire format supports:
      - ``type: "disabled"`` — turn off thinking entirely.
      - ``type: "enabled"``  — activate thinking with an optional
        ``budget_tokens`` cap that limits how many tokens the model
        may spend on its internal reasoning trace.

    When ``budget_tokens`` is ``None`` the server applies its own
    default.  EvoFlux maps the user-facing ``thinking_level`` string
    (off / low / medium / high) to a concrete budget here.
    """

    model_config = ConfigDict()

    type: Literal["enabled", "disabled"] = "enabled"
    budget_tokens: int | None = None


class XiaomiChatRequest(BaseModel):
    """MiMo /chat/completions request body.

    Mirrors ``OpenAIChatRequest`` but uses ``XiaomiMessage`` and carries
    the MiMo-specific ``thinking`` field in place of ``reasoning_effort``,
    which MiMo does not recognize.
    """

    model: str
    messages: list[XiaomiMessage]
    tools: list[OpenAITool] | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_completion_tokens: int | None = None
    stream: bool = False
    stream_options: OpenAIStreamOptions | None = None
    thinking: XiaomiThinking | None = None
