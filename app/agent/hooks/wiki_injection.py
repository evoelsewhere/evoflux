"""WikiInjectionHook — inject the canonical USER.md into the system prompt.

Every LLM call receives a capped ``USER.md`` excerpt when present. Relevant
knowledge pages are injected separately by :mod:`memory_context`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.hooks.base import BaseAgentHook

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage
    from app.agent.state import (
        AgentState,
        ModelCallHandler,
        ModelRequest,
        RunContext,
    )


# ── Hook ─────────────────────────────────────────────────────────────────────


USER_MEMORY_PATH = "USER.md"
USER_MEMORY_MAX_CHARS = 4_000


class WikiInjectionHook(BaseAgentHook):
    """Inject the durable user profile into the system prompt on every call."""

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        user_block = self._read_user_md()
        if not user_block:
            return await handler(request)
        header = "## About the user\n\n"
        block = header + user_block
        new_prompt = (
            f"{request.system_prompt}\n\n{block}" if request.system_prompt else block
        )
        return await handler(request.override(system_prompt=new_prompt))

    def _read_user_md(self) -> str:
        from app.services.memory import memory_root

        user_path = memory_root() / USER_MEMORY_PATH
        if not user_path.exists():
            return ""
        try:
            content = user_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return ""
        if len(content) <= USER_MEMORY_MAX_CHARS:
            return content
        return content[:USER_MEMORY_MAX_CHARS].rstrip() + "\n\n[truncated]"


# Module-level instance for convenience.
default_wiki_injection_hook = WikiInjectionHook()


__all__ = [
    "WikiInjectionHook",
    "default_wiki_injection_hook",
]
