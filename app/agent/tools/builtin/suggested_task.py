"""Park out-of-scope work as a chip the user can spin into its own session.

Unlike ``ask_user`` these tools never block: they write a durable row, push an
event, and return immediately so the current turn continues uninterrupted.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import Field

from app.agent.suggested_task_status import publish_suggested_task
from app.agent.tools.registry import InjectedArg, Tool
from app.core.db import resolve_db_factory
from app.services import suggested_task_service


def _session_id(state: Any) -> UUID:
    metadata = state.metadata if state is not None else {}
    raw = metadata.get("stream_session_id") or metadata.get("session_id")
    if not raw:
        raise suggested_task_service.SuggestedTaskValidationError(
            "Suggested-task tools require an active session."
        )
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise suggested_task_service.SuggestedTaskValidationError(
            "Invalid active session id."
        ) from exc


async def _spawn_task(
    title: Annotated[
        str,
        Field(
            description=(
                "Under 60 chars, imperative action phrase starting with a verb, "
                "e.g. 'Fix stale README badge', 'Remove dead config option'. "
                "Shown as the chip label and the spawned session title."
            )
        ),
    ],
    tldr: Annotated[
        str,
        Field(
            description=(
                "One or two plain-English sentences shown under the title. Lead "
                "with why you are suggesting this now — name what you noticed in "
                "this session — then say what the new session will do. No file "
                "paths or code."
            )
        ),
    ],
    prompt: Annotated[
        str,
        Field(
            description=(
                "The initial message for the spawned session. Must stand alone: "
                "include file paths, reproduction steps and observed output, "
                "because the new session cannot see this conversation."
            )
        ),
    ],
    cwd: Annotated[
        str | None,
        Field(
            description=(
                "Absolute path to a different project root than this session's. "
                "Omit unless the work clearly belongs in another repository."
            )
        ),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Flag an out-of-scope issue for a separate background task.

    Call this when you notice something worth fixing that would bloat the
    current change — dead code, stale docs, missing coverage, a confirmed
    TODO, or a security issue spotted in passing. Do not flag vague code-smell
    observations, trivial fixes you can do inline, or low-confidence hunches.

    A chip appears for the user; one click spins it off into its own session.
    Your current turn continues uninterrupted.

    Re-raising a suggestion already made in this session returns the original
    task id and changes nothing — including one the user dismissed.
    """

    session_id = _session_id(_state)
    db_factory = resolve_db_factory(None)
    async with db_factory() as db:
        try:
            task, created = await suggested_task_service.create(
                db,
                session_id,
                title=title,
                tldr=tldr,
                prompt=prompt,
                cwd=cwd,
            )
        except (
            suggested_task_service.SuggestedTaskValidationError,
            suggested_task_service.SuggestedTaskConflictError,
        ) as exc:
            # Returned, not raised: both are things the agent can fix on the
            # next call (write a fuller prompt, dismiss a stale chip), and a
            # raised tool error reads as a crash rather than an instruction.
            return f"[Error] {exc}"
        snapshot = suggested_task_service.snapshot(task)
        await db.commit()
        if created:
            await publish_suggested_task(str(session_id), snapshot, source="spawn_task")
            return (
                f"Suggested task created (task_id={snapshot.id}). The user can "
                "start it from the chip; do not act on it in this session."
            )
        return (
            f"Already suggested in this session (task_id={snapshot.id}, "
            f"status={snapshot.status}). Nothing was created."
        )


async def _dismiss_task(
    task_id: Annotated[
        str,
        Field(description="The task_id returned by the spawn_task call."),
    ],
    reason: Annotated[
        str | None,
        Field(
            description=(
                "Optional one-line reason the suggestion is no longer needed, "
                "e.g. 'fixed in this session'."
            )
        ),
    ] = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Withdraw a suggestion chip you previously created with spawn_task.

    Call this when a suggestion you flagged is now stale or superseded — you
    or the user already fixed it in this session, or you raised a
    better-scoped replacement.

    Only a chip the user has not acted on can be withdrawn. A task the user
    already started belongs to its own session; this reports that instead of
    changing it.
    """

    session_id = _session_id(_state)
    try:
        parsed = UUID(str(task_id))
    except ValueError:
        return f"[Error] {task_id!r} is not a valid task id."

    db_factory = resolve_db_factory(None)
    async with db_factory() as db:
        task = await suggested_task_service.get(db, parsed)
        if task is None or task.session_id != session_id:
            return "[Error] No such suggested task in this session."
        try:
            await suggested_task_service.dismiss(db, task, reason=reason)
        except suggested_task_service.SuggestedTaskConflictError as exc:
            return f"[Error] {exc}"
        snapshot = suggested_task_service.snapshot(task)
        await db.commit()
        await publish_suggested_task(str(session_id), snapshot, source="dismiss_task")
        return f"Suggested task {snapshot.id} withdrawn."


# ── Tool objects ──────────────────────────────────────────────────────────────

spawn_task = Tool(
    _spawn_task,
    name="spawn_task",
    tiers=("coding",),
    lead_only=True,
    description=(
        "Flag an out-of-scope issue as a chip the user can spin into its own "
        "session. Non-blocking — the current turn continues."
    ),
)

dismiss_task = Tool(
    _dismiss_task,
    name="dismiss_task",
    tiers=("coding",),
    lead_only=True,
    # Deferred: only reachable after a spawn_task in the same session, so it
    # does not belong in the eager payload every coding turn pays for.
    deferred=True,
    deferred_summary="Withdraw a suggestion chip that has gone stale.",
    description="Withdraw a suggestion chip created earlier with spawn_task.",
)
