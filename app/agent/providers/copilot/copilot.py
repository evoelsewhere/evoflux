"""GitHub Copilot provider.

Subclass of :class:`OpenAIProvider` that delegates wire conversion,
streaming, and parsing to the canonical OpenAI handlers.

The Copilot gateway is OpenAI-compatible: messages, tools, and stream
events match the OpenAI Chat Completions and Responses formats. Only a
few facets differ:

* **Headers.** Copilot expects ``Openai-Intent``, ``x-initiator``, and a
  ``User-Agent`` alongside the OAuth bearer.
* **Per-model endpoint routing.** Some Copilot-hosted models accept only
  ``/chat/completions``; others accept only ``/responses``. The live
  ``/models`` contract is used instead of a model-name table.
* **Reasoning gating.** ``reasoning_effort`` is forwarded only when the
  resolved model profile advertises the selected effort.
* **Responses request body.** Copilot's gateway accepts ``temperature``
  and ``top_p`` on ``/responses`` (it ignores them); OpenAI's strict
  endpoint rejects them. The Copilot subclass adds them.

Token resolution order (preserved from the previous implementation):

1. Explicit ``github_token`` constructor arg.
2. ``{CACHE_DIR}/copilot_oauth.json`` (written by ``evoflux auth copilot``).
3. ``GITHUB_COPILOT_TOKEN`` env var.
"""

from __future__ import annotations

from typing import Any

from pydantic.types import SecretStr

from app.agent.providers.copilot.oauth import CopilotOAuth
from app.agent.providers.openai import OpenAIProvider
from app.agent.providers.openai.completions import CompletionsHandler
from app.agent.providers.openai.responses import ResponsesHandler
from app.agent.schemas.chat import AssistantMessage, ChatMessage, Usage

COPILOT_API_BASE = "https://api.githubcopilot.com"

_DEFAULT_HEADERS: dict[str, str] = {
    "Content-Type": "application/json",
    "User-Agent": "EvoFlux/1.0.0",
    "Openai-Intent": "conversation-edits",
    # Overridden per request by ``_copilot_request_headers``; kept here so a
    # code path that bypasses that hook still sends a valid value.
    "x-initiator": "user",
}


def _is_image_block(block: dict[str, Any]) -> bool:
    if block.get("type") == "image_url":
        return True
    if block.get("type") == "input_image":
        return True
    if block.get("type") == "image" and "source" in block:
        return True
    return False


def _has_image_in_messages(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        for block in msg.get("content", []):
            if isinstance(block, dict) and _is_image_block(block):
                return True
    return False


def _copilot_request_headers(
    base: dict[str, str], merged: dict[str, Any]
) -> dict[str, str]:
    """Add Copilot's per-request wire headers to *base*.

    ``x-initiator`` tells the gateway whether a turn was driven by the user
    or by the agent, which it uses for rate-limit classification — so it is
    always sent, defaulting to ``user`` when no tools are in play.
    ``Copilot-Vision-Request`` must accompany any request carrying an image.

    Shared by both handlers so the two endpoints cannot drift apart.
    """
    headers = {**base}
    has_tools = bool(merged.get("tools") or merged.get("tool_choice"))
    headers["x-initiator"] = "agent" if has_tools else "user"
    if _has_image_in_messages(merged.get("messages") or []):
        headers["Copilot-Vision-Request"] = "true"
    return headers


def _endpoint_for_model(model: str) -> str:
    """Resolve the live Copilot model contract, defaulting conservatively."""
    from app.agent.providers.model_metadata import get_model_interfaces

    interfaces = get_model_interfaces(f"copilot:{model}")
    if "responses" in interfaces and "chat/completions" not in interfaces:
        return "responses"
    return "completions"


def _resolve_github_token(explicit: str | SecretStr | None) -> str | None:
    """Resolve a GitHub token: explicit arg → oauth file → env var."""
    if explicit:
        return (
            explicit.get_secret_value() if isinstance(explicit, SecretStr) else explicit
        )
    oauth = CopilotOAuth.load()
    if oauth:
        return oauth.github_token.get_secret_value()
    import os

    return os.getenv("GITHUB_COPILOT_TOKEN") or None


class _CopilotCompletionsHandler(CompletionsHandler):
    """Copilot-specific overrides for /chat/completions.

    * Reasoning gating — only forward ``reasoning_effort`` for models the
      Copilot gateway accepts; Claude / Gemini / Grok reject the field.
    * Usage extraction — Copilot reports ``reasoning_tokens`` at the top
      level of the ``usage`` object (OpenAI nests it under
      ``completion_tokens_details``). Read both, top-level first.
    """

    default_provider_id = "copilot"

    def customize_thinking(self, merged: dict[str, Any], body: dict[str, Any]) -> None:
        """Gate ``reasoning_effort`` on what this Copilot model accepts.

        Copilot exposes a different effort vocabulary per model and rejects
        anything outside it, so the shared dialect table is not enough. The
        allowlist comes from the same resolver every other caller uses —
        reading the raw catalog here dropped valid levels whenever live
        discovery had not run yet.
        """
        from app.agent.providers.thinking import accepts_thinking_level

        thinking_level = merged.get("thinking_level")
        if not thinking_level or thinking_level in {"none", "off"}:
            return
        if accepts_thinking_level(f"copilot:{self.model}", thinking_level):
            body["reasoning_effort"] = thinking_level

    def _request_headers(self, merged: dict[str, Any]) -> dict[str, str]:
        """Dynamic wire headers: ``x-initiator`` and vision support."""
        return _copilot_request_headers(self.headers, merged)

    def _usage_from_openai(self, u: Any) -> Usage:
        usage = super()._usage_from_openai(u)
        # Copilot quirk: reasoning_tokens at the top level of usage.
        # Fall back to OpenAI's nested location if missing.
        thoughts = getattr(u, "reasoning_tokens", None) or None
        if not thoughts and u.completion_tokens_details:
            thoughts = u.completion_tokens_details.reasoning_tokens or None
        usage.thoughts_tokens = thoughts
        return usage


class _CopilotResponsesHandler(ResponsesHandler):
    """Copilot-specific overrides for /responses.

    * Request shape — Copilot's Responses gateway accepts (and ignores)
      ``temperature`` and ``top_p``. Passing them through preserves the
      previous wire format. The strict OpenAI Responses endpoint rejects
      these fields, which is why the canonical handler omits them.
    * Streaming events — Copilot's gateway uses ``call_id`` (not
      ``item_id``) on ``response.function_call_arguments.delta`` /
      ``done`` and embeds the function ``name`` directly on those events.
      The canonical OpenAI parser only reads ``item_id`` and never
      expects an inline ``name``.
    """

    default_provider_id = "copilot"

    def build_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        body = super().build_request(messages, tools, stream, merged)
        if merged.get("temperature") is not None:
            body["temperature"] = merged["temperature"]
        if merged.get("top_p") is not None:
            body["top_p"] = merged["top_p"]
        return body

    def _request_headers(self, merged: dict[str, Any]) -> dict[str, str]:
        """Dynamic wire headers: ``x-initiator`` and vision support."""
        return _copilot_request_headers(self.headers, merged)

    def _extract_call_id_and_name(self, event: dict[str, Any]) -> tuple[str, str]:
        call_id = event.get("item_id") or event.get("call_id", "")
        return call_id, event.get("name", "")


class CopilotProvider(OpenAIProvider):
    """GitHub Copilot provider (OpenAI-compatible).

    Routes to ``/chat/completions`` or ``/responses`` from live model metadata.

    Args:
        model: Model name, e.g. ``"gpt-5-mini"``, ``"claude-sonnet-4"``.
        github_token: Optional explicit GitHub token. Falls back to the
            OAuth cache file and ``GITHUB_COPILOT_TOKEN`` env var.
        temperature: Sampling temperature (Chat Completions only; ignored
            by /responses on the strict OpenAI endpoint, accepted but
            ignored by the Copilot gateway).
        top_p: Nucleus sampling cutoff (same caveats as ``temperature``).
        max_tokens: Hard cap on completion tokens.
        model_kwargs: Extra request body fields. Notable keys:
            ``thinking_level`` (str) — forwarded only when the model profile
            advertises that exact effort.
    """

    default_provider_id = "copilot"

    def __init__(
        self,
        model: str,
        github_token: str | SecretStr | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        model_kwargs: dict[str, Any] | None = None,
    ) -> None:
        token = _resolve_github_token(github_token)
        if not token:
            raise ValueError(
                "GitHub token not found.  Run:\n"
                "  evoflux auth copilot\n"
                "Or set GITHUB_COPILOT_TOKEN env var."
            )
        super().__init__(
            api_key=token,
            model=model,
            base_url=COPILOT_API_BASE,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            model_kwargs=model_kwargs,
        )
        from app.agent.providers.model_metadata import has_runtime_model_metadata

        # Construction is synchronous, while Copilot's per-model endpoint
        # contract is available only from its live catalog. A provider created
        # outside the main team runtime therefore hydrates lazily on its first
        # request instead of permanently defaulting Responses-only models to
        # /chat/completions.
        self._model_contract_loaded = has_runtime_model_metadata(
            f"copilot:{self.model}"
        )

    # Convenience aliases for callers that think in Copilot-specific terms.
    @property
    def _github_token(self) -> str:
        return self.api_key

    @property
    def _endpoint_type(self) -> str:
        return "responses" if self._use_responses else "completions"

    @property
    def _request_url(self) -> str:
        return f"{COPILOT_API_BASE}/{'responses' if self._use_responses else 'chat/completions'}"

    def _build_headers(self) -> dict[str, str]:
        return {**_DEFAULT_HEADERS, "Authorization": f"Bearer {self.api_key}"}

    def _use_responses_for(self, model_kwargs: dict[str, Any]) -> bool:
        return _endpoint_for_model(self.model) == "responses"

    async def _ensure_model_contract(self) -> None:
        if self._model_contract_loaded:
            return

        from app.agent.providers.catalog import find
        from app.agent.providers.model_discovery import discover_provider_model_entries

        entry = find("copilot")
        if entry is not None:
            await discover_provider_model_entries(
                entry,
                overrides={"GITHUB_COPILOT_TOKEN": self.api_key},
            )
        self._use_responses = _endpoint_for_model(self.model) == "responses"
        # Discovery already handles/logs transient failures. Avoid turning one
        # outage into a catalog request before every LLM retry in this instance.
        self._model_contract_loaded = True

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AssistantMessage:
        await self._ensure_model_contract()
        return await super().chat(messages, tools, **kwargs)

    async def stream(
        self,
        messages: list[ChatMessage],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ):
        await self._ensure_model_contract()
        async for chunk in super().stream(messages, tools, **kwargs):
            yield chunk

    def _make_completions_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> CompletionsHandler:
        return _CopilotCompletionsHandler(model, base_url, headers)

    def _make_responses_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> ResponsesHandler:
        return _CopilotResponsesHandler(model, base_url, headers)
