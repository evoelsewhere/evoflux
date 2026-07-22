"""load_tool — unlocks a deferred, heavy/narrow-purpose tool for this run.

A handful of tools (browser automation, AIM, LSP, PR creation, ...) are
excluded from ``tool_defs`` by default — see
:data:`app.agent.mode.team.tier_policy.DEFAULT_DEFERRED_TOOLS` — to keep the
per-call tool-definition overhead down for the common case where a turn
never touches them. This tool reveals one of them for the rest of the
current run, the same two-step shape as ``skill``: call ``load_tool`` first,
then call the real tool on the next turn once it appears in ``tool_defs``.

Activation only ever *reveals* a tool the agent was already granted — a name
that was hard-denied (team tier restriction, WebBridge-session scoping) was
already removed from the run-local tool lookup before this tool ever runs,
so calling ``load_tool`` on it is a harmless no-op, never a bypass.
"""

from __future__ import annotations

from typing import Annotated, Any

from loguru import logger
from pydantic import Field

from app.agent.tools.registry import InjectedArg, tool

# Catalog is intentionally static (no per-run filtering) — Tool descriptions
# are plain no-arg callables with no access to this run's tool lookup. A name
# not actually granted to this agent just fails closed in load_tool() below.
#
# Keys here must exactly match tier_policy.DEFAULT_DEFERRED_TOOLS — enforced
# by tests/agent/mode/team/test_tier_policy.py's
# TestDefaultDeferredTools.test_catalog_matches_default_deferred_tools, not by
# an import-time assertion: tier_policy.py lives under app.agent.mode.team,
# whose package __init__ eagerly imports member.py -> Agent (agent_loop), so
# importing tier_policy from here at module load time is a circular import
# (app.agent.tools.builtin -> load_tool -> tier_policy -> mode.team -> member
# -> agent_loop -> app.agent.tools.registry, whose parent package is this
# same partially-initialized app.agent.tools).  A drifted name here fails
# closed at runtime (load_tool rejects it, never a crash) and loudly in CI.
_CATALOG: dict[str, str] = {
    "browser_use": "Drive a headless browser — navigate, click, type, extract page content.",
    "webbridge": "Drive the user's own real browser via the WebBridge extension.",
    "aim_units": "List/inspect AIM migration units (legacy code comprehension mode).",
    "aim_compare": "Run a functional-equivalence compare between legacy and migrated code.",
    "terminal_run": "Send a command to the interactive AI terminal session.",
    "worktree_start": "Create an isolated git worktree for parallel/experimental work.",
    "worktree_finish": "Merge or discard a worktree created by worktree_start.",
    "lsp_diagnostics": "Get compiler/linter diagnostics for a file via the language server.",
    "lsp_definition": "Jump to a symbol's definition via the language server.",
    "lsp_references": "Find all references to a symbol via the language server.",
    "visualize_read_me": "Load design context needed before rendering a diagram/mockup widget.",
    "show_widget": "Render an SVG/HTML visualization inline in the chat.",
    "create_pull_request": "Open a pull request for the current branch.",
    "schedule_task": "Schedule a reminder or recurring task.",
}


def _load_tool_description() -> str:
    lines = [
        "Unlock a deferred tool not currently in your tool list, making it callable on your next turn.",
        "Use this only when you actually need one of the tools below — most turns never need any of them.",
        "",
        "## Deferred tools",
    ]
    lines += [f"- **{name}**: {desc}" for name, desc in sorted(_CATALOG.items())]
    return "\n".join(lines)


@tool(name="load_tool", description=_load_tool_description)
async def load_tool(
    tool_name: Annotated[
        str,
        Field(description="Name of the deferred tool to unlock, from the list in this tool's description."),
    ],
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Unlock a deferred tool for the rest of this run."""
    if tool_name not in _CATALOG:
        return (
            f"'{tool_name}' is not a deferred tool. Available: {sorted(_CATALOG)}"
        )
    if _state is None:
        # No run context to check grants against or record activation in —
        # nothing was actually unlocked, so don't claim success.
        return f"Cannot activate '{tool_name}': no run context available."
    if tool_name not in _state.tool_names:
        return (
            f"'{tool_name}' is not available in this session "
            "(not granted for your current role/mode)."
        )
    activated = _state.metadata.setdefault("activated_deferred_tools", set())
    activated.add(tool_name)
    logger.info("deferred_tool_activated name={}", tool_name)
    return f"'{tool_name}' is now available — call it directly on your next turn."
