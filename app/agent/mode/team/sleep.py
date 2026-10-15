"""``sleep`` — end the turn and wait for the next message.

An agent that is idle, waiting on a peer or a dependency, or finished calls
``sleep`` instead of writing text. The tool takes no arguments: the runtime
stops the loop once the turn's tool results are persisted, and the agent wakes
when a teammate or the user next writes to it.

Waiting is a tool call rather than a magic string in the reply so that it goes
through the same schema, validation and transcript path as every other action —
a model cannot misspell it, a provider cannot strip it as text, and nothing has
to parse assistant prose to learn that the agent is done.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from loguru import logger

from app.agent.tools.registry import InjectedArg, Tool

_DESCRIPTION = """\
End your turn and wait for the next message. Takes no arguments.

Call `sleep` when you have nothing to send this turn: you are waiting for a \
teammate's reply or a dependency, you have no task to claim, or your work is \
finished. It may accompany other tool calls in the same turn — they run first. \
Never write text to announce that you are waiting; just call `sleep`.\
"""

_GUARD_REFUSALS_KEY = "sleep_guard_refusals"
# A guard that cannot be satisfied must not be able to keep the turn alive
# forever: after this many refusals in one run the yield goes through and the
# team layer's post-stop nudge owns the correction instead.
_MAX_GUARD_REFUSALS = 2


async def _evaluate_guard(
    guard: Callable[[], Awaitable[str | None]],
    state: Any,
) -> str | None:
    """Return the reason to refuse this yield, or ``None`` to allow it.

    ``guard`` is team-owned policy (see ``make_sleep_tool``): it returns the
    outstanding work as text, which is handed back to the model as the tool
    result so it can act on it this turn.
    """
    try:
        reason = await guard()
    except Exception as exc:  # a broken guard must not trap the agent
        logger.warning("sleep_guard_failed error={}", exc)
        return None
    if not reason:
        return None
    metadata = getattr(state, "metadata", None)
    if not isinstance(metadata, dict):
        # No run state to count refusals against: allow the yield rather than
        # risk looping.
        logger.warning("sleep_guard_suppressed reason=no_state")
        return None
    refusals = int(metadata.get(_GUARD_REFUSALS_KEY, 0))
    if refusals >= _MAX_GUARD_REFUSALS:
        logger.warning("sleep_guard_suppressed refusals={}", refusals)
        return None
    metadata[_GUARD_REFUSALS_KEY] = refusals + 1
    logger.warning("sleep_guard_blocked refusals={}", refusals + 1)
    return reason


def make_sleep_tool(
    guard: Callable[[], Awaitable[str | None]] | None = None,
) -> Tool:
    """Return the ``sleep`` tool. Injected for every team agent.

    ``guard`` is the optional policy check for this agent. It returns the work
    still owed (blocking the yield and reporting it back to the model) or
    ``None`` to let the agent sleep. Refusals are capped per run by
    ``_MAX_GUARD_REFUSALS``, so the tool can never be turned into a trap.
    """

    async def sleep(_state: Annotated[Any, InjectedArg()] = None) -> str:
        if guard is not None:
            refusal = await _evaluate_guard(guard, _state)
            if refusal is not None:
                return refusal
        if _state is not None:
            # Same contract as a final ``team_handoff``: stop after this turn's
            # tool results are persisted instead of making another model call.
            _state.metadata["stop_after_tool_call"] = "sleep"
        return "Sleeping until the next message."

    return Tool(sleep, name="sleep", description=_DESCRIPTION)
