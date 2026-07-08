"""Innermost tool executor — the final link in the tool-call chain.

The ``Agent`` builds a ``ToolCallHandler`` chain out of every hook's
``wrap_tool_call`` and lays this executor at the bottom.  When the
chain is invoked it eventually calls ``execute(ctx, state, tc)``,
which:

1. Parses ``tc.function.arguments`` JSON.
2. Looks up the tool in the run-local lookup.
3. Runs it with ``_injected={"_state": state}`` plus the parsed args.
4. Coerces the return into a string (special-casing :class:`ToolResult`
   for multimodal parts, ``dict``/``list`` via ``json.dumps``).
5. On error, normalises the message with :func:`sanitize_error`.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.agent.errors import ToolArgumentError, ToolNotFoundError
from app.agent.schemas.chat import ContentBlock, TextBlock, ToolResult

if TYPE_CHECKING:
    from app.agent.schemas.chat import ToolCall
    from app.agent.state import AgentState, RunContext, ToolCallHandler
    from app.agent.tools.registry import Tool


def sanitize_error(message: str) -> str:
    """Normalise sandbox paths in tool error messages."""
    return message


# Tools intercepted in plan mode — recorded rather than executed.
_PLAN_INTERCEPTED: frozenset[str] = frozenset(
    {"edit", "write", "patch", "rm", "shell", "python", "bg"}
)


def _plan_summary(tool_name: str, args: dict) -> str:
    """Build a short human-readable summary of a planned tool call."""
    if tool_name in ("edit", "write", "patch"):
        path = str(args.get("file_path") or args.get("path") or "?")
        return path
    if tool_name == "rm":
        return str(args.get("path") or "?")
    if tool_name in ("shell", "bg"):
        cmd = str(args.get("command") or "")
        return (cmd[:120] + "…") if len(cmd) > 120 else cmd or "(no command)"
    if tool_name == "python":
        code = str(args.get("code") or "")
        first = code.split("\n")[0].strip()
        return (first[:120] + "…") if len(first) > 120 else first or "(python code)"
    raw = str(args)
    return (raw[:120] + "…") if len(raw) > 120 else raw


def make_tool_executor(
    run_tools: dict[str, Tool],
    agent_name: str,
) -> ToolCallHandler:
    """Return the innermost tool executor coroutine for one ``Agent.run``.

    Closed over ``run_tools`` (constructor + injected tools) and the
    agent's ``name`` (logging only).  The executor itself depends on
    no instance state, so it can live outside the class.
    """

    async def execute(ctx: RunContext, s: AgentState, tc: ToolCall) -> str:
        tool_start = time.monotonic()
        logger.info(
            "tool_start agent={} tool={} id={} args={}",
            agent_name,
            tc.function.name,
            tc.id,
            tc.function.arguments[:500] if tc.function.arguments else "{}",
        )

        try:
            args: dict = {}
            if tc.function.arguments:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, ValueError) as parse_exc:
                    logger.warning(
                        "tool_args_parse_failed tool={} raw_args={} error={}",
                        tc.function.name,
                        tc.function.arguments,
                        parse_exc,
                    )
                    raise ToolArgumentError(
                        f"Could not parse arguments for tool '{tc.function.name}': "
                        f"{parse_exc}. Raw: {tc.function.arguments!r}"
                    ) from parse_exc

            if tc.function.name not in run_tools:
                raise ToolNotFoundError(f"Tool '{tc.function.name}' not found.")

            # ── Plan mode intercept ────────────────────────────────────────
            # When the agent is in plan mode, record destructive tool calls
            # instead of executing them. The agent receives a [PLAN] ack and
            # continues planning; the actual execution only happens after the
            # user approves the plan via exit_plan_mode.
            if s.metadata.get("_plan_mode") and tc.function.name in _PLAN_INTERCEPTED:
                from app.agent.plan import get_plan_mode_service

                plan_svc = get_plan_mode_service()
                summary = _plan_summary(tc.function.name, args)
                result = plan_svc.record_step(tc.function.name, args, summary)
                tool_elapsed = time.monotonic() - tool_start
                logger.info(
                    "plan_step_recorded agent={} tool={} elapsed={:.2f}s step={}",
                    agent_name,
                    tc.function.name,
                    tool_elapsed,
                    plan_svc.step_count,
                )
                return result
            # ─────────────────────────────────────────────────────────────

            # Surface team routing context as first-class injected args so
            # tools (e.g. schedule_task) don't have to fish through
            # ``state.metadata`` themselves.  Falls back to defaults when the
            # caller did not populate ``RunConfig.metadata`` (non-team runs).
            team_mode_raw = s.metadata.get("team_mode", "forge")
            injected_mode = "coding" if team_mode_raw == "coding" else "forge"
            team_workspace_raw = s.metadata.get("team_workspace")
            injected_workspace = (
                str(team_workspace_raw)
                if isinstance(team_workspace_raw, str) and team_workspace_raw
                else None
            )

            result_raw = await run_tools[tc.function.name].arun(
                _injected={
                    "_state": s,
                    "_mode": injected_mode,
                    "_workspace": injected_workspace,
                    "_tool_output": s.metadata.get("_tool_output_callbacks", {}).get(
                        tc.id
                    ),
                    "agent_name": agent_name,
                    "tool_call_id": tc.id,
                    "session_id": s.metadata.get("session_id", ""),
                },
                **args,
            )

            if isinstance(result_raw, ToolResult):
                # Multimodal tool result — stash parts in state metadata
                # for retrieval when constructing the ToolMessage.
                # Derive content from TextBlock items for DB persistence.
                result = " ".join(
                    p.text for p in result_raw.parts if isinstance(p, TextBlock)
                )
                pending: dict[str, list[ContentBlock]] = s.metadata.setdefault(
                    "_multimodal_tool_parts", {}
                )
                pending[tc.id] = result_raw.parts

                if result_raw.mcp_app:
                    mcp_apps: dict[str, dict[str, Any]] = s.metadata.setdefault(
                        "_mcp_apps", {}
                    )
                    mcp_apps[tc.id] = result_raw.mcp_app
            elif isinstance(result_raw, (dict, list)):
                result = json.dumps(result_raw)
            else:
                result = str(result_raw)

            tool_elapsed = time.monotonic() - tool_start
            logger.info(
                "tool_done agent={} tool={} elapsed={:.2f}s result_len={}",
                agent_name,
                tc.function.name,
                tool_elapsed,
                len(result),
            )
            logger.debug(
                "tool_result_preview agent={} tool={} result={}",
                agent_name,
                tc.function.name,
                result[:1000] if len(result) > 1000 else result,
            )

        except Exception as e:
            result = f"Error: {sanitize_error(str(e))}"
            tool_elapsed = time.monotonic() - tool_start
            logger.error(
                "tool_error agent={} tool={} elapsed={:.2f}s error={}",
                agent_name,
                tc.function.name,
                tool_elapsed,
                e,
            )

        return result

    return execute
