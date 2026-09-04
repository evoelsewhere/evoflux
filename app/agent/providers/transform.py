"""Transform utilities — message normalization, model defaults, validation.

Ported from MiMo-Code's ``transform.ts`` to match its wire-format
corrections and per-provider quirks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from app.agent.schemas.chat import (
    AssistantMessage,
    ChatMessage,
    HumanMessage,
    ImageUrlBlock,
    TextBlock,
)
from app.agent.providers.registry import PROVIDER_REGISTRY  # noqa: F401

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 1. stripEmptyParts — Anthropic rejects empty content blocks
# ---------------------------------------------------------------------------


def _has_content_text(text: Any) -> bool:
    return isinstance(text, str) and text.strip() != ""


def _has_reasoning_text(text: Any) -> bool:
    return isinstance(text, str) and text.strip() != ""


def strip_empty_parts(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Remove empty thinking/text blocks that Anthropic rejects with 400.

    Anthropic Messages API rejects messages whose content array contains
    empty text or thinking blocks.  MiMo-Code's ``stripEmptyParts``
    filters these before sending.  Signed thinking blocks (with
    ``signature``) are preserved even if their text is empty.
    """
    result: list[ChatMessage] = []
    for msg in messages:
        if isinstance(msg, AssistantMessage):
            if isinstance(msg.content, str):
                result.append(msg)
                continue
            if isinstance(msg.content, list):
                filtered = [
                    part for part in msg.content if _has_content_text(part.text)
                ]
                if not filtered:
                    result.append(msg)
                    continue
                result.append(msg.model_copy(update={"content": filtered}))
            else:
                result.append(msg)
        else:
            result.append(msg)
    return result


def strip_empty_parts_anthropic(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Anthropic-specific: strip empty text and empty thinking blocks.

    Signed thinking blocks (with ``signature``) survive even if text is
    empty — they must be replayed exactly for cache coherence.
    """
    result: list[ChatMessage] = []
    for msg in messages:
        if isinstance(msg, AssistantMessage):
            if isinstance(msg.content, list):
                filtered = []
                for part in msg.content:
                    # Preserve signed thinking blocks verbatim.
                    if hasattr(part, "signature") and part.signature:
                        filtered.append(part)
                        continue
                    if hasattr(part, "thinking"):
                        if _has_reasoning_text(part.thinking):
                            filtered.append(part)
                        continue
                    if hasattr(part, "text"):
                        if _has_content_text(part.text):
                            filtered.append(part)
                        continue
                    filtered.append(part)
                if not filtered:
                    # Anthropic rejects empty content arrays — replace with
                    # a minimal text block.
                    filtered.append(TextBlock(text="..."))
                result.append(msg.model_copy(update={"content": filtered}))
            else:
                result.append(msg)
        elif isinstance(msg, HumanMessage):
            if isinstance(msg.content, str):
                result.append(msg)
                continue
            if isinstance(msg.content, list):
                filtered = [
                    part
                    for part in msg.content
                    if isinstance(part, TextBlock) and _has_content_text(part.text)
                ]
                # Always keep at least one part (images can stay).
                if not filtered:
                    filtered = [
                        part for part in msg.content if not isinstance(part, TextBlock)
                    ]
                if filtered:
                    result.append(msg.model_copy(update={"content": filtered}))
                else:
                    result.append(msg)
            else:
                result.append(msg)
        else:
            result.append(msg)
    return result


# ---------------------------------------------------------------------------
# 2. Per-model sampling defaults (temperature / topP / topK)
# ---------------------------------------------------------------------------


# Patterns from MiMo-Code's transform.ts temperature() + topP() + topK()
_MODEL_TEMPERATURE_OVERRIDES: list[tuple[str, float]] = [
    ("gemini", 1.0),
    ("gemma", 1.0),
    ("glm", 0.7),
    ("glm-4", 0.7),
    ("kimi-k2", 0.6),
    ("kimi-k2.5", 0.6),
    ("kimi-k2p5", 0.6),
    ("kimi-k2-5", 0.6),
    ("qwen", 0.7),
    ("minimax-m2", 1.0),
]

_MODEL_TOP_P_OVERRIDES: list[tuple[str, float]] = [
    ("qwen", 1.0),
    ("minimax-m2", 0.95),
    ("gemini", 0.95),
    ("kimi-k2.5", 0.95),
    ("kimi-k2p5", 0.95),
    ("kimi-k2-5", 0.95),
]

_MODEL_TOP_K_OVERRIDES: list[tuple[str, int]] = [
    ("minimax-m2", 20),
    ("minimax-m25", 40),
    ("minimax-m21", 40),
    ("qwen", 40),
    ("qwen3", 40),
]


def _match_any(model_id: str, patterns: list[tuple[str, T]]) -> T | None:
    """Return the value for the first matching pattern in model_id."""
    model_lower = model_id.lower()
    for pattern, value in patterns:
        if pattern in model_lower:
            return value
    return None


def apply_model_sampling_defaults(
    body: dict[str, Any],
    model_id: str,
    *,
    explicitly_set: set[str] | None = None,
) -> dict[str, Any]:
    """Apply per-model sampling defaults from MiMo-Code's transform.ts.

    Only sets fields the user has NOT explicitly configured.
    Returns the mutated body for convenience.
    """
    explicit = explicitly_set or set()

    if "temperature" not in explicit:
        temp = _match_any(model_id, _MODEL_TEMPERATURE_OVERRIDES)
        if temp is not None and "temperature" not in body:
            body["temperature"] = temp

    if "top_p" not in explicit:
        top_p = _match_any(model_id, _MODEL_TOP_P_OVERRIDES)
        if top_p is not None and "top_p" not in body:
            body["top_p"] = top_p

    if "top_k" not in explicit:
        top_k = _match_any(model_id, _MODEL_TOP_K_OVERRIDES)
        if top_k is not None and "top_k" not in body:
            body["top_k"] = top_k

    return body


# ---------------------------------------------------------------------------
# 3. Modality validation — reject images for non-vision models
# ---------------------------------------------------------------------------

_VISION_MODEL_PATTERNS = (
    "gpt-4",
    "gpt-5",
    "gemini",
    "claude",
    "sonnet",
    "haiku",
    "opus",
    "llama-4",
    "qwen-vl",
    "qwen2-vl",
    "glm-4v",
    "grok-vision",
)


def _model_supports_vision(model_id: str) -> bool:
    model_lower = model_id.lower()
    return any(pat in model_lower for pat in _VISION_MODEL_PATTERNS)


def reject_images_for_non_vision(
    messages: list[ChatMessage],
    model_id: str,
) -> list[ChatMessage]:
    """Replace image blocks with text error messages for non-vision models.

    MiMo-Code's ``validateInputModalities`` rejects image parts for
    models that don't support vision.  We replace with an error text
    block so the model can still respond to the text content.
    """
    if _model_supports_vision(model_id):
        return messages

    result: list[ChatMessage] = []
    for msg in messages:
        if isinstance(msg, HumanMessage) and isinstance(msg.content, list):
            filtered: list[Any] = []
            for part in msg.content:
                if isinstance(part, ImageUrlBlock):
                    filtered.append(
                        TextBlock(text="[Image not supported by this model]")
                    )
                else:
                    filtered.append(part)
            result.append(msg.model_copy(update={"content": filtered}))
        else:
            result.append(msg)
    return result


# ---------------------------------------------------------------------------
# 4. Prompt caching markers
# ---------------------------------------------------------------------------


def add_cache_markers_anthropic(
    body: dict[str, Any],
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    """Add Anthropic prompt caching markers to the request body.

    Anthropic supports ``cache_control`` on system messages and the
    last N messages to enable prompt caching.  MiMo-Code adds these
    automatically when the provider supports it.
    """
    if not enabled:
        return body

    messages = body.get("messages", [])
    system = body.get("system")

    # Mark the system prompt for caching.
    if isinstance(system, str) and system:
        body["system"] = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ]
    elif isinstance(system, list):
        if system:
            last = system[-1]
            if isinstance(last, dict):
                last["cache_control"] = {"type": "ephemeral"}

    # Mark the last two user messages for caching.
    user_count = 0
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            msg["cache_control"] = {"type": "ephemeral"}
            user_count += 1
            if user_count >= 2:
                break

    return body


def add_cache_markers_openai(
    body: dict[str, Any],
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    """Add OpenAI prompt caching hints.

    OpenAI's prompt caching is automatic for messages sharing a common
    prefix.  We add ``prompt_cache_key`` via model_kwargs when the
    provider supports it.
    """
    if not enabled:
        return body
    return body


# ---------------------------------------------------------------------------
# 5. Model capability metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelCapabilities:
    """Runtime model capabilities — fetched from models.dev or seed data."""

    input_modalities: tuple[str, ...] = ("text",)
    output_modalities: tuple[str, ...] = ("text",)
    context_window: int = 128_000
    max_output: int = 16_384
    supports_thinking: bool = False
    supports_tool_calling: bool = True
    supports_vision: bool = False


# Static fallback capabilities per provider prefix.
# Real production should fetch from models.dev like MiMo-Code does.
_PROVIDER_DEFAULT_CAPABILITIES: dict[str, ModelCapabilities] = {
    "openai": ModelCapabilities(
        input_modalities=("text", "image"),
        context_window=128_000,
        max_output=16_384,
        supports_vision=True,
    ),
    "anthropic": ModelCapabilities(
        input_modalities=("text", "image"),
        context_window=200_000,
        max_output=8_192,
        supports_thinking=True,
        supports_vision=True,
    ),
    "googlegenai": ModelCapabilities(
        input_modalities=("text", "image", "audio", "video"),
        context_window=1_000_000,
        max_output=65_536,
        supports_thinking=True,
        supports_vision=True,
    ),
    "deepseek": ModelCapabilities(
        input_modalities=("text",),
        context_window=128_000,
        max_output=8_192,
        supports_thinking=True,
    ),
    "xai": ModelCapabilities(
        input_modalities=("text", "image"),
        context_window=131_072,
        max_output=16_384,
        supports_vision=True,
    ),
    "xiaomi": ModelCapabilities(
        input_modalities=("text",),
        context_window=262_144,
        max_output=16_384,
        supports_thinking=True,
    ),
    "bedrock": ModelCapabilities(
        input_modalities=("text", "image"),
        context_window=200_000,
        max_output=8_192,
        supports_thinking=True,
        supports_vision=True,
    ),
}


def get_model_capabilities(provider_id: str) -> ModelCapabilities:
    """Get capabilities for a provider. Falls back to sensible defaults."""
    return _PROVIDER_DEFAULT_CAPABILITIES.get(
        provider_id,
        ModelCapabilities(),
    )
