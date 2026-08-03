"""Search for and activate deferred tools for the current agent run."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any

from loguru import logger
from pydantic import BeforeValidator, Field

from app.agent.tools.registry import DeferredToolEntry, InjectedArg, tool


#: Weight applied to a hit on a tool's name or aliases. Those are curated
#: intent vocabulary, so they outrank a summary word that merely coincides:
#: "table of data" should surface the widget renderer, not whichever summary
#: happens to mention "data".
_INTENT_MATCH_WEIGHT = 2

#: Common English function words, dropped from a query before scoring. Matching
#: is a plain term intersection, so otherwise "show me the diagram" scores "the"
#: against every summary containing "the" and buries the tool that actually
#: matched "diagram". Deliberately short: one- and two-letter filler is handled
#: by length below, and any word the catalog itself uses is rescued by
#: *vocabulary*, so this list never has to anticipate a tool's keywords.
_QUERY_STOPWORDS: frozenset[str] = frozenset(
    """
    the and for with from into that this these those their your our
    are was were has have had can will would should could does did not
    any some one just use using please want need
    """.split()
)

#: Query tokens shorter than this are filler unless the catalog uses them —
#: which is what keeps a genuine short keyword such as "cv" searchable.
_MIN_MEANINGFUL_TERM_LENGTH = 3


def _tokenise(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _query_terms(query: str, vocabulary: frozenset[str]) -> set[str]:
    """Tokenise a query, dropping filler that would skew scoring.

    A token the catalog itself uses is never filler, whatever the stopword list
    says — so adding an alias can widen search without a matching edit here.
    """
    terms = _tokenise(query)
    meaningful = {
        term
        for term in terms
        if term in vocabulary
        or (len(term) >= _MIN_MEANINGFUL_TERM_LENGTH and term not in _QUERY_STOPWORDS)
    }
    # An all-filler query still deserves a best effort over nothing.
    return meaningful or terms


def _coerce_tool_names(value: Any) -> Any:
    """Accept a JSON-array string emitted by models that double-encode arguments."""
    if not isinstance(value, str):
        return value
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return value
    return decoded if isinstance(decoded, list) else value


@tool(
    name="load_tool",
    description=(
        "Find and activate a specialized tool whose full schema is hidden by "
        "default. Search with query first, then pass one exact tool_name. "
        "For batching, tool_names must be a native JSON array, not a quoted "
        "or stringified array. Activated tools become available next turn."
    ),
    read_only=True,
)
async def load_tool(
    tool_name: Annotated[
        str | None,
        Field(description="Exact deferred tool name returned by a prior search."),
    ] = None,
    tool_names: Annotated[
        list[str] | None,
        BeforeValidator(_coerce_tool_names),
        Field(description="Exact deferred tool names to activate together."),
    ] = None,
    query: Annotated[
        str | None,
        Field(description="Keywords describing the capability to find."),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Search the run-local deferred catalog or activate one exact tool."""
    if _state is None:
        return "Cannot search or activate tools: no run context available."

    refresh_catalog = _state.metadata.get("_refresh_deferred_tool_catalog")
    if callable(refresh_catalog):
        try:
            refresh_catalog()
        except Exception as exc:  # noqa: BLE001 - discovery must degrade safely
            logger.warning("deferred_tool_catalog_refresh_failed error={}", exc)

    raw_catalog = _state.metadata.get("deferred_tool_catalog") or {}
    catalog = {
        str(name): entry
        for name, entry in raw_catalog.items()
        if isinstance(name, str) and isinstance(entry, DeferredToolEntry)
    }

    requested_names = list(
        dict.fromkeys(
            [*(tool_names or []), *([tool_name] if tool_name is not None else [])]
        )
    )
    if requested_names:
        unavailable = [name for name in requested_names if name not in catalog]
        if unavailable:
            if len(unavailable) == 1:
                missing = unavailable[0]
                return (
                    f"'{missing}' is not a deferred tool; it is not available "
                    "in this session. Search again with query."
                )
            return (
                "These names are not deferred tools available in this session: "
                f"{', '.join(unavailable)}. Search again with query."
            )
        activated = _state.metadata.setdefault("activated_deferred_tools", set())
        newly_activated = [name for name in requested_names if name not in activated]
        activated.update(newly_activated)
        if not newly_activated:
            return "Requested tools are already available: " + ", ".join(
                requested_names
            )
        logger.info("deferred_tools_activated names={}", newly_activated)
        return "These tools are now available on your next turn: " + ", ".join(
            newly_activated
        )

    if not catalog:
        return "No deferred tools are available in this session."

    if not query or not query.strip():
        return "Deferred tool names: " + ", ".join(sorted(catalog))

    # Aliases widen what matches; the model is only ever shown the summary.
    intent_by_name = {
        name: _tokenise(f"{name} {' '.join(entry.aliases)}")
        for name, entry in catalog.items()
    }
    vocabulary = frozenset().union(*intent_by_name.values())

    terms = _query_terms(query, vocabulary)
    ranked: list[tuple[int, str, str]] = []
    for name, entry in catalog.items():
        intent_terms = intent_by_name[name]
        summary_only = _tokenise(entry.summary) - intent_terms
        score = _INTENT_MATCH_WEIGHT * len(terms & intent_terms) + len(
            terms & summary_only
        )
        if score:
            ranked.append((score, name, entry.summary))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    if not ranked:
        return f"No deferred tools matched {query!r}. Try broader capability keywords."
    lines = ["Matching deferred tools:"]
    lines.extend(f"- {name}: {summary}" for _, name, summary in ranked[:10])
    lines.append("Activate matches with load_tool(tool_names=['<exact name>', ...]).")
    return "\n".join(lines)
