from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.tools.builtin import pr as pr_module
from app.models.chat import GitServerConnection
from app.services.code_review_service import RepositoryReviews, RepositoryTarget


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.asyncio
async def test_clean_committed_branch_can_be_pushed_and_opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    remote.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    _git(remote, "init", "--bare")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "switch", "-c", "feature")
    (repo / "feature.txt").write_text("ready\n", encoding="utf-8")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-m", "feature is already committed")

    target = RepositoryTarget(
        workspace_id="workspace-id",
        workspace=str(repo),
        name="repo",
        remote_url=str(remote),
        host="example.test",
        repository="acme/repo",
        detected_provider="gitea",
        remote_name="origin",
    )
    connection = GitServerConnection(
        name="Test",
        provider="gitea",
        base_url="https://example.test/api/v1",
        host="example.test",
        token_env_var="UNSET_TEST_TOKEN",
    )

    async def fake_context(_workspace):
        return target, connection

    async def fake_reviews(_target, _connection):
        return RepositoryReviews(
            target=target,
            connection_id=str(connection.id),
            provider="gitea",
        )

    async def fake_create(_target, _connection, **kwargs):
        assert kwargs["source_branch"] == "feature"
        assert kwargs["target_branch"] == "main"
        return {"number": 7, "web_url": "https://example.test/acme/repo/pulls/7"}

    monkeypatch.setattr(pr_module, "_api_context", fake_context)
    monkeypatch.setattr(pr_module, "list_repository_reviews", fake_reviews)
    monkeypatch.setattr(pr_module, "create_repository_review", fake_create)

    result = await pr_module._create_pull_request(
        str(repo),
        "unused commit message",
        "Feature PR",
        _state=SimpleNamespace(metadata={"team_workspace": str(repo)}),
    )

    assert result == (
        "[Success] Review created: https://example.test/acme/repo/pulls/7"
    )
    assert _git(remote, "show-ref", "--verify", "refs/heads/feature")
