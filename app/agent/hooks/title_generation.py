"""TitleGenerationHook — generates a session title on the first turn.

Fires a background ``asyncio.create_task`` in ``before_agent`` when the
conversation has no prior assistant messages (i.e. the first user turn).
The LLM call, DB write, and ``title_update`` SSE event are handled entirely
by :func:`~app.services.title_service.generate_and_save_title` — this hook
just decides *when* to trigger it.

Because the task is fire-and-forget, the agent loop is never blocked by the
LLM call itself. ``after_agent`` performs a best-effort ``await`` on the task
so the ``title_update`` SSE arrives before ``done`` is emitted, but the wait
is capped by ``wait_timeout`` (default ``3.0`` s).

Usage::

    from app.agent.hooks.title_generation import build_title_generation_hook

    hook = build_title_generation_hook(
        provider=llm_provider,
        db_factory=db_factory,
    )
    if hook is not None:
        agent = Agent(llm_provider=provider, hooks=[hook, ...])
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage

if TYPE_CHECKING:
    from app.agent.providers.base import LLMProviderBase
    from app.agent.state import AgentState, RunContext
    from app.core.db import DbFactory


# ── Module-level defaults (no env-var overrides) ──────────────────────────
# Best-effort cap (seconds) on how long the agent loop waits for the
# background title task to land before completing. ``0`` skips the wait
# entirely — the title still arrives via SSE when the task finishes.
DEFAULT_WAIT_TIMEOUT_SECONDS = 3.0
TITLE_GENERATION_PROMPT = """\
You are a title generator. You output ONLY a conversation title. Nothing else.

Generate a brief title that would help the user find this conversation later.

Your output must be:
- A single line
- <=50 characters
- No explanations

Rules:
- Use the same language as the user message you are summarizing.
- Title must be grammatically correct and read naturally.
- Focus on the main topic, question, or goal the user wants to accomplish.
- Keep exact proper nouns, numbers, names, and specific terms relevant to the topic.
- Never respond to the conversation; only generate a title for it.
"""


class TitleGenerationHook(BaseAgentHook):
    """Fires background title generation on the first turn of a session.

    Construct via :func:`build_title_generation_hook`.

    Args:
        provider: LLM provider used for the lightweight title generation call.
            When the hook is wired from a team chat turn, pass the same
            provider the chat turn is using so title generation shares the
            configured chat model.
        db_factory: Async session factory for persisting the title.
        system_prompt: Title-generator system prompt (required, non-empty).
        wait_timeout: Seconds to wait in ``after_agent`` for the background
            task to complete before the agent loop finishes. ``0`` skips the
            wait entirely (fully non-blocking). Default ``3.0``.
    """

    def __init__(
        self,
        provider: "LLMProviderBase",
        db_factory: "DbFactory",
        system_prompt: str,
        *,
        wait_timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
    ) -> None:
        if not system_prompt or not system_prompt.strip():
            raise ValueError("TitleGenerationHook requires a non-empty system_prompt.")
        self._provider = provider
        self._db_factory = db_factory
        self._system_prompt = system_prompt
        self._wait_timeout = max(0.0, wait_timeout)
        self._task: asyncio.Task[None] | None = None

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        """Spawn background title generation if this is the first turn."""
        if ctx.session_id is None:
            return

        # First turn = no assistant messages in history yet.
        has_assistant = any(isinstance(m, AssistantMessage) for m in state.messages)
        if has_assistant:
            return

        # Find the user message that triggered this run.
        user_text: str | None = None
        for m in reversed(state.messages):
            if isinstance(m, HumanMessage) and m.content:
                user_text = m.content
                break

        if not user_text:
            return

        # Skip title generation for scheduled tasks — their sessions are
        # identified by the "[Scheduled Task: ...]" prefix injected by the
        # scheduler before dispatch.
        if user_text.startswith("[Scheduled Task:"):
            logger.debug(
                "title_generation_hook_skipped reason=scheduled_task session_id={}",
                ctx.session_id,
            )
            return

        from app.services.title_service import generate_and_save_title

        self._task = asyncio.create_task(
            generate_and_save_title(
                session_id=UUID(ctx.session_id),
                user_message=user_text,
                provider=self._provider,
                db_factory=self._db_factory,
                system_prompt=self._system_prompt,
            )
        )
        logger.info(
            "title_generation_hook_spawned session_id={} model={}",
            ctx.session_id,
            getattr(self._provider, "model", None),
        )

    async def after_agent(
        self, ctx: "RunContext", state: "AgentState", response: AssistantMessage
    ) -> None:
        """Best-effort wait for the title task so the SSE event lands before done.

        If ``wait_timeout`` is ``0`` the hook skips the wait entirely and the
        title is delivered via SSE whenever the background task finishes.
        """
        task = self._task
        self._task = None

        if task is None or task.done():
            return

        if self._wait_timeout <= 0:
            # Non-blocking mode: leave the task running in the background.
            # It will push the title_update SSE event when it finishes.
            return

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self._wait_timeout)
        except (TimeoutError, Exception):
            pass


def build_title_generation_hook(
    *,
    provider: "LLMProviderBase",
    db_factory: "DbFactory",
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> "TitleGenerationHook | None":
    """Construct a :class:`TitleGenerationHook`.

    Title generation is always enabled. The caller supplies the provider to
    use; in team chat this should be the same provider the chat turn is using
    so the title is generated with the active chat model.
    """
    return TitleGenerationHook(
        provider=provider,
        db_factory=db_factory,
        system_prompt=TITLE_GENERATION_PROMPT,
        wait_timeout=wait_timeout,
    )
