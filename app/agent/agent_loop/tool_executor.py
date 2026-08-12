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

import hashlib
import json
import time
from collections.abc import Set
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.agent.errors import ToolArgumentError, ToolNotFoundError
from app.agent.schemas.chat import ContentBlock, TextBlock, ToolResult
from app.agent.tool_media import materialize_tool_attachments

if TYPE_CHECKING:
    from app.agent.schemas.chat import ToolCall
    from app.agent.state import AgentState, RunContext, ToolCallHandler
    from app.agent.tools.registry import Tool


def sanitize_error(message: str) -> str:
    """Normalise sandbox paths in tool error messages."""
    return message


# Tools intercepted in plan mode — recorded rather than executed.
_PLAN_INTERCEPTED: frozenset[str] = frozenset(
    {"edit", "write", "patch", "rm", "shell", "python", "process"}
)


def _plan_summary(tool_name: str, args: dict) -> str:
    """Build a short human-readable summary of a planned tool call."""
    if tool_name in ("edit", "write", "patch"):
        path = str(args.get("file_path") or args.get("path") or "?")
        return path
    if tool_name == "rm":
        return str(args.get("path") or "?")
    if tool_name == "shell":
        cmd = str(args.get("command") or "")
        return (cmd[:120] + "…") if len(cmd) > 120 else cmd or "(no command)"
    if tool_name == "python":
        code = str(args.get("code") or "")
        first = code.split("\n")[0].strip()
        return (first[:120] + "…") if len(first) > 120 else first or "(python code)"
    if tool_name == "process":
        action = str(args.get("action") or "?")
        process_id = str(args.get("process_id") or "")
        return f"{action} {process_id}".strip()
    raw = str(args)
    return (raw[:120] + "…") if len(raw) > 120 else raw


def _observation_cache_key(tool: Tool, args: dict[str, Any]) -> str | None:
    key_builder = getattr(tool, "observation_key", None)
    if not callable(key_builder):
        return None
    raw_key = key_builder(args)
    if not raw_key:
        return None
    payload = f"{tool.name}\0{raw_key}".encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _prepare_observation(
    state: AgentState,
    tool: Tool,
    args: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return a revision cache key and an optional reuse receipt."""

    kind = getattr(tool, "observation_kind", None)
    if not isinstance(kind, str) or not kind:
        return None, None

    stats = state.metadata.setdefault(
        "tool_observation_stats",
        {"requests": 0, "executed": 0, "reused": 0, "by_kind": {}},
    )
    stats["requests"] += 1
    by_kind = stats.setdefault("by_kind", {})
    by_kind[kind] = int(by_kind.get(kind, 0)) + 1

    cache_key: str | None = None
    try:
        cache_key = _observation_cache_key(tool, args)
    except Exception as exc:  # noqa: BLE001 - caching must never break the tool
        logger.warning("tool_observation_key_failed tool={} error={}", tool.name, exc)
    if cache_key:
        cached = (state.metadata.get("_tool_observation_cache") or {}).get(cache_key)
        if isinstance(cached, dict):
            stats["reused"] += 1
            return (
                cache_key,
                (
                    "[Observation reused — source revision unchanged]\n"
                    f"tool: {tool.name}\n"
                    f"original_call_id: {cached.get('tool_call_id', 'unknown')}\n"
                    f"result_sha256: {cached.get('result_sha256', 'unknown')}\n"
                    "The prior result remains authoritative. Request a different range "
                    "or wait for the source revision to change before reading it again."
                ),
            )

    stats["executed"] = int(stats.get("executed", 0)) + 1
    return cache_key, None


def make_tool_executor(
    run_tools: dict[str, Tool],
    agent_name: str,
    deferred_names: Set[str] = frozenset(),
) -> ToolCallHandler:
    """Return the innermost tool executor coroutine for one ``Agent.run``.

    Closed over ``run_tools`` (constructor + injected tools) and the
    agent's ``name`` (logging only).  The executor itself depends on
    no instance state, so it can live outside the class.

    ``deferred_names`` are tools hidden from ``tool_defs`` by default (see
    ``Agent.run``'s ``deferred_tools`` param) but still present in
    ``run_tools`` so they work once unlocked via ``load_tool``. Hiding a
    schema is not an execution gate on its own — a model that names one
    directly (e.g. from ``load_tool``'s own catalog, which must list names to
    be useful) would otherwise have it run anyway. This closure enforces the
    activation requirement at the one place every tool call passes through.
    """

    async def execute(ctx: RunContext, s: AgentState, tc: ToolCall) -> str:
        tool_start = time.monotonic()
        logger.debug(
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
            active_tool = run_tools[tc.function.name]

            # ── Deferred-tool activation gate ───────────────────────────────
            # Visibility (tool_defs) says "call load_tool first"; this is the
            # actual enforcement so that guidance can't be silently bypassed.
            if tc.function.name in deferred_names and tc.function.name not in (
                s.metadata.get("activated_deferred_tools") or ()
            ):
                logger.info(
                    "tool_call_blocked_not_activated agent={} tool={}",
                    agent_name,
                    tc.function.name,
                )
                return (
                    f"'{tc.function.name}' is not yet available — call "
                    f"load_tool(tool_name='{tc.function.name}') first, then "
                    f"call '{tc.function.name}' again on your next turn."
                )
            # ─────────────────────────────────────────────────────────────

            observation_cache_key, observation_short_circuit = _prepare_observation(
                s, active_tool, args
            )
            if observation_short_circuit is not None:
                logger.info(
                    "tool_observation_short_circuit agent={} tool={} result={}",
                    agent_name,
                    tc.function.name,
                    observation_short_circuit.splitlines()[0],
                )
                return observation_short_circuit

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

            # Approved plan execution is bound to the exact recorded call
            # sequence. A model cannot silently alter arguments after approval.
            if (
                not s.metadata.get("_plan_mode")
                and tc.function.name in _PLAN_INTERCEPTED
            ):
                from app.agent.plan import get_plan_mode_service

                authorization = get_plan_mode_service().authorize_approved_call(
                    tc.function.name, args
                )
                if authorization is not None:
                    allowed, detail = authorization
                    if not allowed:
                        logger.warning(
                            "approved_plan_call_blocked agent={} tool={} detail={}",
                            agent_name,
                            tc.function.name,
                            detail,
                        )
                        return f"[Blocked — approved plan mismatch] {detail}"
                    logger.info(
                        "approved_plan_call_matched agent={} tool={} detail={}",
                        agent_name,
                        tc.function.name,
                        detail,
                    )

            # Surface team routing context as first-class injected args so
            # tools (e.g. schedule_task) don't have to fish through
            # ``state.metadata`` themselves.  Falls back to defaults when the
            # caller did not populate ``RunConfig.metadata`` (non-team runs).
            team_mode_raw = s.metadata.get("team_mode", "work")
            injected_mode = "coding" if team_mode_raw == "coding" else "work"
            team_workspace_raw = s.metadata.get("team_workspace")
            injected_workspace = (
                str(team_workspace_raw)
                if isinstance(team_workspace_raw, str) and team_workspace_raw
                else None
            )

            result_raw = await active_tool.arun(
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

                explicit_attachments = list(result_raw.attachments or [])
                session_id = str(s.metadata.get("session_id") or "")
                attachments: list[dict[str, str]] = []
                if session_id:
                    attachments = await materialize_tool_attachments(
                        result_raw.parts,
                        session_id=session_id,
                        tool_name=tc.function.name,
                    )
                attachments.extend(explicit_attachments)
                if attachments:
                    pending_attachments: dict[str, list[dict[str, str]]] = (
                        s.metadata.setdefault("_tool_attachments", {})
                    )
                    pending_attachments[tc.id] = attachments

                if result_raw.mcp_app:
                    mcp_apps: dict[str, dict[str, Any]] = s.metadata.setdefault(
                        "_mcp_apps", {}
                    )
                    mcp_apps[tc.id] = result_raw.mcp_app
            elif isinstance(result_raw, (dict, list)):
                result = json.dumps(result_raw)
            else:
                result = str(result_raw)

            if observation_cache_key and not result.startswith("Error:"):
                state_cache = s.metadata.setdefault("_tool_observation_cache", {})
                state_cache[observation_cache_key] = {
                    "tool_call_id": tc.id,
                    "result_sha256": hashlib.sha256(
                        result.encode("utf-8", errors="replace")
                    ).hexdigest()[:16],
                }
            tool_elapsed = time.monotonic() - tool_start
            logger.debug(
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

            # Track file mutations for post-turn Changes review (lead stream id).
            try:
                from app.services import turn_changes as turn_changes_svc

                track_sid = str(
                    s.metadata.get("stream_session_id")
                    or s.metadata.get("session_id")
                    or ""
                )
                if track_sid and not str(result).startswith("Error:"):
                    turn_changes_svc.record_tool_change(
                        track_sid,
                        tc.function.name,
                        args,
                        result=str(result),
                    )
            except Exception:  # noqa: BLE001 — never break tool execution
                pass

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
