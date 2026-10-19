"""Suggest the user's next message as ghost text in the chat composer.

Unlike ``spawn_task`` this tool never blocks and creates no durable row: it
publishes one ephemeral ``next_message_suggestion`` event and the turn
continues. The UI shows the message as ghost text in the chat input — the
user accepts it, types their own message instead, or dismisses it.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from app.agent.next_message_suggestion_status import (
    publish_next_message_suggestion,
)
from app.agent.tools.registry import InjectedArg, Tool


def _session_id(state: Any) -> str:
    metadata = state.metadata if state is not None else {}
    raw = metadata.get("stream_session_id") or metadata.get("session_id")
    if not raw:
        raise ValueError("suggest_next_message requires an active session.")
    return str(raw)


async def _suggest_next_message(
    message: Annotated[
        str,
        Field(
            description=(
                "The suggested next user message: a short imperative "
                "sentence the user can send as-is, written in the user's "
                "voice, e.g. 'write tests for the change'."
            )
        ),
    ],
    reason: Annotated[
        str,
        Field(
            description=(
                "Optional one-line justification shown to the user, "
                "e.g. 'the change has no test coverage yet'."
            )
        ),
    ] = "",
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Suggest the user's next message as ghost text in the chat input.

    Call this near the end of a turn, only when a genuinely useful next
    step exists — after finishing a task, after a diagnosis the user must
    decide on. Never call it every turn, and never instead of doing work
    the user already asked for.
    """
    text = message.strip()
    if not text:
        return "[Error] message must not be empty."
    try:
        session_id = _session_id(_state)
    except ValueError as exc:
        return f"[Error] {exc}"
    await publish_next_message_suggestion(session_id, text, reason=reason.strip())
    return "Next-message suggestion published."


suggest_next_message = Tool(
    _suggest_next_message,
    name="suggest_next_message",
    tiers=("coding",),
    lead_only=False,
    description=(
        "Suggest the user's next message as ghost text in the chat input. "
        "Call near the end of a turn only when a genuinely useful next step "
        "exists. Non-blocking — the turn continues."
    ),
)
