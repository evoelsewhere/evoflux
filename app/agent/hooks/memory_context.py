"""MemoryContextHook — inject small query-relevant Memory v2 excerpts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.schemas.chat import AssistantMessage, HumanMessage, ToolMessage
from app.services.memory import MemorySearchResult
from app.services.memory import search_memory_facts

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage
    from app.agent.state import (
        AgentState,
        ModelCallHandler,
        ModelRequest,
        RunContext,
    )

MAX_MEMORY_QUERY_CHARS = 500
MAX_MEMORY_CONTEXT_CHARS = 2_000
MEMORY_CONTEXT_TOP_K = 3


class MemoryContextHook(BaseAgentHook):
    """Inject relevant Memory v2 snippets for the current user turn.

    This is intentionally conservative: it searches only from the latest user
    message, injects a small cited block, and never blocks the model call if
    memory search fails.
    """

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        query = self._latest_user_text(request)
        if not query:
            return await handler(request)

        try:
            results = search_memory_facts(
                query,
                limit=MEMORY_CONTEXT_TOP_K,
            )
        except Exception as exc:
            logger.warning("memory_context_search_failed error={}", exc)
            return await handler(request)

        results = self._filter_relevant_results(results)
        if not results:
            return await handler(request)

        lines = [
            "## Relevant memory",
            "",
            "Cited active memory facts that may help personalize this answer. Use only if relevant; do not overfit.",
        ]
        for result in results:
            location = f" path={result.path}" if result.path else ""
            lines.append(
                f"- source={result.source_ref}{location} score={result.score:.3f}: "
                f"{result.excerpt}"
            )
        block = "\n".join(lines)
        if len(block) > MAX_MEMORY_CONTEXT_CHARS:
            block = block[:MAX_MEMORY_CONTEXT_CHARS].rstrip() + "\n[truncated]"

        new_prompt = (
            f"{request.system_prompt}\n\n{block}" if request.system_prompt else block
        )
        return await handler(request.override(system_prompt=new_prompt))

    def _filter_relevant_results(
        self, results: list[MemorySearchResult]
    ) -> list[MemorySearchResult]:
        return [
            result
            for result in results
            if result.path
            and result.diagnostics.get("fact_section") == "active"
            and bool(result.diagnostics.get("citations"))
        ]

    def _latest_user_text(self, request: "ModelRequest") -> str:
        for message in reversed(request.messages):
            if isinstance(message, HumanMessage):
                content = message.text_content() or ""
                return " ".join(content.split())[:MAX_MEMORY_QUERY_CHARS]
            if isinstance(message, AssistantMessage) and message.tool_calls:
                return ""
            if isinstance(message, ToolMessage):
                return ""
        return ""


default_memory_context_hook = MemoryContextHook()


__all__ = ["MemoryContextHook", "default_memory_context_hook"]
