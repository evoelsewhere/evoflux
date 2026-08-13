"""memory_search tool — unified deterministic EvoFlux Memory search."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.agent.tools.registry import Tool
from app.core.db import get_write_session
from app.services.memory import memory_search as search_memory


async def _memory_search(
    query: Annotated[
        str, Field(description="Search query — natural language or keywords.")
    ],
    top_k: Annotated[
        int,
        Field(
            description="Maximum number of cited memory results to return (default 8)."
        ),
    ] = 8,
) -> str:
    """Search curated knowledge, raw evidence, and visible chat messages.

    Use this before relying on memory. Results include stable source refs such
    as `topic:<slug>`, `entity:<slug>`, `source:<slug>`,
    `comparison:<slug>`, `memory:user`, and `message:<uuid>`.
    """
    limit = max(1, min(top_k, 20))
    async for db in get_write_session():
        results = await search_memory(query, db=db, limit=limit)
        break
    else:
        results = await search_memory(query, limit=limit)

    if not results:
        return f"No memory results matched '{query}'."

    parts = [f"Memory search results for: '{query}'"]
    for index, result in enumerate(results, start=1):
        location = f" path={result.path}" if result.path else ""
        parts.append(
            f"{index}. source={result.source_ref}{location} score={result.score:.3f}\n"
            f"   title: {result.title}\n"
            f"   excerpt: {result.excerpt}"
        )
    return "\n\n".join(parts)


memory_search = Tool(
    _memory_search,
    name="memory_search",
    description=(
        "Search EvoFlux Memory across USER.md, topics, entities, sources, "
        "comparisons, notes, imports, and visible chat messages. Returns "
        "ranked excerpts with stable source refs."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=False,
    search_aliases=(
        "remember",
        "recall",
        "remembered",
        "previously",
        "earlier",
        "past",
        "history",
        "preference",
        "preferences",
        "decision",
        "decisions",
        "before",
        "told",
        "said",
        "context",
    ),
)
