"""``terminal_run`` — let the lead run a command in the session's LIVE shared
terminal (the same PTY the user has open), so agent and user share one shell.

Unlike the ``shell`` tool (a fresh sandboxed subprocess per call), this drives
the persistent interactive shell from :mod:`app.services.terminal_service`:
the user watches the command run in real time, output scrolls in their
terminal panel, and it shares that shell's cwd/env/history. The captured
output is returned to the agent too. Lead-only, because the shared terminal is
the user-facing session's single shell.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.agent.sandbox import get_sandbox
from app.agent.state import AgentState
from app.agent.tools.registry import InjectedArg, Tool
from app.services.terminal_service import terminal_manager


async def _terminal_run(
    command: Annotated[
        str, Field(description="The shell command to run in the shared terminal.")
    ],
    timeout_s: Annotated[
        int,
        Field(
            description=(
                "Max seconds to wait for output before returning (default 60). "
                "A long-running command returns the output so far at timeout; "
                "it keeps running in the terminal."
            ),
            ge=1,
            le=600,
        ),
    ] = 60,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Run a command in the user's live shared terminal and return its output.

    Use this (instead of ``shell``) when the user should SEE the command run —
    it executes in the terminal panel's own interactive shell, sharing its
    working directory and environment. Assumes that shell is at a prompt (not
    inside a full-screen program like vim); for scripted/background work that
    the user doesn't need to watch, prefer ``shell``.
    """
    sandbox = get_sandbox()
    session_id = sandbox.session_id or (
        _state.metadata.get("session_id") if _state else None
    )
    if not session_id:
        return "Cannot open a terminal: no session is bound to this workspace."

    mode = _state.metadata.get("mode") if _state else None
    env = {"EVOFLUX_MODE": mode} if isinstance(mode, str) and mode else None
    # Reuses the user's already-open shell if there is one; otherwise spawns
    # one in this workspace so the user can watch (and take over) afterwards.
    terminal_manager.attach(session_id, cwd=str(sandbox.workspace_root), env=env)
    output = await terminal_manager.run_command(
        session_id, command, timeout_s=float(timeout_s)
    )
    return output.strip() or "(command produced no output)"


terminal_run = Tool(
    _terminal_run,
    name="terminal_run",
    lead_only=True,
    description=(
        "Run a shell command in the user's LIVE shared terminal (the same PTY "
        "the user has open): the user watches it run and it shares that shell's "
        "cwd/env/history. Returns the command output. Use when the user should "
        "see the command; use the plain `shell` tool for silent/background work."
    ),
)
