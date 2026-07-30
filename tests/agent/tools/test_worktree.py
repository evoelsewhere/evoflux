"""Behavioral tests for lossless managed worktree cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.tools.builtin import worktree as worktree_module


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "initial",
    )

    managed_root = tmp_path / "managed"

    def _test_root(_source: Path) -> Path:
        managed_root.mkdir(parents=True, exist_ok=True)
        return managed_root.resolve()

    monkeypatch.setattr(worktree_module, "_worktree_root", _test_root)
    token = set_sandbox(SandboxConfig(workspace=str(repo), session_id="worktree-test"))
    try:
        yield repo
    finally:
        _sandbox_ctx.reset(token)


async def test_review_retains_dirty_worktree(git_repo: Path):
    state = SimpleNamespace(metadata={"session_id": "worktree-test"})
    started = await worktree_module._worktree_start("safe-review", _state=state)
    assert "[Worktree created]" in started

    worktree = Path(state.metadata["_worktree_path"])
    (worktree / "untracked.txt").write_text("keep me\n", encoding="utf-8")

    reviewed = await worktree_module._worktree_finish("review", _state=state)

    assert "[Worktree review — retained]" in reviewed
    assert worktree.exists()
    assert (worktree / "untracked.txt").read_text(encoding="utf-8") == "keep me\n"


async def test_preserve_snapshots_untracked_changes_and_keeps_branch(git_repo: Path):
    state = SimpleNamespace(metadata={"session_id": "worktree-test"})
    await worktree_module._worktree_start("safe-preserve", _state=state)
    worktree = Path(state.metadata["_worktree_path"])
    branch = state.metadata["_worktree_branch"]
    (worktree / "untracked.txt").write_text("preserved\n", encoding="utf-8")

    result = await worktree_module._worktree_finish("preserve", _state=state)

    assert "[Worktree preserved]" in result
    assert not worktree.exists()
    assert _git(git_repo, "show", f"{branch}:untracked.txt") == "preserved"
    assert _git(git_repo, "show-ref", "--verify", f"refs/heads/{branch}")


async def test_discard_requires_explicit_confirmation_for_dirty_tree(
    git_repo: Path,
):
    state = SimpleNamespace(metadata={"session_id": "worktree-test"})
    await worktree_module._worktree_start("safe-discard", _state=state)
    worktree = Path(state.metadata["_worktree_path"])
    (worktree / "untracked.txt").write_text("do not lose\n", encoding="utf-8")

    refused = await worktree_module._worktree_finish("discard", _state=state)

    assert "Refusing to discard a dirty worktree" in refused
    assert worktree.exists()
