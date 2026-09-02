"""Mark the boundary between the cacheable and per-turn-volatile system prompt.

Anthropic (and Bedrock) prompt caching matches an exact byte prefix up to a
declared breakpoint — a single byte anywhere before that point invalidates
the whole cached segment. If turn-varying content (memory search results,
the query-ranked skill catalog) is concatenated into the same system-prompt
string as everything else, providers have no way to tell "safe to cache"
apart from "changes every turn", so caching either covers nothing or is
invalidated every turn regardless of how much of the prompt is actually
still stable.

``CacheBoundaryHook`` stamps an invisible marker into the system prompt at
the point where volatile hooks take over. ``agent_loop/streaming.py`` strips
the marker before it reaches any provider or gets logged/summarized, and
forwards its position as ``cache_boundary`` so a caching-aware provider can
split the system text into a cacheable head and an uncached tail instead of
one all-or-nothing block.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.hooks.base import BaseAgentHook

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage
    from app.agent.state import AgentState, ModelCallHandler, ModelRequest, RunContext

# A NUL-delimited sentinel: vanishingly unlikely to occur in real prompt
# text, and stripped before any provider or log ever sees it.
CACHE_VOLATILE_MARKER = "\x00EVOFLUX-CACHE-VOLATILE-BOUNDARY\x00"


class CacheBoundaryHook(BaseAgentHook):
    """Stamp the cache boundary marker onto the system prompt built so far.

    Register this immediately before the hooks that append per-turn-volatile
    content (memory context, the ranked skill catalog) so everything already
    in ``request.system_prompt`` at this point — role prompt, team protocol,
    goal/folder/EASD context, workspace instructions — stays a stable,
    cacheable prefix across turns.
    """

    async def wrap_model_call(
        self,
        ctx: "RunContext",
        state: "AgentState",
        request: "ModelRequest",
        handler: "ModelCallHandler",
    ) -> "AssistantMessage":
        return await handler(
            request.override(
                system_prompt=request.system_prompt + CACHE_VOLATILE_MARKER
            )
        )


__all__ = ["CACHE_VOLATILE_MARKER", "CacheBoundaryHook"]
