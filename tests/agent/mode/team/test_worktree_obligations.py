"""Tests for the worktree-obligation predicate on the delegation ledger.

``delegation_ledger.worktree_obligations`` is the single classification both the
lead's ``sleep`` guard and the post-stop nudge consult, so the contract under
test is exactly: which isolated delegation worktrees does the lead still owe an
action on, and which ones is it allowed to be waiting on.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.agent.mode.team import delegation_ledger

_TASK_ID = "01900000-0000-7000-8000-0000000000aa"


def _task(status: str, state: str | None) -> SimpleNamespace:
    allocation: dict = {"source": "kintsugi"}
    if state is not None:
        allocation["state"] = state
    return SimpleNamespace(
        id=_TASK_ID,
        status=status,
        spec={"worktree_allocation": allocation},
    )


def _install(rows: list[SimpleNamespace]):
    """Patch the ledger read so this test exercises classification only."""

    async def fake_tasks_with_worktrees(db, *, lead_session_id):
        return rows

    return patch.object(
        delegation_ledger, "tasks_with_worktrees", fake_tasks_with_worktrees
    )


async def _obligations(rows: list[SimpleNamespace]):
    with _install(rows):
        return await delegation_ledger.worktree_obligations(
            object(), lead_session_id=_TASK_ID
        )


class TestWorktreeObligations:
    async def test_review_state_handed_back_for_decision(self):
        unresolved, merged = await _obligations([_task("review", "review")])

        assert [task.id for task in unresolved] == [_TASK_ID]
        assert merged == []

    async def test_conflict_state_is_owed(self):
        unresolved, _ = await _obligations([_task("review", "conflict")])

        assert [task.id for task in unresolved] == [_TASK_ID]

    async def test_member_still_working_is_not_an_obligation(self):
        unresolved, merged = await _obligations([_task("pending", "active")])

        assert unresolved == []
        assert merged == []

    async def test_member_blocked_is_not_an_obligation(self):
        unresolved, _ = await _obligations([_task("blocked", "review")])

        assert unresolved == []

    async def test_discarded_and_finalized_are_settled(self):
        unresolved, merged = await _obligations(
            [_task("cancelled", "discarded"), _task("completed", "finalized")]
        )

        assert unresolved == []
        assert merged == []

    async def test_merged_worktree_still_owes_finalize(self):
        unresolved, merged = await _obligations([_task("completed", "merged")])

        assert unresolved == []
        assert [task.id for task in merged] == [_TASK_ID]

    async def test_merged_is_withheld_while_another_worktree_is_unresolved(self):
        unresolved, merged = await _obligations(
            [_task("review", "review"), _task("completed", "merged")]
        )

        assert [task.id for task in unresolved] == [_TASK_ID]
        assert merged == []

    async def test_unknown_state_is_left_alone(self):
        unresolved, merged = await _obligations([_task("review", "renamed-state")])

        assert unresolved == []
        assert merged == []
