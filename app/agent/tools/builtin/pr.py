"""Commit, push, and create a PR/MR through the configured Git server API.

Local source-control operations still use the ``git`` executable, invoked
directly with argv (never through a shell). Provider operations use the REST
API credential already configured in Coding mode, so gh/glab are unnecessary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field
from sqlmodel import col, select

from app.agent.state import AgentState
from app.agent.tools.registry import InjectedArg, Tool
from app.core.runtime_settings import load_runtime_settings
from app.core import db as db_module
from app.models.chat import GitServerConnection
from app.services.code_review_service import (
    GitServerApiError,
    create_repository_review,
    inspect_repository,
    list_repository_reviews,
    resolve_connection,
)
from app.services.coding_workspace_service import list_visible_coding_workspaces
from app.services.git_credentials import git_credential_from_connection
from app.services.git_ops import (
    git_locks,
    run_git,
    run_git_long,
    validate_ref_name,
)


async def _api_context(workspace: Path):
    cwd = str(workspace)
    async with db_module.async_session_factory() as db:
        rows = await list_visible_coding_workspaces(db)
        active = next((row for row in rows if row.path == cwd), None)
        if active is None:
            raise GitServerApiError("This workspace is not registered in Coding mode.")
        repository_row = active
        if active.kind == "worktree" and active.source_path:
            repository_row = next(
                (
                    row
                    for row in rows
                    if row.kind == "repo" and row.path == active.source_path
                ),
                active,
            )
        connections = list(
            (
                await db.exec(
                    select(GitServerConnection).order_by(
                        col(GitServerConnection.created_at).desc()
                    )
                )
            ).all()
        )
    target = await inspect_repository(
        str(repository_row.id),
        cwd,
        repository_row.name or workspace.name,
    )
    connection = resolve_connection(target, connections)
    if connection is None:
        raise GitServerApiError(
            "No Git server API connection matches this repository. "
            "Configure it in the Pull Requests panel."
        )
    return target, connection


async def _create_pull_request(
    workspace_path: str,
    commit_message: Annotated[str, Field(min_length=1, max_length=10_000)],
    pr_title: Annotated[str, Field(min_length=1, max_length=1_000)],
    pr_body: str = "",
    base_branch: str = "main",
    branch_name: str | None = None,
    _state: Annotated[AgentState | None, InjectedArg()] = None,
) -> str:
    """Commit all changes, push the branch, and create a PR/MR through REST.

    The operation is idempotent: when the working tree is clean, or when an
    open review already exists for the source/target branch pair, it returns
    that review instead of creating a duplicate.
    """
    path = Path(workspace_path).expanduser().resolve()
    if not path.is_dir():
        return f"[Error] workspace_path not found: {workspace_path}"
    cwd = str(path)
    active_workspace = _state.metadata.get("team_workspace") if _state else None
    if not isinstance(active_workspace, str) or not active_workspace:
        return "[Error] create_pull_request requires an active Coding workspace."
    if path != Path(active_workspace).expanduser().resolve():
        return "[Error] workspace_path must match the active Coding workspace."
    if not validate_ref_name(base_branch):
        return f"[Error] Invalid base branch: {base_branch}"
    if branch_name is not None and not validate_ref_name(branch_name):
        return f"[Error] Invalid branch name: {branch_name}"

    try:
        target, connection = await _api_context(path)
    except GitServerApiError as exc:
        return f"[Error] {exc}"

    repo_check = await run_git(cwd, "rev-parse", "--is-inside-work-tree")
    if not repo_check.ok:
        return f"[Error] {workspace_path} is not a git repository."

    branch_result = await run_git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")
    current_branch = branch_result.stdout.strip()
    if not branch_result.ok and not branch_name:
        return "[Error] HEAD is detached; provide branch_name before creating a review."
    source_branch = branch_name or current_branch
    if source_branch == base_branch:
        return "[Error] Source and base branches must be different."

    reviews = await list_repository_reviews(target, connection)
    existing = next(
        (
            item
            for item in reviews.items
            if item.source_branch == source_branch and item.target_branch == base_branch
        ),
        None,
    )

    remote_name = target.remote_name or "origin"
    credential = git_credential_from_connection(connection)
    git_cfg = load_runtime_settings().git
    async with git_locks.acquire(cwd):
        if branch_name and branch_name != current_branch:
            switched = await run_git(cwd, "switch", "-c", branch_name, timeout=30.0)
            if not switched.ok:
                detail = switched.stderr.strip() or switched.stdout.strip()
                return f"[Error] git switch -c {branch_name} failed:\n{detail}"

        status_result = await run_git(cwd, "status", "--porcelain", timeout=10.0)
        if not status_result.ok:
            return f"[Error] git status failed:\n{status_result.stderr.strip()}"
        committed = False
        if status_result.stdout.strip():
            staged = await run_git(cwd, "add", "-A", timeout=30.0)
            if not staged.ok:
                return f"[Error] git add failed:\n{staged.stderr.strip()}"
            commit = await run_git(cwd, "commit", "-m", commit_message, timeout=30.0)
            if not commit.ok:
                detail = commit.stderr.strip() or commit.stdout.strip()
                return f"[Error] git commit failed:\n{detail}"
            committed = True

        pushed = await run_git_long(
            cwd,
            "push",
            "--set-upstream",
            remote_name,
            source_branch,
            timeout=git_cfg.network_timeout_seconds,
            credential=credential,
        )
        if not pushed.ok:
            detail = pushed.stderr.strip() or pushed.stdout.strip()
            return f"[Error] git push failed:\n{detail}"

    if existing:
        prefix = "Committed and pushed" if committed else "Pushed"
        return (
            f"[{prefix}; review already exists] "
            f"{existing.web_url or f'#{existing.number}'}"
        )
    try:
        created = await create_repository_review(
            target,
            connection,
            title=pr_title,
            body=pr_body,
            source_branch=source_branch,
            target_branch=base_branch,
        )
    except GitServerApiError as exc:
        return f"[Committed & pushed, review creation failed] {exc}"
    identifier = created["web_url"] or f"#{created['number']}"
    return f"[Success] Review created: {identifier}"


create_pull_request = Tool(
    _create_pull_request,
    name="create_pull_request",
    deferred=True,
    deferred_summary=(
        "Commit, push, and create a PR/MR for the current branch through the "
        "configured Git server API."
    ),
    description=(
        "Stage all changes, commit, push, and create a pull/merge request through "
        "the configured Git server REST API. Uses the shared or repository-specific "
        "credential saved in Coding mode; does not require gh, glab, or another "
        "provider CLI."
    ),
    tiers=("coding",),
)
