"""Background command tasks tell the agent about themselves.

A command started with ``shell(background=true)`` outlives the tool call that
launched it. Instead of making the model poll it, the task *announces* itself:
when it exits, or when its output matches the ``notify_on`` pattern the agent
supplied, a short notice is delivered to the session's lead through the team
mailbox. The mailbox already does the two things this needs:

* a lead that is mid-turn receives the notice before its next model call
  (``TeamInboxHook``), so it can keep working while a build runs and learn the
  result the moment it lands;
* an idle lead is woken for a new turn, so a build that finishes after the
  agent has stopped talking still reaches it.

This module only formats notices and decides whether one may be sent. It does
not import the process or team modules at import time, so either can use it.
"""

from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

if TYPE_CHECKING:
    from app.agent.tools.builtin.process import TrackedProcess

TaskEventKind = Literal["exited", "matched"]

#: Sender name carried on the mailbox message and the persisted transcript row.
TASK_EVENT_SENDER = "background_task"

# A task that prints its trigger line in a loop must not wake the agent in a
# loop. Matches are capped per task and per session; exits are one per task
# and are never dropped.
MAX_MATCH_NOTICES_PER_TASK = 5
_MATCH_WINDOW_SECONDS = 600.0
_MAX_MATCH_NOTICES_PER_WINDOW = 20
_MIN_SECONDS_BETWEEN_MATCHES = 2.0

_EXIT_OUTPUT_MAX_BYTES = 6_000
_EXIT_FAILURE_OUTPUT_MAX_BYTES = 12_000

_recent_matches: dict[str, deque[float]] = {}


def _match_budget_left(session_id: str, *, now: float) -> bool:
    window = _recent_matches.setdefault(session_id, deque())
    while window and now - window[0] > _MATCH_WINDOW_SECONDS:
        window.popleft()
    if window and now - window[-1] < _MIN_SECONDS_BETWEEN_MATCHES:
        return False
    return len(window) < _MAX_MATCH_NOTICES_PER_WINDOW


def reset_task_notice_budget() -> None:
    """Forget the per-session match budget (tests)."""

    _recent_matches.clear()


def format_task_notice(
    tracked: "TrackedProcess",
    kind: TaskEventKind,
    *,
    matched_line: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return the notice text for the model and the structured event for the UI."""

    from app.agent.tools.builtin.process import (
        _read_artifact_preview,
        _status_label,
    )

    command = (
        tracked.command
        if len(tracked.command) <= 200
        else (tracked.command[:197] + "...")
    )
    event: dict[str, Any] = {
        "kind": "task_event",
        "task_event": kind,
        "process_id": tracked.process_id,
        "command": command,
        "status": tracked.status,
        "exit_code": tracked.exit_code,
        "duration_ms": round(tracked.elapsed_seconds * 1000),
        "artifact": str(tracked.output_path),
    }

    if kind == "matched":
        line = (matched_line or "").strip()
        event["matched_line"] = line[:500]
        text = "\n".join(
            [
                f"[Background task {tracked.process_id} printed a line you asked "
                "to be told about]",
                f"command: {command}",
                f"line: {line[:500]}",
                f"The task is still running. Output so far: {tracked.output_path}",
            ]
        )
        return text, event

    failed = tracked.timed_out or tracked.exit_code != 0
    limit = _EXIT_FAILURE_OUTPUT_MAX_BYTES if failed else _EXIT_OUTPUT_MAX_BYTES
    output, total, omitted = _read_artifact_preview(tracked.output_path, limit)
    label = _status_label(
        exit_code=tracked.exit_code,
        timed_out=tracked.timed_out,
        running=False,
    )
    lines = [
        f"[Background task {tracked.process_id} finished: {label}]",
        f"command: {command}",
        f"duration: {tracked.elapsed_seconds:.1f}s",
        "",
        output or "(No output)",
    ]
    if omitted:
        lines.extend(["", f"Full output: {tracked.output_path} ({total:,} bytes)"])
    return "\n".join(lines), event


async def announce_task_event(
    tracked: "TrackedProcess",
    kind: TaskEventKind,
    *,
    matched_line: str | None = None,
) -> bool:
    """Deliver a notice about *tracked* to its session's lead.

    Returns whether a notice was handed to the team. A task without a session,
    a session without a live team, and a match over budget all return ``False``
    without raising: an announcement is a courtesy and must never fail a task.
    """

    session_id = tracked.session_id
    if not session_id:
        return False
    if kind == "matched":
        now = time.monotonic()
        if not _match_budget_left(session_id, now=now):
            logger.debug(
                "background_task_match_suppressed process_id={}", tracked.process_id
            )
            return False
        _recent_matches[session_id].append(now)

    try:
        from app.services.team_manager import find_team_for_session

        team = find_team_for_session(session_id)
        if team is None:
            return False
        text, event = format_task_notice(tracked, kind, matched_line=matched_line)
        await team.deliver_background_task_event(text, event)
    except Exception as exc:  # noqa: BLE001 - never fail the task over a notice
        logger.warning(
            "background_task_announce_failed process_id={} kind={} error={}",
            tracked.process_id,
            kind,
            exc,
        )
        return False
    logger.info(
        "background_task_announced process_id={} kind={} session_id={}",
        tracked.process_id,
        kind,
        session_id,
    )
    return True
