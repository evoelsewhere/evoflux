"""Node handlers (plan §6.4).

M3 ships the four headless kinds — ``tool``, ``switch``, ``transform``,
``notify`` — which run inline with no team turn. ``agent``/``gate``/
``input``/``foreach`` land with M4 (team hooks + AskUserService); Phase 2
kinds are refused at run time by the runner. Every handler returns
``(output, answer)`` where ``answer`` is the routing value for
gate/switch and ``None`` otherwise.
"""

from __future__ import annotations

import json
from typing import Any

from app.workflow.models import Node
from app.workflow.template import render, render_object


class WorkflowNodeError(RuntimeError):
    """A node failed; the message is stored on the node run + execution."""


def shape_tool_output(result: Any) -> dict:
    """The §4.3 output-shape rule for tool results.

    MCP results: ``structuredContent`` when present, else JSON-parse the
    flattened text, else ``{"text": ...}``. Registry tools return plain
    strings — same JSON-parse-then-text rule.
    """
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured

    if hasattr(result, "content"):  # MCP CallToolResult
        pieces: list[str] = []
        for block in result.content or []:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                pieces.append(text)
        text_result = "\n".join(pieces)
    else:
        text_result = result if isinstance(result, str) else str(result)

    stripped = text_result.strip()
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {"text": text_result}
        if isinstance(parsed, dict):
            return parsed
        return {"items": parsed} if isinstance(parsed, list) else {"text": text_result}
    return {"text": text_result}


async def run_tool_node(
    node_like: Node | Any, scope: dict, *, workspace: str | None
) -> tuple[dict, None]:
    """Direct tool invocation (F11-F14): registry tools via ``arun``, MCP
    via ``call_app_tool``, both under a sandbox contextvar pinned to the
    workflow's workspace. Permission hooks are bypassed by construction —
    that is exactly what the approved manifest covers (plan §7.2)."""
    from app.agent.sandbox import SandboxConfig, set_sandbox

    rendered_args = render_object(node_like.args, scope)
    if not isinstance(rendered_args, dict):  # pragma: no cover — schema enforced
        raise WorkflowNodeError("tool args must render to an object.")

    tool_name: str = node_like.tool
    # coding/aim scope pins the sandbox to the target workspace; forge scope
    # leaves the contextvar untouched — the tools' own default-sandbox
    # fallback applies (F12).
    sandbox_token = (
        set_sandbox(SandboxConfig(workspace=workspace)) if workspace else None
    )
    try:
        if tool_name.startswith("mcp_"):
            parts = tool_name.split("_", 2)
            if len(parts) < 3:
                raise WorkflowNodeError(
                    f"'{tool_name}' is not a valid mcp_<server>_<tool> name."
                )
            server, bare_tool = parts[1], parts[2]
            from app.agent.mcp.manager import mcp_manager

            try:
                result = await mcp_manager.call_app_tool(
                    server, bare_tool, rendered_args
                )
            except KeyError:
                raise WorkflowNodeError(f"Unknown MCP server '{server}'.")
            except RuntimeError as exc:
                raise WorkflowNodeError(f"MCP server '{server}' not ready: {exc}")
            except ValueError as exc:
                raise WorkflowNodeError(str(exc))
            output = shape_tool_output(result)
        else:
            from app.agent.loader import _default_tool_registry
            from app.agent.tools.registry import (
                ToolArgumentError,
                ToolExecutionError,
            )

            registry = _default_tool_registry()
            tool = registry.get(tool_name)
            if tool is None:
                raise WorkflowNodeError(f"Unknown tool '{tool_name}'.")
            try:
                result = await tool.arun(**rendered_args)
            except (ToolArgumentError, ToolExecutionError) as exc:
                raise WorkflowNodeError(str(exc))
            output = shape_tool_output(result)
    finally:
        if sandbox_token is not None:
            from app.agent.sandbox import _sandbox_ctx

            _sandbox_ctx.reset(sandbox_token)
    return output, None


def run_switch_node(node_like: Node, scope: dict) -> tuple[dict, str]:
    """Pure function: render the value; the answer routes the edges."""
    value = render(node_like.value, scope)
    answer = value if isinstance(value, str) else json.dumps(value, default=str)
    return {"value": answer}, answer


def run_transform_node(node_like: Node | Any, scope: dict) -> tuple[dict, None]:
    rendered = {key: render(tpl, scope) for key, tpl in (node_like.set or {}).items()}
    return rendered, None


async def run_notify_node(
    node_like: Node | Any,
    scope: dict,
    *,
    session_id: str,
    workflow_name: str,
) -> tuple[dict, None]:
    """Push the existing desktop_notification envelope (team.py's payload
    shape) — instant, non-blocking."""
    from app.services import memory_stream_store as stream_store
    from app.services.stream_envelope import StreamEnvelope

    title = render(node_like.title, scope) if node_like.title else workflow_name
    message = render(node_like.message, scope)
    await stream_store.push_event(
        session_id,
        StreamEnvelope.from_parts(
            "desktop_notification",
            {
                "type": "desktop_notification",
                "kind": "workflow_notify",
                "session_id": session_id,
                "title": str(title),
                "body": str(message),
                "metadata": {"session_id": session_id, "workflow": workflow_name},
            },
        ),
    )
    return {"sent": True}, None
