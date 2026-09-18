"""Durable state transitions for parked out-of-scope suggestions.

Callers own the transaction, matching ``goal_service``: nothing here commits.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.suggested_task import SessionSuggestedTask

TITLE_MAX_CHARS = 60
TLDR_MAX_CHARS = 400
PROMPT_MAX_CHARS = 8_000
#: A prompt shorter than this cannot carry the file paths and reproduction
#: steps that make the spawned session able to act without this conversation.
#: Rejecting it here is cheaper than letting the user discover it on click.
PROMPT_MIN_CHARS = 80
#: Past this many open chips the dock stops being a shortlist. The agent is
#: told to dismiss something before adding more rather than silently dropping.
MAX_PENDING_PER_SESSION = 5

_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]")


class SuggestedTaskError(RuntimeError):
    """Base error for invalid suggested-task operations."""


class SuggestedTaskNotFoundError(SuggestedTaskError):
    pass


class SuggestedTaskValidationError(SuggestedTaskError):
    pass


class SuggestedTaskConflictError(SuggestedTaskError):
    pass


class SuggestedTaskSnapshot(BaseModel):
    """Wire shape for one chip — shared by the SSE event and the REST routes."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    title: str
    tldr: str
    prompt: str
    cwd: str | None
    status: str
    spawned_session_id: UUID | None
    worktree_path: str | None
    dismiss_reason: str | None
    created_at: datetime
    updated_at: datetime


def snapshot(task: SessionSuggestedTask) -> SuggestedTaskSnapshot:
    return SuggestedTaskSnapshot.model_validate(task)


def fingerprint(*, title: str, cwd: str | None) -> str:
    """Stable identity for a finding, so re-raising it is a no-op.

    Built from the normalized title and the target project rather than the
    prompt: an agent that notices the same problem twice rarely words the
    long-form prompt identically, but the title stays recognisable. Casing,
    punctuation and spacing are dropped so "Fix flaky uuid7 test" and
    "fix flaky uuid7 test." collapse to one chip.
    """

    normalized = _WHITESPACE.sub(" ", _NON_WORD.sub(" ", title.casefold())).strip()
    payload = f"{(cwd or '').casefold()}\x00{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clean(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def _validate(title: str, tldr: str, prompt: str) -> tuple[str, str, str]:
    title = _clean(title)
    tldr = _clean(tldr)
    prompt = prompt.strip()
    if not title:
        raise SuggestedTaskValidationError("A suggested task needs a title.")
    if len(title) > TITLE_MAX_CHARS:
        raise SuggestedTaskValidationError(
            f"Title must be at most {TITLE_MAX_CHARS} characters."
        )
    if not tldr:
        raise SuggestedTaskValidationError("A suggested task needs a tldr.")
    if len(tldr) > TLDR_MAX_CHARS:
        raise SuggestedTaskValidationError(
            f"tldr must be at most {TLDR_MAX_CHARS} characters."
        )
    if len(prompt) < PROMPT_MIN_CHARS:
        raise SuggestedTaskValidationError(
            "The prompt must stand alone — include file paths and enough "
            f"context to act without this conversation (at least "
            f"{PROMPT_MIN_CHARS} characters)."
        )
    if len(prompt) > PROMPT_MAX_CHARS:
        raise SuggestedTaskValidationError(
            f"Prompt must be at most {PROMPT_MAX_CHARS} characters."
        )
    return title, tldr, prompt


async def count_pending(db: AsyncSession, session_id: UUID) -> int:
    result = await db.execute(
        sa.select(sa.func.count())
        .select_from(SessionSuggestedTask)
        .where(
            SessionSuggestedTask.session_id == session_id,
            SessionSuggestedTask.status == "pending",
        )
    )
    return int(result.scalar_one())


async def create(
    db: AsyncSession,
    session_id: UUID,
    *,
    title: str,
    tldr: str,
    prompt: str,
    cwd: str | None = None,
) -> tuple[SessionSuggestedTask, bool]:
    """Park a suggestion. Returns ``(task, created)``.

    ``created`` is ``False`` when the same finding was already raised in this
    session — including one the user dismissed, which is deliberately not
    resurrected. The caller reports the existing row instead of erroring so a
    duplicate call costs the agent nothing.
    """

    title, tldr, prompt = _validate(title, tldr, prompt)
    digest = fingerprint(title=title, cwd=cwd)

    existing = await db.scalar(
        sa.select(SessionSuggestedTask).where(
            SessionSuggestedTask.session_id == session_id,
            SessionSuggestedTask.fingerprint == digest,
        )
    )
    if existing is not None:
        return existing, False

    if await count_pending(db, session_id) >= MAX_PENDING_PER_SESSION:
        raise SuggestedTaskConflictError(
            f"This session already has {MAX_PENDING_PER_SESSION} open "
            "suggestions. Dismiss one that no longer applies before adding "
            "another."
        )

    task = SessionSuggestedTask(
        session_id=session_id,
        title=title,
        tldr=tldr,
        prompt=prompt,
        cwd=cwd,
        fingerprint=digest,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task, True


async def get(db: AsyncSession, task_id: UUID) -> SessionSuggestedTask | None:
    return await db.get(SessionSuggestedTask, task_id)


async def require(db: AsyncSession, task_id: UUID) -> SessionSuggestedTask:
    task = await get(db, task_id)
    if task is None:
        raise SuggestedTaskNotFoundError("No such suggested task.")
    return task


async def list_for_session(
    db: AsyncSession,
    session_id: UUID,
    *,
    statuses: tuple[str, ...] = ("pending",),
) -> list[SessionSuggestedTask]:
    result = await db.execute(
        sa.select(SessionSuggestedTask)
        .where(
            SessionSuggestedTask.session_id == session_id,
            SessionSuggestedTask.status.in_(statuses),  # type: ignore[attr-defined]
        )
        .order_by(SessionSuggestedTask.created_at)
    )
    return list(result.scalars().all())


def _require_pending(task: SessionSuggestedTask) -> None:
    if task.status != "pending":
        raise SuggestedTaskConflictError(f"This suggestion was already {task.status}.")


async def mark_started(
    db: AsyncSession,
    task: SessionSuggestedTask,
    *,
    spawned_session_id: UUID,
    worktree_path: str | None = None,
) -> SessionSuggestedTask:
    _require_pending(task)
    task.status = "started"
    task.spawned_session_id = spawned_session_id
    task.worktree_path = worktree_path
    task.updated_at = datetime.now(timezone.utc)
    db.add(task)
    await db.flush()
    return task


async def dismiss(
    db: AsyncSession,
    task: SessionSuggestedTask,
    *,
    reason: str | None = None,
) -> SessionSuggestedTask:
    """Retire a suggestion.

    Only a pending one can be dismissed: a started task is owned by its
    spawned session, and withdrawing the chip there would misreport what
    happened to work that is already underway.
    """

    _require_pending(task)
    task.status = "dismissed"
    task.dismiss_reason = _clean(reason)[:200] if reason else None
    task.updated_at = datetime.now(timezone.utc)
    db.add(task)
    await db.flush()
    return task
