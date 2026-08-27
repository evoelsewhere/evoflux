"""Canonical local runtime ownership and serialization for EASD repositories."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


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


def easd_runtime_owner(repository_root: str | Path) -> Path:
    """Return the source checkout that owns local state for a linked worktree.

    Ordinary repositories and non-Git folders own their own runtime. Linked Git
    worktrees point at ``.git/worktrees/<name>`` and carry a ``commondir`` file;
    only that explicit shape is resolved back to the source checkout. Submodules
    and arbitrary ``gitdir`` pointers without ``commondir`` remain self-owned.
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


def easd_runtime_path(repository_root: str | Path, relative: Path) -> Path:
    owner = easd_runtime_owner(repository_root)
    candidate = owner / relative
    resolved = candidate.resolve(strict=False)
    if resolved != owner and owner not in resolved.parents:
        raise ValueError(f"EASD runtime path escapes its owner: {relative}")
    return candidate


def _thread_lock(owner: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(owner, threading.RLock())


@contextmanager
def easd_runtime_lock(repository_root: str | Path) -> Iterator[None]:
    """Serialize EASD Run mutations and migrations for one runtime owner."""

    owner = easd_runtime_owner(repository_root)
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
                lock_path = easd_runtime_path(
                    owner, Path(".evoflux/easd/.local/locks/runtime.lock")
                )
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                handle = lock_path.open("a+b")
                try:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except ImportError:  # pragma: no cover - Windows thread lock fallback
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
    return easd_runtime_owner(root) != root


__all__ = [
    "easd_runtime_lock",
    "easd_runtime_owner",
    "easd_runtime_path",
    "runtime_owner_is_shared",
]
