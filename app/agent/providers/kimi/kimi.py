"""Kimi Code provider — Moonshot's subscription coding API.

Kimi Code is not the general Kimi Platform API. Its OpenAI-compatible surface
is Chat Completions-only and lives at ``https://api.kimi.com/coding/v1``.

Official model contract (August 2026):

- ``k3`` / ``k3-256k`` accept ``reasoning_effort`` low, high, or max.
- ``kimi-for-coding`` variants keep thinking on and expose no effort control.
- Sampling parameters are fixed; sending temperature/top_p can be rejected.
"""

from __future__ import annotations

from typing import Any

from pydantic.types import SecretStr

from app.agent.providers.openai import ChatCompletionsOnlyProvider
from app.agent.providers.openai.completions import CompletionsHandler
from app.agent.schemas.chat import ChatMessage

KIMI_CODE_API_BASE = "https://api.kimi.com/coding/v1"
_LEGACY_KIMI_BASES = frozenset(
    {
        "https://api.kimi.ai/v1",
        "https://api.kimi.ai",
    }
)
_K3_MODELS = frozenset({"k3", "k3-256k"})


def normalize_kimi_code_base_url(base_url: str | None) -> str:
    """Migrate EvoFlux's former Kimi Platform default to Kimi Code."""
    value = (base_url or "").strip().rstrip("/") or KIMI_CODE_API_BASE
    if value.lower() in _LEGACY_KIMI_BASES:
        return KIMI_CODE_API_BASE
    return value


def _kimi_reasoning_effort(value: object) -> str | None:
    """Map common agent effort names to K3's exact accepted values."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"ultra", "xhigh", "max"}:
        return "max"
    if normalized in {"medium", "high"}:
        return "high"
    if normalized in {"minimum", "minimal", "light", "low"}:
        return "low"
    return None


class _KimiCodeCompletionsHandler(CompletionsHandler):
    """Apply Kimi Code's fixed-sampling and model-aware thinking contract."""

    def build_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        body = super().build_request(messages, tools, stream, merged)
        # Kimi Code models have fixed sampling requirements. The official
        # integration guide explicitly warns clients not to override these.
        body.pop("temperature", None)
        body.pop("top_p", None)
        # This Responses-era OpenAI extension is not documented on Kimi's
        # Chat Completions surface.
        body.pop("prompt_cache_key", None)
        return body

    def customize_thinking(self, merged: dict[str, Any], body: dict[str, Any]) -> None:
        if self.model.lower() not in _K3_MODELS:
            # K2.7 Code thinking is always on and has no effort selector.
            return

        requested = merged.get("thinking_level")
        if isinstance(requested, str) and requested.strip().lower() in {
            "none",
            "off",
        }:
            # Kimi documents this exact shape. EvoFlux does not advertise the
            # option because disabling thinking routes K3 to an older model,
            # but honour a deliberate low-level caller rather than silently
            # leaving high effort enabled.
            body["thinking"] = {"type": "disabled"}
            return

        effort = _kimi_reasoning_effort(requested)
        if effort is not None:
            body["reasoning_effort"] = effort


class KimiCodeProvider(ChatCompletionsOnlyProvider):
    """Provider for Kimi Code's OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        api_key: str | SecretStr,
        model: str,
        base_url: str = KIMI_CODE_API_BASE,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=normalize_kimi_code_base_url(base_url),
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )

    def _make_completions_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> CompletionsHandler:
        return _KimiCodeCompletionsHandler(model, base_url, headers)
