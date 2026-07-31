"""Git operations service layer.

Provides async git command execution with proper process-group management,
per-workspace locking for mutating operations, and a background-job registry
for long-running operations (push/pull/fetch).

All git invocations use argument-list subprocess (never shell=True) for
shell-injection safety.
"""

from __future__ import annotations

import asyncio
import ast
import os
import re
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_CREATE_NEW_PROCESS_GROUP = 0x00000200 if sys.platform == "win32" else 0
_FORCE_KILL = getattr(signal, "SIGKILL", signal.SIGTERM)
_EVOFLUX_CREDENTIAL_HELPER = (
    '!f() { test "$1" = get || exit 0; host=""; '
    'while IFS= read -r line; do case "$line" in host=*) host="${line#host=}";; esac; done; '
    'case "$host" in "$EVOFLUX_GIT_HOST"|"$EVOFLUX_GIT_HOST":*) ;; *) exit 0;; esac; '
    'printf "%s\\n" "username=$EVOFLUX_GIT_USERNAME" '
    '"password=$EVOFLUX_GIT_ACCESS_TOKEN"; }; f'
)
_CREDENTIALED_HTTP_URL_RE = re.compile(r"(?P<scheme>https?://)[^/@\s]+@", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class GitResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    output_limited: bool = False


@dataclass(frozen=True, slots=True)
class GitCredential:
    """Ephemeral HTTPS credential passed to Git without exposing it in argv."""

    host: str
    username: str
    token: str
    verify_ssl: bool = True


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
    parent_shas: list[str]
    refs: list[str]
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


def sanitize_git_output(value: str, *secrets: str) -> str:
    """Redact credentials from command output before it reaches logs or APIs."""
    sanitized = value
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return _CREDENTIALED_HTTP_URL_RE.sub(
        lambda match: f"{match.group('scheme')}[REDACTED]@", sanitized
    )


# --- Process helpers ---------------------------------------------------------


async def run_git(
    cwd: str,
    *args: str,
    timeout: float = 5.0,
    max_output_bytes: int | None = None,
) -> GitResult:
    """Run Git non-interactively and terminate its process group on timeout."""
    return await run_git_long(
        cwd,
        *args,
        timeout=timeout,
        max_output_bytes=max_output_bytes,
    )


async def run_git_long(
    cwd: str,
    *args: str,
    timeout: float = 120.0,
    credential: GitCredential | None = None,
    max_output_bytes: int | None = None,
) -> GitResult:
    """Run Git with process-group kill, closed stdin, and optional credentials."""
    creationflags = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    command = ["git", *args]
    process_env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
        "SSH_ASKPASS_REQUIRE": "never",
    }
    if credential is not None:
        command = [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            f"credential.helper={_EVOFLUX_CREDENTIAL_HELPER}",
            *args,
        ]
        process_env.update(
            {
                "EVOFLUX_GIT_HOST": credential.host,
                "EVOFLUX_GIT_USERNAME": credential.username,
                "EVOFLUX_GIT_ACCESS_TOKEN": credential.token,
            }
        )
        if not credential.verify_ssl:
            process_env["GIT_SSL_NO_VERIFY"] = "1"
    try:
        if sys.platform == "win32":
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=cwd,
                env=process_env,
                creationflags=creationflags,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=cwd,
                env=process_env,
                start_new_session=True,
            )
        output_size = [0]

        async def _read(stream: asyncio.StreamReader | None) -> bytes:
            if stream is None:
                return b""
            chunks: list[bytes] = []
            while chunk := await stream.read(64 * 1024):
                output_size[0] += len(chunk)
                if max_output_bytes is not None and output_size[0] > max_output_bytes:
                    raise _GitOutputLimitExceeded
                chunks.append(chunk)
            return b"".join(chunks)

        wait_task = asyncio.create_task(proc.wait())
        stdout_task = asyncio.create_task(_read(proc.stdout))
        stderr_task = asyncio.create_task(_read(proc.stderr))

        async def _cancel_tasks() -> None:
            for task in (wait_task, stdout_task, stderr_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                wait_task,
                stdout_task,
                stderr_task,
                return_exceptions=True,
            )

        try:
            await asyncio.wait_for(
                asyncio.gather(wait_task, stdout_task, stderr_task),
                timeout=timeout,
            )
            stdout = stdout_task.result()
            stderr = stderr_task.result()
        except asyncio.CancelledError:
            await _kill_process_group(proc)
            await _cancel_tasks()
            raise
        except asyncio.TimeoutError:
            await _kill_process_group(proc)
            await _cancel_tasks()
            return GitResult(
                ok=False, stdout="", stderr="timeout", returncode=-1, timed_out=True
            )
        except _GitOutputLimitExceeded:
            await _kill_process_group(proc)
            await _cancel_tasks()
            return GitResult(
                ok=False,
                stdout="",
                stderr="output exceeds configured limit",
                returncode=-1,
                output_limited=True,
            )
        secrets = (credential.token,) if credential is not None else ()
        return GitResult(
            ok=proc.returncode == 0,
            stdout=sanitize_git_output(stdout.decode(errors="replace"), *secrets),
            stderr=sanitize_git_output(stderr.decode(errors="replace"), *secrets),
            returncode=proc.returncode or 0,
        )
    except OSError as exc:
        return GitResult(ok=False, stdout="", stderr=str(exc), returncode=-1)


class _GitOutputLimitExceeded(Exception):
    pass


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
                path = _decode_git_path(parts[8])
                files.extend(_ordinary_changed_files(path, xy))
        elif line.startswith("2 "):
            parts = line.split(" ", 9)
            if len(parts) >= 10:
                xy = parts[1]
                path_pair = parts[9].split("\t", 1)
                path = _decode_git_path(path_pair[0])
                old_path = (
                    _decode_git_path(path_pair[1]) if len(path_pair) > 1 else None
                )
                files.extend(_ordinary_changed_files(path, xy, old_path=old_path))
        elif line.startswith("? "):
            path = _decode_git_path(line[2:].strip())
            files.append(ChangedFile(path=path, status="untracked", staged=False))
        elif line.startswith("u "):
            parts = line.split(" ", 10)
            if len(parts) >= 11:
                xy = parts[1]
                path = _decode_git_path(parts[10])
                status = _unmerged_status(xy)
                files.append(ChangedFile(path=path, status=status, staged=False))

    return GitChangesResult(branch=branch, ahead=ahead, behind=behind, files=files)


def _decode_git_path(value: str) -> str:
    """Decode Git's C-style quoted path representation when present."""
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        try:
            decoded = ast.literal_eval(value)
            if isinstance(decoded, str):
                return decoded
        except (SyntaxError, ValueError):
            pass
    return value


def _status_for_code(code: str) -> str:
    return {
        "A": "added",
        "C": "added",
        "D": "deleted",
        "M": "modified",
        "R": "renamed",
        "T": "modified",
        "U": "unmerged",
    }.get(code, "modified")


def _ordinary_changed_files(
    path: str,
    xy: str,
    *,
    old_path: str | None = None,
) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    if xy and xy[0] not in {".", " "}:
        files.append(
            ChangedFile(
                path=path,
                status=_status_for_code(xy[0]),
                staged=True,
                old_path=old_path,
            )
        )
    if len(xy) > 1 and xy[1] not in {".", " "}:
        files.append(
            ChangedFile(
                path=path,
                status=_status_for_code(xy[1]),
                staged=False,
                old_path=old_path,
            )
        )
    return files


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
                ref_parts = refname.split("/")
                remote = ref_parts[2] if len(ref_parts) > 3 else None
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
    """Parse graph-aware git log output separated by unit separators."""
    entries: list[GitLogEntry] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) >= 6:
            entries.append(
                GitLogEntry(
                    sha=parts[0],
                    short_sha=parts[0][:8],
                    parent_shas=parts[1].split(),
                    refs=[ref.strip() for ref in parts[2].split(",") if ref.strip()],
                    author=parts[3],
                    date=parts[4],
                    message="\x1f".join(parts[5:]),
                )
            )
    return entries


def parse_stash_list(stdout: str) -> list[GitStashEntry]:
    """Parse git stash list output (with --format=%H\\x1f%gD\\x1f%s)."""
    entries: list[GitStashEntry] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) >= 3:
            sha = parts[0].strip()
            gD = parts[1].strip()
            message = parts[2].strip()
            # Extract index from gD like "stash@{0}"
            m = re.search(r"stash@\{(\d+)\}", gD)
            index = int(m.group(1)) if m else 0
            entries.append(GitStashEntry(index=index, message=message, sha=sha[:8]))
        elif line.startswith("stash@{"):
            # Fallback: parse legacy format without --format
            idx_end = line.index("}")
            index = int(line[len("stash@{") : idx_end])
            rest = line[idx_end + 2 :]
            entries.append(GitStashEntry(index=index, message=rest, sha=""))
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
    dot_git = Path(cwd) / ".git"
    return dot_git.is_dir() or dot_git.is_file()


def pathspec_args(paths: list[str] | None) -> list[str]:
    if paths:
        return ["--", *paths]
    return []


# Characters git forbids anywhere in a ref name: ASCII control chars,
# space, and the metacharacters ~ ^ : ? * [ \ (gitcheck-ref-format(1)).
_INVALID_REF_CHARS_RE = re.compile(r"[\000-\037\177 ~^:?*\[\\]")

# Valid short/long SHA-1 or SHA-256 hex string.
_SHA_RE = re.compile(r"^[0-9a-f]{4,64}$")


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


def git_dir_path(cwd: str) -> Path | None:
    """Resolve the repository metadata dir, including linked worktrees."""
    dot_git = Path(cwd) / ".git"
    if dot_git.is_dir():
        return dot_git.resolve()
    if not dot_git.is_file():
        return None
    try:
        marker = dot_git.read_text(encoding="utf-8", errors="replace")[:4096].strip()
    except OSError:
        return None
    prefix = "gitdir:"
    if not marker.lower().startswith(prefix):
        return None
    target = Path(marker[len(prefix) :].strip())
    if not target.is_absolute():
        target = dot_git.parent / target
    return target.resolve()


def detect_inprogress_operation(cwd: str) -> str | None:
    git_dir = git_dir_path(cwd)
    if git_dir is None:
        return None
    if (git_dir / "MERGE_HEAD").exists():
        return "merge"
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        return "rebase"
    if (git_dir / "CHERRY_PICK_HEAD").exists():
        return "cherry-pick"
    if (git_dir / "REVERT_HEAD").exists():
        return "revert"
    return None


# --- Lock registry -----------------------------------------------------------


class _GitLockContext:
    """Context manager wrapping an asyncio.Lock with refcount bookkeeping."""

    def __init__(self, registry: "GitLockRegistry", resolved: str) -> None:
        self._registry = registry
        self._resolved = resolved

    async def __aenter__(self) -> asyncio.Lock:
        lock = self._registry._locks[self._resolved]
        await lock.acquire()
        return lock

    async def __aexit__(
        self, exc_type: object, exc_val: object, exc_tb: object
    ) -> None:
        lock = self._registry._locks[self._resolved]
        lock.release()


class GitLockRegistry:
    """Per-workspace asyncio.Lock registry.  Locks are created once and kept
    for the lifetime of the process to avoid race conditions with cleanup."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def acquire(self, path: str) -> _GitLockContext:
        resolved = str(Path(path).resolve())
        if resolved not in self._locks:
            self._locks[resolved] = asyncio.Lock()
        return _GitLockContext(self, resolved)

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
        coro_factory: Callable[[], Awaitable[object]],
    ) -> tuple[GitJob, bool]:
        key = str(Path(workspace).resolve())
        async with self._lock:
            existing = self._jobs.get(key)
            if existing is not None and existing.status == "running":
                return existing, False
            job = GitJob(workspace=workspace, op=op)
            self._jobs[key] = job
            task = asyncio.create_task(self._run(job=job, coro=coro_factory()))
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
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.error = "Git operation cancelled"
            raise
        except Exception as exc:
            job.status = "error"
            job.error = str(exc)[:500]
            logger.exception("git job failed op={} workspace={}", job.op, job.workspace)
        finally:
            job.finished_at = time.time()
            self._cleanup_old_jobs()

    def _cleanup_old_jobs(self, max_age_seconds: float = 600.0) -> None:
        """Remove finished jobs older than *max_age_seconds* (default 10 min)."""
        cutoff = time.time() - max_age_seconds
        stale = [
            key
            for key, j in self._jobs.items()
            if j.status != "running"
            and j.finished_at is not None
            and j.finished_at < cutoff
        ]
        for key in stale:
            self._jobs.pop(key, None)

    def snapshot(self, workspace: str) -> GitJob | None:
        return self._jobs.get(str(Path(workspace).resolve()))

    def is_running(self, workspace: str) -> bool:
        job = self._jobs.get(str(Path(workspace).resolve()))
        return job is not None and job.status == "running"


git_jobs = GitJobRegistry()
