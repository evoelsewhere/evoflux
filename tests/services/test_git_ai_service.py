from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.schemas.chat import AssistantMessage
from app.services.change_set_service import clear_change_sets
from app.services.git_ai_service import run_git_ai_action
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
async def test_generate_commit_message_returns_structured_text(repository: Path):
    subprocess.run(["git", "add", "app.py"], cwd=repository, check=True)
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
        return_value=[{"path": "app.py", "ours": "value = 2\n"}],
    ):
        result = await run_git_ai_action(
            workspace=repository,
            provider=provider,
            action="propose_conflict_resolution",
            session_id="session-1",
        )

    assert result["change_set"]["origin"] == "git"
    assert "+value = 3" in result["change_set"]["files"][0]["diff"]
