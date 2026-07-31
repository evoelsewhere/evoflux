"""wiki_search tool — search across all knowledge pages.

Supports keyword search with BM25 scoring over the four knowledge dirs
(``topics/``, ``entities/``, ``sources/``, ``comparisons/``).  ``notes/``
is excluded — notes are raw input, not curated knowledge.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.agent.hooks.wiki_injection import _score_topics
from app.agent.tools.registry import Tool
from app.services.wiki import list_tree, wiki_root


async def _wiki_search(
    query: Annotated[
        str, Field(description="Search query — natural language or keywords.")
    ],
    methods: Annotated[
        list[Literal["text"]],
        Field(description='Search methods. Only "text" keyword search is available.'),
    ] = ["text"],
    top_k: Annotated[
        int,
        Field(description="Maximum number of pages to return (default 5)."),
    ] = 5,
) -> str:
    """Search wiki knowledge pages by keyword or meaning.

    Searches across topics, entities, sources, and comparisons — the full
    knowledge graph the dream agent maintains.  Use this to find relevant
    knowledge before starting a task, or to look up a specific concept,
    person, tool, or comparison.

    Returns matching pages with their content (truncated at 4096 bytes
    per page).
    """
    root = wiki_root()
    if not root.exists():
        return "No wiki directory found."

    try:
        tree = list_tree()
    except Exception as exc:
        return f"Failed to list wiki pages: {exc}"

    # Concatenate all knowledge dirs.  ``_score_topics`` is name-agnostic —
    # it scores any WikiFileInfo by description + tags + path.
    candidates = (
        list(tree.topics)
        + list(tree.entities)
        + list(tree.sources)
        + list(tree.comparisons)
    )
    if not candidates:
        return "No knowledge pages in wiki yet."

    scored = _score_topics(query, candidates)
    matches = [(info, score) for info, score in scored if score > 0.0][:top_k]

    if not matches:
        return f"No wiki pages matched '{query}'."

    parts = [f"Wiki search results for: '{query}'\n"]
    for info, score in matches:
        path = root / info.path
        try:
            raw = path.read_bytes()
            content = raw[:4096].decode("utf-8", errors="ignore")
            if len(raw) > 4096:
                content += "\n\n[truncated at 4096 bytes]"
        except (OSError, UnicodeDecodeError) as exc:
            content = f"(read error: {exc})"
        parts.append(f"### wiki/{info.path}  (score: {score:.1f})\n{content.rstrip()}")

    return "\n\n".join(parts)


wiki_search = Tool(
    _wiki_search,
    name="wiki_search",
    tiers=("work",),
    description=(
        "Search the wiki — knowledge pages distilled from past conversations. "
        "Searches topics (concepts), entities (people/tools/orgs), sources, "
        "and comparisons.  Use this to recall what was previously discussed "
        "or decided on any subject.  Returns full content of matching pages."
    ),
    concurrency_safe=True,
    read_only=True,
    deferred=True,
    deferred_summary="Search distilled wiki knowledge from prior conversations.",
)
