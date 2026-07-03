"""create_pull_request — commit changes and open a GitHub PR in one step.

Designed for the Devin-style auto-PR flow in EvoFlux coding mode:
  1. Stage all changes (``git add -A``)
  2. Commit with the given message
  3. Push the branch (creating upstream if needed)
  4. Call ``gh pr create`` with title + body

Requirements on the host:
  - ``git`` in PATH (universally available)
  - ``gh`` CLI authenticated (``gh auth login``) for PR creation

The tool is intentionally conservative: it no-ops when the repo has
no staged/unstaged changes so callers don't accidentally create empty PRs.

All git/gh invocations use ``create_subprocess_exec`` with argv lists (no
shell), so multi-word commit messages / titles / bodies and paths with
spaces are passed verbatim and it behaves identically on POSIX and Windows.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Annotated, Any

from app.agent.tools.registry import InjectedArg, Tool


async def _run(args: list[str], cwd: str | None) -> tuple[int, str]:
    """Run an argv command (no shell) and return ``(returncode, combined_output)``."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    return proc.returncode or 0, stdout.decode(errors="replace").strip()


async def _create_pull_request(
    workspace_path: str,
    commit_message: str,
    pr_title: str,
    pr_body: str = "",
    base_branch: str = "main",
    branch_name: str | None = None,
    _state: Annotated[Any, InjectedArg()] = None,
) -> str:
    """Commit all changes in a workspace, push the branch, and create a PR.

    Stages every modified/untracked file, commits with the given message,
    pushes to the remote, then calls ``gh pr create``. Idempotent: re-running
    on a clean repo (no changes) returns an informational message instead of
    creating an empty commit.

    Args:
        workspace_path: Absolute path to the git repository root.
        commit_message: Conventional-commits style message for the git commit.
        pr_title: Title for the pull request (shown on GitHub/GitLab).
        pr_body: Markdown body for the PR description. Defaults to empty.
        base_branch: Branch to merge into (default: main).
        branch_name: Branch to push and PR from. If given and different from
            the current branch, the working changes are moved onto it (via
            ``git checkout -B``) before committing. Defaults to current branch.
    """
    path = Path(workspace_path).expanduser().resolve()
    if not path.is_dir():
        return f"[Error] workspace_path not found: {workspace_path}"

    cwd = str(path)
    has_gh = shutil.which("gh") is not None

    # ── Sanity check: is this a git repo? ─────────────────────────────────────
    rc, _ = await _run(["git", "rev-parse", "--is-inside-work-tree"], cwd)
    if rc != 0:
        return f"[Error] {workspace_path} is not a git repository."

    # ── Detect current branch ──────────────────────────────────────────────────
    rc, current_branch = await _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if rc != 0:
        return f"[Error] Could not determine current branch: {current_branch}"
    target_branch = branch_name or current_branch

    # ── Check for changes ──────────────────────────────────────────────────────
    rc, status = await _run(["git", "status", "--porcelain"], cwd)
    if not status.strip():
        # No changes — surface an existing PR for this branch if there is one.
        if has_gh:
            rc_pr, pr_url = await _run(
                ["gh", "pr", "view", target_branch, "--json", "url", "--jq", ".url"],
                cwd,
            )
            if rc_pr == 0 and pr_url.strip():
                return f"[No changes] Working tree is clean. Existing PR: {pr_url.strip()}"
        return "[No changes] Working tree is clean. Nothing to commit."

    # ── Move onto the target branch if the caller requested a different one ─────
    if branch_name and branch_name != current_branch:
        rc, out = await _run(["git", "checkout", "-B", branch_name], cwd)
        if rc != 0:
            return f"[Error] git checkout {branch_name} failed:\n{out}"

    # ── Stage all changes ──────────────────────────────────────────────────────
    rc, out = await _run(["git", "add", "-A"], cwd)
    if rc != 0:
        return f"[Error] git add failed:\n{out}"

    # ── Commit ─────────────────────────────────────────────────────────────────
    rc, out = await _run(["git", "commit", "-m", commit_message], cwd)
    if rc != 0:
        if "nothing to commit" in out.lower():
            return "[No changes] Nothing new to commit."
        return f"[Error] git commit failed:\n{out}"

    # ── Push ───────────────────────────────────────────────────────────────────
    rc, out = await _run(
        ["git", "push", "--set-upstream", "origin", target_branch], cwd
    )
    if rc != 0:
        return f"[Error] git push failed:\n{out}"

    # ── Create PR (gh) ────────────────────────────────────────────────────────
    if not has_gh:
        return (
            "[Committed & pushed] gh CLI not found — install it and run "
            f"`gh pr create --base {base_branch} --title '...'` manually."
        )

    rc, pr_out = await _run(
        [
            "gh",
            "pr",
            "create",
            "--base",
            base_branch,
            "--head",
            target_branch,
            "--title",
            pr_title,
            "--body",
            pr_body,
        ],
        cwd,
    )
    if rc != 0:
        # Might already exist
        if "already exists" in pr_out.lower() or "a pull request for branch" in pr_out.lower():
            rc2, pr_url = await _run(
                ["gh", "pr", "view", target_branch, "--json", "url", "--jq", ".url"],
                cwd,
            )
            existing = pr_url.strip() if (rc2 == 0 and pr_url.strip()) else "(check GitHub)"
            return f"[PR already exists] {existing}"
        return f"[Error] gh pr create failed:\n{pr_out}"

    # pr_out contains the URL on success (last non-empty line).
    lines = pr_out.strip().splitlines()
    pr_url = lines[-1].strip() if lines else ""
    return f"[Success] PR created: {pr_url}" if pr_url else "[Success] PR created."


create_pull_request = Tool(
    _create_pull_request,
    name="create_pull_request",
    description=(
        "Stage all changes in a repository, create a git commit, push the branch, "
        "and open a GitHub/GitLab pull request using the gh CLI. "
        "Use after finishing a coding task to ship changes for review. "
        "Requires gh CLI to be installed and authenticated (`gh auth login`)."
    ),
)
