"""Lead-owned review and merge controls for delegated worktrees."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from app.agent.tools.registry import Tool


def make_team_worktree_tool(team) -> Tool:
    async def team_worktree(
        action: Annotated[
            Literal["review", "merge", "discard", "finalize"],
            Field(
                description=(
                    "review/merge/discard operate on one delegation task; finalize "
                    "fast-forwards clean project source repos after all merges."
                )
            ),
        ],
        task_id: Annotated[
            str | None,
            Field(
                description=(
                    "Delegation UUID for review, merge, or discard. Omit only for "
                    "finalize."
                )
            ),
        ] = None,
        target_repos: Annotated[
            list[str],
            Field(
                description=(
                    "Optional exact repository paths for finalize. Empty finalizes "
                    "all merged repositories in the session."
                )
            ),
        ] = [],  # noqa: B006
        confirm_discard: Annotated[
            bool,
            Field(
                description="Required true before permanently discarding reviewed code."
            ),
        ] = False,
    ) -> str:
        if action == "finalize":
            if task_id is not None:
                return "Error: task_id must be omitted for finalize."
            try:
                result = await team.finalize_delegation_worktrees(
                    list(target_repos) or None
                )
            except (TypeError, ValueError, RuntimeError) as exc:
                return f"Error: {exc}"
            return f"Integration finalized:\n{result}"

        if not task_id:
            return f"Error: task_id is required for {action}."
        try:
            if action == "review":
                return await team.review_delegation_worktree(task_id)
            if action == "merge":
                result = await team.merge_delegation_worktree(task_id)
                return f"Delegation merged into the integration branch:\n{result}"
            if not confirm_discard:
                return (
                    "Error: discard permanently removes the task worktree and branch; "
                    "call again with confirm_discard=true."
                )
            return await team.discard_delegation_worktree(task_id)
        except (TypeError, ValueError, RuntimeError) as exc:
            return f"Error: {exc}"

    return Tool(
        team_worktree,
        name="team_worktree",
        description=(
            "Lead-only lifecycle control for isolated delegation worktrees. Review "
            "a final handoff, merge it into the session integration branch, discard "
            "it explicitly, or finalize all integration branches into clean source repos."
        ),
    )
