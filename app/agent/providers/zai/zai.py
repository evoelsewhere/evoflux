"""Z.ai provider — OpenAI-compatible Chat Completions endpoint.

Subclass of :class:`OpenAIProvider` that points at the Z.ai inference
endpoint and overrides only the reasoning-control translation:

* OpenAI exposes reasoning via the ``reasoning_effort`` top-level field.
* Z.ai exposes it via ``thinking: {"type": "enabled" | "disabled"}``;
  reasoning models default to enabled, and the only knob the agent
  surfaces is the *off* switch.

Endpoint:  https://api.z.ai/api/paas/v4
Auth:      Bearer {ZAI_API_KEY}
Docs:      https://docs.z.ai/

Token resolution order:
    1. ``Settings.ZAI_API_KEY`` (from ``.env`` or environment)
    2. ``ZAI_API_KEY`` environment variable
"""

from __future__ import annotations

from typing import Any

from pydantic.types import SecretStr

from app.agent.providers.openai import OpenAIProvider
from app.agent.providers.openai.completions import CompletionsHandler

ZAI_API_BASE = "https://api.z.ai/api/paas/v4"


class _ZAICompletionsHandler(CompletionsHandler):
    """Z.ai request shaping.

    Reasoning translation is inherited: Z.ai does not accept OpenAI's
    ``reasoning_effort`` and instead takes a ``thinking`` object, which is
    registered as the ``glm_thinking`` dialect in
    :mod:`app.agent.providers.thinking`. Nothing else about the GLM request
    diverges from Chat Completions, so this subclass exists only as the
    binding point for that dialect and for the endpoint override below.
    """

    default_provider_id = "zai"


class ZAIProvider(OpenAIProvider):
    """Z.ai provider (OpenAI-compatible Chat Completions).

    The same handler serves Zhipu AI's mainland endpoint
    (``open.bigmodel.cn``), which speaks the identical GLM contract at a
    different host — hence *base_url* being a parameter rather than a
    constant.

    Args:
        api_key: Z.ai API key.
        model: Model name (e.g. ``"glm-4.6"``).
        base_url: Endpoint to call. Defaults to Z.ai's international host.
        temperature: Sampling temperature (0-2).
        top_p: Nucleus sampling probability mass cutoff.
        max_tokens: Hard cap on completion tokens.
        model_kwargs: Extra request body fields. Notable keys:
            ``thinking_level`` (str) — ``"none"`` disables reasoning;
              other values are ignored (Z.ai uses model defaults).
    """

    default_provider_id = "zai"

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        base_url: str = ZAI_API_BASE,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url or ZAI_API_BASE,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )

    def _use_responses_for(self, model_kwargs: dict[str, Any]) -> bool:
        # Z.ai exposes only /chat/completions. Even with ``thinking_level``
        # set, never auto-route to /responses.
        return False

    def _make_completions_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> CompletionsHandler:
        return _ZAICompletionsHandler(model, base_url, headers)
