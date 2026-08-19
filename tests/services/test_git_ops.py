from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services.git_ops import (
    GitJobRegistry,
    GitResult,
    detect_inprogress_operation,
    parse_porcelain_v2_files,
    run_git,
)


def test_porcelain_v2_preserves_dual_state_renames_and_conflict_paths() -> None:
    parsed = parse_porcelain_v2_files(
        "# branch.head feature\n"
        "# branch.ab +2 -3\n"
        "1 MM N... 100644 100644 100644 abc def both.txt\n"
        "2 R. N... 100644 100644 100644 abc def R100 new name.txt\told name.txt\n"
        "u UU N... 100644 100644 100644 100644 a b c conflict name.txt\n"
    )

    assert (parsed.branch, parsed.ahead, parsed.behind) == ("feature", 2, 3)
    assert [(item.path, item.status, item.staged) for item in parsed.files] == [
        ("both.txt", "modified", True),
        ("both.txt", "modified", False),
        ("new name.txt", "renamed", True),
        ("conflict name.txt", "both modified", False),
    ]
    assert parsed.files[2].old_path == "old name.txt"


def test_porcelain_v2_decodes_git_octal_escaped_utf8_paths() -> None:
    parsed = parse_porcelain_v2_files('? "caf\\303\\251 notes.txt"\n')

    assert parsed.files[0].path == "café notes.txt"


def test_detect_inprogress_operation_resolves_linked_worktree_gitdir(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "worktree"
    git_dir = tmp_path / "repo" / ".git" / "worktrees" / "feature"
    workspace.mkdir()
    git_dir.mkdir(parents=True)
    (workspace / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
    (git_dir / "CHERRY_PICK_HEAD").write_text("abc\n", encoding="utf-8")

    assert detect_inprogress_operation(str(workspace)) == "cherry-pick"


@pytest.mark.asyncio
async def test_run_git_stops_collecting_output_at_the_configured_limit(
    tmp_path: Path,
) -> None:
    assert (await run_git(str(tmp_path), "init", "-q")).ok
    (tmp_path / "large.txt").write_text("production-line\n" * 20_000)
    assert (await run_git(str(tmp_path), "add", "large.txt")).ok

    result = await run_git(
        str(tmp_path),
        "diff",
        "--cached",
        timeout=10.0,
        max_output_bytes=1024,
    )

    assert result.ok is False
    assert result.output_limited is True
    assert result.stdout == ""


@pytest.mark.asyncio
async def test_duplicate_git_job_does_not_construct_an_orphan_coroutine() -> None:
    registry = GitJobRegistry()
    release = asyncio.Event()
    factory_calls = 0

    async def work() -> GitResult:
        await release.wait()
        return GitResult(ok=True, stdout="done", stderr="", returncode=0)

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        return work()

    first, first_started = await registry.start(
        workspace="/repo", op="fetch", coro_factory=factory
    )
    second, second_started = await registry.start(
        workspace="/repo", op="pull", coro_factory=factory
    )

    assert first is second
    assert first_started is True
    assert second_started is False
    assert factory_calls == 1

    release.set()
    await asyncio.gather(*registry._tasks)
    assert first.status == "done"
