"""Git operations API routes.

Full git tool window backend: local changes, commit, branches, push/pull/fetch,
log, stash, merge, rebase, cherry-pick, and conflict handling.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.core.runtime_settings import load_runtime_settings
from app.api.schemas.git import (
    BranchCreateRequest,
    BranchDeleteRequest,
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
    GitIdentityRequest,
    GitInitRequest,
    GitJobOut,
    GitLogFileOut,
    GitLogEntryOut,
    GitLogOut,
    GitMergeOut,
    GitRemoteDeleteRequest,
    GitRemoteOut,
    GitRemoteRequest,
    GitRepositoryOut,
    GitStashOut,
    GitTagDeleteRequest,
    GitTagOut,
    GitTagRequest,
    GitTagsPushRequest,
    MergeRequest,
    PullRequest,
    PushRequest,
    RebaseRequest,
    RevertRequest,
    StageRequest,
    StashApplyRequest,
    StashRequest,
    WorkspaceRequest,
)
from app.services import team_manager
from app.services.git_credentials import resolve_workspace_git_credential
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


# --- Repository --------------------------------------------------------------


@router.get("/repository")
async def get_repository(workspace: str) -> GitRepositoryOut:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return GitRepositoryOut(is_git_repo=False)

    async def read(*args: str) -> str | None:
        result = await run_git(cwd, *args, timeout=5.0)
        value = result.stdout.strip()
        return value if result.ok and value else None

    root = await read("rev-parse", "--show-toplevel")
    branch = await read("symbolic-ref", "--quiet", "--short", "HEAD")
    upstream = await read(
        "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    head_sha = await read("rev-parse", "--short=12", "HEAD")
    head_subject = await read("log", "-1", "--format=%s")
    user_name = await read("config", "--get", "user.name")
    user_email = await read("config", "--get", "user.email")
    return GitRepositoryOut(
        is_git_repo=True,
        root=root,
        branch=branch,
        detached=branch is None and head_sha is not None,
        upstream=upstream,
        head_sha=head_sha,
        head_subject=head_subject,
        user_name=user_name,
        user_email=user_email,
    )


@router.post("/repository/init")
async def init_repository(body: GitInitRequest) -> GitRepositoryOut:
    cwd = await _validate(body.workspace)
    if is_git_repo(cwd):
        raise HTTPException(status_code=409, detail="Git is already initialized")
    if not validate_ref_name(body.default_branch):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid default branch: {body.default_branch}",
        )
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "init", "-b", body.default_branch, timeout=30.0)
    _check(result)
    return await get_repository(cwd)


@router.post("/repository/identity")
async def set_repository_identity(body: GitIdentityRequest) -> GitRepositoryOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    name = body.name.strip()
    email = body.email.strip()
    if (
        not name
        or not email
        or any(ord(char) < 32 for char in name)
        or any(ord(char) < 32 for char in email)
    ):
        raise HTTPException(status_code=422, detail="Invalid Git identity")
    async with git_locks.acquire(cwd):
        name_result = await run_git(
            cwd, "config", "--local", "user.name", name, timeout=5.0
        )
        _check(name_result)
        email_result = await run_git(
            cwd, "config", "--local", "user.email", email, timeout=5.0
        )
    _check(email_result)
    return await get_repository(cwd)


# --- Local Changes -----------------------------------------------------------


@router.get("/changes")
async def get_changes(workspace: str) -> GitChangesOut:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return GitChangesOut(
            is_git_repo=False,
            branch=None,
            ahead=0,
            behind=0,
            files=[],
        )
    result = await run_git(cwd, "status", "--porcelain=v2", "--branch", timeout=10.0)
    if not result.ok:
        return GitChangesOut(branch=None, ahead=0, behind=0, files=[])
    parsed = parse_porcelain_v2_files(result.stdout)
    return GitChangesOut(
        is_git_repo=True,
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
    async with git_locks.acquire(cwd):
        head = await run_git(cwd, "rev-parse", "--verify", "HEAD", timeout=5.0)
        pathspec = pathspec_args(body.paths) or ["--", "."]
        args = (
            ["restore", "--staged", *pathspec]
            if head.ok
            else ["rm", "--cached", "-r", *pathspec]
        )
        result = await run_git(cwd, *args, timeout=30.0)
    _check(result)
    return {"ok": True}


@router.post("/unstage-all")
async def unstage_all(body: WorkspaceRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    async with git_locks.acquire(cwd):
        head = await run_git(cwd, "rev-parse", "--verify", "HEAD", timeout=5.0)
        args = (
            ["restore", "--staged", "--", "."]
            if head.ok
            else ["rm", "--cached", "-r", "--", "."]
        )
        result = await run_git(cwd, *args, timeout=30.0)
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
            clean_result = await run_git(cwd, "clean", "-f", "--", ".", timeout=30.0)
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
        if not proc.ok:
            if "nothing to commit" in (proc.stderr + proc.stdout).lower():
                raise HTTPException(status_code=409, detail="Nothing to commit")
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
    max_bytes = load_runtime_settings().git.max_diff_bytes

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
            if (
                not str(resolved).startswith(str(Path(cwd).resolve()) + os.sep)
                and resolved != Path(cwd).resolve()
            ):
                raise HTTPException(status_code=422, detail="Path outside workspace")
            if resolved.stat().st_size > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Diff exceeds the configured {max_bytes} byte limit.",
                )
            content = resolved.read_text(errors="replace")
            diff_lines = [
                "--- /dev/null",
                f"+++ b/{path}",
                f"@@ -0,0 +1,{len(content.splitlines())} @@",
                *[f"+{line}" for line in content.splitlines()],
            ]
            return {"diff": "\n".join(diff_lines)}
        except OSError:
            return {"diff": ""}

    if staged:
        result = await run_git(
            cwd,
            "diff",
            "--cached",
            "--",
            path,
            timeout=10.0,
            max_output_bytes=max_bytes,
        )
    else:
        result = await run_git(
            cwd,
            "diff",
            "--",
            path,
            timeout=10.0,
            max_output_bytes=max_bytes,
        )
        # If no unstaged diff, try staged (could be fully staged)
        if not result.stdout.strip():
            if result.output_limited:
                raise HTTPException(
                    status_code=413,
                    detail=f"Diff exceeds the configured {max_bytes} byte limit.",
                )
            result = await run_git(
                cwd,
                "diff",
                "--cached",
                "--",
                path,
                timeout=10.0,
                max_output_bytes=max_bytes,
            )

    diff = result.stdout if result.ok else ""
    if result.output_limited:
        raise HTTPException(
            status_code=413,
            detail=f"Diff exceeds the configured {max_bytes} byte limit.",
        )
    if len(diff.encode("utf-8", errors="replace")) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Diff exceeds the configured {max_bytes} byte limit.",
        )
    return {"diff": diff}


@router.post("/branches/checkout")
async def checkout_branch(body: CheckoutRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    if not validate_ref_name(body.name):
        raise HTTPException(status_code=422, detail=f"Invalid ref name: {body.name}")
    async with git_locks.acquire(cwd):
        args = ["switch"]
        if body.track:
            args.append("--track")
        args.extend(["--", body.name])
        result = await run_git(cwd, *args, timeout=30.0)
    _check(result)
    return {"ok": True}


@router.delete("/branches")
async def delete_branch(body: BranchDeleteRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    if not validate_ref_name(body.name):
        raise HTTPException(status_code=422, detail=f"Invalid ref name: {body.name}")
    args = ["branch", "-D" if body.force else "-d", "--", body.name]
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, *args, timeout=10.0)
    _check(result)
    return {"ok": True}


# --- Tags --------------------------------------------------------------------


@router.get("/tags")
async def list_tags(workspace: str, limit: int = 200) -> list[GitTagOut]:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return []
    capped = min(max(limit, 1), 500)
    result = await run_git(
        cwd,
        "for-each-ref",
        "--sort=-creatordate",
        f"--count={capped}",
        "--format=%(refname:short)\x1f%(objectname)\x1f%(subject)\x1f%(creatordate:iso8601)",
        "refs/tags",
        timeout=10.0,
    )
    if not result.ok:
        return []
    tags: list[GitTagOut] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) >= 4:
            tags.append(
                GitTagOut(
                    name=parts[0],
                    sha=parts[1][:12],
                    subject=parts[2],
                    date=parts[3],
                )
            )
    return tags


@router.post("/tags")
async def create_tag(body: GitTagRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    valid_name = await run_git(
        cwd, "check-ref-format", f"refs/tags/{body.name}", timeout=5.0
    )
    if not valid_name.ok:
        raise HTTPException(status_code=422, detail=f"Invalid tag name: {body.name}")
    target = body.target or "HEAD"
    verified = await run_git(
        cwd, "rev-parse", "--verify", "--end-of-options", f"{target}^{{commit}}"
    )
    _check(verified)
    sha = verified.stdout.strip()
    args = ["tag"]
    if body.message:
        args.extend(["-a", body.name, "-m", body.message, sha])
    else:
        args.extend([body.name, sha])
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, *args, timeout=10.0)
    _check(result)
    return {"ok": True}


@router.delete("/tags")
async def delete_tag(body: GitTagDeleteRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    valid_name = await run_git(
        cwd, "check-ref-format", f"refs/tags/{body.name}", timeout=5.0
    )
    if not valid_name.ok:
        raise HTTPException(status_code=422, detail=f"Invalid tag name: {body.name}")
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "tag", "--delete", body.name, timeout=10.0)
    _check(result)
    return {"ok": True}


@router.post("/tags/push")
async def push_tags(body: GitTagsPushRequest, db: DbSession) -> GitJobOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    credential = await resolve_workspace_git_credential(db, cwd)
    args = ["push"]
    if body.remote:
        await _validate_remote_name(cwd, body.remote)
        args.append(body.remote)
    if body.tag:
        valid_name = await run_git(
            cwd, "check-ref-format", f"refs/tags/{body.tag}", timeout=5.0
        )
        if not valid_name.ok:
            raise HTTPException(status_code=422, detail=f"Invalid tag name: {body.tag}")
        args.append(f"refs/tags/{body.tag}")
    else:
        args.append("--tags")

    async def _do():
        async with git_locks.acquire(cwd):
            return await run_git_long(
                cwd,
                *args,
                timeout=load_runtime_settings().git.network_timeout_seconds,
                credential=credential,
            )

    job, _ = await git_jobs.start(workspace=cwd, op="push tags", coro_factory=_do)
    return GitJobOut(
        workspace=cwd,
        op=job.op,
        status=job.status,
        message=job.message,
        error=job.error,
    )


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
async def fetch(body: FetchRequest, db: DbSession) -> GitJobOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    credential = await resolve_workspace_git_credential(db, cwd)
    args = ["fetch"]
    git_cfg = load_runtime_settings().git
    if body.prune if body.prune is not None else git_cfg.prune_on_fetch:
        args.append("--prune")
    if body.remote:
        await _validate_remote_name(cwd, body.remote)
        args.append(body.remote)

    async def _do():
        async with git_locks.acquire(cwd):
            return await run_git_long(
                cwd,
                *args,
                timeout=git_cfg.network_timeout_seconds,
                credential=credential,
            )

    job, _ = await git_jobs.start(workspace=cwd, op="fetch", coro_factory=_do)
    return GitJobOut(
        workspace=cwd,
        op=job.op,
        status=job.status,
        message=job.message,
        error=job.error,
    )


@router.post("/pull")
async def pull(body: PullRequest, db: DbSession) -> GitJobOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    credential = await resolve_workspace_git_credential(db, cwd)
    git_cfg = load_runtime_settings().git
    args = ["pull"]
    strategy = body.strategy or (
        "rebase" if body.rebase else git_cfg.default_pull_strategy
    )
    if strategy == "rebase":
        args.append("--rebase")
    elif strategy == "ff_only":
        args.append("--ff-only")
    else:
        args.append("--no-rebase")
    if body.remote:
        await _validate_remote_name(cwd, body.remote)
        args.append(body.remote)
    if body.branch:
        if not validate_ref_name(body.branch):
            raise HTTPException(
                status_code=422, detail=f"Invalid branch name: {body.branch}"
            )
        args.append(body.branch)

    async def _do():
        async with git_locks.acquire(cwd):
            return await run_git_long(
                cwd,
                *args,
                timeout=git_cfg.network_timeout_seconds,
                credential=credential,
            )

    job, _ = await git_jobs.start(workspace=cwd, op="pull", coro_factory=_do)
    return GitJobOut(
        workspace=cwd,
        op=job.op,
        status=job.status,
        message=job.message,
        error=job.error,
    )


@router.post("/push")
async def push(body: PushRequest, db: DbSession) -> GitJobOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    credential = await resolve_workspace_git_credential(db, cwd)
    git_cfg = load_runtime_settings().git
    args = ["push"]
    if body.force_with_lease:
        if not git_cfg.allow_force_push:
            raise HTTPException(
                status_code=403,
                detail="Force push is disabled in Git & reviews settings.",
            )
        args.append("--force-with-lease")
    if body.remote:
        await _validate_remote_name(cwd, body.remote)
        args.append(body.remote)
    if body.set_upstream:
        args.append("--set-upstream")
    if body.branch:
        if not validate_ref_name(body.branch):
            raise HTTPException(
                status_code=422, detail=f"Invalid branch name: {body.branch}"
            )
        args.append(body.branch)

    async def _do():
        async with git_locks.acquire(cwd):
            return await run_git_long(
                cwd,
                *args,
                timeout=git_cfg.network_timeout_seconds,
                credential=credential,
            )

    job, _ = await git_jobs.start(workspace=cwd, op="push", coro_factory=_do)
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


# --- Remotes ----------------------------------------------------------------


@router.get("/remotes")
async def list_remotes(workspace: str) -> list[GitRemoteOut]:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return []
    names_result = await run_git(cwd, "remote", timeout=5.0)
    if not names_result.ok:
        return []
    remotes: list[GitRemoteOut] = []
    for name in names_result.stdout.splitlines():
        name = name.strip()
        if not name:
            continue
        fetch_result = await run_git(cwd, "remote", "get-url", name, timeout=5.0)
        push_result = await run_git(
            cwd, "remote", "get-url", "--push", name, timeout=5.0
        )
        if fetch_result.ok:
            fetch_url = fetch_result.stdout.strip()
            remotes.append(
                GitRemoteOut(
                    name=name,
                    fetch_url=fetch_url,
                    push_url=push_result.stdout.strip()
                    if push_result.ok
                    else fetch_url,
                )
            )
    return remotes


async def _validate_remote_name(cwd: str, name: str) -> None:
    if not validate_ref_name(name):
        raise HTTPException(status_code=422, detail=f"Invalid remote name: {name}")
    result = await run_git(
        cwd, "check-ref-format", f"refs/remotes/{name}/probe", timeout=5.0
    )
    if not result.ok or name == "HEAD":
        raise HTTPException(status_code=422, detail=f"Invalid remote name: {name}")


def _validate_remote_url(url: str) -> str:
    value = url.strip()
    if not value or value.startswith("-") or any(ord(char) < 32 for char in value):
        raise HTTPException(status_code=422, detail="Invalid remote URL")
    if "::" in value:
        raise HTTPException(
            status_code=422,
            detail="Git remote helpers are not allowed.",
        )
    parsed = urlparse(value)
    if parsed.username is not None or parsed.password is not None:
        raise HTTPException(
            status_code=422,
            detail="Store remote credentials in a Git server connection, not the URL.",
        )
    windows_drive_path = (
        len(parsed.scheme) == 1
        and len(value) >= 3
        and value[1] == ":"
        and value[2] in {"/", "\\"}
    )
    if (
        parsed.scheme
        and not windows_drive_path
        and parsed.scheme.lower()
        not in {
            "file",
            "git",
            "http",
            "https",
            "ssh",
        }
    ):
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported Git remote protocol: {parsed.scheme}",
        )
    return value


@router.post("/remotes")
async def create_remote(body: GitRemoteRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    await _validate_remote_name(cwd, body.name)
    url = _validate_remote_url(body.url)
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "remote", "add", body.name, url, timeout=10.0)
    _check(result)
    return {"ok": True}


@router.put("/remotes")
async def update_remote(body: GitRemoteRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    await _validate_remote_name(cwd, body.name)
    url = _validate_remote_url(body.url)
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "remote", "set-url", body.name, url, timeout=10.0)
    _check(result)
    return {"ok": True}


@router.delete("/remotes")
async def delete_remote(body: GitRemoteDeleteRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    await _validate_remote_name(cwd, body.name)
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "remote", "remove", body.name, timeout=10.0)
    _check(result)
    return {"ok": True}


# --- Log ---------------------------------------------------------------------


@router.get("/log")
async def get_log(
    workspace: str,
    branch: str | None = None,
    all_branches: bool = False,
    skip: int = 0,
    limit: int = 100,
    path: str | None = None,
) -> GitLogOut:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return GitLogOut(entries=[], has_more=False)
    page_size = min(max(limit, 1), 500)
    offset = max(skip, 0)
    args = [
        "log",
        "--topo-order",
        "--decorate=short",
        f"--skip={offset}",
        f"--max-count={page_size + 1}",
        "--format=%H\x1f%P\x1f%D\x1f%an\x1f%ai\x1f%s",
        "--date=iso",
    ]
    if branch:
        if not validate_ref_name(branch):
            raise HTTPException(status_code=422, detail=f"Invalid ref name: {branch}")
        args.append(branch)
    elif all_branches:
        args.extend(["--branches", "--tags"])
    if path:
        args.extend(["--", path])
    result = await run_git(cwd, *args, timeout=15.0)
    if not result.ok:
        return GitLogOut(entries=[], has_more=False)
    entries = parse_log(result.stdout)
    has_more = len(entries) > page_size
    entries = entries[:page_size]
    return GitLogOut(
        entries=[
            GitLogEntryOut(
                sha=e.sha,
                short_sha=e.short_sha,
                parent_shas=e.parent_shas,
                refs=e.refs,
                author=e.author,
                date=e.date,
                message=e.message,
            )
            for e in entries
        ],
        has_more=has_more,
        next_skip=offset + len(entries) if has_more else None,
    )


@router.get("/log/{sha}/files")
async def get_log_files(workspace: str, sha: str) -> list[GitLogFileOut]:
    cwd = await _validate(workspace)
    if not is_git_repo(cwd):
        return []
    if not _SHA_RE.match(sha):
        raise HTTPException(status_code=422, detail=f"Invalid SHA: {sha}")
    result = await run_git(
        cwd, "show", "--name-status", "--format=", sha, "--", timeout=10.0
    )
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
    result = await run_git(
        cwd, "stash", "list", "--format=%H\x1f%gD\x1f%s", timeout=5.0
    )
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
        operation = detect_inprogress_operation(cwd)
        conflicted_files: list[str] = []
        if operation or not result.ok:
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
        success=result.ok and not conflicted_files,
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
        operation = detect_inprogress_operation(cwd)
        conflicted_files: list[str] = []
        if operation or not result.ok:
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
        success=result.ok and not conflicted_files,
        conflicts=conflicted_files,
        message=result.stdout.strip()[:500]
        if result.ok
        else result.stderr.strip()[:500],
    )


@router.delete("/stash")
async def drop_stash(body: StashApplyRequest) -> dict:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    async with git_locks.acquire(cwd):
        result = await run_git(
            cwd, "stash", "drop", f"stash@{{{body.index}}}", timeout=10.0
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


# --- Revert ------------------------------------------------------------------


@router.post("/revert")
async def revert_commit(body: RevertRequest) -> GitMergeOut:
    cwd = await _validate(body.workspace)
    _require_repo(cwd)
    if not _SHA_RE.match(body.sha):
        raise HTTPException(status_code=422, detail=f"Invalid SHA: {body.sha}")
    async with git_locks.acquire(cwd):
        result = await run_git(cwd, "revert", "--no-edit", "--", body.sha, timeout=60.0)
        op = detect_inprogress_operation(cwd)
        conflicted_files: list[str] = []
        if op:
            status = await run_git(cwd, "status", "--porcelain=v2", timeout=10.0)
            if status.ok:
                parsed = parse_porcelain_v2_files(status.stdout)
                conflicted_files = [
                    file.path
                    for file in parsed.files
                    if file.status
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
    result = await run_git(cwd, "status", "--porcelain=v2", timeout=10.0)
    if not result.ok:
        return GitConflictsOut(conflicted=op is not None, operation=op, files=[])
    parsed = parse_porcelain_v2_files(result.stdout)
    conflicted = [
        f
        for f in parsed.files
        if f.status in ("both modified", "both added", "both deleted", "unmerged")
    ]
    return GitConflictsOut(
        conflicted=bool(op or conflicted),
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
        elif op == "revert":
            result = await run_git(cwd, "revert", "--continue", timeout=60.0)
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
        elif op == "revert":
            result = await run_git(cwd, "revert", "--abort", timeout=30.0)
        else:
            raise HTTPException(status_code=422, detail=f"Unknown operation: {op}")
    _check(result)
    return {"ok": True}
