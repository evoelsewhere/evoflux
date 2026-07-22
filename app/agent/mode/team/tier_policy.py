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
from typing import Literal

from loguru import logger

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
) -> frozenset[str]:
    """Return the set of tool names denied for *tier*.

    Returns an empty frozenset for unknown or ``None`` tiers (full access).
    """
    if tier is None:
        return frozenset()
    return TIER_DENIED_TOOLS.get(tier, frozenset())


# ── Default-deferred tools ────────────────────────────────────────────────
# Heavy or narrow-purpose tools whose full schema is excluded from every
# agent's tool_defs by default — lead included — to cut baseline per-call
# token overhead. Unlike TIER_DENIED_TOOLS (a hard, unbypassable block),
# these stay reachable: the agent calls ``load_tool`` to unlock one for the
# rest of the current run. A name here has no effect if the tool was already
# hard-denied (tier or WebBridge-session scoping already popped it from
# run_tools) — activation can only reveal a tool that construction-time /
# tier rules already granted, never bypass them.
DEFAULT_DEFERRED_TOOLS: frozenset[str] = frozenset(
    {
        "browser_use",
        "webbridge",
        "aim_units",
        "aim_compare",
        "terminal_run",
        "worktree_start",
        "worktree_finish",
        "lsp_diagnostics",
        "lsp_definition",
        "lsp_references",
        "visualize_read_me",
        "show_widget",
        "create_pull_request",
        "schedule_task",
    }
)


# ── WebBridge session scoping ─────────────────────────────────────────────
# A session created from the WebBridge UI is tagged "webbridge" (persisted on
# ChatSession.tags). In such a session the lead must drive the web ONLY
# through the user's real browser via the webbridge tool — browser_use,
# web_search, web_fetch, image_search and every other registry tool are
# excluded, leaving just the small user-facing allowlist below.

WEBBRIDGE_SESSION_TAG = "webbridge"

#: Tools the team lead keeps in a WebBridge-tagged session: the webbridge
#: tool itself plus user-interaction / coordination basics (no web access).
WEBBRIDGE_SESSION_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {"webbridge", "ask_user", "todo_manage", "note", "date"}
)

#: Lead-only team-coordination tools additionally denied in a WebBridge
#: session. These are NOT registry tools — AgentTeam.get_injected_tools
#: builds them per run — so a registry-minus-allowlist computation alone
#: would leave the lead able to spawn and delegate to members that are not
#: webbridge-scoped. Excluding them keeps a tagged session lead-only.
WEBBRIDGE_SESSION_DENIED_TEAM_TOOLS: frozenset[str] = frozenset(
    {"team_manage", "team_delegate", "team_reject"}
)


def webbridge_session_excluded_tools(tool_names: Iterable[str]) -> frozenset[str]:
    """Return the lead's ``excluded_tools`` set for a WebBridge-tagged session.

    *tool_names* is the full set of tool names the lead would normally run
    with (in practice its registry-granted constructor tools — MCP tools
    included — i.e. ``agent._tools`` keys). Everything outside
    :data:`WEBBRIDGE_SESSION_ALLOWED_TOOLS` is excluded, plus the injected
    roster/delegation tools in :data:`WEBBRIDGE_SESSION_DENIED_TEAM_TOOLS`
    so no members can be spawned. Loader-managed lead tools that survive the
    allowlist (todo_manage, note) are harmless; schedule_task and skill are
    excluded like any other non-allowlisted name.
    """
    return (
        frozenset(tool_names) - WEBBRIDGE_SESSION_ALLOWED_TOOLS
    ) | WEBBRIDGE_SESSION_DENIED_TEAM_TOOLS



# ── Side Chat session scoping ─────────────────────────────────────────────
# A side chat is tagged "side_chat" (persisted on ChatSession.tags, same
# mechanism as WEBBRIDGE_SESSION_TAG). It has its own dedicated team instance
# (team_manager keys teams by session_id), so tagging it never affects the
# main session's tools. Read-only: no file writes, no shell/code execution,
# no team coordination or side-effecting tools.
SIDE_CHAT_SESSION_TAG = "side_chat"

SIDE_CHAT_EXCLUDED_TOOLS: frozenset[str] = frozenset(
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
        "skill",  # Skills may have side effects
        "todo_manage",  # May modify todo state
        "team_message",  # May send messages to team
        "team_handoff",  # May send handoffs
        "team_state",  # May modify shared state
        "team_delegate",  # May delegate work
        "team_reject",  # May reject work
        "create_pull_request",  # May create PRs
        "show_widget",  # May render widgets
        "visualize_read_me",  # May render visualizations
    }
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
