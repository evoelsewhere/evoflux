from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.schemas.chat import AssistantMessage
from app.services.change_set_service import clear_change_sets
from app.services.editor_action_service import run_editor_action
from app.services.editor_context_service import EditorContextEnvelope
from app.services.problems_service import clear_problems, list_problems


@pytest.fixture
def context(tmp_path: Path):
    source = tmp_path / "main.py"
    source.write_text("value = 1\n", encoding="utf-8")
    token = set_sandbox(
        SandboxConfig(
            workspace=str(tmp_path),
            outbound_data_policy="off",
            outbound_pii_policy="off",
        )
    )
    clear_change_sets()
    clear_problems()
    yield EditorContextEnvelope(
        workspace=str(tmp_path),
        active_file="main.py",
        document_version=1,
        content="value = 1\n",
        content_sha256="a" * 64,
        selection=None,
        cursor_symbol="value",
        diagnostics=[],
        git_hunks="",
        related_symbols=[],
        callers=[],
        callees=[],
        recent_agent_changes=None,
        relevant_terminal_failure=None,
        project_instructions=[],
        attachments=[],
    )
    from app.agent.sandbox import _sandbox_ctx

    _sandbox_ctx.reset(token)
    clear_change_sets()
    clear_problems()


@pytest.mark.asyncio
async def test_change_action_materializes_guarded_change_set(context):
    payload = {
        "kind": "changes",
        "summary": "Update value",
        "files": [{"path": "main.py", "proposed_content": "value = 2\n"}],
        "verification_commands": ["pytest -q"],
    }
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(return_value=AssistantMessage(content=json.dumps(payload))),
    )

    result = await run_editor_action(
        provider=provider,
        action="simplify_code",
        instruction=None,
        context=context,
        session_id="session-1",
    )

    assert result["kind"] == "changes"
    assert result["change_set"]["files"][0]["path"] == "main.py"
    assert "+value = 2" in result["change_set"]["files"][0]["diff"]
    sent = provider.chat.await_args.args[0]
    assert sent[0].role == "system"
    assert sent[1].role == "user"


@pytest.mark.asyncio
async def test_find_problems_publishes_structured_findings(context):
    payload = {
        "kind": "findings",
        "summary": "Found an issue",
        "findings": [
            {
                "title": "Wrong value",
                "message": "The value violates the local invariant.",
                "severity": "warning",
                "path": "main.py",
                "line": 1,
                "column": 1,
                "code": "wrong-value",
            }
        ],
    }
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(return_value=AssistantMessage(content=json.dumps(payload))),
    )

    result = await run_editor_action(
        provider=provider,
        action="find_problems",
        instruction=None,
        context=context,
        session_id="session-1",
    )

    assert result["kind"] == "findings"
    problems = list_problems(context.workspace)
    assert len(problems) == 1
    assert problems[0].source == "ai_review"
    assert problems[0].code == "wrong-value"


@pytest.mark.asyncio
async def test_change_action_rejects_prose_response(context):
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(return_value=AssistantMessage(content="Here is a patch")),
    )

    with pytest.raises(ValueError, match="valid JSON"):
        await run_editor_action(
            provider=provider,
            action="refactor_selection",
            instruction=None,
            context=context,
            session_id=None,
        )
