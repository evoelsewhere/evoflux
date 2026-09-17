"""Write serialization for one repository's ASDD catalogue.

ASDD has no optimistic concurrency: a change is a folder of Markdown, and two
writers racing on `proposal.md` would simply overwrite one another. This lock is
what stands in its place, and it has to be held across a read-modify-write of a
page rather than around a single `write_text`.

A linked Git worktree shares its source checkout's lock. Two worktrees of the
same repository share one `.evoflux/` tree through the common Git directory, so
locking per checkout would let them interleave writes to the same file.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ASDD_LOCK_FILE = Path(".evoflux/asdd/locks/catalogue.lock")

_MAX_GIT_POINTER_BYTES = 16 * 1024
_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[Path, threading.RLock] = {}
_LOCK_DEPTH = threading.local()


def _read_pointer(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > _MAX_GIT_POINTER_BYTES:
            return None
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def asdd_runtime_owner(repository_root: str | Path) -> Path:
    """Return the checkout that owns lock state for a possibly linked worktree.

    Ordinary repositories and non-Git folders own themselves. Linked worktrees
    point at ``.git/worktrees/<name>`` and carry a ``commondir``; only that exact
    shape resolves back to the source checkout, so submodules and arbitrary
    ``gitdir`` pointers stay self-owned.
    """

    root = Path(repository_root).expanduser().resolve()
    marker = root / ".git"
    pointer = _read_pointer(marker)
    if pointer is None or not pointer.lower().startswith("gitdir:"):
        return root
    raw_git_dir = Path(pointer.split(":", 1)[1].strip())
    git_dir = (
        raw_git_dir if raw_git_dir.is_absolute() else marker.parent / raw_git_dir
    ).resolve()
    common_pointer = _read_pointer(git_dir / "commondir")
    if not common_pointer:
        return root
    raw_common = Path(common_pointer)
    common_dir = (
        raw_common if raw_common.is_absolute() else git_dir / raw_common
    ).resolve()
    source = common_dir.parent
    if common_dir.name != ".git" or not common_dir.is_dir() or not source.is_dir():
        return root
    if (source / ".git").resolve(strict=False) != common_dir:
        return root
    return source.resolve()


def asdd_runtime_path(repository_root: str | Path, relative: Path) -> Path:
    owner = asdd_runtime_owner(repository_root)
    candidate = owner / relative
    resolved = candidate.resolve(strict=False)
    if resolved != owner and owner not in resolved.parents:
        raise ValueError(f"ASDD runtime path escapes its owner: {relative}")
    return candidate


def _thread_lock(owner: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(owner, threading.RLock())


@contextmanager
def asdd_catalogue_lock(repository_root: str | Path) -> Iterator[None]:
    """Serialize catalogue mutations for one runtime owner.

    Reentrant by design: `archive_change` rewrites several pages through the
    same helpers that take this lock themselves, and only the outermost holder
    touches the file lock.
    """

    owner = asdd_runtime_owner(repository_root)
    lock = _thread_lock(owner)
    key = str(owner)
    depths = getattr(_LOCK_DEPTH, "values", None)
    if depths is None:
        depths = {}
        _LOCK_DEPTH.values = depths
    with lock:
        depth = int(depths.get(key, 0))
        depths[key] = depth + 1
        handle = None
        try:
            if depth == 0:
                lock_path = asdd_runtime_path(owner, ASDD_LOCK_FILE)
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                handle = lock_path.open("a+b")
                try:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except ImportError:  # pragma: no cover - Windows thread lock only
                    pass
            yield
        finally:
            depths[key] = depth
            if depth == 0:
                depths.pop(key, None)
                if handle is not None:
                    try:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    except ImportError:  # pragma: no cover - Windows fallback
                        pass
                    handle.close()


def runtime_owner_is_shared(repository_root: str | Path) -> bool:
    root = Path(repository_root).expanduser().resolve()
    return asdd_runtime_owner(root) != root


__all__ = [
    "ASDD_LOCK_FILE",
    "asdd_catalogue_lock",
    "asdd_runtime_owner",
    "asdd_runtime_path",
    "runtime_owner_is_shared",
]
