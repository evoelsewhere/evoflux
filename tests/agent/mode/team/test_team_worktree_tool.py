from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.agent.mode.team.worktree import make_team_worktree_tool


async def test_review_routes_to_delegation_task():
    team = MagicMock()
    team.review_delegation_worktree = AsyncMock(return_value="review output")
    tool = make_team_worktree_tool(team)

    result = await tool(action="review", task_id="task-1")

    assert result == "review output"
    team.review_delegation_worktree.assert_awaited_once_with("task-1")


async def test_merge_routes_to_integration_queue():
    team = MagicMock()
    team.merge_delegation_worktree = AsyncMock(return_value="repo: commit")
    tool = make_team_worktree_tool(team)

    result = await tool(action="merge", task_id="task-1")

    assert "merged into the integration branch" in result
    team.merge_delegation_worktree.assert_awaited_once_with("task-1")


async def test_discard_requires_confirmation():
    team = MagicMock()
    team.discard_delegation_worktree = AsyncMock()
    tool = make_team_worktree_tool(team)

    result = await tool(action="discard", task_id="task-1")

    assert "confirm_discard=true" in result
    team.discard_delegation_worktree.assert_not_awaited()


async def test_finalize_routes_all_repositories():
    team = MagicMock()
    team.finalize_delegation_worktrees = AsyncMock(return_value="done")
    tool = make_team_worktree_tool(team)

    result = await tool(action="finalize")

    assert "Integration finalized" in result
    team.finalize_delegation_worktrees.assert_awaited_once_with(None)
