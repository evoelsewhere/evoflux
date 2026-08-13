"""Git worktree agent tools — isolate risky changes in a branch.

Two tools that let the agent work in an isolated git worktree:

- ``worktree_start``  — create a new worktree + branch, switch the agent's
  workspace to it for the rest of the current turn.
- ``worktree_finish`` — review changes without deleting them, or preserve
  them in a snapshot commit before cleaning up.

By default the worktree is created under ``<repository>/.evoflux/worktrees/``
(configurable in Settings → Sandbox) and
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
import re
import subprocess
from pathlib import Path
from typing import Annotated, Any

from loguru import logger
from pydantic import Field

from app.agent.sandbox import SandboxConfig, get_sandbox, set_sandbox
from app.agent.sandbox_config import (
    managed_worktree_roots,
    selected_worktree_root,
)
from app.agent.tools.registry import InjectedArg, Tool

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
    return selected_worktree_root(source)


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


def _sandbox_snapshot(sandbox: SandboxConfig) -> dict[str, Any]:
    """Serialize active grants so a worktree switch cannot weaken them."""
    return {
        "workspace": str(sandbox.workspace_root),
        "session_id": sandbox.session_id,
        "denied_roots": [str(path) for path in sandbox.denied_roots],
        "denied_patterns": list(sandbox.denied_patterns),
        "max_execution_seconds": sandbox.max_execution_seconds,
        "max_output_bytes": sandbox.max_output_bytes,
        "inherit_shell_environment": sandbox.inherit_shell_environment,
        "load_shell_profile": sandbox.load_shell_profile,
        "extra_workspace_paths": list(sandbox.extra_workspace_paths),
        "read_only_paths": [str(path) for path in sandbox.read_only_paths],
        "write_allowed_paths": [str(path) for path in sandbox.write_allowed_paths],
    }


def _sandbox_from_snapshot(
    snapshot: dict[str, Any],
    *,
    workspace: Path,
    translate_claims_from: Path | None = None,
) -> SandboxConfig:
    """Restore grants, optionally translating source-repo write claims."""
    claims: list[str] = []
    for raw_path in snapshot.get("write_allowed_paths") or []:
        claim = Path(str(raw_path)).resolve()
        if translate_claims_from is not None:
            try:
                claim = workspace / claim.relative_to(translate_claims_from)
            except ValueError:
                pass
        claims.append(str(claim))

    return SandboxConfig(
        workspace=str(workspace),
        session_id=snapshot.get("session_id"),
        denied_roots=[Path(str(path)) for path in snapshot.get("denied_roots") or []],
        denied_patterns=list(snapshot.get("denied_patterns") or []),
        max_execution_seconds=snapshot.get("max_execution_seconds"),
        max_output_bytes=snapshot.get("max_output_bytes"),
        inherit_shell_environment=snapshot.get("inherit_shell_environment"),
        load_shell_profile=snapshot.get("load_shell_profile"),
        extra_workspace_paths=list(snapshot.get("extra_workspace_paths") or []),
        read_only_paths=list(snapshot.get("read_only_paths") or []),
        write_allowed_paths=claims,
    )


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

    Creates a new managed worktree at the location configured in Settings →
    Sandbox (repository-local by default) with a fresh branch named
    ``EvoFlux/<name>``. All file and shell tools for the **rest of this turn**
    operate inside the worktree, leaving the original branch clean.

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
    previous_sandbox = _sandbox_snapshot(sandbox)
    set_sandbox(
        _sandbox_from_snapshot(
            previous_sandbox,
            workspace=worktree_dir,
            translate_claims_from=source,
        )
    )

    # ── Persist in metadata (available to worktree_finish this turn) ─────────
    if _state is not None:
        _state.metadata["_worktree_path"] = str(worktree_dir)
        _state.metadata["_worktree_source"] = str(source)
        _state.metadata["_worktree_branch"] = branch
        _state.metadata["_worktree_head_branch"] = head_branch
        _state.metadata["_worktree_previous_sandbox"] = previous_sandbox
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
                "'review' — show changes and keep the worktree (default). "
                "'preserve' — snapshot all changes, remove the worktree, and keep "
                "its branch for merge/cherry-pick. 'discard' — permanently remove "
                "the worktree and branch; dirty worktrees require confirm_discard."
            )
        ),
    ] = "review",
    confirm_discard: Annotated[
        bool,
        Field(
            description=(
                "Required when action='discard' and the worktree has uncommitted "
                "or untracked changes. Confirms permanent deletion."
            )
        ),
    ] = False,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Review or safely preserve a worktree and restore the original workspace.

    The default action is non-destructive. ``preserve`` commits every tracked,
    untracked, and deleted path to the managed branch before removing the
    directory. The branch is deliberately retained for later merge/cherry-pick.
    """
    if action not in {"review", "preserve", "discard"}:
        return "[Error] action must be one of: review, preserve, discard."
    # ── Read stored state ─────────────────────────────────────────────────────
    metadata = _state.metadata if _state is not None else {}
    worktree_path = metadata.get("_worktree_path")
    source_path = metadata.get("_worktree_source")
    branch = metadata.get("_worktree_branch")
    head_branch = metadata.get("_worktree_head_branch", "HEAD")

    if not worktree_path or not source_path:
        # Fallback: check if current sandbox is inside a known worktree
        sandbox = get_sandbox()
        current = sandbox.workspace_root.resolve()
        rc, common, _ = await _git(
            current, "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        inferred_source: Path | None = None
        if rc == 0:
            common_p = Path(common.strip()).resolve()
            inferred_source = common_p.parent if common_p.name == ".git" else common_p
        recognized = inferred_source is not None and any(
            root in current.parents for root in managed_worktree_roots(inferred_source)
        )
        if not recognized:
            return (
                "[Error] No active worktree found in the current turn. "
                "Call worktree_start first."
            )
        worktree_path = str(current)
        source_path = str(inferred_source)

    source = Path(str(source_path))
    worktree = Path(str(worktree_path))
    if not worktree.exists():
        return f"[Error] Worktree directory no longer exists: {worktree}"
    if not branch:
        rc_branch, branch_out, _ = await _git(
            worktree, "rev-parse", "--abbrev-ref", "HEAD"
        )
        branch = branch_out.strip() if rc_branch == 0 else None

    rc_status, status_out, status_err = await _git(
        worktree, "status", "--short", "--untracked-files=all"
    )
    if rc_status != 0:
        return (
            "[Error] Could not inspect worktree status; nothing was removed: "
            f"{status_err.strip()}"
        )
    dirty = bool(status_out.strip())

    # ── Get diff summary ──────────────────────────────────────────────────────
    diff_summary = "(no committed changes)"
    if branch:
        rc, diff_stat, _ = await _git(
            source, "diff", f"{head_branch}...{branch}", "--stat"
        )
        if rc == 0 and diff_stat.strip():
            diff_summary = diff_stat.strip()
    if dirty:
        rc_dirty, dirty_stat, _ = await _git(worktree, "diff", "HEAD", "--stat")
        rc_untracked, untracked, _ = await _git(
            worktree, "ls-files", "--others", "--exclude-standard"
        )
        dirty_parts = []
        if rc_dirty == 0 and dirty_stat.strip():
            dirty_parts.append(dirty_stat.strip())
        if rc_untracked == 0 and untracked.strip():
            dirty_parts.append(
                "Untracked files:\n"
                + "\n".join(f"  {path}" for path in untracked.splitlines())
            )
        if dirty_parts:
            diff_summary = "\n".join([diff_summary, *dirty_parts])

    if action == "review":
        return "\n".join(
            [
                "[Worktree review — retained]",
                f"branch    : {branch}",
                f"directory : {worktree}",
                f"dirty     : {'yes' if dirty else 'no'}",
                "",
                diff_summary,
                "",
                "Nothing was removed. Use action='preserve' to snapshot and clean up,",
                "or action='discard' with confirm_discard=true to permanently delete changes.",
            ]
        )

    if action == "discard" and dirty and not confirm_discard:
        return (
            "[Error] Refusing to discard a dirty worktree. Review the changes or "
            "call again with action='discard' and confirm_discard=true."
        )

    snapshot_commit = ""
    if action == "preserve" and dirty:
        rc_add, _, add_err = await _git(worktree, "add", "--all")
        if rc_add != 0:
            return (
                "[Error] Could not stage the worktree snapshot; nothing was removed: "
                f"{add_err.strip()}"
            )
        rc_commit, commit_out, commit_err = await _git(
            worktree,
            "-c",
            "user.name=EvoFlux",
            "-c",
            "user.email=evoflux@localhost",
            "commit",
            "--no-verify",
            "-m",
            "chore(evoflux): preserve worktree snapshot",
        )
        if rc_commit != 0:
            return (
                "[Error] Could not create the worktree snapshot; the worktree and "
                f"staged changes were retained: {commit_err.strip() or commit_out.strip()}"
            )
        rc_rev, rev_out, _ = await _git(worktree, "rev-parse", "HEAD")
        snapshot_commit = rev_out.strip() if rc_rev == 0 else ""

    remove_args = ["worktree", "remove"]
    if action == "discard":
        remove_args.append("--force")
    remove_args.append(str(worktree))
    rc, _, err = await _git(source, *remove_args)
    if rc != 0:
        return (
            "[Error] Could not remove the worktree; branch and files were retained: "
            f"{err.strip()}"
        )

    # A preserved branch is the recovery artifact and must remain mergeable.
    if action == "discard" and branch and branch.startswith(f"{_BRANCH_PREFIX}/"):
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
    previous_sandbox = metadata.get("_worktree_previous_sandbox")
    if isinstance(previous_sandbox, dict):
        set_sandbox(_sandbox_from_snapshot(previous_sandbox, workspace=source))
    else:
        session_id = metadata.get("session_id")
        set_sandbox(SandboxConfig(workspace=str(source), session_id=session_id))

    # ── Restore metadata ──────────────────────────────────────────────────────
    if _state is not None:
        _state.metadata["team_workspace"] = str(source)
        for key in (
            "_worktree_path",
            "_worktree_source",
            "_worktree_branch",
            "_worktree_head_branch",
            "_worktree_previous_sandbox",
        ):
            _state.metadata.pop(key, None)

    logger.info(
        "worktree_finished branch={} source={} action={} snapshot={}",
        branch,
        source,
        action,
        snapshot_commit,
    )

    if action == "discard":
        return (
            f"[Worktree removed]\n"
            f"Branch {branch} deleted after explicit discard. "
            f"Workspace restored to {source}."
        )

    lines = [
        "[Worktree preserved]",
        f"branch    : {branch}  (retained)",
        f"snapshot  : {snapshot_commit or '(existing commits; no dirty files)'}",
        f"workspace : restored to {source}",
        "",
        diff_summary,
        "",
        "To apply these changes, merge the retained branch or cherry-pick its commits:",
        f"  git merge {branch}",
        f"  git diff {head_branch}..{branch}",
    ]

    return "\n".join(lines)


# ── Tool objects ──────────────────────────────────────────────────────────────

worktree_start = Tool(
    _worktree_start,
    name="worktree_start",
    tiers=("coding",),
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
    tiers=("coding",),
    lead_only=True,
    deferred=True,
    deferred_summary="Review or snapshot a worktree before safe cleanup.",
    description=(
        "Review changes without cleanup, or preserve every change in a snapshot "
        "commit before removing the worktree. Destructive discard requires confirmation."
    ),
)
