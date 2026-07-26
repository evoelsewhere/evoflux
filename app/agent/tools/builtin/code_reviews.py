"""Provider-neutral code-review tools backed by configured Git server APIs."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Annotated

from pydantic import Field
from sqlmodel import col, select

from app.agent.state import AgentState
from app.agent.tools.registry import InjectedArg, Tool
from app.core import db as db_module
from app.models.chat import CodingProjectWorkspace, GitServerConnection
from app.services.code_review_service import (
    GitServerApiError,
    RepositoryTarget,
    add_code_review_comment as service_add_comment,
    add_code_review_inline_comment as service_add_inline_comment,
    aggregate_reviews,
    get_repository_review_checks as service_get_checks,
    get_repository_review_context,
    inspect_repository,
    merge_code_review as service_merge,
    reply_code_review_thread as service_reply_thread,
    resolve_connection,
    set_code_review_state as service_set_state,
    set_code_review_thread_resolved as service_set_thread_resolved,
    submit_code_review as service_submit_review,
    update_code_review as service_update_review,
)
from app.services.coding_workspace_service import list_visible_coding_workspaces


def _active_workspace(state: AgentState | None) -> str:
    workspace = state.metadata.get("team_workspace") if state else None
    if not isinstance(workspace, str) or not workspace:
        raise ValueError("Code review tools require an active Coding workspace.")
    return workspace


async def _session_targets(
    state: AgentState | None,
) -> tuple[list[RepositoryTarget], list[GitServerConnection]]:
    workspace = _active_workspace(state)
    async with db_module.async_session_factory() as db:
        rows = await list_visible_coding_workspaces(db)
        active = next((row for row in rows if row.path == workspace), None)
        if active is None:
            raise ValueError("The active Coding workspace is not registered.")
        if active.kind == "worktree" and active.source_path:
            active = next(
                (
                    row
                    for row in rows
                    if row.kind == "repo" and row.path == active.source_path
                ),
                active,
            )

        project_link = (
            await db.exec(
                select(CodingProjectWorkspace).where(
                    CodingProjectWorkspace.workspace_id == active.id
                )
            )
        ).first()
        if project_link is not None:
            member_ids = {
                link.workspace_id
                for link in (
                    await db.exec(
                        select(CodingProjectWorkspace).where(
                            CodingProjectWorkspace.project_id
                            == project_link.project_id
                        )
                    )
                ).all()
            }
            repository_rows = [
                row for row in rows if row.kind == "repo" and row.id in member_ids
            ]
        else:
            repository_rows = [active]
        connections = list(
            (
                await db.exec(
                    select(GitServerConnection).order_by(
                        col(GitServerConnection.created_at).desc()
                    )
                )
            ).all()
        )

    targets = list(
        await asyncio.gather(
            *(
                inspect_repository(
                    str(row.id),
                    row.path,
                    row.name or row.path.rsplit("/", 1)[-1],
                )
                for row in repository_rows
            )
        )
    )
    return targets, connections


def _select_target(
    targets: list[RepositoryTarget],
    repository: str | None,
) -> RepositoryTarget:
    if repository:
        needle = repository.strip().lower()
        matches = [
            target
            for target in targets
            if needle
            in {
                target.workspace_id.lower(),
                target.workspace.lower(),
                target.name.lower(),
                (target.repository or "").lower(),
            }
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f"Repository '{repository}' is not in this Coding session.")
        raise ValueError(f"Repository selector '{repository}' is ambiguous.")
    if len(targets) == 1:
        return targets[0]
    choices = ", ".join(target.repository or target.name for target in targets)
    raise ValueError(f"Choose a repository for this project: {choices}")


async def _list_code_reviews(
    repository: Annotated[
        str | None,
        Field(
            description=(
                "Optional repository name, remote path, workspace path, or workspace ID. "
                "Omit to list every repository in the active Coding project."
            )
        ),
    ] = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """List open PRs/MRs through saved Git server API credentials.

    Use this instead of gh/glab or shell commands. In a project session it
    covers every member repository; in a workspace session it covers that
    repository only.
    """
    targets, connections = await _session_targets(_state)
    if repository:
        targets = [_select_target(targets, repository)]
    results = await aggregate_reviews(targets, connections)
    return json.dumps(
        {
            "repositories": [
                {
                    "workspace_id": result.target.workspace_id,
                    "workspace": result.target.workspace,
                    "repository": result.target.repository or result.target.name,
                    "provider": result.provider or result.target.detected_provider,
                    "error": result.error,
                    "reviews": [asdict(item) for item in result.items],
                }
                for result in results
            ]
        },
        indent=2,
    )


async def _get_code_review(
    number: Annotated[int, Field(gt=0, description="Pull/merge request number.")],
    repository: Annotated[
        str | None,
        Field(
            description=(
                "Repository name, remote path, workspace path, or workspace ID. "
                "Required only when the Coding session contains multiple repositories."
            )
        ),
    ] = None,
    include_changes: Annotated[
        bool,
        Field(description="Include changed files and provider diff metadata."),
    ] = True,
    include_comments: Annotated[
        bool,
        Field(description="Include conversation and inline review comments."),
    ] = True,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Read one PR/MR, its changes, and comments through the configured API."""
    targets, connections = await _session_targets(_state)
    target = _select_target(targets, repository)
    connection = resolve_connection(target, connections)
    if connection is None:
        raise GitServerApiError(
            "No configured Git server API connection matches this repository."
        )
    context = await get_repository_review_context(
        target,
        connection,
        number,
        include_changes=include_changes,
        include_comments=include_comments,
    )
    return json.dumps(context, indent=2)


async def _review_resources(
    state: AgentState | None,
    repository: str | None,
) -> tuple[RepositoryTarget, GitServerConnection]:
    targets, connections = await _session_targets(state)
    target = _select_target(targets, repository)
    connection = resolve_connection(target, connections)
    if connection is None:
        raise GitServerApiError(
            "No configured Git server API connection matches this repository."
        )
    return target, connection


async def _add_code_review_comment(
    number: Annotated[int, Field(gt=0)],
    body: Annotated[str, Field(min_length=1, max_length=100_000)],
    repository: str | None = None,
    idempotency_key: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Add a conversation comment to a PR/MR using its saved API credential."""
    target, connection = await _review_resources(_state, repository)
    result = await service_add_comment(
        target, connection, number, body, idempotency_key=idempotency_key
    )
    return json.dumps(result, indent=2)


async def _add_code_review_inline_comment(
    number: Annotated[int, Field(gt=0)],
    body: Annotated[str, Field(min_length=1, max_length=100_000)],
    path: Annotated[str, Field(min_length=1)],
    line: Annotated[int, Field(gt=0)],
    repository: str | None = None,
    side: Annotated[str, Field(pattern="^(LEFT|RIGHT)$")] = "RIGHT",
    commit_id: str | None = None,
    base_commit_id: str | None = None,
    start_commit_id: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Add an inline PR/MR comment using position data from get_code_review."""
    target, connection = await _review_resources(_state, repository)
    result = await service_add_inline_comment(
        target,
        connection,
        number,
        body,
        path=path,
        line=line,
        side=side,
        commit_id=commit_id,
        base_commit_id=base_commit_id,
        start_commit_id=start_commit_id,
    )
    return json.dumps(result, indent=2)


async def _reply_code_review_thread(
    number: Annotated[int, Field(gt=0)],
    thread_id: Annotated[str, Field(min_length=1)],
    body: Annotated[str, Field(min_length=1, max_length=100_000)],
    repository: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Reply to a normalized review thread ID returned by get_code_review."""
    target, connection = await _review_resources(_state, repository)
    result = await service_reply_thread(
        target, connection, number, thread_id, body
    )
    return json.dumps(result, indent=2)


async def _set_thread_resolution(
    number: int,
    thread_id: str,
    repository: str | None,
    state: AgentState | None,
    *,
    resolved: bool,
) -> str:
    target, connection = await _review_resources(state, repository)
    result = await service_set_thread_resolved(
        target, connection, number, thread_id, resolved=resolved
    )
    return json.dumps(result, indent=2)


async def _resolve_code_review_thread(
    number: Annotated[int, Field(gt=0)],
    thread_id: Annotated[str, Field(min_length=1)],
    repository: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Resolve a review thread when the provider REST API supports it."""
    return await _set_thread_resolution(
        number, thread_id, repository, _state, resolved=True
    )


async def _reopen_code_review_thread(
    number: Annotated[int, Field(gt=0)],
    thread_id: Annotated[str, Field(min_length=1)],
    repository: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Reopen a resolved review thread when the provider supports it."""
    return await _set_thread_resolution(
        number, thread_id, repository, _state, resolved=False
    )


async def _submit_code_review(
    number: Annotated[int, Field(gt=0)],
    event: Annotated[str, Field(pattern="^(approve|request_changes|comment)$")],
    repository: str | None = None,
    body: str = "",
    reviewer_id: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Submit approve, request-changes, or comment review state."""
    target, connection = await _review_resources(_state, repository)
    result = await service_submit_review(
        target,
        connection,
        number,
        event,
        body=body,
        reviewer_id=reviewer_id,
    )
    return json.dumps(result, indent=2)


async def _update_code_review(
    number: Annotated[int, Field(gt=0)],
    repository: str | None = None,
    title: str | None = None,
    body: str | None = None,
    draft: bool | None = None,
    labels: list[str] | None = None,
    reviewers: list[str] | None = None,
    assignees: list[str] | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Update PR/MR metadata supported by the active provider."""
    target, connection = await _review_resources(_state, repository)
    updates = {
        key: value
        for key, value in {
            "title": title,
            "body": body,
            "draft": draft,
            "labels": labels,
            "reviewers": reviewers,
            "assignees": assignees,
        }.items()
        if value is not None
    }
    result = await service_update_review(target, connection, number, updates)
    return json.dumps(result, indent=2)


async def _get_code_review_checks(
    number: Annotated[int, Field(gt=0)],
    repository: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Get provider CI checks or pipeline statuses for a PR/MR."""
    target, connection = await _review_resources(_state, repository)
    result = await service_get_checks(target, connection, number)
    return json.dumps(result, indent=2)


async def _merge_code_review(
    number: Annotated[int, Field(gt=0)],
    repository: str | None = None,
    method: str | None = None,
    commit_title: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Merge a PR/MR. This is an important action and must be confirmed."""
    target, connection = await _review_resources(_state, repository)
    result = await service_merge(
        target,
        connection,
        number,
        method=method,
        commit_title=commit_title,
    )
    return json.dumps(result, indent=2)


async def _set_review_open(
    number: int,
    repository: str | None,
    state: AgentState | None,
    *,
    open: bool,
) -> str:
    target, connection = await _review_resources(state, repository)
    result = await service_set_state(target, connection, number, open=open)
    return json.dumps(result, indent=2)


async def _close_code_review(
    number: Annotated[int, Field(gt=0)],
    repository: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Close/decline a PR/MR. This important action must be confirmed."""
    return await _set_review_open(number, repository, _state, open=False)


async def _reopen_code_review(
    number: Annotated[int, Field(gt=0)],
    repository: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Reopen a closed PR/MR. This mutation follows the tool permission policy."""
    return await _set_review_open(number, repository, _state, open=True)


list_code_reviews = Tool(
    _list_code_reviews,
    name="list_code_reviews",
    read_only=True,
    concurrency_safe=True,
    tiers=("coding",),
    deferred=True,
    deferred_summary=(
        "List open PRs/MRs for the active Coding workspace or multi-repo project "
        "using configured Git server API credentials."
    ),
)

get_code_review = Tool(
    _get_code_review,
    name="get_code_review",
    read_only=True,
    concurrency_safe=True,
    tiers=("coding",),
    deferred=True,
    deferred_summary=(
        "Fetch a PR/MR with changed files and comments using configured Git "
        "server API credentials."
    ),
)

add_code_review_comment = Tool(
    _add_code_review_comment,
    name="add_code_review_comment",
    tiers=("coding",),
    deferred=True,
    deferred_summary="Add a provider-neutral PR/MR conversation comment.",
)
add_code_review_inline_comment = Tool(
    _add_code_review_inline_comment,
    name="add_code_review_inline_comment",
    tiers=("coding",),
    deferred=True,
    deferred_summary="Add an inline PR/MR comment using normalized file position data.",
)
reply_code_review_thread = Tool(
    _reply_code_review_thread,
    name="reply_code_review_thread",
    tiers=("coding",),
    deferred=True,
    deferred_summary="Reply to a PR/MR discussion thread.",
)
resolve_code_review_thread = Tool(
    _resolve_code_review_thread,
    name="resolve_code_review_thread",
    tiers=("coding",),
    deferred=True,
    deferred_summary="Resolve a PR/MR discussion thread when supported.",
)
reopen_code_review_thread = Tool(
    _reopen_code_review_thread,
    name="reopen_code_review_thread",
    tiers=("coding",),
    deferred=True,
    deferred_summary="Reopen a resolved PR/MR discussion thread when supported.",
)
submit_code_review = Tool(
    _submit_code_review,
    name="submit_code_review",
    tiers=("coding",),
    deferred=True,
    deferred_summary="Approve, request changes, or submit a PR/MR review comment.",
)
update_code_review = Tool(
    _update_code_review,
    name="update_code_review",
    tiers=("coding",),
    deferred=True,
    deferred_summary="Update PR/MR metadata supported by the configured provider.",
)
get_code_review_checks = Tool(
    _get_code_review_checks,
    name="get_code_review_checks",
    read_only=True,
    concurrency_safe=True,
    tiers=("coding",),
    deferred=True,
    deferred_summary="Read normalized CI checks or pipelines for a PR/MR.",
)
merge_code_review = Tool(
    _merge_code_review,
    name="merge_code_review",
    tiers=("coding",),
    deferred=True,
    deferred_summary="Merge a PR/MR through its provider REST API (important action).",
)
close_code_review = Tool(
    _close_code_review,
    name="close_code_review",
    tiers=("coding",),
    deferred=True,
    deferred_summary="Close or decline a PR/MR (important action).",
)
reopen_code_review = Tool(
    _reopen_code_review,
    name="reopen_code_review",
    tiers=("coding",),
    deferred=True,
    deferred_summary="Reopen a closed PR/MR through its provider REST API.",
)
