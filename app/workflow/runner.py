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
from datetime import datetime, timedelta, timezone
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

#: Upper bound a human gate/input node will wait for a reply before the run
#: fails. A gate legitimately waits for a person (approve a cutover overnight),
#: but must not pin the session's single execution slot *forever* — an
#: abandoned gate eventually frees it. Restart recovery is handled separately
#: (:func:`reconcile_orphaned_executions`).
_GATE_TIMEOUT_S = 24 * 3600
_CLAIM_HEARTBEAT_S = 60
_CLAIM_HEARTBEAT_LEASE = timedelta(hours=4)

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


def _normalize_agent_output(output: dict | None) -> dict:
    normalized = dict(output or {})
    if isinstance(normalized.get("text"), str):
        return normalized

    sections: list[str] = []
    summary = normalized.get("summary")
    if isinstance(summary, str) and summary.strip():
        sections.append(summary.strip())

    for key, heading in (
        ("findings", "Findings"),
        ("evidence", "Evidence"),
        ("next_actions", "Next actions"),
    ):
        values = normalized.get(key)
        if isinstance(values, list):
            items = [
                value.strip()
                for value in values
                if isinstance(value, str) and value.strip()
            ]
            if items:
                sections.append(
                    f"### {heading}\n" + "\n".join(f"- {item}" for item in items)
                )

    verification = normalized.get("verification")
    if isinstance(verification, dict):
        details = []
        for key, label in (("method", "Method"), ("result", "Result")):
            value = verification.get(key)
            if isinstance(value, str) and value.strip():
                details.append(f"- **{label}:** {value.strip()}")
        if details:
            sections.append("### Verification\n" + "\n".join(details))

    normalized["text"] = "\n\n".join(sections) or json.dumps(normalized, default=str)
    return normalized


@dataclass
class ExecutionState:
    execution_id: UUID
    definition: WorkflowDefinition
    session_id: str
    scope_workspace: str | None
    graph: GraphState
    inputs: dict[str, Any]
    retry_of_execution_id: UUID | None = None
    node_outputs: dict[str, dict] = field(default_factory=dict)
    status: str = "running"  # running | waiting_gate | completed | failed | stopped
    error: str | None = None
    pending_node: str | None = None
    pending_node_run_id: UUID | None = None
    pending_iteration: int | None = None
    watermark: str | None = None
    captured_artifact: dict | None = None
    #: Output the boundary-capture hook computed for the pending agent node;
    #: consumed by the drive task when advance resumes it.
    captured_output: dict | None = None
    captured_failed: bool = False
    interrupted: bool = False
    stop_requested: bool = False
    #: The asyncio task driving inline execution; cancelled by stop.
    drive_task: asyncio.Task | None = None
    #: Current cancellable awaitable owner (gate future / tool task).
    current_node_id: str | None = None
    #: True while the drive task awaits a turn boundary (agent node turn in
    #: flight). advance only resumes when this is set — a user turn that ran
    #: mid-workflow must not spuriously wake the walk.
    awaiting_boundary: bool = False
    resume_event: asyncio.Event = field(default_factory=asyncio.Event)
    #: How many synthetic turns this execution injected — terminal DoneEvent
    #: is only owed when > 0 (headless-only runs never opened a turn).
    injected_turns: int = 0
    listener_task: asyncio.Task | None = None
    claim_heartbeat_task: asyncio.Task | None = None

    def template_scope(self, extra: dict | None = None) -> dict:
        import os

        from app.workflow.template import referenced_env_names

        # Only expose the env vars this definition actually references — the
        # exact names the approval manifest surfaced to the reviewer — never
        # the whole host environment. A template can't read a secret it didn't
        # declare (and an edit that adds one re-invalidates the approval hash).
        allowed = referenced_env_names(self.definition.model_dump())
        scope: dict[str, Any] = {
            "inputs": self.inputs,
            "nodes": {
                node_id: {"output": output}
                for node_id, output in self.node_outputs.items()
            },
            "env": {name: os.environ[name] for name in allowed if name in os.environ},
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

    def is_execution_driving(self, execution_id: UUID) -> bool:
        return any(state.execution_id == execution_id for state in self.active.values())

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
        retry_of_execution_id: UUID | None = None,
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
            retry_of_execution_id=retry_of_execution_id,
        )
        self.active[session_id] = state
        await self._persist_execution_start(state, definition_hash)
        await self._emit_progress(state, node_id=None)
        state.claim_heartbeat_task = asyncio.create_task(
            self._claim_heartbeat_loop(state)
        )
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
        from app.workflow.exec_context import current_execution_id

        team = self._find_team(state.session_id)
        if team is not None:
            team.set_inline_busy(True)
        exec_token = current_execution_id.set(str(state.execution_id))
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
                if node.kind in HEADLESS_KINDS:
                    await self._run_headless_node(state, node)
                elif node.kind == "agent":
                    await self._run_agent_node(state, node)
                elif node.kind in ("gate", "input"):
                    await self._run_question_node(state, node)
                elif node.kind == "foreach":
                    await self._run_foreach_node(state, node)
                else:  # pragma: no cover — kinds are closed by the schema
                    await self._fail(
                        state, node_id=node_id, error=f"unknown kind '{node.kind}'."
                    )
                    return
                if state.graph.node_status[node.id] == "failed":
                    return
        finally:
            current_execution_id.reset(exec_token)
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

    # -- M4: team + human nodes ---------------------------------------------------

    async def _run_agent_node(self, state: ExecutionState, node) -> None:
        state.current_node_id = node.id
        state.graph.mark_running(node.id)
        await self._emit_progress(state, node_id=node.id)
        try:
            prompt = render(node.prompt, state.template_scope())
        except TemplateError as exc:
            node_run_id = await self._persist_node_start(state, node.id)
            await self._persist_node_end(node_run_id, status="failed", error=str(exc))
            await self._fail(state, node_id=node.id, error=str(exc))
            return
        output = await self._run_agent_turn(
            state, node, node_id=node.id, prompt=str(prompt), iteration=None
        )
        if output is None:
            return  # _run_agent_turn already failed the execution
        state.node_outputs[node.id] = output
        state.graph.mark_succeeded(node.id)
        state.current_node_id = None

    async def _run_agent_turn(
        self,
        state: ExecutionState,
        node_like,
        *,
        node_id: str,
        prompt: str,
        iteration: int | None,
    ) -> dict | None:
        """One injected lead turn for an agent node (plan §6.4). Returns the
        captured output, or None after failing the execution."""
        team = await self._ensure_team(state)
        if team is None:
            error = "no team could be started for this session."
            node_run_id = await self._persist_node_start(state, node_id, iteration)
            await self._persist_node_end(node_run_id, status="failed", error=error)
            await self._fail(state, node_id=node_id, error=error)
            return None

        # 1. Pre-spawn roster blueprints with no live instance (F5/F6).
        subagents = list(getattr(node_like, "subagents", None) or [])
        try:
            for blueprint in subagents:
                if not team.live_instances_for_blueprint(blueprint):
                    await team.spawn(blueprint)
        except KeyError as exc:
            error = f"roster spawn failed: {exc}"
            node_run_id = await self._persist_node_start(state, node_id, iteration)
            await self._persist_node_end(node_run_id, status="failed", error=error)
            await self._fail(state, node_id=node_id, error=error)
            return None

        # 2. Per-turn allowlist — cleared at capture.
        team.turn_allowed_blueprints = set(subagents)

        # 3. Watermark + in-process handoff listener (F3/F4).
        state.watermark = await self._last_message_created_at(state.session_id)
        state.captured_artifact = None
        state.captured_output = None
        state.captured_failed = False
        state.listener_task = asyncio.create_task(self._listen_for_handoff(state))

        # 4. Inject the turn (F2 recipe via the team method).
        node_run_id = await self._persist_node_start(state, node_id, iteration)
        state.pending_node = node_id
        state.pending_node_run_id = node_run_id
        state.pending_iteration = iteration
        state.awaiting_boundary = True
        state.resume_event = asyncio.Event()
        injected = await team.inject_synthetic_turn(state.session_id, prompt)
        if injected is None:
            state.pending_node = None
            state.awaiting_boundary = False
            error = "turn injection failed."
            await self._persist_node_end(node_run_id, status="failed", error=error)
            await self._fail(state, node_id=node_id, error=error)
            return None
        state.injected_turns += 1

        # 5. Wait for the boundary (capture_cb stores the output, advance_cb
        #    resumes us). Per-node timeout interrupts the team (F9 path).
        timeout = getattr(node_like, "timeout_s", None) or 900
        try:
            await asyncio.wait_for(state.resume_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            team.interrupt_turn()
            error = f"agent node '{node_id}' timed out after {timeout}s."
            await self._persist_node_end(node_run_id, status="failed", error=error)
            await self._fail(state, node_id=node_id, error=error)
            return None
        finally:
            state.awaiting_boundary = False
            if state.listener_task is not None:
                state.listener_task.cancel()
                state.listener_task = None

        if state.stop_requested or state.interrupted or state.captured_failed:
            error = "interrupted."
            await self._persist_node_end(node_run_id, status="failed", error=error)
            if self.active.get(state.session_id) is state:
                await self._finish(state, status="stopped")
            return None
        output = _normalize_agent_output(state.captured_output)
        await self._persist_node_end(node_run_id, status="succeeded", output=output)
        return output

    async def _run_question_node(self, state: ExecutionState, node) -> None:
        """gate + input (plan §6.4): a literal ask_user round trip, no turn."""
        from app.agent.ask_user import (
            AskUserService,
            reset_ask_user_service,
            set_ask_user_service,
        )
        from app.agent.tools.builtin.ask_user import QuestionSpec

        state.current_node_id = node.id
        state.graph.mark_running(node.id)
        node_run_id = await self._persist_node_start(state, node.id)
        try:
            scope = state.template_scope()
            if node.kind == "gate":
                title = str(render(node.title, scope))
                body = str(render(node.body, scope)) if node.body else ""
                question = f"{title}\n\n{body}".strip()
                options = list(node.choices or [])
            else:  # input
                question = str(render(node.question, scope))
                options = []
        except TemplateError as exc:
            await self._persist_node_end(node_run_id, status="failed", error=str(exc))
            await self._fail(state, node_id=node.id, error=str(exc))
            return

        state.status = "waiting_gate"
        # Mirror the pause into the DB row: REST readers (the AIM Pipelines
        # table polls GET /workflows/executions) only see the persisted
        # status, and a gate can stay open for hours.
        await self._persist_execution_status(state)
        await self._emit_progress(state, node_id=node.id)
        svc = AskUserService(state.session_id)
        token = set_ask_user_service(svc)
        # A gate's choices route edges, so its answer must be one of them —
        # enforced at the reply endpoint via ``strict`` (a free-text answer
        # would match no ``when`` edge and silently strand the run).
        strict = node.kind == "gate"
        try:
            answers = await asyncio.wait_for(
                svc.ask(
                    [QuestionSpec(question=question, options=options, strict=strict)]
                ),
                timeout=_GATE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            error = (
                f"{node.kind} '{node.id}' timed out after {_GATE_TIMEOUT_S}s "
                f"with no reply."
            )
            await self._persist_node_end(node_run_id, status="failed", error=error)
            await self._fail(state, node_id=node.id, error=error)
            return
        finally:
            reset_ask_user_service(token, state.session_id)
        state.status = "running"
        await self._persist_execution_status(state)

        answer = answers[0] if answers else ""
        if node.kind == "gate":
            output = {"choice": answer}
            state.node_outputs[node.id] = output
            state.graph.mark_succeeded(node.id, answer=answer)
        else:
            output = {"text": answer}
            state.node_outputs[node.id] = output
            state.graph.mark_succeeded(node.id)
        await self._persist_node_end(node_run_id, status="succeeded", output=output)
        await self._emit_progress(state, node_id=node.id)
        state.current_node_id = None

    async def _run_foreach_node(self, state: ExecutionState, node) -> None:
        """Sequential per-item body run (plan §6.4) — one node-run row per
        iteration; a failing iteration fails the whole node."""
        state.current_node_id = node.id
        state.graph.mark_running(node.id)
        await self._emit_progress(state, node_id=node.id)
        try:
            items = render(node.items, state.template_scope())
        except TemplateError as exc:
            node_run_id = await self._persist_node_start(state, node.id)
            await self._persist_node_end(node_run_id, status="failed", error=str(exc))
            await self._fail(state, node_id=node.id, error=str(exc))
            return
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except json.JSONDecodeError:
                items = None
        if not isinstance(items, list):
            error = f"foreach '{node.id}': items must render to a JSON array."
            node_run_id = await self._persist_node_start(state, node.id)
            await self._persist_node_end(node_run_id, status="failed", error=error)
            await self._fail(state, node_id=node.id, error=error)
            return

        body = node.foreach_body
        outputs: list[dict] = []
        for index, item in enumerate(items):
            if state.stop_requested or state.interrupted:
                await self._finish(state, status="stopped")
                return
            item_scope = state.template_scope({"item": item, "index": index})
            try:
                if body.kind == "tool":
                    node_run_id = await self._persist_node_start(
                        state, node.id, iteration=index
                    )
                    output, _ = await asyncio.wait_for(
                        run_tool_node(
                            body, item_scope, workspace=state.scope_workspace
                        ),
                        timeout=body.timeout_s or 900,
                    )
                    await self._persist_node_end(
                        node_run_id, status="succeeded", output=output
                    )
                elif body.kind == "transform":
                    node_run_id = await self._persist_node_start(
                        state, node.id, iteration=index
                    )
                    output, _ = run_transform_node(body, item_scope)
                    await self._persist_node_end(
                        node_run_id, status="succeeded", output=output
                    )
                elif body.kind == "notify":
                    node_run_id = await self._persist_node_start(
                        state, node.id, iteration=index
                    )
                    output, _ = await run_notify_node(
                        body,
                        item_scope,
                        session_id=state.session_id,
                        workflow_name=state.definition.name,
                    )
                    await self._persist_node_end(
                        node_run_id, status="succeeded", output=output
                    )
                elif body.kind == "agent":
                    prompt = render(body.prompt, item_scope)
                    result = await self._run_agent_turn(
                        state,
                        body,
                        node_id=node.id,
                        prompt=str(prompt),
                        iteration=index,
                    )
                    if result is None:
                        return  # execution already failed/stopped
                    output = result
                else:  # pragma: no cover — schema restricts body kinds
                    raise WorkflowNodeError(f"bad body kind '{body.kind}'")
            except (WorkflowNodeError, TemplateError, asyncio.TimeoutError) as exc:
                error = (
                    f"iteration {index} failed: {exc}"
                    if not isinstance(exc, asyncio.TimeoutError)
                    else f"iteration {index} timed out."
                )
                node_run_id = await self._persist_node_start(
                    state, node.id, iteration=index
                )
                await self._persist_node_end(node_run_id, status="failed", error=error)
                await self._fail(state, node_id=node.id, error=error)
                return
            outputs.append(output)
            state.node_outputs[node.id] = {
                "items": list(outputs),
                "count": len(outputs),
                "partial": True,
            }

        result_output = {"items": outputs, "count": len(outputs), "partial": False}
        state.node_outputs[node.id] = result_output
        state.graph.mark_succeeded(node.id)
        await self._emit_progress(state, node_id=node.id)
        state.current_node_id = None

    # -- turn-boundary hooks (registered via team.set_workflow_hooks) -----------

    async def on_turn_boundary_capture(self, session_id: str) -> None:
        """Hook ① — top of the barrier: capture the pending agent node's
        output before queued user messages can run (plan §6.1)."""
        state = self.active.get(session_id)
        if state is None or state.pending_node is None:
            return
        team = self._find_team(session_id)
        if team is not None:
            team.turn_allowed_blueprints = None
        if state.listener_task is not None:
            state.listener_task.cancel()
            state.listener_task = None
        if state.interrupted:
            state.captured_failed = True
        elif state.captured_artifact is not None:
            state.captured_output = state.captured_artifact
        else:
            text = await self._last_assistant_text_after(session_id, state.watermark)
            state.captured_output = {"text": text or ""}
        state.pending_node = None

    async def on_turn_boundary_advance(self, session_id: str) -> bool:
        """Hook ② — after the queued branch declines: resume the walk. True
        = this boundary is consumed by the workflow."""
        state = self.active.get(session_id)
        if state is None:
            return False
        if not state.awaiting_boundary:
            # The workflow wasn't waiting on this boundary (a user turn ran
            # mid-workflow, or the walk is inside inline nodes/a gate) —
            # let the normal chain emit its DoneEvent.
            return False
        team = self._find_team(session_id)
        if team is not None:
            # Hold the boundary so a user message arriving in the gap
            # queues instead of colliding with the imminent next node.
            team.set_inline_busy(True)
        state.resume_event.set()
        return True

    # -- team + message helpers ---------------------------------------------------

    async def _ensure_team(self, state: ExecutionState):
        """Find (or boot) the live team for this session — work sessions
        via the session team map, coding/aim via the workspace-keyed map
        with the same wiring the chat route uses."""
        from app.services import team_manager

        scope = state.definition.scope
        team = team_manager.find_team_for_session(state.session_id)
        if team is not None:
            # A coding/aim definition must run on a team with that roster —
            # a stray default-mode team bound to this session id (e.g. by an
            # old, pre-fix /commands call) would silently swap the lead.
            if scope == "work" or getattr(team, "mode", scope) == scope:
                return team
            logger.warning(
                "workflow_team_mode_mismatch session_id={} team_mode={} scope={}"
                " — booting the {}-mode team instead",
                state.session_id,
                getattr(team, "mode", None),
                scope,
                scope,
            )
        # Boot by the SESSION's mode, not the definition scope: a work-scope
        # workflow in a coding/aim session must still run on that session's
        # own team (M3: "work runs anywhere" means anywhere, with the
        # session's lead). For coding/aim scopes the run endpoint already
        # guaranteed session.mode == scope and a bound workspace.
        session_mode, session_workspace = await self._session_mode_workspace(state)
        try:
            if session_mode in ("coding", "aim") and session_workspace:
                extra_paths: list[str] = []
                read_only: list[str] = []
                if session_mode == "aim":
                    extra_paths, read_only = await self._aim_session_paths(state)
                return await team_manager.get_or_start_coding_team(
                    session_workspace,
                    state.session_id,
                    extra_workspace_paths=extra_paths or None,
                    mode=session_mode,
                    read_only_paths=read_only or None,
                )
            if scope != "work":
                # coding/aim definition but the session lost its
                # mode/workspace — refuse rather than run on the wrong team.
                return None
            team = await team_manager.get_or_start_team_for_session(state.session_id)
            if team is not None:
                team.workspace = session_workspace
            return team
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_team_boot_failed error={}", exc)
            return None

    async def _session_mode_workspace(
        self, state: ExecutionState
    ) -> tuple[str | None, str | None]:
        """(mode, workspace) of the session row, with the definition scope /
        scope_workspace as fallback when the row can't be read."""
        from app.core import db as db_module
        from app.models.chat import ChatSession, normalize_mode

        try:
            async with db_module.async_session_factory() as db:
                session = await db.get(ChatSession, UUID(state.session_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_session_lookup_failed error={}", exc)
            session = None
        if session is None:
            return state.definition.scope, state.scope_workspace
        mode = normalize_mode(session.mode)
        if mode == "work":
            # A NULL Work workspace is an explicit reset to the generated
            # session sandbox, not a reason to resurrect the workflow's stale
            # launch-time folder.
            return mode, session.workspace
        return mode, session.workspace or state.scope_workspace

    async def _aim_session_paths(
        self, state: ExecutionState
    ) -> tuple[list[str], list[str]]:
        """extra_workspace_paths + read_only_paths for an aim session — the
        same resolution the chat dispatch does (source read-only, source+kb
        ride along)."""
        from app.core import db as db_module
        from app.models.chat import ChatSession
        from app.services.coding_project_service import get_project
        from app.services.aim.project import (
            resolve_kb_workspace_path,
            resolve_source_workspace_paths,
        )

        try:
            async with db_module.async_session_factory() as db:
                session = await db.get(ChatSession, UUID(state.session_id))
                if session is None or session.project_id is None:
                    return [], []
                project = await get_project(db, session.project_id)
                if project is None:
                    return [], []
                sources = await resolve_source_workspace_paths(db, project)
                kb = await resolve_kb_workspace_path(db, project)
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_aim_paths_failed error={}", exc)
            return [], []
        extra = [p for p in [*sources, kb] if p]
        return extra, list(sources)

    async def _last_message_created_at(self, session_id: str) -> str | None:
        from sqlmodel import col, select

        from app.core import db as db_module
        from app.models.chat import SessionMessage

        try:
            async with db_module.async_session_factory() as db:
                row = (
                    await db.exec(
                        select(SessionMessage)
                        .where(col(SessionMessage.session_id) == UUID(session_id))
                        .order_by(col(SessionMessage.created_at).desc())
                        .limit(1)
                    )
                ).first()
                return row.created_at.isoformat() if row is not None else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_watermark_failed error={}", exc)
            return None

    async def _last_assistant_text_after(
        self, session_id: str, watermark: str | None
    ) -> str | None:
        from datetime import datetime as dt

        from sqlmodel import col, select

        from app.core import db as db_module
        from app.models.chat import SessionMessage

        try:
            async with db_module.async_session_factory() as db:
                query = (
                    select(SessionMessage)
                    .where(col(SessionMessage.session_id) == UUID(session_id))
                    .where(col(SessionMessage.role) == "assistant")
                    .order_by(col(SessionMessage.created_at).desc())
                    .limit(20)
                )
                rows = (await db.exec(query)).all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_capture_query_failed error={}", exc)
            return None
        boundary = dt.fromisoformat(watermark) if watermark else None
        for row in rows:
            if boundary is not None and row.created_at <= boundary:
                continue
            if row.content and row.content.strip():
                return row.content
        return None

    async def _listen_for_handoff(self, state: ExecutionState) -> None:
        """Best-effort structured-output capture (F4): watch the session's
        SSE stream for handoff events while the agent turn runs."""
        from app.services import memory_stream_store as stream_store

        try:
            async for event in stream_store.attach(state.session_id):
                if event.get("event") != "handoff":
                    continue
                try:
                    data = json.loads(event.get("data") or "{}")
                except json.JSONDecodeError:
                    continue
                artifact = data.get("artifact")
                if isinstance(artifact, dict):
                    state.captured_artifact = artifact
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — optimization only
            logger.debug("workflow_handoff_listener_stopped error={}", exc)

    # -- terminal transitions ---------------------------------------------------
    async def _complete(self, state: ExecutionState) -> None:
        outputs: dict[str, Any] = {}
        for key, template in state.definition.outputs.items():
            try:
                outputs[key] = render(template, state.template_scope())
            except TemplateError as exc:
                # Outputs referencing skipped branches are omitted independently;
                # resolvable keys remain available to callers.
                logger.debug(
                    "workflow_output_omitted execution={} key={} error={}",
                    state.execution_id,
                    key,
                    exc,
                )
        state.status = "completed"
        await self._stop_claim_heartbeat(state)
        await self._release_execution_claims(state.execution_id)
        await self._persist_execution_end(state, outputs=outputs)
        await self._emit_progress(state, node_id=None)
        self.active.pop(state.session_id, None)
        await self._emit_done_if_owned(state)

    async def _fail(
        self, state: ExecutionState, *, node_id: str | None, error: str
    ) -> None:
        if node_id is not None:
            state.graph.mark_failed(node_id)
        state.status = "failed"
        state.error = error
        await self._stop_claim_heartbeat(state)
        await self._release_execution_claims(state.execution_id)
        partial_outputs = (
            {"partial_nodes": state.node_outputs} if state.node_outputs else None
        )
        await self._persist_execution_end(state, outputs=partial_outputs, error=error)
        await self._emit_progress(state, node_id=node_id, error=error)
        self.active.pop(state.session_id, None)
        await self._emit_done_if_owned(state)

    async def _finish(self, state: ExecutionState, *, status: str) -> None:
        if self.active.get(state.session_id) is not state:
            return  # already finalised
        state.status = status
        await self._stop_claim_heartbeat(state)
        await self._release_execution_claims(state.execution_id)
        await self._persist_execution_end(state)
        await self._emit_progress(state, node_id=state.current_node_id)
        self.active.pop(state.session_id, None)
        team = self._find_team(state.session_id)
        if team is not None:
            team.set_inline_busy(False)
        await self._emit_done_if_owned(state)

    async def _release_execution_claims(self, execution_id: UUID) -> None:
        from sqlmodel import select

        from app.core import db as db_module
        from app.models.aim import AimClaim

        try:
            async with db_module.async_session_factory() as db:
                claims = (
                    await db.exec(
                        select(AimClaim).where(
                            AimClaim.workflow_execution_id == execution_id
                        )
                    )
                ).all()
                for claim in claims:
                    await db.delete(claim)
                if claims:
                    await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "workflow_claim_cleanup_failed execution={} error={}",
                execution_id,
                exc,
            )

    async def _claim_heartbeat_loop(self, state: ExecutionState) -> None:
        while self.active.get(state.session_id) is state:
            try:
                await self._renew_execution_claims(state.execution_id)
            except Exception as exc:  # noqa: BLE001 — retry on next heartbeat
                logger.warning(
                    "workflow_claim_heartbeat_failed execution={} error={}",
                    state.execution_id,
                    exc,
                )
            await asyncio.sleep(_CLAIM_HEARTBEAT_S)

    async def _renew_execution_claims(self, execution_id: UUID) -> int:
        from sqlmodel import select

        from app.core import db as db_module
        from app.models.aim import AimClaim

        async with db_module.async_session_factory() as db:
            claims = (
                await db.exec(
                    select(AimClaim).where(
                        AimClaim.workflow_execution_id == execution_id
                    )
                )
            ).all()
            if not claims:
                return 0
            expires_at = _utcnow() + _CLAIM_HEARTBEAT_LEASE
            for claim in claims:
                claim.lease_expires_at = expires_at
                db.add(claim)
            await db.commit()
            return len(claims)

    async def _stop_claim_heartbeat(self, state: ExecutionState) -> None:
        task = state.claim_heartbeat_task
        state.claim_heartbeat_task = None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # -- side channels ------------------------------------------------------------
    @staticmethod
    def _find_team(session_id: str):
        from app.services import team_manager

        return team_manager.find_team_for_session(session_id)

    async def _emit_done_if_owned(self, state: ExecutionState) -> None:
        """Close the SSE turn at workflow end. Owed only when this execution
        injected turns — the boundary DoneEvents of those turns were
        consumed by advance, so the stream is still open."""
        if state.injected_turns <= 0:
            return
        try:
            from app.agent.schemas.events import DoneEvent
            from app.services import memory_stream_store as stream_store
            from app.services.stream_envelope import StreamEnvelope

            await stream_store.push_event(
                state.session_id, StreamEnvelope.from_event(DoneEvent())
            )
            await stream_store.mark_done(state.session_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("workflow_done_emit_failed error={}", exc)

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
                        inputs=state.inputs,
                        retry_of_execution_id=state.retry_of_execution_id,
                    )
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow_execution_persist_failed error={}", exc)

    async def _persist_execution_status(self, state: ExecutionState) -> None:
        """Best-effort mid-run status mirror (running ⇄ waiting_gate) so REST
        readers see a paused gate without the in-memory runner state."""
        from app.core import db as db_module
        from app.models.workflow import WorkflowExecution

        try:
            async with db_module.async_session_factory() as db:
                row = await db.get(WorkflowExecution, state.execution_id)
                if row is not None:
                    row.status = state.status
                    db.add(row)
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


async def reconcile_orphaned_executions() -> int:
    """Mark executions the in-memory runner can no longer drive as failed.

    The runner holds all live state in memory (one :class:`ExecutionState`
    per session); a crash or restart loses it. Any ``workflow_executions``
    row still in ``running``/``waiting_gate`` at boot is therefore orphaned:
    its :class:`~app.agent.ask_user.AskUserService` is gone, so a paused gate
    can never be answered and the REST run table would show it live forever.
    Called once from the app lifespan. Returns the number of rows reconciled.
    """
    from sqlmodel import col, select

    from app.core import db as db_module
    from app.models.aim import AimClaim
    from app.models.workflow import WorkflowExecution, WorkflowNodeRun

    reconciled = 0
    try:
        async with db_module.async_session_factory() as db:
            rows = (
                await db.exec(
                    select(WorkflowExecution).where(
                        col(WorkflowExecution.status).in_(("running", "waiting_gate"))
                    )
                )
            ).all()
            for row in rows:
                row.status = "failed"
                row.error = "interrupted by a server restart"
                row.ended_at = _utcnow()
                db.add(row)
                node_rows = (
                    await db.exec(
                        select(WorkflowNodeRun).where(
                            WorkflowNodeRun.execution_id == row.id,
                            WorkflowNodeRun.status == "running",
                        )
                    )
                ).all()
                for node_row in node_rows:
                    node_row.status = "failed"
                    node_row.error = "interrupted by a server restart"
                    node_row.ended_at = _utcnow()
                    db.add(node_row)
                claim_rows = (
                    await db.exec(
                        select(AimClaim).where(AimClaim.workflow_execution_id == row.id)
                    )
                ).all()
                for claim_row in claim_rows:
                    await db.delete(claim_row)
                reconciled += 1
            if reconciled:
                await db.commit()
    except Exception as exc:  # noqa: BLE001 — never block startup
        logger.warning("workflow_reconcile_failed error={}", exc)
        return 0
    if reconciled:
        logger.info("workflow_executions_reconciled count={}", reconciled)
    return reconciled
