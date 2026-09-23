"""StepFun provider — OpenAI-compatible API.

Thin wrapper around ``ChatCompletionsOnlyProvider`` with the two request
quirks StepFun's Chat Completions surface has. Base URL is configurable
(``STEPFUN_BASE_URL``) because StepFun publishes the same API under four
hosts: a global and a China open platform, each with a subscription
``step_plan`` variant.

Endpoint:  https://api.stepfun.ai/v1 (override via ``STEPFUN_BASE_URL``)
Auth:      Bearer {STEPFUN_API_KEY}
Docs:      https://platform.stepfun.ai/docs/en/api-reference/chat/chat-completion-create

StepFun quirks (vs plain OpenAI):
    1. StepFun documents the reasoning trace as ``reasoning`` by default —
       a field name ``OpenAIStreamDelta`` does not parse, and the response
       schemas ignore unknown fields, so a trace that arrived only under
       that name would vanish without a trace of its own. ``reasoning_format:
       "deepseek-style"`` is StepFun's own switch for returning it as
       ``reasoning_content`` instead, which every other provider here
       already speaks. Probed 2026-09-21 against ``step_plan`` global, that
       endpoint returns *both* spellings whatever the format says; sending
       the field pins the one EvoFlux reads rather than depending on a host
       and a version behaving that way.
    2. ``max_tokens`` is the documented output cap. ``max_completion_tokens``
       was also accepted when probed, but the field this endpoint publishes
       is the one to send.

Thinking translation itself is inherited: StepFun takes OpenAI's
``reasoning_effort``, which is the default dialect for this transport, so
no entry in :mod:`app.agent.providers.thinking` is needed. What this
handler does add is the enum guard — see :meth:`customize_thinking`.

Token resolution order:
    1. ``Settings.STEPFUN_API_KEY`` (from ``.env`` or environment)
    2. ``STEPFUN_API_KEY`` environment variable

Usage::

    model: stepfun:step-3.7-flash
    model: stepfun:step-5-preview
"""

from __future__ import annotations

from typing import Any

from app.agent.providers.openai import ChatCompletionsOnlyProvider
from app.agent.providers.openai.completions import CompletionsHandler
from app.agent.schemas.chat import ChatMessage

#: Reasoning-trace spelling StepFun should use. ``"general"`` — its default
#: — returns the trace as ``reasoning``; ``"deepseek-style"`` returns it as
#: ``reasoning_content``, which is what EvoFlux's response schemas read.
REASONING_FORMAT = "deepseek-style"

#: Values StepFun's ``reasoning_effort`` accepts. The documented request
#: shape names these three and nothing else — no ``none``, which is the one
#: level the shared dialect can emit that this endpoint has never published.
_SUPPORTED_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high"})


class _StepFunCompletionsHandler(CompletionsHandler):
    """StepFun-specific completions handler.

    Differences from the base ``CompletionsHandler``:

    1. ``max_tokens`` only — StepFun documents no ``max_completion_tokens``.
    2. Every request carries ``reasoning_format`` so the reasoning trace
       arrives under ``reasoning_content`` rather than ``reasoning``.
    3. ``reasoning_effort`` is dropped rather than sent with a value
       StepFun has not published.
    """

    default_provider_id = "stepfun"

    uses_max_completion_tokens = False

    def build_request(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        stream: bool,
        merged: dict[str, Any],
    ) -> dict[str, Any]:
        body = super().build_request(messages, tools, stream, merged)
        # A caller may still pick the other spelling explicitly; the default
        # is the one the rest of EvoFlux can read.
        requested = merged.get("reasoning_format")
        body["reasoning_format"] = (
            requested.strip()
            if isinstance(requested, str) and requested.strip()
            else REASONING_FORMAT
        )
        return body

    def customize_thinking(self, merged: dict[str, Any], body: dict[str, Any]) -> None:
        """Keep ``reasoning_effort`` inside the enum StepFun documents.

        The shared dialect emits ``reasoning_effort: "none"`` for an explicit
        "do not reason" request, because on an OpenAI-shaped endpoint that is
        the off switch. StepFun's reasoning models publish ``low``,
        ``medium`` and ``high`` and no way to turn thinking off.

        Probed 2026-09-21, ``none`` is answered with a 200 and ignored — the
        model reasons anyway — so this is not the 400 the MiMo handler
        clamps its legacy effort field to avoid. It is still not a value
        StepFun published, and the outcome is identical either way, so the
        field is withheld rather than sent on a guess about how the next
        host or version validates it. Thinking stays on at StepFun's own
        default; the level the user asked for is the only thing lost.

        Levels above the enum are already clamped upstream by
        :func:`app.agent.providers.thinking.thinking_request_fields`.
        """
        super().customize_thinking(merged, body)

        effort = body.get("reasoning_effort")
        if not isinstance(effort, str) or effort not in _SUPPORTED_EFFORTS:
            body.pop("reasoning_effort", None)


class StepFunProvider(ChatCompletionsOnlyProvider):
    """StepFun provider (OpenAI-compatible).

    Args:
        api_key: StepFun API key from https://platform.stepfun.ai.
        model: Model name, e.g. ``"step-3.7-flash"``, ``"step-5-preview"``.
        base_url: API base URL — defaults to StepFun's global open platform,
            overridable via ``STEPFUN_BASE_URL`` for the China host
            (``https://api.stepfun.com/v1``) or either ``step_plan``
            subscription endpoint.
        temperature: Sampling temperature (0-2).
        top_p: Nucleus sampling probability mass cutoff.
        max_tokens: Hard cap on completion tokens.
        model_kwargs: Extra request body fields passed as-is.
    """

    default_provider_id = "stepfun"

    def _make_completions_handler(
        self, model: str, base_url: str, headers: dict[str, str]
    ) -> CompletionsHandler:
        return _StepFunCompletionsHandler(model, base_url, headers)
