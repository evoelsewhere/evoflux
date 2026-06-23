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
        "schedule_task",
        "skill",
    }
)

_SIMPLE_DENIED: frozenset[str] = frozenset(
    {
        "browser_use",
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
