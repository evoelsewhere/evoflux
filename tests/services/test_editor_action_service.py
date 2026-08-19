from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.sandbox import SandboxConfig, set_sandbox
from app.agent.schemas.chat import AssistantMessage
from app.services.change_set_service import clear_change_sets
from app.services.editor_action_service import run_editor_action
from app.services.editor_context_service import ContextProvenance, EditorContextEnvelope
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
    content = "value = 1\n"
    content_sha = hashlib.sha256(content.encode()).hexdigest()
    yield EditorContextEnvelope(
        workspace=str(tmp_path),
        active_file="main.py",
        document_version=1,
        content=content,
        content_sha256=content_sha,
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
        provenance=[
            ContextProvenance(
                kind="active_file",
                source="editor-buffer",
                path="main.py",
                sha256=content_sha,
            )
        ],
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


@pytest.mark.asyncio
async def test_change_action_rejects_unseen_existing_file(context):
    workspace = Path(context.workspace)
    (workspace / "unseen.py").write_text("keep = True\n", encoding="utf-8")
    payload = {
        "kind": "changes",
        "summary": "Replace unseen file",
        "files": [{"path": "unseen.py", "proposed_content": "keep = False\n"}],
    }
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(return_value=AssistantMessage(content=json.dumps(payload))),
    )

    with pytest.raises(ValueError, match="not fully included"):
        await run_editor_action(
            provider=provider,
            action="simplify_code",
            instruction=None,
            context=context,
            session_id="session-1",
        )


@pytest.mark.asyncio
async def test_change_action_rejects_file_changed_after_context_preview(context):
    workspace = Path(context.workspace)
    original = "helper = 1\n"
    helper = workspace / "helper.py"
    helper.write_text(original, encoding="utf-8")
    context.provenance.append(
        ContextProvenance(
            kind="attachment",
            source="explicit-mention",
            path="helper.py",
            sha256=hashlib.sha256(original.encode()).hexdigest(),
        )
    )
    helper.write_text("helper = 2\n", encoding="utf-8")
    payload = {
        "kind": "changes",
        "summary": "Update helper",
        "files": [{"path": "helper.py", "proposed_content": "helper = 3\n"}],
    }
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(return_value=AssistantMessage(content=json.dumps(payload))),
    )

    with pytest.raises(ValueError, match="changed since preview"):
        await run_editor_action(
            provider=provider,
            action="propagate_api_change",
            instruction=None,
            context=context,
            session_id="session-1",
        )


@pytest.mark.asyncio
async def test_change_action_rejects_truncated_existing_file(context):
    context.provenance[0].truncated = True
    payload = {
        "kind": "changes",
        "summary": "Unsafe truncation",
        "files": [{"path": "main.py", "proposed_content": "value = 2\n"}],
    }
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(return_value=AssistantMessage(content=json.dumps(payload))),
    )

    with pytest.raises(ValueError, match="not fully included"):
        await run_editor_action(
            provider=provider,
            action="simplify_code",
            instruction=None,
            context=context,
            session_id="session-1",
        )


@pytest.mark.asyncio
async def test_explanation_action_cannot_return_file_changes(context):
    payload = {
        "kind": "changes",
        "summary": "Unexpected mutation",
        "files": [{"path": "main.py", "proposed_content": "value = 2\n"}],
    }
    provider = SimpleNamespace(
        provider_name="test",
        chat=AsyncMock(return_value=AssistantMessage(content=json.dumps(payload))),
    )

    with pytest.raises(ValueError, match="expected explanation"):
        await run_editor_action(
            provider=provider,
            action="explain_code",
            instruction=None,
            context=context,
            session_id="session-1",
        )
