from __future__ import annotations

from types import SimpleNamespace

from app.agent.mcp.tools import validate_mcp_tool


def test_valid_mcp_tool_schema_is_advertisable() -> None:
    valid, reason = validate_mcp_tool(
        SimpleNamespace(
            name="tickets.search",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    )

    assert valid
    assert reason == ""


def test_malformed_mcp_tool_schema_is_rejected() -> None:
    valid, reason = validate_mcp_tool(
        SimpleNamespace(
            name="tickets.search",
            input_schema={"type": "object", "properties": {}, "required": ["query"]},
        )
    )

    assert not valid
    assert "required" in reason


def test_invalid_mcp_tool_name_is_rejected() -> None:
    valid, reason = validate_mcp_tool(SimpleNamespace(name="", input_schema={}))

    assert not valid
    assert "name" in reason
