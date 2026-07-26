"""Commit, push, and create a PR/MR through the configured Git server API.

Local source-control operations still use the ``git`` executable, invoked
directly with argv (never through a shell). Provider operations use the REST
API credential already configured in Coding mode, so gh/glab are unnecessary.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

from sqlmodel import col, select

from app.agent.tools.registry import InjectedArg, Tool
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


async def _run(args: list[str], cwd: str | None) -> tuple[int, str]:
    """Run an argv command (no shell) and return combined output."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    return proc.returncode or 0, stdout.decode(errors="replace").strip()


async def _api_context(workspace: Path):
    cwd = str(workspace)
    async with db_module.async_session_factory() as db:
        rows = await list_visible_coding_workspaces(db)
        active = next((row for row in rows if row.path == cwd), None)
        if active is None:
            raise GitServerApiError(
                "This workspace is not registered in Coding mode."
            )
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
    commit_message: str,
    pr_title: str,
    pr_body: str = "",
    base_branch: str = "main",
    branch_name: str | None = None,
    _state: Annotated[Any, InjectedArg()] = None,
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

    try:
        target, connection = await _api_context(path)
    except GitServerApiError as exc:
        return f"[Error] {exc}"

    rc, _ = await _run(["git", "rev-parse", "--is-inside-work-tree"], cwd)
    if rc != 0:
        return f"[Error] {workspace_path} is not a git repository."

    rc, current_branch = await _run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd
    )
    if rc != 0:
        return f"[Error] Could not determine current branch: {current_branch}"
    source_branch = branch_name or current_branch

    reviews = await list_repository_reviews(target, connection)
    existing = next(
        (
            item
            for item in reviews.items
            if item.source_branch == source_branch
            and item.target_branch == base_branch
        ),
        None,
    )

    _, status = await _run(["git", "status", "--porcelain"], cwd)
    if not status.strip():
        if existing:
            return (
                "[No changes] Working tree is clean. Existing review: "
                f"{existing.web_url or f'#{existing.number}'}"
            )
        return "[No changes] Working tree is clean. Nothing to commit."

    if branch_name and branch_name != current_branch:
        rc, out = await _run(["git", "checkout", "-B", branch_name], cwd)
        if rc != 0:
            return f"[Error] git checkout {branch_name} failed:\n{out}"

    rc, out = await _run(["git", "add", "-A"], cwd)
    if rc != 0:
        return f"[Error] git add failed:\n{out}"
    rc, out = await _run(["git", "commit", "-m", commit_message], cwd)
    if rc != 0:
        if "nothing to commit" in out.lower():
            return "[No changes] Nothing new to commit."
        return f"[Error] git commit failed:\n{out}"
    rc, out = await _run(
        ["git", "push", "--set-upstream", "origin", source_branch], cwd
    )
    if rc != 0:
        return f"[Error] git push failed:\n{out}"

    if existing:
        return f"[Review already exists] {existing.web_url or f'#{existing.number}'}"
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
