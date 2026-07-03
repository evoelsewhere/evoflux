"""WikiInjectionHook — inject memory v2 wiki/user.md into the system prompt.

Every LLM call receives a capped ``wiki/user.md`` excerpt when present. Topic
injection is no longer automatic; the agent uses memory search tools explicitly.

The BM25-style scoring helpers (``_score_topics``, ``_tokenize``) live in this
module because the ``wiki_search`` tool imports them.
"""

from __future__ import annotations

import re
from pathlib import Path
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


USER_MEMORY_PATH = "wiki/user.md"
USER_MEMORY_MAX_CHARS = 4_000


class WikiInjectionHook(BaseAgentHook):
    """Inject memory v2 wiki/user.md into the system prompt on every LLM call."""

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


# ── BM25-style relevance scoring (used by wiki_search tool) ──────────────────


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, drop tokens shorter than 2 chars."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 2]


def _score_topics(query: str, topics: list) -> list[tuple]:
    """Score each topic against *query* using weighted token overlap.

    Returns topics sorted descending by score.  Topics with zero overlap are
    included (score=0) so the caller can still render a complete index.
    """
    if not query.strip():
        return [(t, 0.0) for t in topics]

    query_tokens = set(_tokenize(query))
    results: list[tuple] = []

    for info in topics:
        stem = Path(info.path).stem  # e.g. "auth-strategy"
        desc_tokens = _tokenize(info.description)
        tag_tokens = [t for tag in info.tags for t in _tokenize(tag)]
        stem_tokens = _tokenize(stem)

        score = 0.0
        for tok in desc_tokens:
            if tok in query_tokens:
                score += 1.0
        for tok in tag_tokens:
            if tok in query_tokens:
                score += 1.5
        for tok in stem_tokens:
            if tok in query_tokens:
                score += 0.5

        results.append((info, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


# Module-level instance for convenience.
default_wiki_injection_hook = WikiInjectionHook()


__all__ = [
    "WikiInjectionHook",
    "default_wiki_injection_hook",
    "_score_topics",
    "_tokenize",
]
