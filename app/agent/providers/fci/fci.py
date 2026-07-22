"""FCI provider — FPT's OpenAI-compatible inference gateway.

Thin wrapper around ``ChatCompletionsOnlyProvider`` (chat-completions only,
never routed to OpenAI's ``/responses`` endpoint) that reads ``FCI_API_KEY``
and ``FCI_BASE_URL`` from settings or environment.

Unlike xAI/DeepSeek/Kimi, FCI has no fixed public host — it's an
organization-specific gateway, so there is no safe default base URL to fall
back to. ``FCI_BASE_URL`` (or the ``base_url`` constructor arg) is required;
a missing value raises immediately instead of silently hitting a relative
URL and failing with a confusing connection error.

Auth:   Bearer {FCI_API_KEY}
Token resolution order:
    1. ``Settings.FCI_API_KEY`` / ``Settings.FCI_BASE_URL`` (``.env`` or environment)
    2. ``FCI_API_KEY`` / ``FCI_BASE_URL`` environment variables

Supported models (as of the FPT catalog this was configured against):
    Qwen3.6-27B, GLM-5.1, GLM-5.2, gemma-4-31B-it, gemma-4-26B-A4B-it,
    gemma-3-27b-it, gpt-oss-20b, gpt-oss-120b, DeepSeek-V4-Flash,
    Qwen2.5-VL-7B-Instruct, Llama-3.3-70B-Instruct — see
    ``app/agent/providers/model_registry.json`` (key prefix ``fci:``) for
    per-model context length / cost / thinking-level metadata.

Usage::

    model: fci:gpt-oss-120b
    model: fci:deepseek-v4-flash
"""

from __future__ import annotations

from typing import Any

from pydantic.types import SecretStr

from app.agent.providers.openai import ChatCompletionsOnlyProvider


class FCIProvider(ChatCompletionsOnlyProvider):
    """FCI (FPT inference gateway) provider — OpenAI-compatible.

    Delegates entirely to ``ChatCompletionsOnlyProvider``; the only
    FCI-specific behavior is requiring a non-empty ``base_url`` (FCI has no
    public default endpoint, unlike xAI/DeepSeek).

    Args:
        api_key: FCI API key issued by FPT.
        model: Model name, e.g. ``"gpt-oss-120b"``, ``"deepseek-v4-flash"``.
        base_url: FCI gateway endpoint (org-specific — no default).
        temperature: Sampling temperature (0-2).
        top_p: Nucleus sampling probability mass cutoff.
        max_tokens: Hard cap on completion tokens.
        model_kwargs: Extra request body fields passed as-is.
    """

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        base_url: str,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if not base_url:
            raise ValueError(
                "FCI base URL is required. Set FCI_BASE_URL in your .env "
                "or environment to your FPT FCI gateway endpoint."
            )
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )
