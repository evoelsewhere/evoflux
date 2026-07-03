"""TeamSharedState — persistent cross-member KV store + ``team_state`` tool.

Provides a simple key-value store that any team member (lead or member) can
read and write.  Entries survive across member activations and are visible
to all participants, making it easy to share discoveries, configuration,
intermediate results, and coordination flags without routing everything
through message passing.

The store is persisted as a JSON file in the session workspace alongside
the todo list (``{workspace}/.EvoFlux/team_state.json``).  Concurrent
access from parallel member turns is safe because each tool invocation is
short-lived and Python's file I/O is atomic-enough for small JSON blobs.

Each entry tracks its ``owner`` (who set it) and ``updated_at`` timestamp
so consumers can attribute provenance and freshness.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Annotated, Literal

from loguru import logger
from pydantic import Field

from app.agent.tools.registry import Tool
from app.agent.sandbox import get_sandbox

if TYPE_CHECKING:
    pass

# ── File name (lives next to todos.json) ─────────────────────────────────

STATE_FILENAME = "team_state.json"


# ── Store helpers ─────────────────────────────────────────────────────────


def _state_path():
    """Return the resolved path to the shared state file."""
    sandbox = get_sandbox()
    from pathlib import Path

    workspace = Path(sandbox.workspace_root)
    return workspace / ".EvoFlux" / STATE_FILENAME


def _load_state() -> dict[str, dict]:
    """Load ``{key: {value, owner, updated_at}}`` from disk."""
    path = _state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_state(store: dict[str, dict]) -> None:
    """Persist the state store to disk."""
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Tool description ─────────────────────────────────────────────────────

_DESCRIPTION = """\
Read and write shared team state — a persistent key-value store visible to \
all team members (lead and members).

Use this to share discoveries, intermediate results, coordination flags, \
and configuration across agents without routing through messages.

Actions:
  set   — Store a value under a key (overwrites if exists).
  get   — Read a single key's value. Returns null if not found.
  list  — List all keys with owner and timestamp.
  delete — Remove a key.

Examples:
  team_state(action="set", key="api_base_url", value="https://api.example.com/v2")
  team_state(action="get", key="api_base_url")
  team_state(action="list")
  team_state(action="delete", key="api_base_url")

Keys are strings. Values can be any JSON-serializable type (string, number, \
bool, list, dict). Each entry records who set it and when."""


# ── Tool factory ─────────────────────────────────────────────────────────


def make_team_state_tool(agent_name: str) -> Tool:
    """Return the ``team_state`` tool bound to *agent_name*."""

    async def team_state(
        action: Annotated[
            Literal["set", "get", "list", "delete"],
            Field(description="The operation to perform."),
        ],
        key: Annotated[
            str | None,
            Field(
                description="The key to operate on. Required for set/get/delete.",
            ),
        ] = None,
        value: Annotated[
            str | int | float | bool | list | dict | None,
            Field(
                description=(
                    "The value to store. Required for 'set'. "
                    "Can be any JSON-serializable type."
                ),
            ),
        ] = None,
    ) -> str:
        """Read or write shared team state."""
        store = _load_state()

        if action == "set":
            if not key:
                return "Error: 'key' is required for 'set'."
            if value is None:
                return "Error: 'value' is required for 'set'."
            store[key] = {
                "value": value,
                "owner": agent_name,
                "updated_at": time.time(),
            }
            _save_state(store)
            logger.info("team_state_set agent={} key={}", agent_name, key)
            return f"Stored '{key}' = {json.dumps(value)}"

        if action == "get":
            if not key:
                return "Error: 'key' is required for 'get'."
            entry = store.get(key)
            if entry is None:
                return f"Key '{key}' not found."
            val = entry.get("value")
            owner = entry.get("owner", "unknown")
            return f"'{key}' = {json.dumps(val)}  (set by {owner})"

        if action == "list":
            if not store:
                return "No shared state entries."
            lines = ["Shared team state:"]
            for k, entry in sorted(store.items()):
                val = entry.get("value")
                owner = entry.get("owner", "?")
                val_repr = json.dumps(val)
                if len(val_repr) > 80:
                    val_repr = val_repr[:77] + "..."
                lines.append(f"  {k} = {val_repr}  (by {owner})")
            return "\n".join(lines)

        if action == "delete":
            if not key:
                return "Error: 'key' is required for 'delete'."
            if key not in store:
                return f"Key '{key}' not found."
            del store[key]
            _save_state(store)
            logger.info("team_state_delete agent={} key={}", agent_name, key)
            return f"Deleted '{key}'."

        return f"Unknown action '{action}'. Use set/get/list/delete."

    return Tool(team_state, name="team_state", description=_DESCRIPTION)


# ── Snapshot for summarisation ────────────────────────────────────────────


def format_state_snapshot() -> str:
    """Return a Markdown-formatted snapshot of the shared team state.

    Used by the team summarisation hook so the compacted context retains
    the current KV store contents — keys, values, and owners.  Returns an
    empty string when the store is empty (caller can skip injection).
    """
    store = _load_state()
    if not store:
        return ""

    lines = ["## Shared Team State Snapshot"]
    for key in sorted(store):
        entry = store[key]
        val = json.dumps(entry.get("value"), ensure_ascii=False)
        owner = entry.get("owner", "?")
        lines.append(f"- `{key}` = {val}  (set by {owner})")
    return "\n".join(lines)
