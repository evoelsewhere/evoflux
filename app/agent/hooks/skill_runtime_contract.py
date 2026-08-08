"""Rehydrate declarative runtime contracts for durable skill activations."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.agent.skills.activation import (
    SkillDependencyError,
    apply_skill_runtime_contract,
)

if TYPE_CHECKING:
    from app.agent.schemas.chat import AssistantMessage, ToolCall
    from app.agent.state import AgentState, RunContext, ToolCallHandler


_INVESTIGATION_SKILL = "coding-investigation"
_INVESTIGATION_POLICY_KEY = "_coding_investigation_policy"
_MAX_GRAPH_OBSERVATIONS = 6
_MAX_SOURCE_FALLBACKS = 8
_MUTATING_INVESTIGATION_TOOLS = frozenset(
    {"edit", "patch", "process", "python", "rm", "shell", "write"}
)
_MATCH_COUNT_RE = re.compile(r"(?m)^matches: (\d+)$")


def _investigation_active(state: AgentState) -> bool:
    contracts = state.metadata.get("skill_runtime_contracts") or {}
    loaded = state.metadata.get("loaded_skills") or {}
    return _INVESTIGATION_SKILL in contracts or _INVESTIGATION_SKILL in loaded


def _call_fingerprint(tool_call: ToolCall) -> tuple[str, str]:
    arguments = tool_call.function.arguments or "{}"
    try:
        arguments = json.dumps(
            json.loads(arguments), sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return tool_call.function.name, arguments


def _is_source_fallback(state: AgentState, tool_name: str) -> bool:
    capabilities = (state.metadata.get("_tool_capabilities") or {}).get(
        tool_name, ()
    )
    normalized = {str(value).casefold() for value in capabilities}
    return bool(normalized & {"source_navigation", "workspace_read"})


def _match_count(result: str) -> int | None:
    match = _MATCH_COUNT_RE.search(result)
    return int(match.group(1)) if match is not None else None


def _successful_observation(result: str) -> bool:
    return not result.lstrip().startswith(("Error:", "[Blocked"))


def _reuse_receipt(tool_call: ToolCall, cached: dict[str, str]) -> str:
    return (
        "[Observation reused by coding-investigation runtime contract]\n"
        f"tool: {tool_call.function.name}\n"
        f"original_call_id: {cached['tool_call_id']}\n"
        f"result_sha256: {cached['result_sha256']}\n"
        "The earlier result remains authoritative in this read-only investigation. "
        "Use a different symbol, operation, or bounded source range only for a "
        "specific unresolved evidence gap."
    )


def _blocked(reason: str, next_step: str) -> str:
    return (
        "[Blocked by coding-investigation runtime contract]\n"
        f"reason: {reason}\n"
        f"next: {next_step}"
    )


class SkillRuntimeContractHook(BaseAgentHook):
    """Apply dependencies and observation policy for every loaded skill."""

    def __init__(self, *, mode: str) -> None:
        self._mode = "coding" if mode == "coding" else "work"

    async def before_agent(self, ctx: RunContext, state: AgentState) -> None:
        from app.agent.tools.builtin.skill import (
            _loaded_skills_from_messages,
            discover_skill_records_runtime,
        )

        loaded = _loaded_skills_from_messages(state)
        state.metadata["loaded_skills"] = loaded
        if not loaded:
            return
        records = discover_skill_records_runtime(mode=self._mode)
        for name in loaded:
            record = records.get(name)
            if record is None or not record.valid:
                continue
            try:
                apply_skill_runtime_contract(state, record)
            except SkillDependencyError as exc:
                state.metadata.setdefault("skill_runtime_errors", {})[name] = str(exc)
                logger.warning(
                    "skill_runtime_contract_unavailable agent={} skill={} error={}",
                    ctx.agent_name,
                    name,
                    exc,
                )

        if _investigation_active(state):
            state.metadata.setdefault(
                _INVESTIGATION_POLICY_KEY,
                {
                    "awaiting_graph": False,
                    "searches": 0,
                    "graph_attempts": 0,
                    "fallbacks": 0,
                    "observations": {},
                },
            )

    async def wrap_tool_call(
        self,
        ctx: RunContext,
        state: AgentState,
        tool_call: ToolCall,
        handler: ToolCallHandler,
    ) -> str:
        """Enforce bounded evidence collection for the investigation skill.

        The skill body remains the semantic contract. This runtime layer only
        enforces its objective invariants: read-only execution, one broad
        discovery before graph promotion, bounded fallback evidence, and no
        identical observation replay within the same run.
        """
        if not _investigation_active(state):
            return await handler(ctx, state, tool_call)

        policy = state.metadata.setdefault(
            _INVESTIGATION_POLICY_KEY,
            {
                "awaiting_graph": False,
                "searches": 0,
                "graph_attempts": 0,
                "fallbacks": 0,
                "observations": {},
            },
        )
        tool_name = tool_call.function.name
        if tool_name in _MUTATING_INVESTIGATION_TOOLS:
            return _blocked(
                f"'{tool_name}' can mutate the workspace during a read-only investigation.",
                "Use code_search, code_graph, grep, read, glob, or LSP evidence; "
                "report findings without changing code.",
            )

        is_navigation = tool_name in {"code_search", "code_graph"} or (
            _is_source_fallback(state, tool_name)
        )
        fingerprint = _call_fingerprint(tool_call)
        observations: dict[tuple[str, str], dict[str, str]] = policy["observations"]
        if is_navigation and (cached := observations.get(fingerprint)) is not None:
            return _reuse_receipt(tool_call, cached)

        if tool_name == "code_search":
            if policy["awaiting_graph"] or policy["searches"] >= 1:
                return _blocked(
                    "Broad discovery already returned declared source anchors.",
                    "Choose one identifier from the existing result and call "
                    "code_graph with the smallest structural operation.",
                )
            result = await handler(ctx, state, tool_call)
            policy["searches"] += 1
            count = _match_count(result)
            policy["awaiting_graph"] = bool(count and count > 0)
        elif tool_name == "code_graph":
            if policy["graph_attempts"] >= _MAX_GRAPH_OBSERVATIONS:
                return _blocked(
                    f"The graph evidence budget ({_MAX_GRAPH_OBSERVATIONS}) is exhausted.",
                    "Synthesize the bounded evidence already collected, or use one "
                    "targeted source observation for a named semantic gap.",
                )
            result = await handler(ctx, state, tool_call)
            policy["graph_attempts"] += 1
            # A graph attempt completes the mandatory discovery-to-graph
            # transition even when it reports a dynamic or unresolved gap.
            policy["awaiting_graph"] = False
        elif _is_source_fallback(state, tool_name):
            if policy["awaiting_graph"]:
                return _blocked(
                    "A promotable identifier was discovered but has not passed the graph gate.",
                    "Call code_graph for that exact identifier before reading or "
                    "searching more source.",
                )
            if policy["fallbacks"] >= _MAX_SOURCE_FALLBACKS:
                return _blocked(
                    f"The targeted source fallback budget ({_MAX_SOURCE_FALLBACKS}) is exhausted.",
                    "Stop observing and answer from the current evidence, naming any "
                    "remaining dynamic limitation explicitly.",
                )
            result = await handler(ctx, state, tool_call)
            policy["fallbacks"] += 1
        else:
            return await handler(ctx, state, tool_call)

        if _successful_observation(result):
            observations[fingerprint] = {
                "tool_call_id": tool_call.id,
                "result_sha256": hashlib.sha256(
                    result.encode("utf-8", errors="replace")
                ).hexdigest()[:16],
            }
        return result

    async def before_completion(
        self,
        ctx: RunContext,
        state: AgentState,
        response: AssistantMessage,
    ) -> str | None:
        del ctx, response
        if not _investigation_active(state):
            return None
        policy = state.metadata.get(_INVESTIGATION_POLICY_KEY) or {}
        if policy.get("awaiting_graph"):
            return (
                "The coding-investigation contract cannot complete yet: discovery "
                "returned an exact source anchor, but no code_graph transition was "
                "attempted. Use the smallest structural operation, then answer."
            )
        if not policy.get("graph_attempts"):
            return (
                "The coding-investigation contract requires at least one exact-symbol "
                "code_graph attempt before completion. If static resolution fails, "
                "report that bounded limitation after the attempt."
            )
        return None


__all__ = ["SkillRuntimeContractHook"]
