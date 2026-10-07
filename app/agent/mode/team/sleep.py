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

from typing import Annotated, Any

from app.agent.tools.registry import InjectedArg, Tool

_DESCRIPTION = """\
End your turn and wait for the next message. Takes no arguments.

Call `sleep` when you have nothing to send this turn: you are waiting for a \
teammate's reply or a dependency, you have no task to claim, or your work is \
finished. It may accompany other tool calls in the same turn — they run first. \
Never write text to announce that you are waiting; just call `sleep`.\
"""


def make_sleep_tool() -> Tool:
    """Return the ``sleep`` tool. Injected for every team agent."""

    async def sleep(_state: Annotated[Any, InjectedArg()] = None) -> str:
        if _state is not None:
            # Same contract as a final ``team_handoff``: stop after this turn's
            # tool results are persisted instead of making another model call.
            _state.metadata["stop_after_tool_call"] = "sleep"
        return "Sleeping until the next message."

    return Tool(sleep, name="sleep", description=_DESCRIPTION)
