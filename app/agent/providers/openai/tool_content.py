"""Provider-specific tool content flattening.

MiMo, GLM-5.2, and Xiaomi models reject tool role messages where
``content`` is a ``ContentPart[]`` array. They require a plain string.
This module provides a shared transform that flattens all array-format
tool content to strings for affected providers, including:

- Single text part → extracted text string
- Single image part → placeholder string (e.g. "[image data]" or "[image: <url>]")
- Multiple parts (text + images) → combined string with newline separators
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


def _flatten_content_parts_to_string(parts: list[Any]) -> str:
    """Convert a content parts array to a plain string representation.

    Handles text parts, image_url parts (both URL and base64 data), and
    mixed content. For images, extracts the URL or provides a placeholder
    since providers like MiMo only accept plain string tool content.
    """
    text_parts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            text_parts.append(part.get("text", ""))
        elif part_type == "image_url":
            img = part.get("image_url", {})
            url = img.get("url", "") if isinstance(img, dict) else str(img)
            # For base64 data URLs, include a note (too large for string content)
            if url.startswith("data:"):
                text_parts.append("[image data]")
            elif url:
                text_parts.append(f"[image: {url}]")
    return "\n".join(text_parts) if text_parts else ""


def flatten_tool_content_for_provider(
    messages: list[Any],
    model_id: str,
) -> list[Any]:
    """Flatten tool ``content`` arrays to plain strings.

    For providers that reject ``content: [{"type": "text", ...}]`` or
    ``content: [{"type": "image_url", ...}]`` (e.g. MiMo, GLM), this
    converts all array-format tool messages to plain strings.

    - Single text part → the text string directly
    - Single image part → "[image data]" or "[image: <url>]"
    - Multiple parts → combined text with newlines, images as placeholders

    Works with any message type that has ``role``, ``content``,
    ``tool_call_id``, and ``name`` attributes (OpenAIMessage, XiaomiMessage).
    """
    if not should_flatten_tool_content(model_id):
        return messages

    result: list[Any] = []
    for msg in messages:
        if getattr(msg, "role", None) == "tool" and isinstance(
            getattr(msg, "content", None), list
        ):
            # Single text part: extract text directly (fast path)
            if len(msg.content) == 1:
                part = msg.content[0]
                if isinstance(part, dict) and part.get("type") == "text":
                    result.append(msg.model_copy(update={"content": part["text"]}))
                    continue
            # All other cases: flatten to string representation
            flat = _flatten_content_parts_to_string(msg.content)
            result.append(msg.model_copy(update={"content": flat}))
            continue
        result.append(msg)
    return result
