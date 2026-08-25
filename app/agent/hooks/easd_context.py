"""Inject one accepted active EASD contract into Coding agent turns."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from app.agent.hooks.base import BaseAgentHook
from app.core.db import DbFactory, resolve_db_factory
from app.services.trace_service import (
    build_easd_runtime_contract,
    preimplementation_run_for_session,
)

if TYPE_CHECKING:
    from app.agent.state import AgentState, ModelRequest, RunContext


class EasdContextHook(BaseAgentHook):
    def __init__(
        self,
        *,
        db_factory: DbFactory,
        lead_session_id: str,
        agent_name: str,
        role: str,
    ) -> None:
        self._db_factory = resolve_db_factory(db_factory)
        self._lead_session_id = lead_session_id
        self._agent_name = agent_name
        self._role = role
        self._loaded = False
        self._block: str | None = None

    async def before_agent(self, ctx: RunContext, state: AgentState) -> None:
        self._loaded = True
        self._block = None
        for key in (
            "_easd_run_id",
            "_easd_phase",
            "_easd_spec_hash",
            "_easd_plan_hash",
            "_easd_verification_commands",
            "_easd_impact_targets",
            "_easd_repository_roots",
            "_easd_context_error",
            "_easd_preimplementation_run_id",
            "_easd_preimplementation_phase",
        ):
            state.metadata.pop(key, None)
        try:
            async with self._db_factory() as db:
                preimplementation_run = await preimplementation_run_for_session(
                    db, self._lead_session_id
                )
                contract = await build_easd_runtime_contract(
                    db,
                    session_id=self._lead_session_id,
                    agent_name=self._agent_name,
                    role=self._role,
                )
        except Exception as exc:  # noqa: BLE001 - context must not break a turn
            logger.warning(
                "easd_context_load_failed session_id={} agent={} error={}",
                self._lead_session_id,
                self._agent_name,
                exc,
            )
            state.metadata["_easd_context_error"] = str(exc)
            self._block = (
                "## EASD Contract Unavailable\n\n"
                "The accepted EASD contract could not be loaded. Do not mutate "
                "workspace files or claim completion until the local contract "
                "store is available."
            )
            return
        if preimplementation_run is not None:
            state.metadata["_easd_preimplementation_run_id"] = str(
                preimplementation_run.id
            )
            state.metadata["_easd_preimplementation_phase"] = (
                preimplementation_run.status
            )
        if contract is None:
            return
        self._block = contract.prompt
        state.metadata["_easd_run_id"] = contract.run_id
        state.metadata["_easd_phase"] = contract.run_status
        state.metadata["_easd_spec_hash"] = contract.spec_hash
        state.metadata["_easd_plan_hash"] = contract.plan_hash
        state.metadata["_easd_verification_commands"] = list(
            contract.verification_commands
        )
        state.metadata["_easd_impact_targets"] = list(contract.impact_targets)
        state.metadata["_easd_repository_roots"] = list(contract.repository_roots)

    async def before_model(
        self,
        ctx: RunContext,
        state: AgentState,
        request: ModelRequest,
    ) -> ModelRequest | None:
        if not self._loaded:
            await self.before_agent(ctx, state)
        if not self._block:
            return None
        prompt = (
            f"{request.system_prompt}\n\n{self._block}"
            if request.system_prompt
            else self._block
        )
        return request.override(system_prompt=prompt)

    async def wrap_tool_call(self, ctx, state, tool_call, handler) -> str:
        if state.metadata.get(
            "_easd_preimplementation_run_id"
        ) and tool_call.function.name in {
            "edit",
            "patch",
            "python",
            "rm",
            "shell",
            "team_delegate",
            "team_worktree",
            "worktree_start",
            "write",
        }:
            phase = state.metadata.get("_easd_preimplementation_phase")
            if phase == "planning":
                next_action = (
                    "inspect with read/grep/glob/code_context, then call "
                    "easd_submit_plan. Wait for user plan approval before implementation."
                )
            elif phase in {"plan_review", "planned"}:
                next_action = (
                    "wait for user plan approval and Run implementation in chat."
                )
            else:
                next_action = (
                    "during authoring, inspect with read/grep/glob/code_context, "
                    "ask clarifying questions, then call easd_submit_specification. "
                    "After drafting, wait for user specification approval and Run plan."
                )
            return "BLOCKED — EASD pre-implementation work is read-only. " + next_action
        read_only_phase = state.metadata.get("_easd_phase")
        if read_only_phase in {"reviewing", "verifying"} and (
            tool_call.function.name
            in {
                "edit",
                "patch",
                "python",
                "rm",
                "team_worktree",
                "worktree_start",
                "write",
            }
        ):
            if read_only_phase == "reviewing":
                return (
                    "BLOCKED — EASD Review is read-only for product files. Inspect "
                    "the integrated revision, run safe verification, delegate an "
                    "independent review when required, and submit cited review evidence."
                )
            return (
                "BLOCKED — EASD Verify is read-only for product files. Run the "
                "approved verification missions, assess persisted evidence, and "
                "report gaps without modifying implementation."
            )
        return await handler(ctx, state, tool_call)


__all__ = ["EasdContextHook"]
