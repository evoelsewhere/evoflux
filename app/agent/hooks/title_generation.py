"""TitleGenerationHook — generates a session title on the first turn.

``before_agent`` records the first user message but deliberately does not
start title generation yet. The background task starts only after the main
model stream emits its first chunk, ensuring the user's request reaches the
provider before the secondary title request. ``after_model`` is the fallback
for providers that complete without emitting a stream chunk.

The LLM call, DB write, and ``title_update`` SSE event are handled entirely by
:func:`~app.services.title_service.generate_and_save_title`. The task is never
awaited by the agent lifecycle, so title generation cannot delay the first
model call or the final ``done`` event.

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
from app.agent.schemas.chat import (
    AssistantMessage,
    ChatCompletionChunk,
    HumanMessage,
)

if TYPE_CHECKING:
    from app.agent.providers.base import LLMProviderBase
    from app.agent.state import AgentState, RunContext
    from app.core.db import DbFactory


# ── Module-level defaults (no env-var overrides) ──────────────────────────
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


# Keep strong references to detached tasks until they finish. The hook itself
# is scoped to one agent run and may be released while title generation is
# still updating the session in the background.
_background_title_tasks: set[asyncio.Task[None]] = set()


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
    """

    def __init__(
        self,
        provider: "LLMProviderBase",
        db_factory: "DbFactory",
        system_prompt: str,
    ) -> None:
        if not system_prompt or not system_prompt.strip():
            raise ValueError("TitleGenerationHook requires a non-empty system_prompt.")
        self._provider = provider
        self._db_factory = db_factory
        self._system_prompt = system_prompt
        self._pending: tuple[UUID, str] | None = None
        self._task: asyncio.Task[None] | None = None

    async def before_agent(self, ctx: "RunContext", state: "AgentState") -> None:
        """Queue title generation if this is the first turn."""
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

        self._pending = (UUID(ctx.session_id), user_text)
        logger.info(
            "title_generation_hook_queued session_id={} model={}",
            ctx.session_id,
            getattr(self._provider, "model", None),
        )

    def _spawn_pending(self) -> None:
        pending = self._pending
        if pending is None:
            return

        self._pending = None
        session_id, user_text = pending

        from app.services.title_service import generate_and_save_title

        task = asyncio.create_task(
            generate_and_save_title(
                session_id=session_id,
                user_message=user_text,
                provider=self._provider,
                db_factory=self._db_factory,
                system_prompt=self._system_prompt,
            )
        )
        self._task = task
        _background_title_tasks.add(task)
        task.add_done_callback(_background_title_tasks.discard)
        logger.info(
            "title_generation_hook_spawned session_id={} model={}",
            session_id,
            getattr(self._provider, "model", None),
        )

    async def on_model_delta(
        self,
        ctx: "RunContext",
        state: "AgentState",
        chunk: ChatCompletionChunk,
    ) -> None:
        """Start title generation only after the primary request is streaming."""
        del ctx, state, chunk
        self._spawn_pending()

    async def after_model(
        self, ctx: "RunContext", state: "AgentState", response: AssistantMessage
    ) -> None:
        """Fallback for providers that return without yielding stream chunks."""
        del ctx, state, response
        self._spawn_pending()


def build_title_generation_hook(
    *,
    provider: "LLMProviderBase",
    db_factory: "DbFactory",
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
    )
