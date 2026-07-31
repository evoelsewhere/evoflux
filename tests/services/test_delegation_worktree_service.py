from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.services import delegation_worktree_service as service


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(root: Path, name: str) -> Path:
    repo = root / name
    repo.mkdir()
    _git(repo, "init")
    (repo / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "shared.txt")
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
    return repo.resolve()


def _spec(*repos: Path) -> dict:
    return {
        "goal": "change code",
        "resolved_isolation": "worktree",
        "target_repos": [str(repo) for repo in repos],
    }


def test_resolve_isolation_policy():
    assert (
        service.resolve_isolation(
            requested="auto",
            team_mode="coding",
            target_paths=["app/a.py"],
            target_repos=[],
        )
        == "worktree"
    )
    assert (
        service.resolve_isolation(
            requested="auto",
            team_mode="coding",
            target_paths=[],
            target_repos=[],
        )
        == "shared"
    )
    assert (
        service.resolve_isolation(
            requested="shared",
            team_mode="coding",
            target_paths=["app/a.py"],
            target_repos=[],
        )
        == "shared"
    )


@pytest.mark.asyncio
async def test_single_repo_snapshot_merge_and_finalize(tmp_path: Path):
    repo = _repo(tmp_path, "api")
    allocation = await service.allocate(
        task_id="11111111-1111-7111-8111-111111111111",
        recipient="executor#1",
        session_id="aaaaaaaa-aaaa-7aaa-8aaa-aaaaaaaaaaaa",
        primary_workspace=str(repo),
        extra_workspace_paths=[],
        read_only_paths=[],
        spec=_spec(repo),
    )
    task_workspace = Path(allocation["repositories"][0]["workspace"])
    (task_workspace / "shared.txt").write_text("agent\n", encoding="utf-8")

    reviewed, result = await service.snapshot(allocation)

    assert reviewed["state"] == "review"
    assert result["repositories"][0]["changed_files"] == ["shared.txt"]
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "base\n"

    merged, summary = await service.merge(reviewed)

    assert merged["state"] == "merged"
    assert str(repo) in summary
    assert not task_workspace.exists()
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "base\n"

    finalized, _ = await service.finalize([merged])
    finalized_again, _ = await service.finalize([merged])
    cleanup_warnings = await service.cleanup_finalized(finalized_again)
    finalized_after_cleanup, _ = await service.finalize([merged])

    assert finalized[0]["state"] == "finalized"
    assert finalized_again[0]["state"] == "finalized"
    assert finalized_after_cleanup[0]["state"] == "finalized"
    assert cleanup_warnings == []
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "agent\n"
    assert _git(repo, "status", "--porcelain") == ""


@pytest.mark.asyncio
async def test_multi_repo_worktree_set_finalizes_together(tmp_path: Path):
    frontend = _repo(tmp_path, "frontend")
    backend = _repo(tmp_path, "backend")
    allocation = await service.allocate(
        task_id="22222222-2222-7222-8222-222222222222",
        recipient="executor#2",
        session_id="bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
        primary_workspace=str(frontend),
        extra_workspace_paths=[str(backend)],
        read_only_paths=[],
        spec=_spec(frontend, backend),
    )
    by_source = {
        Path(item["source"]).name: Path(item["workspace"])
        for item in allocation["repositories"]
    }
    (by_source["frontend"] / "shared.txt").write_text(
        "frontend-agent\n", encoding="utf-8"
    )
    (by_source["backend"] / "shared.txt").write_text(
        "backend-agent\n", encoding="utf-8"
    )

    reviewed, _ = await service.snapshot(allocation)
    merged, _ = await service.merge(reviewed)
    finalized, _ = await service.finalize([merged])

    assert len(finalized[0]["repositories"]) == 2
    assert (frontend / "shared.txt").read_text(encoding="utf-8") == "frontend-agent\n"
    assert (backend / "shared.txt").read_text(encoding="utf-8") == "backend-agent\n"


@pytest.mark.asyncio
async def test_multi_repo_worktree_set_can_finalize_in_separate_repo_steps(
    tmp_path: Path,
):
    frontend = _repo(tmp_path, "frontend-step")
    backend = _repo(tmp_path, "backend-step")
    allocation = await service.allocate(
        task_id="23232323-2323-7323-8323-232323232323",
        recipient="executor#2",
        session_id="bcbcbcbc-bcbc-7bcb-8bcb-bcbcbcbcbcbc",
        primary_workspace=str(frontend),
        extra_workspace_paths=[str(backend)],
        read_only_paths=[],
        spec=_spec(frontend, backend),
    )
    by_source = {
        Path(item["source"]).name: Path(item["workspace"])
        for item in allocation["repositories"]
    }
    (by_source["frontend-step"] / "shared.txt").write_text(
        "frontend-step\n", encoding="utf-8"
    )
    (by_source["backend-step"] / "shared.txt").write_text(
        "backend-step\n", encoding="utf-8"
    )
    reviewed, _ = await service.snapshot(allocation)
    merged, _ = await service.merge(reviewed)

    partially_finalized, _ = await service.finalize(
        [merged], target_repos=[str(frontend)]
    )
    await service.cleanup_finalized(partially_finalized)
    fully_finalized, _ = await service.finalize(
        partially_finalized, target_repos=[str(backend)]
    )
    cleanup_warnings = await service.cleanup_finalized(fully_finalized)

    assert fully_finalized[0]["state"] == "finalized"
    assert cleanup_warnings == []
    assert (frontend / "shared.txt").read_text(encoding="utf-8") == "frontend-step\n"
    assert (backend / "shared.txt").read_text(encoding="utf-8") == "backend-step\n"


@pytest.mark.asyncio
async def test_conflict_rolls_back_integration_branch(tmp_path: Path):
    repo = _repo(tmp_path, "conflict")
    common = {
        "session_id": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
        "primary_workspace": str(repo),
        "extra_workspace_paths": [],
        "read_only_paths": [],
        "spec": _spec(repo),
    }
    first = await service.allocate(
        task_id="33333333-3333-7333-8333-333333333333",
        recipient="executor#1",
        **common,
    )
    second = await service.allocate(
        task_id="44444444-4444-7444-8444-444444444444",
        recipient="executor#2",
        **common,
    )
    Path(first["repositories"][0]["workspace"], "shared.txt").write_text(
        "first\n", encoding="utf-8"
    )
    Path(second["repositories"][0]["workspace"], "shared.txt").write_text(
        "second\n", encoding="utf-8"
    )
    first, _ = await service.snapshot(first)
    second, _ = await service.snapshot(second)
    first, _ = await service.merge(first)
    integration = Path(first["repositories"][0]["integration_workspace"])
    head_after_first = _git(integration, "rev-parse", "HEAD")

    conflicted, detail = await service.merge(second)

    assert conflicted["state"] == "conflict"
    assert "conflict" in detail.lower()
    assert _git(integration, "rev-parse", "HEAD") == head_after_first
    assert (integration / "shared.txt").read_text(encoding="utf-8") == "first\n"
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "base\n"
    await service.discard(conflicted)
    await service.finalize([first])
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "first\n"


@pytest.mark.asyncio
async def test_merge_rejects_task_branch_changes_after_snapshot(tmp_path: Path):
    repo = _repo(tmp_path, "branch-drift")
    allocation = await service.allocate(
        task_id="77777777-7777-7777-8777-777777777777",
        recipient="executor#5",
        session_id="ffffffff-ffff-7fff-8fff-ffffffffffff",
        primary_workspace=str(repo),
        extra_workspace_paths=[],
        read_only_paths=[],
        spec=_spec(repo),
    )
    workspace = Path(allocation["repositories"][0]["workspace"])
    (workspace / "shared.txt").write_text("reviewed\n", encoding="utf-8")
    reviewed, _ = await service.snapshot(allocation)
    integration = Path(reviewed["repositories"][0]["integration_workspace"])
    integration_head = _git(integration, "rev-parse", "HEAD")

    (workspace / "after.txt").write_text("not reviewed\n", encoding="utf-8")
    _git(workspace, "add", "after.txt")
    _git(
        workspace,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "post handoff",
    )

    conflicted, detail = await service.merge(reviewed)

    assert conflicted["state"] == "conflict"
    assert "changed after its final handoff" in detail
    assert _git(integration, "rev-parse", "HEAD") == integration_head
    await service.discard(conflicted)


@pytest.mark.asyncio
async def test_merge_rejects_dirty_worktree_after_snapshot(tmp_path: Path):
    repo = _repo(tmp_path, "dirty-after-review")
    allocation = await service.allocate(
        task_id="88888888-8888-7888-8888-888888888888",
        recipient="executor#6",
        session_id="11111111-2222-7333-8444-555555555555",
        primary_workspace=str(repo),
        extra_workspace_paths=[],
        read_only_paths=[],
        spec=_spec(repo),
    )
    workspace = Path(allocation["repositories"][0]["workspace"])
    (workspace / "shared.txt").write_text("reviewed\n", encoding="utf-8")
    reviewed, _ = await service.snapshot(allocation)
    (workspace / "after.txt").write_text("dirty\n", encoding="utf-8")

    conflicted, detail = await service.merge(reviewed)

    assert conflicted["state"] == "conflict"
    assert "changed after its final handoff" in detail
    await service.discard(conflicted)


@pytest.mark.asyncio
async def test_source_head_cannot_advance_after_integration_starts(tmp_path: Path):
    repo = _repo(tmp_path, "advanced-source")
    common = {
        "session_id": "22222222-3333-7444-8555-666666666666",
        "primary_workspace": str(repo),
        "extra_workspace_paths": [],
        "read_only_paths": [],
        "spec": _spec(repo),
    }
    first = await service.allocate(
        task_id="99999999-9999-7999-8999-999999999999",
        recipient="executor#7",
        **common,
    )
    (repo / "source-only.txt").write_text("advanced\n", encoding="utf-8")
    _git(repo, "add", "source-only.txt")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "advance source",
    )

    with pytest.raises(service.DelegationWorktreeError, match="Source HEAD changed"):
        await service.allocate(
            task_id="aaaaaaaa-1111-7222-8333-bbbbbbbbbbbb",
            recipient="executor#8",
            **common,
        )

    await service.discard(first)


def test_finalize_selector_requires_unique_repository_name(tmp_path: Path):
    left_root = tmp_path / "left"
    right_root = tmp_path / "right"
    left_root.mkdir()
    right_root.mkdir()
    left = _repo(left_root, "api")
    right = _repo(right_root, "api")

    with pytest.raises(service.DelegationWorktreeError, match="matched 2"):
        service._resolve_finalize_selectors(
            {str(left), str(right)},
            target_repos=["api"],
        )


@pytest.mark.asyncio
async def test_sandbox_binding_maps_each_allocated_repo(tmp_path: Path):
    primary = _repo(tmp_path, "primary")
    extra = _repo(tmp_path, "extra")
    allocation = await service.allocate(
        task_id="55555555-5555-7555-8555-555555555555",
        recipient="executor#3",
        session_id="dddddddd-dddd-7ddd-8ddd-dddddddddddd",
        primary_workspace=str(primary),
        extra_workspace_paths=[str(extra)],
        read_only_paths=[],
        spec=_spec(primary, extra),
    )

    binding = service.sandbox_binding(
        primary_workspace=str(primary),
        extra_workspace_paths=[str(extra)],
        read_only_paths=[],
        active_specs=[{"worktree_allocation": allocation}],
    )

    mapped = {
        Path(item["source"]).resolve(): Path(item["workspace"]).resolve()
        for item in allocation["repositories"]
    }
    assert Path(binding.workspace) == mapped[primary]
    assert binding.extra_workspace_paths == [str(mapped[extra])]
    assert set(binding.write_allowed_paths) == {
        str(mapped[primary]),
        str(mapped[extra]),
    }


@pytest.mark.asyncio
async def test_read_only_repository_cannot_receive_worktree(tmp_path: Path):
    primary = _repo(tmp_path, "target")
    source = _repo(tmp_path, "source")

    with pytest.raises(service.DelegationWorktreeError, match="read-only"):
        await service.allocate(
            task_id="66666666-6666-7666-8666-666666666666",
            recipient="executor#4",
            session_id="eeeeeeee-eeee-7eee-8eee-eeeeeeeeeeee",
            primary_workspace=str(primary),
            extra_workspace_paths=[str(source)],
            read_only_paths=[str(source)],
            spec=_spec(source),
        )
