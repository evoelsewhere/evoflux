"""WorkflowRunner — inline execution driver (plan §6.1-§6.3, §6.5).

A process singleton holding one in-memory :class:`ExecutionState` per
session (409 on a second `/run`). M3 drives the headless kinds end to end
in an asyncio task; agent/gate/input/foreach handlers arrive with M4 —
until then a definition containing them fails at run start with a clear
error. DB rows (`workflow_executions`/`workflow_node_runs`) are a
best-effort debug log, never read back.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid7

from loguru import logger

from app.workflow.graph import GraphState
from app.workflow.models import PHASE2_KINDS, WorkflowDefinition
from app.workflow.nodes import (
    WorkflowNodeError,
    run_notify_node,
    run_switch_node,
    run_tool_node,
    run_transform_node,
)
from app.workflow.template import TemplateError, render

_OUTPUT_CAP_BYTES = 32 * 1024

#: Node kinds the M3 runner can execute inline. M4 extends this set.
HEADLESS_KINDS = frozenset({"tool", "switch", "transform", "notify"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cap_output(output: dict | None) -> dict | None:
    if output is None:
        return None
    encoded = json.dumps(output, default=str)
    if len(encoded) <= _OUTPUT_CAP_BYTES:
        return output
    return {"_truncated": True, "text": encoded[:_OUTPUT_CAP_BYTES]}


@dataclass
class ExecutionState:
    execution_id: UUID
    definition: WorkflowDefinition
    session_id: str
    scope_workspace: str | None
    graph: GraphState
    inputs: dict[str, Any]
    node_outputs: dict[str, dict] = field(default_factory=dict)
    status: str = "running"  # running | waiting_gate | completed | failed | stopped
    error: str | None = None
    pending_node: str | None = None
    watermark: str | None = None
    captured_artifact: dict | None = None
    interrupted: bool = False
    stop_requested: bool = False
    #: The asyncio task driving inline execution; cancelled by stop.
    drive_task: asyncio.Task | None = None
    #: Current cancellable awaitable owner (gate future / tool task).
    current_node_id: str | None = None

    def template_scope(self, extra: dict | None = None) -> dict:
        import os

        scope: dict[str, Any] = {
            "inputs": self.inputs,
            "nodes": {
                node_id: {"output": output}
                for node_id, output in self.node_outputs.items()
            },
            "env": dict(os.environ),
        }
        if extra:
            scope.update(extra)
        return scope


class WorkflowRunner:
    def __init__(self) -> None:
        self.active: dict[str, ExecutionState] = {}

    # -- lifecycle ------------------------------------------------------------
    def is_driving(self, session_id: str) -> bool:
        return session_id in self.active

    def get(self, session_id: str) -> ExecutionState | None:
        return self.active.get(session_id)

    async def start(
        self,
        definition: WorkflowDefinition,
        *,
        definition_hash: str,
        session_id: str,
        inputs: dict[str, Any],
        scope_workspace: str | None,
    ) -> ExecutionState:
        if session_id in self.active:
            raise RuntimeError("execution already active in this session")
        state = ExecutionState(
            execution_id=uuid7(),
            definition=definition,
            session_id=session_id,
            scope_workspace=scope_workspace,
            graph=GraphState.create(definition),
            inputs=inputs,
        )
        self.active[session_id] = state
        await self._persist_execution_start(state, definition_hash)
        await self._emit_progress(state, node_id=None)
        state.drive_task = asyncio.create_task(self._drive_safely(state))
        return state

    async def stop(self, execution_id: UUID) -> bool:
        for state in list(self.active.values()):
            if state.execution_id == execution_id:
                state.stop_requested = True
                if state.drive_task is not None and not state.drive_task.done():
                    state.drive_task.cancel()
                await self._finish(state, status="stopped")
                return True
        return False

    def notify_interrupt(self, session_id: str) -> None:
        """Stop-button path (F9): the next capture/advance marks the
        execution stopped instead of advancing."""
        state = self.active.get(session_id)
        if state is not None:
            state.interrupted = True

    # -- the sequential walk ----------------------------------------------------
    async def _drive_safely(self, state: ExecutionState) -> None:
        try:
            await self._drive(state)
        except asyncio.CancelledError:  # stop() already finalised
            raise
        except Exception as exc:  # noqa: BLE001 — belt-and-braces
            logger.exception("workflow_drive_crashed execution={}", state.execution_id)
            await self._fail(state, node_id=state.current_node_id, error=str(exc))

    async def _drive(self, state: ExecutionState) -> None:
        team = self._find_team(state.session_id)
        if team is not None:
            team.set_inline_busy(True)
        try:
            while True:
                if state.stop_requested or state.interrupted:
                    await self._finish(state, status="stopped")
                    return
                node_id = state.graph.next_ready()
                if node_id is None:
                    await self._complete(state)
                    return
                node = next(n for n in state.definition.nodes if n.id == node_id)
                if node.kind in PHASE2_KINDS:
                    await self._fail(
                        state,
                        node_id=node_id,
                        error=f"'{node.kind}' nodes arrive in Phase 2.",
                    )
                    return
                if node.kind not in HEADLESS_KINDS:
                    await self._fail(
                        state,
                        node_id=node_id,
                        error=(
                            f"'{node.kind}' nodes need the team runner (M4) — "
                            f"not available yet."
                        ),
                    )
                    return
                await self._run_headless_node(state, node)
                if state.graph.node_status[node.id] == "failed":
                    return
        finally:
            # Lower the busy flag whenever this execution no longer drives
            # the session (terminal paths pop it from `active`).
            if team is not None and self.active.get(state.session_id) is not state:
                team.set_inline_busy(False)

    async def _run_headless_node(self, state: ExecutionState, node) -> None:
        state.current_node_id = node.id
        state.graph.mark_running(node.id)
        node_run_id = await self._persist_node_start(state, node.id)
        await self._emit_progress(state, node_id=node.id)
        try:
            scope = state.template_scope()
            if node.kind == "tool":
                timeout = node.timeout_s or 900
                output, answer = await asyncio.wait_for(
                    run_tool_node(node, scope, workspace=state.scope_workspace),
                    timeout=timeout,
                )
            elif node.kind == "switch":
                output, answer = run_switch_node(node, scope)
            elif node.kind == "transform":
                output, answer = run_transform_node(node, scope)
            elif node.kind == "notify":
                output, answer = await run_notify_node(
                    node,
                    scope,
                    session_id=state.session_id,
                    workflow_name=state.definition.name,
                )
            else:  # pragma: no cover — guarded by the caller
                raise WorkflowNodeError(f"unsupported kind '{node.kind}'")
        except (WorkflowNodeError, TemplateError) as exc:
            await self._persist_node_end(node_run_id, status="failed", error=str(exc))
            await self._fail(state, node_id=node.id, error=str(exc))
            return
        except asyncio.TimeoutError:
            error = f"node '{node.id}' timed out."
            await self._persist_node_end(node_run_id, status="failed", error=error)
            await self._fail(state, node_id=node.id, error=error)
            return

        state.node_outputs[node.id] = output
        state.graph.mark_succeeded(node.id, answer=answer)
        await self._persist_node_end(node_run_id, status="succeeded", output=output)
        state.current_node_id = None

    # -- terminal transitions ---------------------------------------------------
    async def _complete(self, state: ExecutionState) -> None:
        outputs: dict[str, Any] = {}
        try:
            outputs = {
                key: render(tpl, state.template_scope())
                for key, tpl in state.definition.outputs.items()
            }
        except TemplateError as exc:
            # Outputs referencing skipped branches simply come back partial.
            logger.debug(
                "workflow_outputs_partial execution={} error={}",
                state.execution_id,
                exc,
            )
        state.status = "completed"
        await self._persist_execution_end(state, outputs=outputs)
        await self._emit_progress(state, node_id=None)
        self.active.pop(state.session_id, None)

    async def _fail(
        self, state: ExecutionState, *, node_id: str | None, error: str
    ) -> None:
        if node_id is not None:
            state.graph.mark_failed(node_id)
        state.status = "failed"
        state.error = error
        await self._persist_execution_end(state, error=error)
        await self._emit_progress(state, node_id=node_id, error=error)
        self.active.pop(state.session_id, None)

    async def _finish(self, state: ExecutionState, *, status: str) -> None:
        if self.active.get(state.session_id) is not state:
            return  # already finalised
        state.status = status
        await self._persist_execution_end(state)
        await self._emit_progress(state, node_id=state.current_node_id)
        self.active.pop(state.session_id, None)
        team = self._find_team(state.session_id)
        if team is not None:
            team.set_inline_busy(False)

    # -- side channels ------------------------------------------------------------
    @staticmethod
    def _find_team(session_id: str):
        from app.services import team_manager

        return team_manager.find_team_for_session(session_id)

    async def _emit_progress(
        self,
        state: ExecutionState,
        *,
        node_id: str | None,
        error: str | None = None,
    ) -> None:
        from app.services import memory_stream_store as stream_store
        from app.services.stream_envelope import StreamEnvelope

        order = state.graph.order
        payload = {
            "type": "workflow_progress",
            "session_id": state.session_id,
            "execution_id": str(state.execution_id),
            "definition_name": state.definition.name,
            "status": state.status,
            "node_id": node_id,
            "node_index": (order.index(node_id) + 1) if node_id in order else None,
            "total_nodes": len(order),
        }
        if error:
            payload["error"] = error
        try:
            await stream_store.push_event(
                state.session_id,
                StreamEnvelope.from_parts("workflow_progress", payload),
            )
        except Exception as exc:  # noqa: BLE001 — SSE must never kill a run
            logger.debug("workflow_progress_emit_failed error={}", exc)

    # -- persistence (best-effort debug log) --------------------------------------
    async def _persist_execution_start(
        self, state: ExecutionState, definition_hash: str
    ) -> None:
        from app.core import db as db_module
        from app.models.workflow import WorkflowExecution

        try:
            async with db_module.async_session_factory() as db:
                db.add(
                    WorkflowExecution(
                        id=state.execution_id,
                        definition_name=state.definition.name,
                        definition_hash=definition_hash,
                        session_id=UUID(state.session_id),
                        status="running",
                    )
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_execution_persist_failed error={}", exc)

    async def _persist_execution_end(
        self,
        state: ExecutionState,
        *,
        outputs: dict | None = None,
        error: str | None = None,
    ) -> None:
        from app.core import db as db_module
        from app.models.workflow import WorkflowExecution

        try:
            async with db_module.async_session_factory() as db:
                row = await db.get(WorkflowExecution, state.execution_id)
                if row is not None:
                    row.status = state.status
                    row.error = error
                    row.outputs = _cap_output(outputs) or {}
                    row.ended_at = _utcnow()
                    db.add(row)
                    await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_execution_persist_failed error={}", exc)

    async def _persist_node_start(
        self, state: ExecutionState, node_id: str, iteration: int | None = None
    ) -> UUID | None:
        from app.core import db as db_module
        from app.models.workflow import WorkflowNodeRun

        try:
            async with db_module.async_session_factory() as db:
                row = WorkflowNodeRun(
                    execution_id=state.execution_id,
                    node_id=node_id,
                    iteration=iteration,
                    status="running",
                )
                db.add(row)
                await db.commit()
                return row.id
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_node_persist_failed error={}", exc)
            return None

    async def _persist_node_end(
        self,
        node_run_id: UUID | None,
        *,
        status: str,
        output: dict | None = None,
        error: str | None = None,
    ) -> None:
        if node_run_id is None:
            return
        from app.core import db as db_module
        from app.models.workflow import WorkflowNodeRun

        try:
            async with db_module.async_session_factory() as db:
                row = await db.get(WorkflowNodeRun, node_run_id)
                if row is not None:
                    row.status = status
                    row.output = _cap_output(output)
                    row.error = error
                    row.ended_at = _utcnow()
                    db.add(row)
                    await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_node_persist_failed error={}", exc)


#: Process singleton (plan §6.1).
runner = WorkflowRunner()
