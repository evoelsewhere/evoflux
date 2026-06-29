"""PromptSuggestionsHook — generate follow-up prompt chips after each response.

Fires ``after_agent`` and spawns a background LLM task that reads the
last assistant response and generates 2–3 short contextual follow-up
suggestions.  The suggestions are pushed as a ``prompt_suggestions`` SSE
event to the session stream; the frontend renders them as clickable chips
below the assistant's latest message.

Design
------
- Fire-and-forget: ``asyncio.create_task``; the agent loop is never blocked.
- Lead-only: member agents skip this hook.
- Content gate: skips very short responses and tool-only turns (no prose).
- Graceful: any error in the background task is logged and suppressed.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage

if TYPE_CHECKING:
    from app.agent.providers.base import LLMProviderBase
    from app.agent.state import AgentState, RunContext
    from app.core.runtime_settings import PromptSuggestionsSettings


# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a suggestion generator. Output ONLY follow-up suggestions.

Given a conversation, generate the next natural things the user might want to ask or do.
Each suggestion must:
- Be ≤ 60 characters
- Be a complete, natural request or question
- Be genuinely useful to the user

Output exactly {count} suggestions, one per line. No numbering, no bullets,
no explanation, no extra lines.
"""

_MIN_RESPONSE_CHARS = 80  # skip suggestions for very short responses


def _last_assistant_text(state: "AgentState") -> str | None:
    """Return the text content of the most recent assistant message."""
    for msg in reversed(state.messages):
        if isinstance(msg, AssistantMessage) and not msg.exclude_from_context:
            content = (msg.content or "").strip()
            if content and len(content) >= _MIN_RESPONSE_CHARS:
                return content
    return None


def _last_user_text(state: "AgentState") -> str | None:
    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage) and not msg.exclude_from_context:
            return (msg.content or "").strip()
    return None


def _parse_suggestions(raw: str, count: int) -> list[str]:
    """Extract up to *count* non-empty lines from the raw LLM output."""
    lines = [ln.strip() for ln in raw.strip().splitlines()]
    # Strip common list prefixes ("1. ", "- ", "• ")
    cleaned = []
    for ln in lines:
        ln = re.sub(r"^[\d]+[.)]\s*", "", ln)
        ln = re.sub(r"^[-•*]\s*", "", ln).strip()
        if ln and len(ln) <= 120:
            cleaned.append(ln)
        if len(cleaned) >= count:
            break
    return cleaned


async def _generate_and_push(
    provider: "LLMProviderBase",
    state: "AgentState",
    session_id: str,
    count: int,
) -> None:
    """Background: call LLM for suggestions and push to SSE stream."""
    try:
        assistant_text = _last_assistant_text(state)
        if not assistant_text:
            return

        user_text = _last_user_text(state) or ""
        conversation = f"User: {user_text}\n\nAssistant: {assistant_text[:1200]}"

        request_msgs: list = [HumanMessage(content=conversation)]
        system = _SYSTEM_PROMPT.format(count=count)

        response = await asyncio.wait_for(
            provider.chat(
                request_msgs,
                tools=None,
                max_tokens=200,
                system_prompt=system,
            ),
            timeout=20.0,
        )
        raw = (response.content or "").strip()
        if not raw:
            return

        suggestions = _parse_suggestions(raw, count)
        if not suggestions:
            return

        from app.agent.schemas.events import PromptSuggestionsEvent
        from app.services import memory_stream_store as stream_store
        from app.services.stream_envelope import StreamEnvelope

        await stream_store.push_event(
            session_id,
            StreamEnvelope.from_event(PromptSuggestionsEvent(suggestions=suggestions)),
        )
        logger.debug(
            "prompt_suggestions_pushed session_id={} count={}",
            session_id,
            len(suggestions),
        )

    except asyncio.TimeoutError:
        logger.debug("prompt_suggestions_timeout session_id={}", session_id)
    except Exception as exc:  # noqa: BLE001 — background task, never crash
        logger.debug(
            "prompt_suggestions_failed session_id={} error={}", session_id, exc
        )


# ── Hook class ────────────────────────────────────────────────────────────────


class PromptSuggestionsHook(BaseAgentHook):
    """Generates follow-up suggestion chips after each agent response."""

    def __init__(self, provider: "LLMProviderBase", *, count: int = 3) -> None:
        self._provider = provider
        self._count = max(1, min(count, 5))

    async def after_agent(
        self, ctx: "RunContext", state: "AgentState", response: AssistantMessage
    ) -> None:
        session_id = ctx.session_id
        if not session_id:
            return

        # Skip if this is a scheduled task session
        user_text = _last_user_text(state) or ""
        if user_text.startswith("[Scheduled Task:"):
            return

        asyncio.create_task(
            _generate_and_push(self._provider, state, session_id, self._count)
        )


# ── Factory ───────────────────────────────────────────────────────────────────


def build_prompt_suggestions_hook(
    provider: "LLMProviderBase",
    *,
    cfg: "PromptSuggestionsSettings | None" = None,
) -> "PromptSuggestionsHook | None":
    """Return a :class:`PromptSuggestionsHook` or ``None`` when disabled."""
    if cfg is None:
        from app.core.runtime_settings import load_runtime_settings

        cfg = load_runtime_settings().prompt_suggestions

    if not cfg.enabled:
        return None

    suggestion_provider = provider
    if cfg.model and cfg.model.strip() and cfg.model != provider.model:
        try:
            from app.agent.providers.factory import build_provider

            suggestion_provider = build_provider(cfg.model)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "prompt_suggestions_provider_build_failed model={} err={}",
                cfg.model,
                exc,
            )

    return PromptSuggestionsHook(suggestion_provider, count=cfg.count)
