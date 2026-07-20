"""Provider-specific tool content flattening.

MiMo, GLM-5.2, and Xiaomi models reject tool role messages where
``content`` is a ``ContentPart[]`` array. They require a plain string.
This module provides a shared transform that flattens single-part
tool results to strings for affected providers.
"""

from __future__ import annotations

from typing import Any

# Predicates that identify providers requiring plain-string tool content.
FLATTEN_TOOL_CONTENT_PROVIDERS: tuple = (
    lambda model_id: "mimo" in model_id.lower(),
    lambda model_id: "glm" in model_id.lower(),
    lambda model_id: "xiaomi" in model_id.lower(),
)


def should_flatten_tool_content(model_id: str) -> bool:
    """Return True if *model_id* belongs to a provider that rejects array tool content."""
    return any(pred(model_id) for pred in FLATTEN_TOOL_CONTENT_PROVIDERS)


def flatten_tool_content_for_provider(
    messages: list[Any],
    model_id: str,
) -> list[Any]:
    """Flatten single-part tool ``content`` arrays to plain strings.

    For providers that reject ``content: [{"type": "text", ...}]``, this
    converts single-text-part tool messages to ``content: "..."``.
    Multi-part tool content is left as-is (providers that reject arrays
    will error on it, preserving the signal).

    Works with any message type that has ``role``, ``content``,
    ``tool_call_id``, and ``name`` attributes (OpenAIMessage, XiaomiMessage).
    """
    if not should_flatten_tool_content(model_id):
        return messages

    result: list[Any] = []
    for msg in messages:
        if (
            getattr(msg, "role", None) == "tool"
            and isinstance(getattr(msg, "content", None), list)
            and len(msg.content) == 1
        ):
            part = msg.content[0]
            if isinstance(part, dict) and part.get("type") == "text":
                result.append(msg.model_copy(update={"content": part["text"]}))
                continue
        result.append(msg)
    return result
