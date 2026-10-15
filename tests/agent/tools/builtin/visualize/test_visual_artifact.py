from __future__ import annotations

import json

import pytest

from app.agent.schemas.chat import HumanMessage, ToolMessage
from app.agent.state import AgentState
from app.agent.tools.builtin.visualize.visual_artifact import visual_artifact


def valid_dashboard_args(**overrides: object) -> dict[str, object]:
    return {
        "artifact_id": "revenue-dashboard",
        "kind": "dashboard",
        "title": "Revenue",
        "summary": "Quarterly revenue by region",
        "source_html": "<main>Revenue</main>",
        "sources": [],
        **overrides,
    }


def tool_context(messages: list[object]) -> dict[str, object]:
    return {
        "_state": AgentState(messages=messages, system_prompt=""),
        "agent_name": "assistant",
        "tool_call_id": "artifact-call",
        "session_id": "",
    }


@pytest.mark.asyncio
async def test_dashboard_source_must_match_successful_tool_call_in_active_history() -> (
    None
):
    result = await visual_artifact(
        **valid_dashboard_args(
            sources=[
                {"tool_call_id": "missing-call", "query_summary": "pipeline totals"}
            ]
        ),
        _injected=tool_context([HumanMessage(content="Build a dashboard")]),
    )
    assert result["success"] is False
    assert "source tool call" in result["error"]


@pytest.mark.asyncio
async def test_visual_artifact_description_teaches_task_fit_and_payload_contract() -> (
    None
):
    description = visual_artifact.description.lower()
    assert (
        "dashboard" in description and "motion" in description and "3d" in description
    )
    assert "when" in description
    assert all(
        cue in description
        for cue in ("state changes", "enables the next", "prompt length")
    )


@pytest.mark.asyncio
async def test_accepts_only_successful_matching_dashboard_source() -> None:
    messages = [
        HumanMessage(content="Build a dashboard"),
        ToolMessage(
            tool_call_id="query-call",
            name="mcp_salesforce.query",
            content=json.dumps({"success": True, "rows": 3}),
        ),
    ]
    result = await visual_artifact(
        **valid_dashboard_args(
            sources=[
                {"tool_call_id": "query-call", "query_summary": "opportunity totals"}
            ]
        ),
        _injected=tool_context(messages),
    )
    assert result["success"] is True


@pytest.mark.asyncio
async def test_tool_executor_injects_active_history_without_exposing_internal_fields() -> (
    None
):
    schema_fields = visual_artifact.definition["function"]["parameters"]["properties"]
    assert "_state" not in schema_fields and "_injected" not in schema_fields
    result = await visual_artifact.arun(
        _injected=tool_context([HumanMessage(content="Build a dashboard")]),
        **valid_dashboard_args(
            sources=[
                {"tool_call_id": "missing-call", "query_summary": "pipeline totals"}
            ]
        ),
    )
    assert result["success"] is False
    assert "source tool call" in result["error"]
