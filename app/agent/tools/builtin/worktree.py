"""Git worktree agent tools — isolate risky changes in a branch.

Two tools that let the agent work in an isolated git worktree:

- ``worktree_start``  — create a new worktree + branch, switch the agent's
  workspace to it for the rest of the current turn.
- ``worktree_finish`` — show what changed, clean up the worktree.  The agent
  may then merge or discard the changes with ``shell``.

The worktree is created under ``{EVOFLUX_DATA_DIR}/worktrees/`` and
registered in the ``coding_workspaces`` table (``kind="worktree"``,
``managed=True``).  Only works when the current workspace is a git repo.

Scope note
----------
``worktree_start`` updates the sandbox contextvar for the **current turn
only**.  After the turn ends the sandbox resets automatically.  The
worktree itself (directory + branch) persists on disk until ``worktree_finish``
removes it.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import subprocess
from pathlib import Path
from typing import Annotated, Any

from loguru import logger
from pydantic import Field

from app.agent.sandbox import SandboxConfig, get_sandbox, set_sandbox
from app.agent.tools.registry import InjectedArg, Tool
from app.core.config import settings

_BRANCH_PREFIX = "EvoFlux"
_WORKTREE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


# ── Low-level git helpers ─────────────────────────────────────────────────────


def _git_sync(workspace: Path, *args: str) -> tuple[int, str, str]:
    """Run a git command synchronously; return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


async def _git(workspace: Path, *args: str) -> tuple[int, str, str]:
    """Async wrapper — runs git in a thread to avoid blocking the event loop."""
    return await asyncio.to_thread(_git_sync, workspace, *args)


# ── Path helpers ──────────────────────────────────────────────────────────────


def _worktree_root(source: Path) -> Path:
    """Directory under which EvoFlux-managed worktrees for *source* live."""
    key = hashlib.sha1(str(source).encode()).hexdigest()[:10]
    root = Path(settings.EVOFLUX_DATA_DIR) / "worktrees" / f"{source.name}-{key}"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return (slug or "task")[:60]


def _unique_worktree(source: Path, name: str) -> tuple[Path, str]:
    """Find an unused worktree directory + branch name pair."""
    root = _worktree_root(source)
    slug = _slugify(name)
    for attempt in range(20):
        suffix = "" if attempt == 0 else f"-{attempt}"
        candidate_name = f"{slug}{suffix}"
        directory = (root / candidate_name).resolve()
        if directory.parent != root:
            raise ValueError("Worktree path traversal rejected.")
        if directory.exists():
            continue
        branch = f"{_BRANCH_PREFIX}/{candidate_name}"
        rc, _, _ = _git_sync(
            source, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"
        )
        if rc == 0:
            continue  # branch already exists
        return directory, branch
    raise RuntimeError("Could not find a unique worktree name after 20 attempts.")


# ── Tool implementations ──────────────────────────────────────────────────────


async def _worktree_start(
    name: Annotated[
        str,
        Field(
            description=(
                "Short name for the worktree (e.g. 'fix-auth', 'refactor-api'). "
                "Used to name the directory and branch (EvoFlux/<name>). "
                "Lowercase letters, numbers and hyphens only."
            )
        ),
    ] = "task",
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Create an isolated git worktree and switch the agent's workspace to it.

    Creates a new worktree at ``{data_dir}/worktrees/`` with a fresh branch
    named ``EvoFlux/<name>``.  All file and shell tools for the **rest of this
    turn** will operate inside the worktree, leaving the original branch clean.

    After finishing the work in the worktree, call ``worktree_finish`` to see
    the diff and clean up.  You can then merge/cherry-pick using ``shell``.

    Only works when the current workspace is a git repository.
    """
    sandbox = get_sandbox()
    source = sandbox.workspace_root.resolve()

    # ── Validate git repo ─────────────────────────────────────────────────────
    rc, out, _ = await _git(source, "rev-parse", "--is-inside-work-tree")
    if rc != 0 or out.strip() != "true":
        return (
            "[Error] The current workspace is not a git repository. "
            "Worktrees require a git project."
        )

    # ── Find unique name/branch ───────────────────────────────────────────────
    try:
        worktree_dir, branch = _unique_worktree(source, name)
    except (ValueError, RuntimeError) as exc:
        return f"[Error] {exc}"

    # ── Get HEAD branch for the diff reference later ─────────────────────────
    rc_hb, head_branch, _ = await _git(source, "rev-parse", "--abbrev-ref", "HEAD")
    head_branch = head_branch.strip() if rc_hb == 0 else "HEAD"

    # ── Create worktree (no-checkout first, then reset --hard) ───────────────
    rc, out, err = await _git(
        source, "worktree", "add", "--no-checkout", "-b", branch, str(worktree_dir)
    )
    if rc != 0:
        return f"[Error] Failed to create worktree: {err.strip() or out.strip()}"

    rc, out, err = await _git(Path(worktree_dir), "reset", "--hard")
    if rc != 0:
        await _git(source, "worktree", "remove", "--force", str(worktree_dir))
        await _git(source, "branch", "-D", branch)
        return f"[Error] Failed to populate worktree: {err.strip() or out.strip()}"

    # ── Register in DB ────────────────────────────────────────────────────────
    try:
        from app.core.db import async_session_factory
        from app.services.coding_workspace_service import upsert_coding_workspace

        async with async_session_factory() as db:
            await upsert_coding_workspace(
                db, path=str(source), kind="repo", hidden=False
            )
            await upsert_coding_workspace(
                db,
                path=str(worktree_dir),
                kind="worktree",
                source_path=str(source),
                name=worktree_dir.name,
                managed=True,
                hidden=False,
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("worktree_db_register_failed error={}", exc)

    # ── Switch sandbox to the worktree for the rest of this turn ─────────────
    session_id = _state.metadata.get("session_id") if _state else None
    set_sandbox(SandboxConfig(workspace=worktree_dir, session_id=session_id))

    # ── Persist in metadata (available to worktree_finish this turn) ─────────
    if _state is not None:
        _state.metadata["_worktree_path"] = str(worktree_dir)
        _state.metadata["_worktree_source"] = str(source)
        _state.metadata["_worktree_branch"] = branch
        _state.metadata["_worktree_head_branch"] = head_branch
        _state.metadata["team_workspace"] = str(worktree_dir)

    logger.info(
        "worktree_started path={} branch={} source={}",
        worktree_dir,
        branch,
        source,
    )

    return (
        f"[Worktree created]\n"
        f"directory : {worktree_dir}\n"
        f"branch    : {branch}\n"
        f"from      : {head_branch} ({source})\n\n"
        f"The agent workspace is now the worktree. "
        f"All file and shell tools will operate here until worktree_finish is called.\n"
        f"When done, call worktree_finish to review the diff and clean up."
    )


async def _worktree_finish(
    action: Annotated[
        str,
        Field(
            description=(
                "'diff' — show what changed and remove the worktree (default). "
                "'discard' — silently remove the worktree without showing diff."
            )
        ),
    ] = "diff",
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Show the diff, clean up the worktree, and restore the original workspace.

    After reviewing the diff you can apply the changes to the main branch using
    ``shell`` (e.g. ``git cherry-pick``, ``git merge``, or ``git rebase``).
    The worktree branch (``EvoFlux/<name>``) is deleted along with the directory.
    """
    # ── Read stored state ─────────────────────────────────────────────────────
    metadata = _state.metadata if _state is not None else {}
    worktree_path = metadata.get("_worktree_path")
    source_path = metadata.get("_worktree_source")
    branch = metadata.get("_worktree_branch")
    head_branch = metadata.get("_worktree_head_branch", "HEAD")

    if not worktree_path or not source_path:
        # Fallback: check if current sandbox is inside a known worktree
        sandbox = get_sandbox()
        data_root = (Path(settings.EVOFLUX_DATA_DIR) / "worktrees").resolve()
        current = sandbox.workspace_root.resolve()
        if data_root in current.parents:
            worktree_path = str(current)
            # Try to infer source via git
            rc, common, _ = await _git(
                current, "rev-parse", "--path-format=absolute", "--git-common-dir"
            )
            if rc == 0:
                common_p = Path(common.strip()).resolve()
                source_path = str(
                    common_p.parent if common_p.name == ".git" else common_p
                )
        else:
            return (
                "[Error] No active worktree found in the current turn. "
                "Call worktree_start first."
            )

    source = Path(source_path)
    worktree = Path(worktree_path)

    # ── Get diff summary ──────────────────────────────────────────────────────
    diff_summary = ""
    if action != "discard":
        rc, diff_stat, _ = await _git(
            source, "diff", f"{head_branch}...{branch}", "--stat"
        )
        if rc == 0 and diff_stat.strip():
            diff_summary = diff_stat.strip()
        elif rc == 0:
            diff_summary = "(no changes)"
        else:
            # Fallback: diff against HEAD
            rc2, diff2, _ = await _git(worktree, "diff", "HEAD", "--stat")
            diff_summary = diff2.strip() if rc2 == 0 else "(could not compute diff)"

    # ── Remove worktree ───────────────────────────────────────────────────────
    rc, _, err = await _git(source, "worktree", "remove", "--force", str(worktree))
    if rc != 0:
        logger.warning("worktree_remove_failed path={} err={}", worktree, err.strip())

    # ── Delete branch (EvoFlux-managed only) ─────────────────────────────────
    if branch and branch.startswith(f"{_BRANCH_PREFIX}/"):
        await _git(source, "branch", "-D", branch)

    # ── Update DB ─────────────────────────────────────────────────────────────
    try:
        from app.core.db import async_session_factory
        from app.services.coding_workspace_service import mark_coding_workspace_deleted

        async with async_session_factory() as db:
            await mark_coding_workspace_deleted(db, str(worktree))
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("worktree_db_delete_failed error={}", exc)

    # ── Restore sandbox ───────────────────────────────────────────────────────
    session_id = metadata.get("session_id")
    set_sandbox(SandboxConfig(workspace=source, session_id=session_id))

    # ── Restore metadata ──────────────────────────────────────────────────────
    if _state is not None:
        _state.metadata["team_workspace"] = str(source)
        for key in (
            "_worktree_path",
            "_worktree_source",
            "_worktree_branch",
            "_worktree_head_branch",
        ):
            _state.metadata.pop(key, None)

    logger.info("worktree_finished branch={} source={}", branch, source)

    if action == "discard":
        return (
            f"[Worktree removed]\n"
            f"Branch {branch} deleted. Workspace restored to {source}."
        )

    lines = [
        "[Worktree finished]",
        f"branch    : {branch}  (deleted)",
        f"workspace : restored to {source}",
        "",
    ]
    if diff_summary and diff_summary != "(no changes)":
        lines += [
            f"Changes made in {branch}:",
            diff_summary,
            "",
            "To apply these changes to your main branch, use shell with:",
            "  git cherry-pick <commit>  — pick specific commits",
            f"  git merge {branch}        — merge the branch (already deleted; use reflog if needed)",
            f"  git diff {head_branch}..{branch} — view full diff (use reflog for deleted branch)",
        ]
    else:
        lines.append("No changes were made in the worktree.")

    return "\n".join(lines)


# ── Tool objects ──────────────────────────────────────────────────────────────

worktree_start = Tool(
    _worktree_start,
    name="worktree_start",
    lead_only=True,
    deferred=True,
    deferred_summary="Create an isolated git worktree for parallel or experimental work.",
    description=(
        "Create an isolated git worktree + branch and switch the agent's workspace "
        "to it. All file/shell tools will operate in the worktree until worktree_finish."
    ),
)

worktree_finish = Tool(
    _worktree_finish,
    name="worktree_finish",
    lead_only=True,
    deferred=True,
    deferred_summary="Finish and remove a worktree, showing or discarding its changes.",
    description=(
        "Show the diff from the worktree, remove it, and restore the original workspace. "
        "Use action='discard' to skip the diff."
    ),
)
