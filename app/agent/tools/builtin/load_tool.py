"""Search for and activate deferred tools for the current agent run."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any

from loguru import logger
from pydantic import BeforeValidator, Field

from app.agent.tools.registry import InjectedArg, tool


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

    raw_catalog = _state.metadata.get("deferred_tool_catalog") or {}
    catalog = {
        str(name): str(summary)
        for name, summary in raw_catalog.items()
        if isinstance(name, str)
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

    terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
    ranked: list[tuple[int, str, str]] = []
    for name, summary in catalog.items():
        haystack_terms = set(re.findall(r"[a-z0-9]+", f"{name} {summary}".casefold()))
        score = len(terms & haystack_terms)
        if score:
            ranked.append((score, name, summary))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    if not ranked:
        return f"No deferred tools matched {query!r}. Try broader capability keywords."
    lines = ["Matching deferred tools:"]
    lines.extend(f"- {name}: {summary}" for _, name, summary in ranked[:10])
    lines.append("Activate matches with load_tool(tool_names=['<exact name>', ...]).")
    return "\n".join(lines)
