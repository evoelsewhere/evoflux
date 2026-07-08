"""Git operations API routes.

Full git tool window backend: local changes, commit, branches, push/pull/fetch,
log, stash, merge, rebase, cherry-pick, and conflict handling.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.schemas.git import (
    BranchCreateRequest,
    ChangedFileOut,
    CheckoutRequest,
    CherryPickRequest,
    CommitRequest,
    ConflictedFileOut,
    FetchRequest,
    GitBranchOut,
    GitChangesOut,
    GitCommitOut,
    GitConflictsOut,
    GitJobOut,
    GitLogFileOut,
    GitLogEntryOut,
    GitLogOut,
    GitMergeOut,
    GitStashOut,
    MergeRequest,
    PullRequest,
    PushRequest,
    RebaseRequest,
    StageRequest,
    StashApplyRequest,
    StashRequest,
    WorkspaceRequest,
)
from app.services import team_manager
from app.services.git_ops import (
    GitResult,
    _SHA_RE,
    detect_inprogress_operation,
    git_jobs,
    git_locks,
    is_git_repo,
    parse_ahead_behind,
    parse_branches,
    parse_log,
    parse_log_files,
    parse_porcelain_v2_files,
    parse_stash_list,
    pathspec_args,
    run_git,
    run_git_long,
    validate_ref_name,
)

router = APIRouter(prefix="/workspace/git", tags=["git"])


async def _validate(workspace: str) -> str:
    try:
        return team_manager.validate_workspace(workspace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_repo(cwd: str) -> None:
    if not is_git_repo(cwd):
        raise HTTPException(status_code=422, detail="Not a git repository")


def _check(result: GitResult) -> None:
    if not result.ok:
        raise HTTPException(
            status_code=504 if result.timed_out else 502,
            detail=result.stderr.strip()
            or result.stdout.strip()
            or "git command failed",
        )


def _changed_files_to_out(files):
    return [
        ChangedFileOut(
            path=f.path, status=f.status, staged=f.staged, old_path=f.old_path
        )
        for f in files
    ]


# --- Local Changes -----------------------------------------------------------


@router.get("/changes")
async def get_changes(workspace: str) -> GitChangesOut:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return GitChangesOut(branch=None, ahead=0, behind=0, files=[])
    result = await run_git(cwd, "status", "--porcelain=v2", "--branch", timeout=10.0)
    if not result.ok:
        return GitChangesOut(branch=None, ahead=0, behind=0, files=[])
    parsed = parse_porcelain_v2_files(result.stdout)
    return GitChangesOut(
        branch=parsed.branch,
        ahead=parsed.ahead,
        behind=parsed.behind,
        files=_changed_files_to_out(parsed.files),
    )


@router.post("/stage")
async def stage_files(body: StageRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    args = ["add", *pathspec_args(body.paths)]
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, *args, timeout=30.0)
    _check(result)
    return {"ok": True}


@router.post("/stage-all")
async def stage_all(body: WorkspaceRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "add", "-A", "--", ".", timeout=30.0)
    _check(result)
    return {"ok": True}


@router.post("/unstage")
async def unstage_files(body: StageRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    args = ["restore", "--staged", *pathspec_args(body.paths)]
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, *args, timeout=30.0)
    _check(result)
    return {"ok": True}


@router.post("/unstage-all")
async def unstage_all(body: WorkspaceRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "restore", "--staged", "--", ".", timeout=30.0)
    _check(result)
    return {"ok": True}


@router.post("/discard")
async def discard_changes(body: StageRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    async with git_locks.acquire(cwd):
        if body.paths:
            result = await run_git(
                cwd, "restore", *pathspec_args(body.paths), timeout=30.0
            )
            if not result.ok:
                _check(result)
            clean_result = await run_git(
                cwd, "clean", "-f", *pathspec_args(body.paths), timeout=30.0
            )
            if not clean_result.ok:
                _check(clean_result)
        else:
            result = await run_git(cwd, "restore", "--", ".", timeout=30.0)
            if not result.ok:
                _check(result)
            clean_result = await run_git(
                cwd, "clean", "-f", "--", ".", timeout=30.0
            )
            if not clean_result.ok:
                _check(clean_result)
    return {"ok": True}


# --- Commit ------------------------------------------------------------------


@router.post("/commit")
async def commit(body: CommitRequest) -> GitCommitOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    async with git_locks.acquire(cwd):
        if body.paths:
            stage_result = await run_git(
                cwd, "add", *pathspec_args(body.paths), timeout=30.0
            )
            if not stage_result.ok:
                _check(stage_result)
        args = ["commit"]
        if body.amend:
            args.append("--amend")
            if not body.message:
                args.append("--no-edit")
        if body.message:
            args.extend(["-m", body.message])
        proc = await run_git(cwd, *args, timeout=30.0)
        if not proc.ok and "nothing to commit" not in (proc.stderr + proc.stdout):
            _check(proc)
    # Deterministically get the SHA of the new commit
    sha = ""
    if proc.ok:
        rev = await run_git(cwd, "rev-parse", "HEAD", timeout=5.0)
        if rev.ok:
            sha = rev.stdout.strip()
    return GitCommitOut(sha=sha, message=body.message or "")


# --- Branches ----------------------------------------------------------------


@router.get("/branches")
async def list_branches(workspace: str) -> list[GitBranchOut]:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return []
    result = await run_git(
        cwd,
        "for-each-ref",
        "--format=%(refname)\t%(refname:short)\t%(upstream:short)\t%(HEAD)",
        "refs/heads",
        "refs/remotes",
        timeout=10.0,
    )
    if not result.ok:
        return []
    branches = parse_branches(result.stdout)
    out: list[GitBranchOut] = []
    for b in branches:
        ahead = behind = 0
        if b.current and b.name:
            ab = await run_git(
                cwd,
                "rev-list",
                "--left-right",
                "--count",
                f"{b.name}...{b.name}@{{upstream}}",
                timeout=5.0,
            )
            if ab.ok:
                parsed = parse_ahead_behind(ab.stdout)
                if parsed:
                    ahead, behind = parsed
        out.append(
            GitBranchOut(
                name=b.name,
                current=b.current,
                remote=b.remote,
                ahead=ahead,
                behind=behind,
            )
        )
    return out


@router.post("/branches")
async def create_branch(body: BranchCreateRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    if not validate_ref_name(body.name):
        raise HTTPException(status_code=422, detail=f"Invalid branch name: {body.name}")
    async with git_locks.acquire(cwd):
        args = ["branch", body.name]
        if body.start_point:
            args.append(body.start_point)
        result = await run_git(cwd, *args, timeout=10.0)
        _check(result)
        if body.checkout:
            result = await run_git(cwd, "switch", "--", body.name, timeout=30.0)
    _check(result)
    return {"ok": True}


# --- Diff view ---------------------------------------------------------------


@router.get("/diff-view")
async def get_diff_view(workspace: str, path: str) -> dict:
    """Return unified diff for a single file.

    Staged files → ``git diff --cached``, unstaged → ``git diff``,
    untracked → full file content shown as additions.
    """
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return {"diff": ""}

    # H1: Reject absolute paths and path traversal
    if Path(path).is_absolute() or ".." in Path(path).parts:
        raise HTTPException(status_code=422, detail="Invalid path")

    # Determine whether the file is staged or unstaged
    status_result = await run_git(cwd, "status", "--porcelain=v2", timeout=5.0)
    staged = False
    untracked = False
    if status_result.ok:
        for line in status_result.stdout.splitlines():
            if line.startswith("1 ") or line.startswith("2 "):
                parts = line.split(" ", 8)
                if len(parts) >= 9 and parts[8] == path:
                    xy = parts[1]
                    if xy[0] != ".":
                        staged = True
                    break
            elif line.startswith("? ") and line[2:].strip() == path:
                untracked = True
                break

    if untracked:
        # Show entire file as additions
        try:
            resolved = Path(cwd, path).resolve()
            if not str(resolved).startswith(str(Path(cwd).resolve()) + os.sep) and resolved != Path(cwd).resolve():
                raise HTTPException(status_code=422, detail="Path outside workspace")
            content = resolved.read_text(errors="replace")
            diff_lines = [
                f"--- /dev/null",
                f"+++ b/{path}",
                f"@@ -0,0 +1,{len(content.splitlines())} @@",
                *[f"+{line}" for line in content.splitlines()],
            ]
            return {"diff": "\n".join(diff_lines)}
        except OSError:
            return {"diff": ""}

    if staged:
        result = await run_git(cwd, "diff", "--cached", "--", path, timeout=10.0)
    else:
        result = await run_git(cwd, "diff", "--", path, timeout=10.0)
        # If no unstaged diff, try staged (could be fully staged)
        if not result.stdout.strip():
            result = await run_git(cwd, "diff", "--cached", "--", path, timeout=10.0)

    return {"diff": result.stdout if result.ok else ""}



@router.post("/branches/checkout")
async def checkout_branch(body: CheckoutRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    if not validate_ref_name(body.name):
        raise HTTPException(status_code=422, detail=f"Invalid ref name: {body.name}")
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "switch", "--", body.name, timeout=30.0)
    _check(result)
    return {"ok": True}


@router.delete("/branches")
async def delete_branch(workspace: str, name: str, force: bool = False) -> dict:
    cwd = await _validate(workspace)
    _require_repo(cwd)
    if not validate_ref_name(name):
        raise HTTPException(status_code=422, detail=f"Invalid ref name: {name}")
    args = ["branch", "-D" if force else "-d", "--", name]
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, *args, timeout=10.0)
    _check(result)
    return {"ok": True}


# --- Merge -------------------------------------------------------------------


@router.post("/merge")
async def merge(body: MergeRequest) -> GitMergeOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    if not validate_ref_name(body.branch):
        raise HTTPException(status_code=422, detail=f"Invalid ref name: {body.branch}")
    async with git_locks.acquire(cwd):
        result = await run_git(
            cwd, "merge", "--no-edit", "--", body.branch, timeout=60.0
        )
        conflicts = detect_inprogress_operation(cwd)
        conflicted_files = []
        if conflicts:
            status = await run_git(cwd, "status", "--porcelain=v2", timeout=10.0)
            if status.ok:
                parsed = parse_porcelain_v2_files(status.stdout)
                conflicted_files = [
                    f.path
                    for f in parsed.files
                    if f.status
                    in ("both modified", "both added", "both deleted", "unmerged")
                ]
    return GitMergeOut(
        success=result.ok and not conflicts,
        conflicts=conflicted_files,
        message=result.stdout.strip()[:500]
        if result.ok
        else result.stderr.strip()[:500],
    )


# --- Push / Pull / Fetch -----------------------------------------------------


@router.post("/fetch")
async def fetch(body: FetchRequest) -> GitJobOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    args = ["fetch"]
    if body.remote:
        args.append(body.remote)

    async def _do():
        return await run_git_long(cwd, *args, timeout=120.0)

    job, started = await git_jobs.start(workspace=cwd, op="fetch", coro=_do())
    return GitJobOut(
        workspace=cwd,
        op=job.op,
        status=job.status,
        message=job.message,
        error=job.error,
    )


@router.post("/pull")
async def pull(body: PullRequest) -> GitJobOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    args = ["pull"]
    if body.rebase:
        args.append("--rebase")
    if body.remote:
        args.append(body.remote)
    if body.branch:
        args.append(body.branch)

    async def _do():
        return await run_git_long(cwd, *args, timeout=120.0)

    job, started = await git_jobs.start(workspace=cwd, op="pull", coro=_do())
    return GitJobOut(
        workspace=cwd,
        op=job.op,
        status=job.status,
        message=job.message,
        error=job.error,
    )


@router.post("/push")
async def push(body: PushRequest) -> GitJobOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    args = ["push"]
    if body.force_with_lease:
        args.append("--force-with-lease")
    if body.remote:
        args.append(body.remote)
    if body.set_upstream:
        args.append("--set-upstream")
    if body.branch:
        args.append(body.branch)

    async def _do():
        return await run_git_long(cwd, *args, timeout=120.0)

    job, started = await git_jobs.start(workspace=cwd, op="push", coro=_do())
    return GitJobOut(
        workspace=cwd,
        op=job.op,
        status=job.status,
        message=job.message,
        error=job.error,
    )


@router.get("/jobs")
async def get_jobs(workspace: str) -> GitJobOut | None:
    cwd = await _validate(workspace)
    job = git_jobs.snapshot(cwd)
    if job is None:
        return None
    return GitJobOut(
        workspace=cwd,
        op=job.op,
        status=job.status,
        message=job.message,
        error=job.error,
    )


# --- Log ---------------------------------------------------------------------


@router.get("/log")
async def get_log(
    workspace: str,
    branch: str | None = None,
    skip: int = 0,
    limit: int = 50,
    path: str | None = None,
) -> GitLogOut:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return GitLogOut(entries=[], has_more=False)
    capped = min(max(limit, 1), 501)
    args = [
        "log",
        f"--skip={skip}",
        f"--max-count={capped}",
        "--format=%H\x1f%an\x1f%ai\x1f%s",
        "--date=iso",
    ]
    if branch:
        if not validate_ref_name(branch):
            raise HTTPException(status_code=422, detail=f"Invalid ref name: {branch}")
        args.append(branch)
    if path:
        args.extend(["--", path])
    result = await run_git(cwd, *args, timeout=15.0)
    if not result.ok:
        return GitLogOut(entries=[], has_more=False)
    entries = parse_log(result.stdout)
    has_more = len(entries) > min(limit, 500)
    entries = entries[: min(limit, 500)]
    return GitLogOut(
        entries=[
            GitLogEntryOut(
                sha=e.sha,
                short_sha=e.short_sha,
                author=e.author,
                date=e.date,
                message=e.message,
            )
            for e in entries
        ],
        has_more=has_more,
    )


@router.get("/log/{sha}/files")
async def get_log_files(workspace: str, sha: str) -> list[GitLogFileOut]:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return []
    if not _SHA_RE.match(sha):
        raise HTTPException(status_code=422, detail=f"Invalid SHA: {sha}")
    result = await run_git(cwd, "show", "--name-status", "--format=", "--", sha, timeout=10.0)
    if not result.ok:
        return []
    files = parse_log_files(result.stdout)
    return [GitLogFileOut(path=f.path, status=f.status) for f in files]


# --- Stash -------------------------------------------------------------------


@router.get("/stash")
async def list_stashes(workspace: str) -> list[GitStashOut]:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return []
    result = await run_git(cwd, "stash", "list", "--format=%H\x1f%gD\x1f%s", timeout=5.0)
    if not result.ok:
        return []
    entries = parse_stash_list(result.stdout)
    return [GitStashOut(index=e.index, message=e.message, sha=e.sha) for e in entries]


@router.post("/stash")
async def create_stash(body: StashRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    args = ["stash", "push"]
    if body.include_untracked:
        args.append("-u")
    if body.message:
        args.extend(["-m", body.message])
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, *args, timeout=30.0)
    _check(result)
    return {"ok": True}


@router.post("/stash/apply")
async def apply_stash(body: StashApplyRequest) -> GitMergeOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    async with git_locks.acquire(cwd):
        result = await run_git(
            cwd, "stash", "apply", f"stash@{{{body.index}}}", timeout=30.0
        )
        conflicts = detect_inprogress_operation(cwd) is not None
        conflicted_files: list[str] = []
        if conflicts:
            status = await run_git(cwd, "status", "--porcelain=v2", timeout=10.0)
            if status.ok:
                parsed = parse_porcelain_v2_files(status.stdout)
                conflicted_files = [
                    f.path
                    for f in parsed.files
                    if f.status
                    in ("both modified", "both added", "both deleted", "unmerged")
                ]
    return GitMergeOut(
        success=result.ok and not conflicts,
        conflicts=conflicted_files,
        message=result.stdout.strip()[:500]
        if result.ok
        else result.stderr.strip()[:500],
    )


@router.post("/stash/pop")
async def pop_stash(body: StashApplyRequest) -> GitMergeOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    async with git_locks.acquire(cwd):
        result = await run_git(
            cwd, "stash", "pop", f"stash@{{{body.index}}}", timeout=30.0
        )
        conflicts = detect_inprogress_operation(cwd) is not None
        conflicted_files: list[str] = []
        if conflicts:
            status = await run_git(cwd, "status", "--porcelain=v2", timeout=10.0)
            if status.ok:
                parsed = parse_porcelain_v2_files(status.stdout)
                conflicted_files = [
                    f.path
                    for f in parsed.files
                    if f.status
                    in ("both modified", "both added", "both deleted", "unmerged")
                ]
    return GitMergeOut(
        success=result.ok and not conflicts,
        conflicts=conflicted_files,
        message=result.stdout.strip()[:500]
        if result.ok
        else result.stderr.strip()[:500],
    )


@router.delete("/stash")
async def drop_stash(workspace: str, index: int = 0) -> dict:
    cwd = await _validate(workspace)
    _require_repo(cwd)
    async with git_locks.acquire(cwd):
        result = await run_git(
            cwd, "stash", "drop", f"stash@{{{index}}}", timeout=10.0
        )
    _check(result)
    return {"ok": True}


# --- Rebase ------------------------------------------------------------------


@router.post("/rebase")
async def rebase(body: RebaseRequest) -> GitMergeOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    if not validate_ref_name(body.onto):
        raise HTTPException(status_code=422, detail=f"Invalid ref name: {body.onto}")
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "rebase", "--", body.onto, timeout=120.0)
        op = detect_inprogress_operation(cwd)
        conflicted_files = []
        if op:
            status = await run_git(cwd, "status", "--porcelain=v2", timeout=10.0)
            if status.ok:
                parsed = parse_porcelain_v2_files(status.stdout)
                conflicted_files = [
                    f.path
                    for f in parsed.files
                    if f.status
                    in ("both modified", "both added", "both deleted", "unmerged")
                ]
    return GitMergeOut(
        success=result.ok and op is None,
        conflicts=conflicted_files,
        message=result.stdout.strip()[:500]
        if result.ok
        else result.stderr.strip()[:500],
    )


# --- Cherry-pick -------------------------------------------------------------


@router.post("/cherry-pick")
async def cherry_pick(body: CherryPickRequest) -> GitMergeOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    # H3: Validate each SHA
    for sha in body.shas:
        if not _SHA_RE.match(sha):
            raise HTTPException(status_code=422, detail=f"Invalid SHA: {sha}")
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "cherry-pick", "--", *body.shas, timeout=60.0)
        op = detect_inprogress_operation(cwd)
        conflicted_files = []
        if op:
            status = await run_git(cwd, "status", "--porcelain=v2", timeout=10.0)
            if status.ok:
                parsed = parse_porcelain_v2_files(status.stdout)
                conflicted_files = [
                    f.path
                    for f in parsed.files
                    if f.status
                    in ("both modified", "both added", "both deleted", "unmerged")
                ]
    return GitMergeOut(
        success=result.ok and op is None,
        conflicts=conflicted_files,
        message=result.stdout.strip()[:500]
        if result.ok
        else result.stderr.strip()[:500],
    )


# --- Conflict resolution -----------------------------------------------------


@router.get("/conflicts")
async def get_conflicts(workspace: str) -> GitConflictsOut:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return GitConflictsOut(conflicted=False, operation=None, files=[])
    op = detect_inprogress_operation(cwd)
    if not op:
        return GitConflictsOut(conflicted=False, operation=None, files=[])
    result = await run_git(cwd, "status", "--porcelain=v2", timeout=10.0)
    if not result.ok:
        return GitConflictsOut(conflicted=True, operation=op, files=[])
    parsed = parse_porcelain_v2_files(result.stdout)
    conflicted = [
        f
        for f in parsed.files
        if f.status in ("both modified", "both added", "both deleted", "unmerged")
    ]
    return GitConflictsOut(
        conflicted=True,
        operation=op,
        files=[ConflictedFileOut(path=f.path, status=f.status) for f in conflicted],
    )


@router.post("/continue")
async def continue_operation(body: WorkspaceRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    op = detect_inprogress_operation(cwd)
    if not op:
        raise HTTPException(status_code=422, detail="No in-progress operation found")
    async with git_locks.acquire(cwd):
        if op == "merge":
            result = await run_git(cwd, "merge", "--continue", timeout=60.0)
        elif op == "rebase":
            result = await run_git(cwd, "rebase", "--continue", timeout=120.0)
        elif op == "cherry-pick":
            result = await run_git(cwd, "cherry-pick", "--continue", timeout=60.0)
        else:
            raise HTTPException(status_code=422, detail=f"Unknown operation: {op}")
    _check(result)
    return {"ok": True}


@router.post("/abort")
async def abort_operation(body: WorkspaceRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    op = detect_inprogress_operation(cwd)
    if not op:
        raise HTTPException(status_code=422, detail="No in-progress operation found")
    async with git_locks.acquire(cwd):
        if op == "merge":
            result = await run_git(cwd, "merge", "--abort", timeout=30.0)
        elif op == "rebase":
            result = await run_git(cwd, "rebase", "--abort", timeout=30.0)
        elif op == "cherry-pick":
            result = await run_git(cwd, "cherry-pick", "--abort", timeout=30.0)
        else:
            raise HTTPException(status_code=422, detail=f"Unknown operation: {op}")
    _check(result)
    return {"ok": True}
