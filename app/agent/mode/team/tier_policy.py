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
import re
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
        "bg",
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


# ── Deferred-tool visibility ─────────────────────────────────────────────

_BROWSER_SIGNAL_RE = re.compile(
    r"(?:https?://|\blocalhost(?::\d+)?\b|\b127\.0\.0\.1(?::\d+)?\b|"
    r"\b(?:browser|chrome|firefox|playwright|selenium|screenshot|viewport|"
    r"responsive|website|web[ -]?app|front[ -]?end|dom|visual[ -]?regression)\b)",
    re.IGNORECASE,
)

BROWSER_SIGNAL_REVEALED_TOOLS: frozenset[str] = frozenset(
    {"browser_use", "preview"}
)


def request_has_browser_signal(text: str | None) -> bool:
    """Return whether the latest request clearly needs browser capabilities."""
    return bool(text and _BROWSER_SIGNAL_RE.search(text))


def deferred_tools_for_run(
    tools: Iterable[Tool],
    *,
    request_text: str | None = None,
    reveal_webbridge: bool = False,
) -> frozenset[str]:
    """Resolve metadata-driven deferred names for one team-agent run.

    Browser automation and preview are revealed automatically for a clear
    browser/UI request. WebBridge is only auto-revealed for its tagged session.
    Hard exclusions are applied separately and still win after this step.
    """
    tool_list = tuple(tools)
    if not any(tool.name == "load_tool" for tool in tool_list):
        return frozenset()
    deferred = {
        tool.name for tool in tool_list if getattr(tool, "deferred", False)
    }
    if request_has_browser_signal(request_text):
        deferred.difference_update(BROWSER_SIGNAL_REVEALED_TOOLS)
    if reveal_webbridge:
        deferred.discard("webbridge")
    return frozenset(deferred)


# ── WebBridge session scoping ─────────────────────────────────────────────
# A normal chat can enable WebBridge through the composer; the capability is
# persisted as the "webbridge" ChatSession tag. It keeps the lead's normal
# workspace tools, but the lead must drive the web ONLY through the user's
# real browser via webbridge.
# Competing built-in and MCP browser/web backends are hard-excluded.

WEBBRIDGE_SESSION_TAG = "webbridge"

#: Built-ins that would bypass the tagged session's real-browser backend.
WEBBRIDGE_SESSION_DENIED_WEB_TOOLS: frozenset[str] = frozenset(
    {"browser_use", "web_search", "web_fetch", "image_search"}
)

#: MCP names are ``mcp_<server>_<tool>``. These markers identify browser
#: automation servers while leaving filesystem, database, and other workspace
#: MCP tools available through the normal deferred loader.
_WEBBRIDGE_MCP_BROWSER_MARKERS: tuple[str, ...] = (
    "browser",
    "chrome-devtools",
    "chrome_devtools",
    "chromedevtools",
    "devtools",
    "playwright",
    "puppeteer",
    "selenium",
)


def webbridge_session_excluded_tools(tool_names: Iterable[str]) -> frozenset[str]:
    """Return the lead's ``excluded_tools`` set for a WebBridge-tagged session.

    Workspace, coding, user-interaction, and non-browser MCP tools remain
    available. Competing web backends are excluded so browser interaction can
    only use ``webbridge``. The call site applies this policy to every team
    member, so normal workspace delegation cannot bypass the browser routing.
    """
    denied = set(WEBBRIDGE_SESSION_DENIED_WEB_TOOLS)
    for name in tool_names:
        lowered = name.casefold()
        if lowered.startswith("mcp_") and any(
            marker in lowered for marker in _WEBBRIDGE_MCP_BROWSER_MARKERS
        ):
            denied.add(name)
    return frozenset(denied)



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
