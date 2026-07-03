"""Git operations service layer.

Provides async git command execution with proper process-group management,
per-workspace locking for mutating operations, and a background-job registry
for long-running operations (push/pull/fetch).

All git invocations use argument-list subprocess (never shell=True) for
shell-injection safety.
"""

from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_CREATE_NEW_PROCESS_GROUP = 0x00000200 if sys.platform == "win32" else 0
_FORCE_KILL = getattr(signal, "SIGKILL", signal.SIGTERM)


@dataclass(frozen=True, slots=True)
class GitResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


@dataclass
class ChangedFile:
    path: str
    status: str
    staged: bool
    old_path: str | None = None


@dataclass
class GitChangesResult:
    branch: str | None
    ahead: int
    behind: int
    files: list[ChangedFile]


@dataclass
class GitBranchInfo:
    name: str
    current: bool
    remote: str | None
    ahead: int
    behind: int


@dataclass
class GitLogEntry:
    sha: str
    short_sha: str
    author: str
    date: str
    message: str


@dataclass
class GitLogFile:
    path: str
    status: str


@dataclass
class GitStashEntry:
    index: int
    message: str
    sha: str


@dataclass
class ConflictedFile:
    path: str
    status: str


@dataclass
class GitConflictsResult:
    conflicted: bool
    operation: str | None
    files: list[ConflictedFile]


@dataclass(slots=True)
class GitJob:
    workspace: str
    op: str
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    message: str = ""
    error: str | None = None


# --- Process helpers ---------------------------------------------------------


async def run_git(cwd: str, *args: str, timeout: float = 5.0) -> GitResult:
    """Run a git command with a timeout, returning structured result."""
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=cwd,
        )
        return GitResult(
            ok=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return GitResult(
            ok=False, stdout="", stderr="timeout", returncode=-1, timed_out=True
        )
    except OSError as exc:
        return GitResult(ok=False, stdout="", stderr=str(exc), returncode=-1)


async def run_git_long(cwd: str, *args: str, timeout: float = 120.0) -> GitResult:
    """Run a git command with process-group kill on timeout.

    For push/pull/fetch — kills the whole process group so child ssh processes
    don't hang. stdin=DEVNULL so auth prompts fail immediately.
    """
    creationflags = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            cwd=cwd,
            creationflags=creationflags if sys.platform == "win32" else 0,
            **({} if sys.platform == "win32" else {"start_new_session": True}),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            await _kill_process_group(proc)
            return GitResult(
                ok=False, stdout="", stderr="timeout", returncode=-1, timed_out=True
            )
        return GitResult(
            ok=proc.returncode == 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            returncode=proc.returncode or 0,
        )
    except OSError as exc:
        return GitResult(ok=False, stdout="", stderr=str(exc), returncode=-1)


async def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Kill the entire process group, escalating to SIGKILL after 5s."""
    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), _FORCE_KILL)
        except (ProcessLookupError, OSError):
            pass


# --- Parsing -----------------------------------------------------------------


def parse_porcelain_v2_files(stdout: str) -> GitChangesResult:
    """Parse git status --porcelain=v2 --branch into structured changes."""
    branch: str | None = None
    ahead = behind = 0
    files: list[ChangedFile] = []

    for line in stdout.splitlines():
        if line.startswith("# branch.head "):
            head = line[len("# branch.head ") :].strip()
            branch = None if head == "(detached)" else head
        elif line.startswith("# branch.ab "):
            parts = line[len("# branch.ab ") :].strip().split()
            if len(parts) == 2:
                ahead, behind = int(parts[0]), abs(int(parts[1]))
        elif line.startswith("1 "):
            parts = line.split(" ", 8)
            if len(parts) >= 9:
                xy = parts[1]
                path = parts[8]
                old_path = None
                if xy[0] != ".":
                    staged_flag = True
                else:
                    staged_flag = False
                status = _xy_to_status(xy)
                if len(parts) > 9 and parts[9]:
                    old_path = parts[9]
                files.append(
                    ChangedFile(
                        path=path, status=status, staged=staged_flag, old_path=old_path
                    )
                )
        elif line.startswith("2 "):
            parts = line.split(" ", 9)
            if len(parts) >= 9:
                xy = parts[1]
                path = parts[8]
                old_path = parts[9] if len(parts) > 9 else None
                staged_flag = xy[0] != "."
                status = _xy_to_status(xy)
                files.append(
                    ChangedFile(
                        path=path, status=status, staged=staged_flag, old_path=old_path
                    )
                )
        elif line.startswith("? "):
            path = line[2:].strip()
            files.append(ChangedFile(path=path, status="untracked", staged=False))
        elif line.startswith("u "):
            parts = line.split(" ", 8)
            if len(parts) >= 9:
                xy = parts[1]
                path = parts[8]
                status = _unmerged_status(xy)
                files.append(ChangedFile(path=path, status=status, staged=False))

    return GitChangesResult(branch=branch, ahead=ahead, behind=behind, files=files)


def _xy_to_status(xy: str) -> str:
    if xy[0] in ("A", "."):
        if xy[1] == "D":
            return "deleted"
        if xy[0] == "A":
            return "added"
    if "D" in xy:
        return "deleted"
    if "R" in xy:
        return "renamed"
    if "M" in xy:
        return "modified"
    return "modified"


def _unmerged_status(xy: str) -> str:
    mapping = {
        "DD": "both deleted",
        "AU": "added by us",
        "UD": "deleted by them",
        "UA": "added by them",
        "DU": "deleted by us",
        "AA": "both added",
        "UU": "both modified",
    }
    return mapping.get(xy, "unmerged")


def parse_ahead_behind(stdout: str) -> tuple[int, int] | None:
    """Parse git rev-list --left-right --count output."""
    parts = stdout.strip().split()
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return None


def parse_branches(stdout: str) -> list[GitBranchInfo]:
    """Parse git for-each-ref output."""
    branches: list[GitBranchInfo] = []
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            refname = parts[0]
            shortname = parts[1]
            is_current = parts[3] == "*" if len(parts) > 3 else False
            remote = None
            if refname.startswith("refs/remotes/"):
                remote = refname.split("/")[3] if len(refname.split("/")) > 3 else None
            branches.append(
                GitBranchInfo(
                    name=shortname,
                    current=is_current,
                    remote=remote,
                    ahead=0,
                    behind=0,
                )
            )
    return branches


def parse_log(stdout: str) -> list[GitLogEntry]:
    """Parse git log with custom format using \\x1f/\\x1e delimiters."""
    entries: list[GitLogEntry] = []
    for line in stdout.split("\x1e"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) >= 5:
            entries.append(
                GitLogEntry(
                    sha=parts[0],
                    short_sha=parts[0][:8],
                    author=parts[1],
                    date=parts[2],
                    message=parts[3],
                )
            )
    return entries


def parse_stash_list(stdout: str) -> list[GitStashEntry]:
    """Parse git stash list output."""
    entries: list[GitStashEntry] = []
    for line in stdout.splitlines():
        if line.startswith("stash@{"):
            idx_end = line.index("}")
            index = int(line[len("stash@{") : idx_end])
            rest = line[idx_end + 2 :]
            sha = rest[:8] if len(rest) >= 8 else ""
            message = rest
            entries.append(GitStashEntry(index=index, message=message, sha=sha))
    return entries


def parse_log_files(stdout: str) -> list[GitLogFile]:
    """Parse git show --name-status --format= output."""
    files: list[GitLogFile] = []
    for line in stdout.splitlines():
        line = line.strip()
        if (
            not line
            or line.startswith("commit")
            or line.startswith("Author")
            or line.startswith("Date")
        ):
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            files.append(GitLogFile(path=parts[1], status=parts[0]))
    return files


# --- Helpers -----------------------------------------------------------------


def is_git_repo(cwd: str) -> bool:
    return (Path(cwd) / ".git").exists()


def pathspec_args(paths: list[str] | None) -> list[str]:
    if paths:
        return ["--", *paths]
    return []


# Characters git forbids anywhere in a ref name: ASCII control chars,
# space, and the metacharacters ~ ^ : ? * [ \ (gitcheck-ref-format(1)).
_INVALID_REF_CHARS_RE = re.compile(r"[\000-\037\177 ~^:?*\[\\]")


def validate_ref_name(name: str) -> bool:
    """Check if a string is a valid git branch name.

    Pure-Python port of the ``git check-ref-format --branch`` rules — this
    is called synchronously from async handlers, so shelling out here would
    block the event loop for every request.
    """
    if not name or name in ("@", "HEAD"):
        return False
    # ``--branch`` additionally rejects dash-prefixed names (option lookalikes).
    if name.startswith("-"):
        return False
    if name.startswith("/") or name.endswith("/") or name.endswith("."):
        return False
    if ".." in name or "@{" in name:
        return False
    if _INVALID_REF_CHARS_RE.search(name):
        return False
    for component in name.split("/"):
        if not component or component.startswith(".") or component.endswith(".lock"):
            return False
    return True


def detect_inprogress_operation(cwd: str) -> str | None:
    git_dir = Path(cwd) / ".git"
    if (git_dir / "MERGE_HEAD").exists():
        return "merge"
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        return "rebase"
    if (git_dir / "CHERRY_PICK_HEAD").exists():
        return "cherry-pick"
    return None


# --- Lock registry -----------------------------------------------------------


class GitLockRegistry:
    """Per-workspace asyncio.Lock registry."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._refcounts: dict[str, int] = {}

    def acquire(self, path: str) -> asyncio.Lock:
        resolved = str(Path(path).resolve())
        if resolved not in self._locks:
            self._locks[resolved] = asyncio.Lock()
            self._refcounts[resolved] = 0
        self._refcounts[resolved] += 1
        return self._locks[resolved]

    def is_locked(self, path: str) -> bool:
        resolved = str(Path(path).resolve())
        lock = self._locks.get(resolved)
        return lock is not None and lock.locked()


git_locks = GitLockRegistry()


# --- Job registry -----------------------------------------------------------


class GitJobRegistry:
    """Background job registry for push/pull/fetch."""

    def __init__(self) -> None:
        self._jobs: dict[str, GitJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        workspace: str,
        op: str,
        coro,
    ) -> tuple[GitJob, bool]:
        key = str(Path(workspace).resolve())
        async with self._lock:
            existing = self._jobs.get(key)
            if existing is not None and existing.status == "running":
                return existing, False
            job = GitJob(workspace=workspace, op=op)
            self._jobs[key] = job
            task = asyncio.create_task(self._run(job=job, coro=coro))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return job, True

    async def _run(self, *, job: GitJob, coro) -> None:
        try:
            result = await coro
            if isinstance(result, GitResult):
                if result.ok:
                    job.status = "done"
                    job.message = result.stdout.strip()[:500]
                else:
                    job.status = "error"
                    job.error = (
                        result.stderr.strip()[:500] or result.stdout.strip()[:500]
                    )
            else:
                job.status = "done"
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)[:500]
            logger.exception("git job failed op={} workspace={}", job.op, job.workspace)
        finally:
            job.finished_at = time.time()

    def snapshot(self, workspace: str) -> GitJob | None:
        return self._jobs.get(str(Path(workspace).resolve()))

    def is_running(self, workspace: str) -> bool:
        job = self._jobs.get(str(Path(workspace).resolve()))
        return job is not None and job.status == "running"


git_jobs = GitJobRegistry()
