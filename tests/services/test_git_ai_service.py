from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.schemas.chat import AssistantMessage
from app.services.change_set_service import clear_change_sets
from app.services.git_ai_service import _evidence, run_git_ai_action
from app.services.problems_service import clear_problems, list_problems


@pytest.fixture
def repository(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    source = tmp_path / "app.py"
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=tmp_path, check=True)
    source.write_text("value = 2\n", encoding="utf-8")
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            outbound_data_policy="off",
            outbound_pii_policy="off",
        )
    )
    clear_problems()
    clear_change_sets()
    yield tmp_path
    clear_problems()
    clear_change_sets()
    from app.agent.sandbox import _sandbox_ctx

    _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_self_review_publishes_ai_and_security_findings(repository: Path):
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(
            return_value=AssistantMessage(
                content=json.dumps(
                    {
                        "kind": "review",
                        "summary": "Two findings",
                        "findings": [
                            {
                                "message": "Value change breaks the contract.",
                                "severity": "error",
                                "path": "app.py",
                                "line": 1,
                                "code": "contract",
                            },
                            {
                                "message": "Security rule needs review.",
                                "severity": "warning",
                                "path": "app.py",
                                "line": 1,
                                "code": "security-review",
                                "source": "security",
                            },
                        ],
                    }
                )
            )
        ),
    )
    with patch(
        "app.services.git_ai_service._code_impact",
        new_callable=AsyncMock,
        return_value=[{"symbol": "value"}],
    ):
        result = await run_git_ai_action(
            workspace=repository,
            provider=provider,
            action="self_review",
            session_id="session-1",
        )

    assert len(result["findings"]) == 2
    assert {problem.source for problem in list_problems(repository)} == {
        "ai_review",
        "security",
    }
    prompt = provider.chat.await_args.args[0][1].content
    assert "value = 2" in prompt
    assert "code_impact" in prompt


@pytest.mark.asyncio
async def test_self_review_includes_untracked_text_content(repository: Path):
    marker = "UNTRACKED_REVIEW_MARKER = True\n"
    (repository / "new_module.py").write_text(marker, encoding="utf-8")

    with patch(
        "app.services.git_ai_service._code_impact",
        new_callable=AsyncMock,
        return_value=[],
    ):
        evidence = await _evidence(repository, "self_review", None, None)

    assert evidence["status"].strip().endswith("new_module.py")
    assert evidence["untracked_files"] == [
        {
            "path": "new_module.py",
            "size": len(marker.encode()),
            "content": marker,
            "truncated": False,
        }
    ]


@pytest.mark.asyncio
async def test_pr_description_uses_committed_source_to_target_range(
    repository: Path,
):
    target_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "switch", "-qc", "feature/review-draft"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "add", "app.py"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "update application value"],
        cwd=repository,
        check=True,
    )

    with patch(
        "app.services.git_ai_service._code_impact",
        new_callable=AsyncMock,
        return_value=[],
    ):
        evidence = await _evidence(
            repository,
            "generate_pr_description",
            None,
            {
                "source_branch": "feature/review-draft",
                "target_branch": target_branch,
            },
        )

    assert evidence["source_branch"] == "feature/review-draft"
    assert evidence["target_branch"] == target_branch
    assert any("update application value" in row for row in evidence["commits"])
    assert "+value = 2" in evidence["committed_diff"]
    assert "staged_diff" not in evidence
    assert "unstaged_diff" not in evidence


@pytest.mark.asyncio
async def test_pr_description_rejects_the_same_source_and_target(repository: Path):
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    with pytest.raises(ValueError, match="must be different"):
        await _evidence(
            repository,
            "generate_pr_description",
            None,
            {"source_branch": branch, "target_branch": branch},
        )


@pytest.mark.asyncio
async def test_generate_commit_message_returns_structured_text(repository: Path):
    subprocess.run(["git", "add", "app.py"], cwd=repository, check=True)
    (repository / "notes.txt").write_text(
        "UNSTAGED_CONTENT_MUST_NOT_SHAPE_COMMIT\n", encoding="utf-8"
    )
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(
            return_value=AssistantMessage(
                content=json.dumps(
                    {
                        "kind": "text",
                        "summary": "Commit message generated",
                        "message": "fix: update application value",
                    }
                )
            )
        ),
    )
    with patch(
        "app.services.git_ai_service._code_impact",
        new_callable=AsyncMock,
        return_value=[],
    ):
        result = await run_git_ai_action(
            workspace=repository,
            provider=provider,
            action="generate_commit_message",
            session_id="session-1",
        )

    assert result["message"] == "fix: update application value"
    prompt = provider.chat.await_args.args[0][1].content
    assert "UNSTAGED_CONTENT_MUST_NOT_SHAPE_COMMIT" not in prompt


@pytest.mark.asyncio
async def test_conflict_proposal_becomes_guarded_change_set(repository: Path):
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(
            return_value=AssistantMessage(
                content=json.dumps(
                    {
                        "kind": "changes",
                        "summary": "Resolve app conflict",
                        "files": [
                            {"path": "app.py", "proposed_content": "value = 3\n"}
                        ],
                    }
                )
            )
        ),
    )
    with patch(
        "app.services.git_ai_service._conflict_evidence",
        new_callable=AsyncMock,
        return_value=[
            {
                "path": "app.py",
                "ours": "value = 2\n",
                "working_sha256": hashlib.sha256(b"value = 2\n").hexdigest(),
            }
        ],
    ):
        result = await run_git_ai_action(
            workspace=repository,
            provider=provider,
            action="propose_conflict_resolution",
            session_id="session-1",
        )

    assert result["change_set"]["origin"] == "git"
    assert "+value = 3" in result["change_set"]["files"][0]["diff"]


@pytest.mark.asyncio
async def test_explain_commit_rejects_option_like_reference(repository: Path):
    outside = repository.parent / "leaked.patch"

    with pytest.raises(ValueError, match="Invalid Git commit reference"):
        await _evidence(
            repository,
            "explain_commit",
            f"--output={outside}",
            None,
        )

    assert not outside.exists()


@pytest.mark.asyncio
async def test_non_conflict_action_cannot_return_file_changes(repository: Path):
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(
            return_value=AssistantMessage(
                content=json.dumps(
                    {
                        "kind": "changes",
                        "summary": "Unexpected mutation",
                        "files": [
                            {"path": "app.py", "proposed_content": "value = 9\n"}
                        ],
                    }
                )
            )
        ),
    )
    with patch(
        "app.services.git_ai_service._code_impact",
        new_callable=AsyncMock,
        return_value=[],
    ):
        with pytest.raises(ValueError, match="unexpected kind"):
            await run_git_ai_action(
                workspace=repository,
                provider=provider,
                action="self_review",
                session_id="session-1",
            )


@pytest.mark.asyncio
async def test_conflict_change_is_stale_if_working_file_changes_during_model_call(
    repository: Path,
):
    async def mutate_then_reply(*_args, **_kwargs):
        (repository / "app.py").write_text("value = 4\n", encoding="utf-8")
        return AssistantMessage(
            content=json.dumps(
                {
                    "kind": "changes",
                    "summary": "Resolve conflict",
                    "files": [{"path": "app.py", "proposed_content": "value = 3\n"}],
                }
            )
        )

    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(side_effect=mutate_then_reply),
    )
    evidence = [
        {
            "path": "app.py",
            "working": "value = 2\n",
            "working_sha256": hashlib.sha256(b"value = 2\n").hexdigest(),
        }
    ]
    with patch(
        "app.services.git_ai_service._conflict_evidence",
        new_callable=AsyncMock,
        return_value=evidence,
    ):
        with pytest.raises(ValueError, match="changed since preview"):
            await run_git_ai_action(
                workspace=repository,
                provider=provider,
                action="propose_conflict_resolution",
                session_id="session-1",
            )


@pytest.mark.asyncio
async def test_conflict_change_rejects_truncated_working_file(repository: Path):
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(
            return_value=AssistantMessage(
                content=json.dumps(
                    {
                        "kind": "changes",
                        "summary": "Resolve large conflict",
                        "files": [
                            {"path": "app.py", "proposed_content": "value = 3\n"}
                        ],
                    }
                )
            )
        ),
    )
    evidence = [
        {
            "path": "app.py",
            "working": "value = 2\n",
            "working_sha256": hashlib.sha256(b"value = 2\n").hexdigest(),
            "working_truncated": True,
        }
    ]
    with patch(
        "app.services.git_ai_service._conflict_evidence",
        new_callable=AsyncMock,
        return_value=evidence,
    ):
        with pytest.raises(ValueError, match="truncated"):
            await run_git_ai_action(
                workspace=repository,
                provider=provider,
                action="propose_conflict_resolution",
                session_id="session-1",
            )
