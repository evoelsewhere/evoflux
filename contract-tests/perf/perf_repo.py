r"""A large git repository kept outside this checkout for the ``large_repo_open`` scenario.

Default location ``D:\evoelsewhere\.tmp-perf\large-repo`` on the reference
machine; ``EVOFLUX_PERF_ROOT`` relocates the whole perf scratch area. The repo
is built once and reused; a marker file records the shape so a changed shape
rebuilds it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DIRS = 400
FILES_PER_DIR = 50  # 20,000 tracked files
UNTRACKED = 200
_MARKER = f"shape={DIRS}x{FILES_PER_DIR}+{UNTRACKED}\n"


def perf_root() -> Path:
    override = os.environ.get("EVOFLUX_PERF_ROOT")
    root = Path(override) if override else Path(r"D:\evoelsewhere\.tmp-perf")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=perf", "-c", "user.email=perf@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def ensure_large_repo() -> Path:
    repo = perf_root() / "large-repo"
    marker = repo / ".perf-shape"
    if marker.exists() and marker.read_text() == _MARKER:
        return repo
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    for d in range(DIRS):
        folder = repo / "src" / f"pkg{d:03d}"
        folder.mkdir(parents=True)
        for f in range(FILES_PER_DIR):
            (folder / f"mod{f:02d}.py").write_text(
                f"def f_{d}_{f}():\n    return {d * f}\n" * 8, encoding="utf-8"
            )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "perf fixture")
    for n in range(UNTRACKED):
        (repo / f"untracked{n:03d}.txt").write_text("x\n", encoding="utf-8")
    marker.write_text(_MARKER)
    return repo
