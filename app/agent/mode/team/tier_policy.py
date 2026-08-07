"""Tier-based tool access policies for team members.

Each todo task has a ``tier`` (trivial / simple / multi_step / complex) that
controls the breadth of tools exposed to the assigned agent.  Lower tiers
restrict heavy tools so that simple tasks cannot accidentally invoke shell,
browser, or write operations.

Tier policies
-------------
* **trivial** — read-only + team coordination tools.  No file writes, no
  shell, no code execution.
* **simple** — standard coding tools.  No browser or scheduled tasks.
* **multi_step** — full agent tools (no restrictions).
* **complex** — full agent tools (no restrictions).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal

from loguru import logger

if TYPE_CHECKING:
    from app.agent.tools import Tool

# ── Denied-tool sets per tier ─────────────────────────────────────────────
# Each set lists tool *names* that a member should NOT have access to when
# working at the given tier.  ``frozenset()`` means "no restrictions".

_TRIVIAL_DENIED: frozenset[str] = frozenset(
    {
        "write",
        "edit",
        "patch",
        "rm",
        "shell",
        "process",
        "python",
        "browser_use",
        "webbridge",
        "schedule_task",
        "skill",
    }
)

_SIMPLE_DENIED: frozenset[str] = frozenset(
    {
        "browser_use",
        "webbridge",
        "schedule_task",
    }
)

TIER_DENIED_TOOLS: dict[str, frozenset[str]] = {
    "trivial": _TRIVIAL_DENIED,
    "simple": _SIMPLE_DENIED,
    "multi_step": frozenset(),
    "complex": frozenset(),
}


def denied_tools_for_tier(
    tier: Literal["trivial", "simple", "multi_step", "complex"] | str | None,
    tools: Iterable[Tool] = (),
) -> frozenset[str]:
    """Return the set of tool names denied for *tier*.

    Returns an empty frozenset for unknown or ``None`` tiers (full access).
    """
    if tier is None:
        return frozenset()
    denied = TIER_DENIED_TOOLS.get(tier, frozenset())
    if tier == "trivial":
        # Trivial tasks are read-only by contract. Derive this part from tool
        # metadata so newly registered built-ins, plugins, and MCP tools fail
        # closed without another hand-maintained name list. Injected team
        # coordination tools are intentionally not passed by the call site.
        denied |= frozenset(
            tool.name for tool in tools if not getattr(tool, "read_only", False)
        )
    return denied


def deferred_tools_for_run(
    tools: Iterable[Tool],
    *,
    reveal_webbridge: bool = False,
) -> frozenset[str]:
    """Resolve metadata-driven deferred names for one team-agent run.

    Deferred tools remain hidden until the model activates them through
    ``load_tool``. WebBridge is auto-revealed only from its explicit session
    tag. Hard exclusions are applied separately and still win after this step.
    """
    tool_list = tuple(tools)
    if not any(tool.name == "load_tool" for tool in tool_list):
        return frozenset()
    deferred = {tool.name for tool in tool_list if getattr(tool, "deferred", False)}
    if reveal_webbridge:
        deferred.discard("webbridge")
    return frozenset(deferred)


# ── WebBridge session scoping ─────────────────────────────────────────────
# A normal chat can enable WebBridge through the composer; the capability is
# persisted as the "webbridge" ChatSession tag. It keeps the lead's normal
# workspace tools, but the lead must drive the web ONLY through the user's
# real browser via webbridge.
# Competing built-in and MCP browser/web backends are hard-excluded.

#: Built-ins that would bypass the tagged session's real-browser backend.
WEBBRIDGE_SESSION_DENIED_WEB_TOOLS: frozenset[str] = frozenset(
    {"browser_use", "web_search", "web_fetch", "image_search"}
)


def webbridge_session_excluded_tools(tools: Iterable[Tool]) -> frozenset[str]:
    """Return the lead's ``excluded_tools`` set for a WebBridge-tagged session.

    Workspace, coding, user-interaction, and non-browser MCP tools remain
    available. Competing web backends are excluded so browser interaction can
    only use ``webbridge``. The call site applies this policy to every team
    member, so normal workspace delegation cannot bypass the browser routing.
    """
    denied = set(WEBBRIDGE_SESSION_DENIED_WEB_TOOLS)
    for tool in tools:
        capabilities = getattr(tool, "capabilities", frozenset())
        if "browser" in capabilities or (
            getattr(tool, "origin", "builtin") == "mcp"
            and "webbridge-safe" not in capabilities
        ):
            denied.add(tool.name)
    return frozenset(denied)


# WebBridge is an explicit composer mode, not the default browser backend.
# Keeping it out of ordinary sessions prevents ``load_tool`` from selecting
# the extension when the user expects EvoFlux's visible in-app browser.
NON_WEBBRIDGE_SESSION_DENIED_TOOLS: frozenset[str] = frozenset({"webbridge"})


# ── Side Chat session scoping ─────────────────────────────────────────────
# A side chat is tagged "side_chat" (persisted on ChatSession.tags, same
# mechanism as WEBBRIDGE_SESSION_TAG). It has its own dedicated team instance
# (team_manager keys teams by session_id), so tagging it never affects the
# main session's tools. Read-only: no file writes, no shell/code execution,
# no team coordination or side-effecting tools.
SIDE_CHAT_SESSION_TAG = "side_chat"

SIDE_CHAT_ALWAYS_EXCLUDED_TOOLS: frozenset[str] = frozenset(
    {
        "todo_manage",
        "team_manage",
        "team_message",
        "team_handoff",
        "team_state",
        "team_delegate",
        "team_reject",
        "team_worktree",
        "show_widget",
        "visualize_read_me",
    }
)


def side_chat_session_excluded_tools(tools: Iterable[Tool]) -> frozenset[str]:
    """Return tools that must not run in a read-only side-chat session.

    Tool access is deny-by-default: only tools explicitly declaring
    ``read_only=True`` survive. This also blocks newly registered, plugin, and
    MCP tools unless they opt into the read-only contract. Team coordination
    and presentation tools are always excluded even if their metadata changes.
    """
    return frozenset(
        tool.name
        for tool in tools
        if not getattr(tool, "read_only", False)
        or tool.name in SIDE_CHAT_ALWAYS_EXCLUDED_TOOLS
    )


def resolve_member_tier(agent_name: str) -> str | None:
    """Look up the highest tier among active tasks assigned to *agent_name*.

    Reads the todo store on disk.  Returns the tier string (``"trivial"``,
    ``"simple"``, ``"multi_step"``, ``"complex"``) or ``None`` when the
    agent has no assigned in-progress/pending tasks.

    When multiple tasks are assigned, the *highest* tier wins (complex >
    multi_step > simple > trivial) so the agent has the tools needed for
    its hardest task.
    """
    from app.agent.tools.builtin.todo import _load_store

    _TIER_ORDER = {"trivial": 0, "simple": 1, "multi_step": 2, "complex": 3}

    store = _load_store()
    items = store.get("items", [])

    best_tier: str | None = None
    best_rank = -1

    for item in items:
        assigned = item.get("assigned_to") or item.get("claimed_by")
        if assigned != agent_name:
            continue
        status = item.get("status", "")
        if status in ("completed", "cancelled"):
            continue
        tier = item.get("tier", "simple")
        rank = _TIER_ORDER.get(tier, 1)
        if rank > best_rank:
            best_rank = rank
            best_tier = tier

    if best_tier is not None:
        logger.debug("tier_resolved agent={} tier={}", agent_name, best_tier)

    return best_tier
