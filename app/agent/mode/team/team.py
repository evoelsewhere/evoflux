"""AgentTeam — coordinates a team lead + members via mailbox activation.

Members are not built at startup; they exist as **blueprints** on the team
and are constructed on demand by ``team_delegate`` or explicitly through
``team_manage`` (see :meth:`AgentTeam.spawn`). Each spawn yields a handle of the form
``blueprint#N`` so the lead can run multiple parallel instances of the same
blueprint (e.g. ``executor#1`` and ``executor#2`` working in parallel) and
each instance has its own DB session / chat history.

Agents do **not** run persistent background loops.  Instead, ``register``
attaches an agent to the mailbox and installs an ``on_message`` callback
that activates the receiving agent on demand.

Streaming to the frontend uses the in-memory stream store: lifecycle events
(agent_status, done) are pushed to the same stream key as the LLM deltas,
so the frontend receives one unified event feed per session.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID, uuid7  # ty: ignore[unresolved-import] - backported in app.__init__

from loguru import logger
from sqlmodel import col, select

from app.agent.hooks.continuation import CONTINUATION_DIRECTIVE
from app.agent.hooks.goal import GOAL_CONTINUATION_DIRECTIVE
from app.agent.goal_status import publish_goal_status
from app.agent.mode.team.mailbox import Message, TeamMailbox
from app.agent.mode.team.member import (
    AlreadyWorkingError,
    TeamLead,
    TeamMember,
    TeamMemberBase,
)
from app.agent.mode.team.delegate import make_team_delegate_tool
from app.agent.mode.team.handoff import make_team_handoff_tool
from app.agent.mode.team.manage import make_team_manage_tool
from app.agent.mode.team.reject import make_team_reject_tool
from app.agent.mode.team.shared_state import make_team_state_tool
from app.agent.mode.team.tools import make_team_message_tool
from app.agent.mode.team.worktree import make_team_worktree_tool
from app.agent.easd import (
    EasdContext,
    make_easd_plan_tool,
    make_easd_review_tool,
    make_easd_spec_tool,
)
from app.agent.multimodal import build_parts_from_metas
from app.agent.schemas.chat import AssistantMessage, HumanMessage, ToolMessage
from app.agent.schemas.events import DoneEvent
from app.agent.tools.registry import Tool
from app.core.db import DbFactory, resolve_db_factory
from app.core.app_mode import parse_app_mode
from app.core.paths import session_workspace_dir
from app.models.chat import ChatSession, SessionMessage
from app.models.goal import SessionGoal
from app.models.team import DelegationTask
from app.services import memory_stream_store as stream_store
from app.services import snapshot_service
from app.services.commands import parse_slash_invocation
from app.services.stream_envelope import StreamEnvelope
from app.services.chat_service import (
    BoundaryShift,
    get_messages_for_llm,
    heal_orphaned_tool_calls,
    mark_channel_source_delivered,
    pop_queued_user_messages,
    redo_session_messages,
    save_message,
    undo_session_messages,
)

if TYPE_CHECKING:
    from app.agent.providers.factory import ProviderFactory


@dataclass(frozen=True)
class GoalCommand:
    action: Literal["start", "status", "pause", "resume", "budget", "stop"]
    objective: str | None = None
    token_budget: int | None = None


def parse_goal_command(content: str) -> GoalCommand | None:
    """Parse the durable ``/goal`` command namespace.

    Supported forms are ``/goal <objective>``, bare ``/goal`` for status,
    and ``/goal:pause|resume|stop|budget`` controls. ``/goal:set`` is
    intentionally not an alias: replacing a goal is always explicit through
    the objective form.
    """

    invocation = parse_slash_invocation(content)
    if invocation is None or invocation.command != "goal":
        return None

    if invocation.subcommand is None:
        objective = invocation.arguments.strip()
        if not objective:
            return GoalCommand(action="status")
        return GoalCommand(action="start", objective=objective)

    if invocation.subcommand in {"status", "pause", "resume", "stop"}:
        if invocation.argv:
            return None
        action = cast(
            Literal["status", "pause", "resume", "stop"],
            invocation.subcommand,
        )
        return GoalCommand(action=action)

    if invocation.subcommand != "budget" or len(invocation.argv) != 1:
        return None
    raw_budget = invocation.argv[0].casefold()
    if raw_budget in {"none", "unlimited"}:
        return GoalCommand(action="budget", token_budget=None)
    if not raw_budget.isdigit() or int(raw_budget) <= 0:
        return None
    return GoalCommand(action="budget", token_budget=int(raw_budget))


def is_goal_command(content: str) -> bool:
    invocation = parse_slash_invocation(content)
    return invocation is not None and invocation.command == "goal"


# ---------------------------------------------------------------------------
# Blueprint registry
# ---------------------------------------------------------------------------


@dataclass
class MemberBlueprint:
    """A member ``.md`` file the lead can spawn instances from.

    Construction is deferred — the team holds blueprint metadata + the
    factories needed to build an Agent, and ``AgentTeam.spawn`` does the
    actual construction.
    """

    name: str  # blueprint name (matches the ``.md`` ``name:`` field)
    description: str
    source_path: Path
    # Monotonic per-blueprint counter — bumped each time an instance is
    # spawned in this process.  Spawning seeds it from the DB on first use
    # so it survives restarts (see AgentTeam._next_instance_id).
    next_instance_id: int = 1
    # ``True`` once spawn() has reconciled the counter against existing DB
    # sessions for the *current* lead session.  Reset when the lead session
    # changes so a fresh chat starts the counter at #1 again.
    counter_reconciled_for: str | None = field(default=None)


@dataclass(frozen=True)
class SpawnRuntimeConfig:
    """User-confirmed model configuration for one materialized member."""

    model: str
    thinking_level: str | None


class SpawnCancelledError(ValueError):
    """Raised when the user declines an interactive member spawn."""


# ---------------------------------------------------------------------------
# Instance handle parsing
# ---------------------------------------------------------------------------


_INSTANCE_HANDLE_RE = re.compile(r"^(?P<blueprint>[^#]+)#(?P<n>\d+)$")


def parse_instance_handle(handle: str) -> tuple[str, int] | None:
    """Parse ``blueprint#N`` into ``(blueprint, N)``.  Return ``None`` on miss."""
    m = _INSTANCE_HANDLE_RE.match(handle)
    if not m:
        return None
    return m.group("blueprint"), int(m.group("n"))


def make_instance_handle(blueprint: str, n: int) -> str:
    """Format an instance handle from a blueprint name + counter."""
    return f"{blueprint}#{n}"


class ContinuePreconditionError(Exception):
    """Raised when ``/continue`` is requested on a session that can't be continued.

    Carries a ``reason`` (human-readable, surfaced to the user) and an HTTP
    ``status`` so the route layer can map straight to a response.  All
    precondition failures use 409 (Conflict) — the session exists but is in
    a state where continuation is not meaningful.
    """

    def __init__(self, reason: str, *, status: int = 409) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


_command_locks: dict[str, asyncio.Lock] = {}


def _command_lock(session_id: str) -> asyncio.Lock:
    """Return the (lazily-created) per-session command lock."""
    lock = _command_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _command_locks[session_id] = lock
    return lock


def _is_interrupted_thinking_only_tail(messages: list) -> bool:
    """Return true for a stopped assistant row that has no visible output."""
    if not messages:
        return False
    last = messages[-1]
    return (
        isinstance(last, AssistantMessage)
        and not (last.content and last.content.strip())
        and not last.tool_calls
        and bool(last.extra and last.extra.get("interrupted"))
    )


def _tool_tail_has_matching_assistant_call(messages: list) -> bool:
    """A trailing tool result is continuable only if a prior assistant called it."""
    if not messages or not isinstance(messages[-1], ToolMessage):
        return False
    tool_call_id = messages[-1].tool_call_id
    if not tool_call_id:
        return False
    for msg in reversed(messages[:-1]):
        if not isinstance(msg, AssistantMessage):
            continue
        return any(tc.id == tool_call_id for tc in msg.tool_calls or [])
    return False


def _is_hidden_continuation_directive(message: object) -> bool:
    """Return true for the internal /continue directive row."""
    return (
        isinstance(message, HumanMessage)
        and message.content == CONTINUATION_DIRECTIVE
        and bool(message.extra and message.extra.get("command") == "continue")
        and bool(message.extra and message.extra.get("hidden_from_user"))
    )


# ── Workflow hooks (plan v5 §6.1) ────────────────────────────────────────────
# Registered from app startup via set_workflow_hooks to avoid a circular
# import between team.py and app.workflow.runner. Both are optional; when
# unset the turn-completion chain behaves exactly as before.
#
# capture_cb(session_id): runs unconditionally at the top of the barrier —
#   if a workflow agent-node turn was in flight, capture its output NOW so
#   a queued user message can never be mis-captured as node output.
# advance_cb(session_id) -> bool: runs after the queued-message branch
#   declines; True = an active execution consumed this boundary (the chain
#   stops; the runner drives on), False = fall through to Goal/DoneEvent.
_workflow_capture_cb = None
_workflow_advance_cb = None


def set_workflow_hooks(capture_cb, advance_cb) -> None:
    global _workflow_capture_cb, _workflow_advance_cb
    _workflow_capture_cb = capture_cb
    _workflow_advance_cb = advance_cb


class AgentTeam:
    """Singleton team: one lead, N member blueprints, dynamic instance roster.

    Lifecycle::

        team = AgentTeam(lead=lead, blueprints={...}, ...)
        await team.start()   # registers lead with mailbox; members stay un-built
        ...
        await team.stop()    # cancels active tasks, deregisters all instances

    Spawn / dismiss::

        instance = await team.spawn("executor")          # → executor#1
        instance = await team.spawn("executor")          # → executor#2
        await team.dismiss("executor#1")                 # frees the agent
        instance = await team.spawn("executor", instance_id=1)  # restore #1

    Handling a user message::

        session_id = await team.handle_user_message(content="...", session_id="...")
        # client subscribes to GET /team/{session_id}/stream
    """

    def __init__(
        self,
        lead: TeamLead,
        blueprints: dict[str, "MemberBlueprint"] | None = None,
        *,
        provider_factory: "ProviderFactory | None" = None,
        extra_tools: dict[str, Tool] | None = None,
        db_factory: DbFactory | None = None,
        mode: str = "work",
        workspace: str | None = None,
        permission_mode: str = "auto",
        extra_workspace_paths: list[str] | None = None,
        # Session tags persisted on the ChatSession row (e.g. {"webbridge"}).
        # Restored onto the in-memory team by the chat routes on every
        # request (same pattern as permission_mode) so a cold team boot after
        # a server restart still enforces tag-based tool scoping — see
        # member.py's excluded_tools computation for the "webbridge" tag.
        session_tags: frozenset[str] | None = None,
        # Paths the team's filesystem tools must never write to, even
        # though they may sit in extra_workspace_paths. Threaded into
        # SandboxConfig.read_only_paths (app/agent/sandbox.py) the same way
        # extra_workspace_paths already is.
        read_only_paths: list[str] | None = None,
        # Back-compat: callers (especially older tests) can still pass a
        # pre-built members map.  These instances are registered as if they
        # were spawned by name; their handles stay verbatim (no ``#1``
        # suffix is added) so existing tests keep passing.
        members: dict[str, "TeamMember"] | None = None,
    ) -> None:
        self.lead = lead
        self.blueprints: dict[str, MemberBlueprint] = blueprints or {}
        self.members: dict[str, TeamMember] = dict(members or {})

        self._provider_factory = provider_factory
        self._extra_tools = extra_tools
        self._db_factory = db_factory
        self.mode = parse_app_mode(mode).value
        self.workspace = workspace
        self.permission_mode = permission_mode
        self.session_tags: frozenset[str] = session_tags or frozenset()
        self.extra_workspace_paths: list[str] = extra_workspace_paths or []
        self.read_only_paths: list[str] = read_only_paths or []

        self.mailbox = TeamMailbox(on_message=self._on_message)

        # Guard: only emit done after at least one user turn has started
        self._has_active_turn: bool = False
        # Workflow-node roster allowlist (plan v5 §6.4 step 2): while an
        # agent node's turn is in flight, delegation/spawn is limited to
        # that node's declared subagents. None = no restriction (normal
        # turns). Set/cleared by the workflow runner.
        self.turn_allowed_blueprints: set[str] | None = None

        # Delegator name -> {task_id: recipient} for durable delegation rows
        # whose status is blocked/pending. The DB is the source of truth; this
        # projection keeps the lead's wait-nudge path synchronous and cheap.
        # Used to catch a delegator (in practice, the lead) answering the user
        # on its own before delegated work actually reports back — see
        # TeamMemberBase._maybe_inject_delegation_wait_nudge.
        self._pending_delegations: dict[str, dict[str, str]] = {}
        self._dispatching_delegations: set[str] = set()
        self._dispatching_handoffs: set[str] = set()
        self._ephemeral_delegation_ids: set[str] = set()
        self._resolved_ephemeral_delegations: dict[tuple[str, str], str] = {}

        # Index agents by name for fast lookup in on_message.  Kept in sync
        # by spawn() / dismiss().
        self._members_by_name: dict[str, TeamMemberBase] = {lead.name: lead}
        for name, m in self.members.items():
            self._members_by_name[name] = m

        # Serialise spawn / dismiss against each other.  The mailbox + DB
        # work is short, but two concurrent roster-management calls from the
        # same lead turn could otherwise race the counter.
        self._roster_lock = asyncio.Lock()

        # Serialise task-ledger state transitions and replay decisions. This
        # prevents duplicate dispatch when a handoff releases dependencies at
        # the same time as a session/member restore.
        self._delegation_lock = asyncio.Lock()

        # Serialise user ingress so quick follow-ups queue behind the active
        # turn instead of racing in as adjacent normal user rows.
        self._user_message_lock = asyncio.Lock()
        # Runtime-owned source context copied into every delegation contract.
        self._current_user_request: str | None = None

    @property
    def user_message_lock(self) -> asyncio.Lock:
        """Lock that serialises route-level user message dispatch decisions."""
        return self._user_message_lock

    def has_active_user_turn(self) -> bool:
        """Return whether a user turn is active or the lead is already running."""
        return self._has_active_turn or self.lead.state == "working"

    def current_user_request_for_delegation(self) -> str | None:
        """Return a bounded copy of the active turn's original user request."""
        if not self._current_user_request:
            return None
        limit = 8_000
        value = self._current_user_request.strip()
        if len(value) <= limit:
            return value
        return value[:limit].rstrip() + "\n[truncated by team runtime]"

    def reserve_user_turn(self) -> None:
        """Reserve the ingress slot before deferred turn preparation starts.

        The HTTP chat route may return as soon as preparation has been scheduled.
        Raising the flag synchronously keeps a second quick send on the queued
        path instead of letting it race the still-pending snapshot/persist work.
        """
        self._has_active_turn = True

    def release_user_turn_reservation(self) -> None:
        """Release a deferred ingress reservation that failed before activation."""
        if self.lead.state != "working":
            self._has_active_turn = False

    def set_inline_busy(self, busy: bool) -> None:
        """Workflow-runner accessor (plan v5 §6.1): while the runner executes
        inline nodes (tool/gate/switch/...) there is no team turn, but user
        messages must still queue rather than splice in — so the runner
        raises the same busy flag a turn would, and lowers it before handing
        the boundary back."""
        self._has_active_turn = busy

    def register_delegation(
        self,
        delegator: str,
        recipients: list[str],
        *,
        task_ids: list[str] | None = None,
    ) -> list[str]:
        """Cache tasks that *delegator* is awaiting final handoffs for.

        ``task_ids`` comes from the durable ledger. When omitted, UUIDs are
        generated for compatibility with tests and callers that only exercise
        the in-memory coordination contract.
        """
        if not recipients:
            return []
        generated = task_ids is None
        ids = task_ids or [str(uuid7()) for _ in recipients]
        if len(ids) != len(recipients):
            raise ValueError("task_ids must match recipients one-for-one.")
        pending = self._pending_delegations.setdefault(delegator, {})
        for task_id, recipient in zip(ids, recipients):
            pending[task_id] = recipient
            if generated:
                self._ephemeral_delegation_ids.add(task_id)
        return ids

    def resolve_delegation(
        self,
        delegator: str,
        recipient: str,
        *,
        task_id: str | None = None,
    ) -> bool:
        """Remove exactly one completed task from the in-memory projection.

        Recipient-only resolution remains supported when exactly one matching
        task is open. Ambiguous resolution is rejected instead of silently
        clearing multiple assignments to the same member.
        """
        pending = self._pending_delegations.get(delegator)
        if not pending:
            return False
        if task_id is None:
            matches = [tid for tid, target in pending.items() if target == recipient]
            if len(matches) != 1:
                return False
            task_id = matches[0]
        elif pending.get(task_id) != recipient:
            return False
        pending.pop(task_id, None)
        if task_id in self._ephemeral_delegation_ids:
            self._ephemeral_delegation_ids.discard(task_id)
            self._resolved_ephemeral_delegations[(delegator, recipient)] = task_id
        if not pending:
            self._pending_delegations.pop(delegator, None)
        self._dispatching_delegations.discard(task_id)
        return True

    def pending_delegation_recipients(self, delegator: str) -> set[str]:
        """Return the recipients *delegator* is still awaiting a handoff from."""
        return set(self._pending_delegations.get(delegator, {}).values())

    def pending_delegation_task_ids(
        self, delegator: str, recipient: str | None = None
    ) -> list[str]:
        pending = self._pending_delegations.get(delegator, {})
        return [
            task_id
            for task_id, target in pending.items()
            if recipient is None or target == recipient
        ]

    async def create_delegation_tasks(
        self,
        *,
        delegator: str,
        recipients: list[str],
        spec: dict,
        dependencies: list[str],
        deadline_at: datetime | None,
    ) -> list[DelegationTask]:
        """Persist one task per recipient and cache their open identities."""
        from app.agent.mode.team import delegation_ledger

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with self._delegation_lock:
            async with db_factory() as db:
                trace_context = None
                trace_run_id = None
                if spec.get("trace_run_id"):
                    from app.services.trace_service import validate_mission_binding

                    trace_context = await validate_mission_binding(
                        db,
                        run_id=str(spec.get("trace_run_id")),
                        spec_hash=str(spec.get("trace_spec_hash") or ""),
                        plan_hash=(
                            str(spec["trace_plan_hash"])
                            if spec.get("trace_plan_hash")
                            else None
                        ),
                        plan_mission_id=(
                            str(spec["plan_mission_id"])
                            if spec.get("plan_mission_id")
                            else None
                        ),
                        criterion_ids=[
                            str(item)
                            for item in spec.get("acceptance_criteria", [])
                            if isinstance(item, str)
                        ],
                        target_paths=[
                            str(item)
                            for item in spec.get("target_paths", [])
                            if isinstance(item, str)
                        ],
                        target_repositories=[
                            str(item)
                            for item in spec.get("target_repos", [])
                            if isinstance(item, str)
                        ],
                    )
                    trace_run_id = trace_context.run.id
                    spec = {
                        **spec,
                        "_easd_owner_workspace": trace_context.run.workspace,
                    }
                tasks = await delegation_ledger.create_tasks(
                    db,
                    lead_session_id=lead_session_id,
                    delegator=delegator,
                    recipients=recipients,
                    spec=spec,
                    dependencies=dependencies,
                    deadline_at=deadline_at,
                    trace_run_id=trace_run_id,
                )
                await db.commit()
            if trace_context is not None:
                from app.services.trace_service import record_mission_binding

                record_mission_binding(trace_context, missions=tasks)
            self.register_delegation(
                delegator,
                [task.recipient for task in tasks],
                task_ids=[str(task.id) for task in tasks],
            )
        return tasks

    async def _ensure_delegation_worktree(self, task: DelegationTask) -> DelegationTask:
        """Allocate and durably bind an isolated pending task before dispatch."""
        if task.spec.get("resolved_isolation") != "worktree":
            return task
        from app.agent.mode.team import delegation_ledger
        from app.services import delegation_worktree_service

        allocation = delegation_worktree_service.allocation_from_spec(task.spec)
        if allocation is not None:
            return task
        allocation = await delegation_worktree_service.allocate(
            task_id=str(task.id),
            recipient=task.recipient,
            session_id=self.lead.session_id,
            primary_workspace=self.workspace or "",
            extra_workspace_paths=self.extra_workspace_paths,
            read_only_paths=self.read_only_paths,
            spec=task.spec,
        )
        spec = dict(task.spec)
        spec["worktree_allocation"] = allocation
        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        try:
            async with self._delegation_lock:
                async with db_factory() as db:
                    task = await delegation_ledger.update_task_spec(
                        db,
                        lead_session_id=lead_session_id,
                        task_id=str(task.id),
                        spec=spec,
                    )
                    await db.commit()
        except Exception:
            await delegation_worktree_service.discard(allocation)
            raise
        return task

    async def fail_delegation_task(self, task: DelegationTask, error: str) -> None:
        from app.agent.mode.team import delegation_ledger

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with self._delegation_lock:
            async with db_factory() as db:
                failed = await delegation_ledger.fail_task(
                    db,
                    lead_session_id=lead_session_id,
                    task_id=str(task.id),
                    error=error,
                )
                (
                    ready,
                    dependency_failures,
                ) = await delegation_ledger.release_ready_tasks(
                    db,
                    lead_session_id=lead_session_id,
                    live_recipients=set(self.mailbox.registered_agents),
                )
                await db.commit()
            self.resolve_delegation(
                failed.delegator, failed.recipient, task_id=str(failed.id)
            )
            for row in ready:
                self.register_delegation(
                    row.delegator, [row.recipient], task_ids=[str(row.id)]
                )
            for row in dependency_failures:
                self.resolve_delegation(
                    row.delegator, row.recipient, task_id=str(row.id)
                )
        await self.dispatch_delegation_tasks(ready)

    async def refresh_delegations(self, *, dispatch: bool = True) -> None:
        """Rehydrate open tasks, restore recipients, and optionally replay work."""
        try:
            lead_session_id = UUID(self.lead.session_id)
        except (TypeError, ValueError):
            return
        try:
            tasks, handoffs = await self._load_reconciled_delegations(lead_session_id)
            if await self._restore_delegation_recipients(tasks):
                tasks, handoffs = await self._load_reconciled_delegations(
                    lead_session_id
                )

            self._pending_delegations.clear()
            self._dispatching_delegations.clear()
            self._dispatching_handoffs.clear()
            for task in tasks:
                self.register_delegation(
                    task.delegator,
                    [task.recipient],
                    task_ids=[str(task.id)],
                )
            if dispatch:
                await self.dispatch_recovered_coordination(handoffs=handoffs)
        except Exception as exc:
            logger.warning(
                "team_delegation_restore_failed session_id={} error={}",
                lead_session_id,
                exc,
            )

    async def _load_reconciled_delegations(
        self, lead_session_id: UUID
    ) -> tuple[list[DelegationTask], list[DelegationTask]]:
        from app.agent.mode.team import delegation_ledger

        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with self._delegation_lock:
            async with db_factory() as db:
                await delegation_ledger.expire_overdue_tasks(db, lead_session_id)
                await delegation_ledger.release_ready_tasks(
                    db,
                    lead_session_id=lead_session_id,
                    live_recipients=set(self.mailbox.registered_agents),
                )
                tasks = await delegation_ledger.load_open_tasks(db, lead_session_id)
                handoffs = await delegation_ledger.load_unacknowledged_handoffs(
                    db,
                    lead_session_id=lead_session_id,
                    live_recipients=set(self.mailbox.registered_agents),
                )
                await db.commit()
        return tasks, handoffs

    async def _restore_delegation_recipients(self, tasks: list[DelegationTask]) -> bool:
        """Materialise missing ``blueprint#N`` recipients from open task rows."""
        restored = False
        for recipient in sorted({task.recipient for task in tasks}):
            if recipient in self.mailbox.registered_agents:
                continue
            parsed = parse_instance_handle(recipient)
            if parsed is None or parsed[0] not in self.blueprints:
                continue
            try:
                await self.spawn(
                    parsed[0],
                    instance_id=parsed[1],
                    _refresh_delegations=False,
                )
            except ValueError as exc:
                if "already live" not in str(exc):
                    logger.warning(
                        "delegation_recipient_restore_failed recipient={} error={}",
                        recipient,
                        exc,
                    )
            except Exception as exc:
                logger.warning(
                    "delegation_recipient_restore_failed recipient={} error={}",
                    recipient,
                    exc,
                )
            else:
                restored = True
        return restored

    async def dispatch_recovered_coordination(
        self, *, handoffs: list[DelegationTask] | None = None
    ) -> None:
        """Best-effort ordered replay after a turn/session boundary is ready."""
        try:
            await self.dispatch_undelivered_delegations()
            await self.dispatch_unacknowledged_handoffs(handoffs)
        except Exception as exc:
            logger.warning("delegation_replay_failed error={}", exc)

    async def dispatch_delegation_tasks(self, tasks: list[DelegationTask]) -> None:
        """Send pending, unacknowledged task rows through the live mailbox."""
        from app.agent.mode.team.delegate import format_delegation_message
        from app.agent.mode.team.reject import format_rejection_message

        for task in tasks:
            task_id = str(task.id)
            if task.status != "pending" or task_id in self._dispatching_delegations:
                continue
            if task.recipient not in self.mailbox.registered_agents:
                continue
            self._dispatching_delegations.add(task_id)
            try:
                task = await self._ensure_delegation_worktree(task)
            except Exception as exc:
                self._dispatching_delegations.discard(task_id)
                await self.fail_delegation_task(task, str(exc))
                raise
            if task.last_rejection:
                content = format_rejection_message(
                    task.delegator,
                    task_id,
                    task.last_rejection,
                    attempt=task.attempt,
                )
                extra = {
                    "kind": "rejection",
                    "task_id": task_id,
                    "_rejection_feedback": task.last_rejection,
                    "_task_spec": task.spec,
                }
            else:
                content = format_delegation_message(
                    task.delegator,
                    task_id,
                    task.spec,
                    attempt=task.attempt,
                )
                extra = {
                    "kind": "delegation",
                    "task_id": task_id,
                    "_task_spec": task.spec,
                }
            message = Message(
                id=f"{task_id}:attempt:{task.attempt}",
                from_agent=task.delegator,
                to_agent=task.recipient,
                content=content,
                extra=extra,
            )
            try:
                await self.mailbox.send(to=task.recipient, message=message)
            except Exception:
                self._dispatching_delegations.discard(task_id)
                raise

    async def dispatch_undelivered_delegations(self) -> None:
        """Replay pending tasks that have no durable inbox acknowledgement."""
        from app.agent.mode.team import delegation_ledger

        try:
            lead_session_id = UUID(self.lead.session_id)
        except (TypeError, ValueError):
            return
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with self._delegation_lock:
            async with db_factory() as db:
                tasks = await delegation_ledger.load_undelivered_tasks(
                    db,
                    lead_session_id=lead_session_id,
                    live_recipients=set(self.mailbox.registered_agents),
                )
        await self.dispatch_delegation_tasks(tasks)

    async def dispatch_unacknowledged_handoffs(
        self, tasks: list[DelegationTask] | None = None
    ) -> None:
        """Replay completed handoffs that lack a durable inbox acknowledgement."""
        from app.agent.mode.team import delegation_ledger
        from app.agent.mode.team.handoff import format_handoff_message

        lead_session_id = UUID(self.lead.session_id)
        if tasks is None:
            db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
            async with self._delegation_lock:
                async with db_factory() as db:
                    tasks = await delegation_ledger.load_unacknowledged_handoffs(
                        db,
                        lead_session_id=lead_session_id,
                        live_recipients=set(self.mailbox.registered_agents),
                    )
        for task in tasks:
            task_id = str(task.id)
            if task_id in self._dispatching_handoffs or not task.result:
                continue
            if task.delegator not in self.mailbox.registered_agents:
                continue
            self._dispatching_handoffs.add(task_id)
            message = Message(
                id=f"{task_id}:handoff:{task.attempt}",
                from_agent=task.recipient,
                to_agent=task.delegator,
                content=format_handoff_message(task.recipient, task.result),
                extra={
                    "kind": "handoff",
                    "task_id": task_id,
                    "_handoff_artifact": task.result,
                },
            )
            try:
                await self.mailbox.send(to=task.delegator, message=message)
            except Exception:
                self._dispatching_handoffs.discard(task_id)
                raise

    async def complete_delegation(
        self,
        *,
        task_id: str,
        delegator: str,
        recipient: str,
        artifact: dict,
    ) -> DelegationTask:
        """Complete one task and dispatch newly dependency-ready assignments."""
        from app.agent.mode.team import delegation_ledger

        if task_id in self._ephemeral_delegation_ids:
            self.resolve_delegation(delegator, recipient, task_id=task_id)
            return DelegationTask(
                id=UUID(task_id),
                lead_session_id=UUID(self.lead.session_id),
                delegator=delegator,
                recipient=recipient,
                status="completed",
                spec={},
                result=artifact,
            )

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with self._delegation_lock:
            async with db_factory() as db:
                expired = await delegation_ledger.expire_overdue_tasks(
                    db, lead_session_id
                )
                existing = await delegation_ledger.get_task(
                    db,
                    lead_session_id=lead_session_id,
                    task_id=task_id,
                )
                if expired:
                    await db.commit()
            for expired_task in expired:
                self.resolve_delegation(
                    expired_task.delegator,
                    expired_task.recipient,
                    task_id=str(expired_task.id),
                )
        if any(str(row.id) == task_id for row in expired):
            raise ValueError(f"Delegation task '{task_id}' missed its deadline.")

        if existing.status in {"review", "completed"}:
            stored_result = dict(existing.result or {})
            comparable_result = dict(stored_result)
            comparable_result.pop("workspace_result", None)
            if comparable_result != artifact:
                raise ValueError(
                    f"Delegation task '{task_id}' already has a different final result."
                )
            artifact.clear()
            artifact.update(stored_result)
            return existing

        allocation = existing.spec.get("worktree_allocation")
        if isinstance(allocation, dict):
            from app.services import delegation_worktree_service

            (
                updated_allocation,
                workspace_result,
            ) = await delegation_worktree_service.snapshot(allocation)
            artifact["workspace_result"] = workspace_result
            updated_spec = dict(existing.spec)
            updated_spec["worktree_allocation"] = updated_allocation
            async with self._delegation_lock:
                async with db_factory() as db:
                    reviewed = await delegation_ledger.submit_task_for_review(
                        db,
                        lead_session_id=lead_session_id,
                        task_id=task_id,
                        delegator=delegator,
                        recipient=recipient,
                        result=artifact,
                        spec=updated_spec,
                    )
                    await db.commit()
            return reviewed

        async with self._delegation_lock:
            async with db_factory() as db:
                completed = await delegation_ledger.complete_task(
                    db,
                    lead_session_id=lead_session_id,
                    task_id=task_id,
                    delegator=delegator,
                    recipient=recipient,
                    result=artifact,
                )
                if completed.trace_run_id is not None:
                    from app.services.trace_service import (
                        record_mission_handoff_evidence,
                    )

                    await record_mission_handoff_evidence(
                        db,
                        task=completed,
                        artifact=artifact,
                    )
                ready, failed = await delegation_ledger.release_ready_tasks(
                    db,
                    lead_session_id=lead_session_id,
                    live_recipients=set(self.mailbox.registered_agents),
                )
                await db.commit()
            self.resolve_delegation(
                delegator,
                recipient,
                task_id=task_id,
            )
            for task in ready:
                self.register_delegation(
                    task.delegator,
                    [task.recipient],
                    task_ids=[str(task.id)],
                )
            for task in failed:
                self.resolve_delegation(
                    task.delegator,
                    task.recipient,
                    task_id=str(task.id),
                )
        await self.dispatch_delegation_tasks(ready)
        return completed

    async def review_delegation_worktree(self, task_id: str) -> str:
        from app.agent.mode.team import delegation_ledger
        from app.services import delegation_worktree_service

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with db_factory() as db:
            task = await delegation_ledger.get_task(
                db, lead_session_id=lead_session_id, task_id=task_id
            )
        allocation = task.spec.get("worktree_allocation")
        if not isinstance(allocation, dict):
            raise ValueError(f"Delegation task '{task_id}' has no worktree allocation.")
        return await delegation_worktree_service.review(allocation)

    async def merge_delegation_worktree(self, task_id: str) -> str:
        """Merge one reviewed worktree set and release dependent tasks."""
        from app.agent.mode.team import delegation_ledger
        from app.services import delegation_worktree_service

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with db_factory() as db:
            task = await delegation_ledger.get_task(
                db, lead_session_id=lead_session_id, task_id=task_id
            )
        if task.status != "review":
            raise ValueError(
                f"Delegation task '{task_id}' is {task.status}, not review."
            )
        allocation = task.spec.get("worktree_allocation")
        if not isinstance(allocation, dict):
            raise ValueError(f"Delegation task '{task_id}' has no worktree allocation.")
        updated_allocation, summary = await delegation_worktree_service.merge(
            allocation
        )
        updated_spec = dict(task.spec)
        updated_spec["worktree_allocation"] = updated_allocation
        if updated_allocation.get("state") == "conflict":
            async with db_factory() as db:
                await delegation_ledger.update_task_spec(
                    db,
                    lead_session_id=lead_session_id,
                    task_id=task_id,
                    spec=updated_spec,
                )
                await db.commit()
            raise ValueError(summary)

        async with self._delegation_lock:
            async with db_factory() as db:
                completed = await delegation_ledger.complete_reviewed_task(
                    db,
                    lead_session_id=lead_session_id,
                    task_id=task_id,
                    spec=updated_spec,
                )
                if completed.trace_run_id is not None:
                    from app.services.trace_service import (
                        record_mission_handoff_evidence,
                    )

                    await record_mission_handoff_evidence(
                        db,
                        task=completed,
                        artifact=dict(completed.result or {}),
                    )
                ready, failed = await delegation_ledger.release_ready_tasks(
                    db,
                    lead_session_id=lead_session_id,
                    live_recipients=set(self.mailbox.registered_agents),
                )
                await db.commit()
            self.resolve_delegation(
                completed.delegator, completed.recipient, task_id=task_id
            )
            for row in ready:
                self.register_delegation(
                    row.delegator, [row.recipient], task_ids=[str(row.id)]
                )
            for row in failed:
                self.resolve_delegation(
                    row.delegator, row.recipient, task_id=str(row.id)
                )
        await self.dispatch_delegation_tasks(ready)
        return summary

    async def discard_delegation_worktree(self, task_id: str) -> str:
        from app.agent.mode.team import delegation_ledger
        from app.services import delegation_worktree_service

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with db_factory() as db:
            task = await delegation_ledger.get_task(
                db, lead_session_id=lead_session_id, task_id=task_id
            )
        if task.status not in {"review", "failed"}:
            raise ValueError(
                f"Delegation task '{task_id}' is {task.status}, not review/failed."
            )
        allocation = task.spec.get("worktree_allocation")
        if not isinstance(allocation, dict):
            raise ValueError(f"Delegation task '{task_id}' has no worktree allocation.")
        updated_allocation = await delegation_worktree_service.discard(allocation)
        updated_spec = dict(task.spec)
        updated_spec["worktree_allocation"] = updated_allocation
        async with self._delegation_lock:
            async with db_factory() as db:
                if task.status == "review":
                    terminal = await delegation_ledger.cancel_reviewed_task(
                        db,
                        lead_session_id=lead_session_id,
                        task_id=task_id,
                        spec=updated_spec,
                    )
                else:
                    terminal = await delegation_ledger.update_task_spec(
                        db,
                        lead_session_id=lead_session_id,
                        task_id=task_id,
                        spec=updated_spec,
                    )
                ready, failed = await delegation_ledger.release_ready_tasks(
                    db,
                    lead_session_id=lead_session_id,
                    live_recipients=set(self.mailbox.registered_agents),
                )
                await db.commit()
            self.resolve_delegation(
                terminal.delegator, terminal.recipient, task_id=task_id
            )
            for row in ready:
                self.register_delegation(
                    row.delegator, [row.recipient], task_ids=[str(row.id)]
                )
            for row in failed:
                self.resolve_delegation(
                    row.delegator, row.recipient, task_id=str(row.id)
                )
        await self.dispatch_delegation_tasks(ready)
        return f"Discarded isolated changes for delegation {task_id}."

    async def finalize_delegation_worktrees(
        self, target_repos: list[str] | None = None
    ) -> str:
        """Fast-forward source repos after every isolated task is merged."""
        from app.agent.mode.team import delegation_ledger
        from app.services import delegation_worktree_service

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with db_factory() as db:
            tasks = await delegation_ledger.tasks_with_worktrees(
                db, lead_session_id=lead_session_id
            )
        unfinished = []
        for task in tasks:
            allocation = task.spec.get("worktree_allocation")
            state = allocation.get("state") if isinstance(allocation, dict) else None
            if state not in {"merged", "finalized", "discarded"}:
                unfinished.append(f"{task.id} ({task.status}/{state or 'unknown'})")
        if unfinished:
            raise ValueError(
                "Cannot finalize while isolated worktrees remain unresolved: "
                + ", ".join(unfinished)
                + ". Merge or explicitly discard them first."
            )
        eligible = [
            task
            for task in tasks
            if isinstance(task.spec.get("worktree_allocation"), dict)
            and task.spec["worktree_allocation"].get("state") == "merged"
        ]
        allocations = [task.spec["worktree_allocation"] for task in eligible]
        if not allocations:
            finalized_allocations = [
                task.spec["worktree_allocation"]
                for task in tasks
                if isinstance(task.spec.get("worktree_allocation"), dict)
                and task.spec["worktree_allocation"].get("state") == "finalized"
            ]
            cleanup_warnings = await delegation_worktree_service.cleanup_finalized(
                finalized_allocations
            )
            if cleanup_warnings:
                return (
                    "No new integrations to finalize.\nCleanup pending:\n"
                    + "\n".join(cleanup_warnings)
                )
            return "No new integrations to finalize; finalized refs are clean."
        updated, summary = await delegation_worktree_service.finalize(
            allocations, target_repos=target_repos
        )
        by_task = {str(allocation.get("task_id")): allocation for allocation in updated}
        async with self._delegation_lock:
            async with db_factory() as db:
                for task in eligible:
                    allocation = by_task.get(str(task.id))
                    if allocation is None:
                        continue
                    spec = dict(task.spec)
                    spec["worktree_allocation"] = allocation
                    await delegation_ledger.update_task_spec(
                        db,
                        lead_session_id=lead_session_id,
                        task_id=str(task.id),
                        spec=spec,
                    )
                await db.commit()
        cleanup_warnings = await delegation_worktree_service.cleanup_finalized(updated)
        if cleanup_warnings:
            summary += "\nCleanup pending:\n" + "\n".join(cleanup_warnings)
        return summary

    async def validate_delegation(
        self,
        *,
        task_id: str,
        delegator: str,
        recipient: str,
        allow_completed: bool = False,
    ) -> DelegationTask:
        """Validate task ownership/status before accepting a linked artifact."""
        from app.agent.mode.team import delegation_ledger

        if task_id in self._ephemeral_delegation_ids:
            return DelegationTask(
                id=UUID(task_id),
                lead_session_id=UUID(self.lead.session_id),
                delegator=delegator,
                recipient=recipient,
                status="pending",
                spec={},
            )
        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with db_factory() as db:
            task = await delegation_ledger.get_task(
                db,
                lead_session_id=lead_session_id,
                task_id=task_id,
            )
        if task.delegator != delegator or task.recipient != recipient:
            raise ValueError(
                f"Delegation task '{task_id}' belongs to "
                f"{task.delegator} -> {task.recipient}."
            )
        allowed = {"pending", "review", "completed"} if allow_completed else {"pending"}
        if task.status not in allowed:
            raise ValueError(
                f"Delegation task '{task_id}' is {task.status}, not pending."
            )
        return task

    async def get_delegation_task(self, task_id: str) -> DelegationTask | None:
        """Return one durable task for lifecycle reconciliation.

        Legacy in-memory task ids have no ledger row and return ``None``.
        """
        if task_id in self._ephemeral_delegation_ids:
            return None
        from app.agent.mode.team import delegation_ledger

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with db_factory() as db:
            return await delegation_ledger.get_task(
                db,
                lead_session_id=lead_session_id,
                task_id=task_id,
            )

    async def reopen_delegation(
        self,
        *,
        task_id: str | None,
        delegator: str,
        recipient: str,
        feedback: dict,
    ) -> DelegationTask:
        """Reopen the identified completed task for another attempt."""
        from app.agent.mode.team import delegation_ledger

        resolved_legacy_id = self._resolved_ephemeral_delegations.get(
            (delegator, recipient)
        )
        legacy_id = task_id if task_id in self._ephemeral_delegation_ids else None
        if task_id is None:
            legacy_id = resolved_legacy_id
        if legacy_id is not None:
            self._resolved_ephemeral_delegations.pop((delegator, recipient), None)
            self.register_delegation(
                delegator,
                [recipient],
                task_ids=[legacy_id],
            )
            self._ephemeral_delegation_ids.add(legacy_id)
            return DelegationTask(
                id=UUID(legacy_id),
                lead_session_id=UUID(self.lead.session_id),
                delegator=delegator,
                recipient=recipient,
                status="pending",
                spec={},
                attempt=2,
                last_rejection=feedback,
            )

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with self._delegation_lock:
            async with db_factory() as db:
                if task_id is None:
                    candidates = await delegation_ledger.completed_tasks_for_pair(
                        db,
                        lead_session_id=lead_session_id,
                        delegator=delegator,
                        recipient=recipient,
                    )
                    if len(candidates) != 1:
                        raise ValueError(
                            "task_id is required when the member has zero or multiple "
                            "completed delegation tasks."
                        )
                    task_id = str(candidates[0].id)
                durable_feedback = {**feedback, "task_id": task_id}
                task = await delegation_ledger.reopen_task(
                    db,
                    lead_session_id=lead_session_id,
                    task_id=task_id,
                    delegator=delegator,
                    recipient=recipient,
                    feedback=durable_feedback,
                )
                await db.commit()
            self.register_delegation(
                delegator,
                [recipient],
                task_ids=[str(task.id)],
            )
        return task

    async def mark_delegation_dispatched(self, task_id: str) -> None:
        """Acknowledge delivery after the recipient inbox row is durable."""
        from app.agent.mode.team import delegation_ledger

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with self._delegation_lock:
            async with db_factory() as db:
                await delegation_ledger.mark_task_dispatched(
                    db,
                    lead_session_id=lead_session_id,
                    task_id=task_id,
                )
                await db.commit()
            self._dispatching_delegations.discard(task_id)

    async def attach_delegation_handoff_message(
        self, task_id: str, message_id: UUID
    ) -> None:
        """Link a persisted final-handoff inbox row back to its task."""
        from app.agent.mode.team import delegation_ledger

        lead_session_id = UUID(self.lead.session_id)
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with self._delegation_lock:
            async with db_factory() as db:
                await delegation_ledger.attach_handoff_message(
                    db,
                    lead_session_id=lead_session_id,
                    task_id=task_id,
                    message_id=message_id,
                )
                await db.commit()
            self._dispatching_handoffs.discard(task_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Register the lead with the mailbox.

        Members are NOT registered here — they exist as blueprints and are
        registered when ``team_manage`` materialises an instance.  Pre-existing
        members in ``self.members`` (e.g. supplied directly by tests via the
        ``members=`` constructor kwarg) are also registered for back-compat.
        """
        self.lead.register(self)
        for member in self.members.values():
            member.register(self)
        logger.info(
            "agent_team_started lead={} blueprints={} eager_members={}",
            self.lead.name,
            sorted(self.blueprints.keys()),
            list(self.members.keys()),
        )

    async def stop(self) -> None:
        """Gracefully stop all agents: cancel active tasks and deregister."""
        for member in list(self.members.values()):
            await member.stop()
        await self.lead.stop()
        logger.info("agent_team_stopped")

    # ------------------------------------------------------------------
    # On-message activation callback
    # ------------------------------------------------------------------

    async def _on_message(self, agent_name: str, message: Message) -> None:
        """Called by the mailbox after every send.  Activates the target agent."""
        member = self._members_by_name.get(agent_name)
        if member is None:
            logger.warning("team_on_message_unknown_agent agent={}", agent_name)
            return
        member._maybe_activate()

    # ------------------------------------------------------------------
    # Stream event helpers
    # ------------------------------------------------------------------

    async def _emit(
        self,
        agent: str,
        event: str,
        status: Literal["idle", "working", "offline", "error"] | None = None,
        extra: dict | None = None,
    ) -> None:
        """Push a lifecycle event to the stream store for the current session."""
        from app.agent.schemas.events import AgentStatusEvent

        session_id = self.lead.session_id
        if event == "agent_status" and status is not None:
            envelope = StreamEnvelope.from_event(
                AgentStatusEvent(
                    agent=agent,
                    status=status,
                    metadata=extra or {},
                )
            )
        else:
            envelope = StreamEnvelope.from_parts(
                event,
                {"type": event, "agent": agent, "event": event, **(extra or {})},
            )

        try:
            await stream_store.push_event(session_id, envelope)
        except Exception as exc:
            logger.warning("team_emit_failed event={} error={}", event, exc)

    async def _try_emit_done(self) -> None:
        """Emit 'done' when lead + all live members are idle.

        Called from every member's _run_activation finally block.
        Guard: only fires after at least one user turn has started.
        """
        if not self._has_active_turn:
            return
        lead_done = self.lead.state in ("idle", "error")
        all_members_done = all(
            m.state in ("idle", "error") for m in self.members.values()
        )
        if lead_done and all_members_done:
            self._has_active_turn = False  # reset for next turn
            session_id = self.lead.session_id

            # Workflow hook ① (capture): unconditional, BEFORE queued
            # messages, so a queued user turn can never be mis-captured as
            # an agent node's output.
            if _workflow_capture_cb is not None:
                try:
                    await _workflow_capture_cb(session_id)
                except Exception as exc:  # noqa: BLE001 — never break the chain
                    logger.warning("workflow_capture_hook_failed error={}", exc)

            if await self._activate_queued_user_messages(session_id):
                return

            # Workflow hook ② (advance): an active execution consumes the
            # boundary before autonomous Goal continuation.
            if _workflow_advance_cb is not None:
                try:
                    if await _workflow_advance_cb(session_id):
                        return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("workflow_advance_hook_failed error={}", exc)

            if await self._activate_goal_continuation(session_id):
                return

            try:
                await self._emit_completion_notification(session_id)
                await self._emit_turn_changes(session_id)
                await stream_store.push_event(
                    session_id,
                    StreamEnvelope.from_event(DoneEvent()),
                )
                await stream_store.mark_done(session_id)
            except Exception as exc:
                logger.warning("team_emit_done_failed error={}", exc)
            logger.info("team_turn_done session_id={}", session_id)

    async def _emit_turn_changes(self, session_id: str) -> None:
        """Flush turn file mutations and push ``turn_changes`` SSE if any."""
        try:
            from app.agent.schemas.events import TurnChangesEvent
            from app.services import turn_changes as turn_changes_svc

            snap = turn_changes_svc.flush_turn(session_id)
            await stream_store.push_event(
                session_id,
                StreamEnvelope.from_event(
                    TurnChangesEvent(
                        session_id=session_id,
                        additions=snap.additions if snap else 0,
                        deletions=snap.deletions if snap else 0,
                        files=[f.to_dict() for f in snap.files] if snap else [],
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("team_emit_turn_changes_failed error={}", exc)

    async def _emit_completion_notification(self, session_id: str) -> None:
        try:
            session_uuid = UUID(session_id)
        except ValueError:
            return

        title: str | None = None
        mode: str | None = None
        workspace: str | None = None
        try:
            db_factory = resolve_db_factory(self.lead.db_factory)
            async with db_factory() as db:
                row = await db.get(ChatSession, session_uuid)
                if row is not None:
                    title = row.title
                    mode = row.mode
                    workspace = row.workspace
        except Exception as exc:
            logger.warning(
                "team_completion_notification_metadata_failed session_id={} error={}",
                session_id,
                exc,
            )

        workspace_name = (
            Path(workspace).name if mode == "coding" and workspace else None
        )
        notification_title = (
            f"Session completed - {workspace_name}"
            if workspace_name
            else "Session completed"
        )
        title_text = title.strip() if title else ""
        notification_body = title_text or f"Session {session_id[:8]}"
        await stream_store.push_event(
            session_id,
            StreamEnvelope.from_parts(
                "desktop_notification",
                {
                    "type": "desktop_notification",
                    "kind": "assistant_done",
                    "session_id": session_id,
                    "title": notification_title,
                    "body": notification_body,
                    "metadata": {
                        "session_id": session_id,
                        "title": title,
                        "mode": mode,
                        "workspace": workspace,
                    },
                },
            ),
        )

    async def _try_activate_queued_after_lead_turn(self) -> None:
        """Wake the lead with queued user messages as soon as its loop ends.

        Team ``done`` still waits for all members to finish. This only shortens
        the handoff from the persisted queue into the lead mailbox when the lead
        has completed its own activation but delegated members are still busy.
        """
        if not self._has_active_turn:
            return
        if self.lead.state not in ("idle", "error"):
            return

        if not self.mailbox.inbox_empty(self.lead.name):
            return

        if await self._activate_queued_user_messages(self.lead.session_id):
            self._has_active_turn = True

        # If sending to the mailbox did not spawn a new lead activation because
        # the lead was still marked working by its finally block, start it after
        # returning to idle.
        if (
            not self.mailbox.inbox_empty(self.lead.name)
            and self.lead.state != "working"
        ):
            self.lead._maybe_activate()

    async def _activate_queued_user_messages(self, session_id: str) -> bool:
        try:
            session_uuid = UUID(session_id)
        except ValueError:
            return False

        db_factory = resolve_db_factory(self.lead.db_factory)
        async with db_factory() as db:
            queued = await pop_queued_user_messages(db, session_uuid)
            if not queued:
                await db.commit()
                return False
            await db.commit()

        try:
            await stream_store.init_turn(session_id, keep_subscribers=True)
        except Exception as exc:
            logger.warning("team_init_queued_turn_failed error={}", exc)
            return False

        message_ids = [str(row.id) for row in queued]
        await stream_store.push_event(
            session_id,
            StreamEnvelope.from_parts(
                "queued_turn_start",
                {
                    "type": "queued_turn_start",
                    "agent": self.lead.name,
                    "message_ids": message_ids,
                    "messages": [
                        {"id": str(row.id), "content": row.content or ""}
                        for row in queued
                    ],
                },
            ),
        )
        self._has_active_turn = True
        for row in queued:
            msg = Message(
                from_agent="user",
                to_agent=self.lead.name,
                content=f"[user]: {row.content or ''}",
            )
            await self.mailbox.send(to=self.lead.name, message=msg)
            await asyncio.shield(
                self._mark_channel_source_delivered(session_id, row.id)
            )
        logger.info(
            "team_queued_messages_activated session_id={} count={} message_ids={}",
            session_id,
            len(queued),
            message_ids,
        )
        return True

    async def _activate_goal_continuation(self, session_id: str) -> bool:
        """Start the next hidden lead activation for an active durable goal."""

        try:
            session_uuid = UUID(session_id)
        except ValueError:
            return False

        db_factory = resolve_db_factory(self.lead.db_factory)
        try:
            async with db_factory() as db:
                from app.services import goal_service

                goal = await goal_service.get_goal(db, session_uuid)
                if goal is None or goal.status != "active":
                    return False
        except Exception as exc:  # noqa: BLE001 - preserve completion barrier
            logger.warning(
                "team_goal_state_load_failed session_id={} error={}",
                session_id,
                exc,
            )
            return False

        try:
            await stream_store.init_turn(session_id, keep_subscribers=True)
        except Exception as exc:
            logger.warning("team_init_goal_turn_failed error={}", exc)
            return False

        directive_id: UUID | None = None
        try:
            async with db_factory() as db:
                directive = await save_message(
                    db,
                    session_uuid,
                    HumanMessage(content=GOAL_CONTINUATION_DIRECTIVE),
                    exclude_from_context=False,
                    extra={
                        "command": "goal_continue",
                        "hidden_from_user": True,
                        "hidden_from_summary": True,
                    },
                )
                directive_id = directive.id
                await db.commit()
        except Exception as exc:  # noqa: BLE001 - preserve completion barrier
            logger.warning(
                "team_save_goal_directive_failed session_id={} error={}",
                session_id,
                exc,
            )
            return False

        self._has_active_turn = True
        try:
            self.lead.activate_for_continuation()
        except AlreadyWorkingError:
            # Another activation won the race. Remove the unused directive and
            # let that activation's completion boundary reassess the goal.
            if directive_id is not None:
                async with db_factory() as db:
                    directive = await db.get(SessionMessage, directive_id)
                    if directive is not None:
                        await db.delete(directive)
                        await db.commit()
            return True

        logger.info("team_goal_continued session_id={}", session_id)
        return True

    async def inject_synthetic_turn(self, session_id: str, prompt: str) -> str | None:
        """Start a synthetic lead turn for a workflow agent node.

        Returns the saved message row id (the caller's watermark anchor),
        or ``None`` on failure.
        """
        # Bind the lead to this session first — a freshly-booted team's lead
        # has no session yet, while normal user dispatch already performs this
        # binding (session pointer, DB row, member restore).
        if self.lead.session_id != session_id:
            self.lead.session_id = session_id
            try:
                await self.lead._ensure_db_session(
                    title=prompt[:100] if prompt else None,
                    mode=self.mode,
                    workspace=self.workspace,
                )
                for bp in self.blueprints.values():
                    bp.counter_reconciled_for = None
                await self._restore_or_drop_members_for_lead(session_id)
                await self.refresh_delegations(dispatch=False)
            except Exception as exc:
                logger.warning("workflow_lead_bind_failed error={}", exc)
                return None
        try:
            await stream_store.init_turn(session_id, keep_subscribers=True)
        except Exception as exc:
            logger.warning("workflow_init_turn_failed error={}", exc)
            return None
        try:
            session_uuid = UUID(session_id)
        except ValueError:
            return None
        try:
            db_factory = resolve_db_factory(self.lead.db_factory)
            async with db_factory() as db:
                row = await save_message(db, session_uuid, HumanMessage(content=prompt))
                await db.commit()
        except Exception as exc:
            logger.warning("workflow_save_turn_message_failed error={}", exc)
            return None

        self._has_active_turn = True
        await stream_store.push_event(
            session_id,
            StreamEnvelope.from_parts(
                "queued_turn_start",
                {
                    "type": "queued_turn_start",
                    "agent": self.lead.name,
                    "message_ids": [str(row.id)],
                    "messages": [{"id": str(row.id), "content": prompt}],
                },
            ),
        )
        await self.mailbox.send(
            to=self.lead.name,
            message=Message(
                from_agent="user",
                to_agent=self.lead.name,
                content=f"[user]: {prompt}",
            ),
        )
        await self.dispatch_recovered_coordination()
        return str(row.id)

    def interrupt_turn(self) -> list[str]:
        """Cancel every working member — the F9 interrupt effect without a
        user message. Used by the workflow runner's per-node timeout."""
        cancelled = [m for m in self.all_members if m.state == "working"]
        for member in cancelled:
            member._cancel_event.set()
        return [m.name for m in cancelled]

    # ------------------------------------------------------------------
    # User message entry point
    # ------------------------------------------------------------------

    async def prepare_user_session(
        self,
        *,
        content: str,
        session_id: str,
        mode: str | None = None,
        workspace: str | None = None,
        project_id: UUID | None = None,
    ) -> None:
        """Ensure a user session exists before deferred ingress is acknowledged.

        This is intentionally the lightweight, durable prefix of
        :meth:`handle_user_message`. Creating the ChatSession before HTTP 202
        means an immediate second send can safely persist as a queued child row
        while snapshot/persistence for the first message continues in the
        background.
        """
        if mode is not None:
            requested_mode = parse_app_mode(mode).value
            if requested_mode != self.mode:
                raise ValueError(
                    f"Session mode '{requested_mode}' does not match team mode "
                    f"'{self.mode}'."
                )
        if workspace is not None:
            self.workspace = workspace

        is_new_session = self.lead.session_id != session_id
        if not is_new_session:
            return

        self.lead.session_id = session_id
        await self.lead._ensure_db_session(
            title=content[:100] if content else None,
            mode=self.mode,
            workspace=self.workspace,
            project_id=project_id,
        )

        # Reset blueprint counters so a fresh chat starts at #1 for each
        # blueprint. Reconciliation against existing DB rows is lazy.
        for bp in self.blueprints.values():
            bp.counter_reconciled_for = None

        await self._restore_or_drop_members_for_lead(session_id)
        await self.refresh_delegations(dispatch=False)

    async def handle_user_message(
        self,
        content: str,
        session_id: str,
        interrupt: bool = False,
        attachment_metas: list[dict] | None = None,
        message_extra: dict | None = None,
        mode: str | None = None,
        workspace: str | None = None,
        project_id: UUID | None = None,
        model: str | None = None,
        model_provided: bool = False,
        thinking_level: str | None = None,
        thinking_level_provided: bool = False,
        service_tier: str | None = None,
        persist_message: bool = True,
        existing_message_id: UUID | None = None,
    ) -> str:
        """Deliver a user message to the team lead. Returns the session_id.

        ``session_id`` controls which conversation the lead continues.
        Passing a new UUID starts a fresh lead conversation.

        If interrupt=True, all working agents are cancelled immediately and
        all non-completed tasks are reset so the lead can re-plan.

        The caller should subscribe to GET /team/{session_id}/stream to
        receive the SSE event stream.
        """
        invocation = parse_slash_invocation(content)
        if invocation is not None and invocation.command == "loop":
            raise ContinuePreconditionError(
                "/loop has been removed. Use /goal <objective> instead.",
                status=410,
            )

        # Update the lead's active session

        await self.prepare_user_session(
            content=content,
            session_id=session_id,
            mode=mode,
            workspace=workspace,
            project_id=project_id,
        )

        if interrupt:
            cancelled = [m for m in self.all_members if m.state == "working"]
            for member in cancelled:
                member._cancel_event.set()

            # Stop button also stops an in-flight workflow (plan §6.1):
            # the runner marks the pending node failed instead of advancing.
            try:
                from app.workflow.runner import runner as workflow_runner

                workflow_runner.notify_interrupt(session_id)
            except Exception as exc:  # noqa: BLE001 — never break interrupts
                logger.debug("workflow_interrupt_notify_failed error={}", exc)

            logger.info(
                "team_interrupted cancelled={}",
                [m.name for m in cancelled],
            )

        # Persist user message and parent member sessions
        skip_delivery = False
        turn_was_active = self.has_active_user_turn()
        goal_command = parse_goal_command(content)
        goal_status_pending = False
        goal_status_value: SessionGoal | None = None
        if goal_command is not None:
            from app.services import goal_service

            try:
                goal_session_id = UUID(session_id)
                db_factory = resolve_db_factory(self.lead.db_factory)
                async with db_factory() as db:
                    if goal_command.action == "start":
                        assert goal_command.objective is not None
                        if turn_was_active:
                            raise goal_service.GoalConflictError(
                                "Cannot replace a goal during an active turn. "
                                "Pause or interrupt it, wait for the turn to stop, "
                                "then set the new objective."
                            )
                        goal_status_value = await goal_service.replace_goal(
                            db,
                            goal_session_id,
                            goal_command.objective,
                        )
                        content = goal_command.objective
                        message_extra = {
                            **(message_extra or {}),
                            "command": "goal_start",
                        }
                    elif goal_command.action == "status":
                        goal_status_value = await goal_service.get_goal(
                            db, goal_session_id
                        )
                        skip_delivery = True
                    elif goal_command.action == "pause":
                        goal_status_value = await goal_service.pause_goal(
                            db,
                            goal_session_id,
                        )
                        skip_delivery = True
                    elif goal_command.action == "resume":
                        goal_status_value = await goal_service.resume_goal(
                            db,
                            goal_session_id,
                        )
                        skip_delivery = True
                    elif goal_command.action == "budget":
                        goal_status_value = await goal_service.set_token_budget(
                            db,
                            goal_session_id,
                            goal_command.token_budget,
                        )
                        skip_delivery = True
                    else:
                        existing_goal = await goal_service.get_goal(db, goal_session_id)
                        if existing_goal is not None:
                            await goal_service.clear_goal(db, goal_session_id)
                        goal_status_value = None
                        skip_delivery = True
                    await db.commit()
                goal_status_pending = True
            except goal_service.GoalValidationError as exc:
                raise ContinuePreconditionError(str(exc), status=422) from exc
            except goal_service.GoalError as exc:
                raise ContinuePreconditionError(str(exc)) from exc

        if goal_command is not None and skip_delivery:
            if not turn_was_active:
                await stream_store.init_turn(session_id)
            if goal_status_pending:
                await publish_goal_status(
                    session_id,
                    goal_status_value,
                    source=f"command:{goal_command.action}",
                )
            if (
                goal_command.action == "resume"
                and not turn_was_active
                and await self._activate_goal_continuation(session_id)
            ):
                return session_id
            if not turn_was_active:
                await stream_store.push_event(
                    session_id, StreamEnvelope.from_event(DoneEvent())
                )
                await stream_store.mark_done(session_id)
            return session_id

        # Capture only messages that actually start/continue a user turn.
        # Control commands returned above must not replace delegation context.
        self._current_user_request = content
        if attachment_metas:
            attachment_refs: list[str] = []
            for attachment in attachment_metas:
                name = attachment.get("original_name") or attachment.get("filename")
                location = attachment.get("path") or attachment.get("workspace_path")
                if name and location:
                    attachment_refs.append(f"- {name}: {location}")
                elif name:
                    attachment_refs.append(f"- {name}")
            if attachment_refs:
                self._current_user_request += (
                    "\n\nAttached inputs available to the team:\n"
                    + "\n".join(attachment_refs)
                )

        saved_user_message_id = existing_message_id
        source_required = isinstance(
            (message_extra or {}).get("webbridge_source"), dict
        )
        try:
            db_factory = resolve_db_factory(self.lead.db_factory)
            lead_uuid = UUID(session_id)
            # Snapshot before opening the DB session: track() runs git
            # subprocesses over the whole workspace and must not hold a
            # SQLite write transaction open while it does.
            workspace_path = session_workspace_dir(str(lead_uuid), self.workspace)
            snapshot_hash = await snapshot_service.track(str(lead_uuid), workspace_path)
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                raise asyncio.CancelledError
            async with db_factory() as db:
                # Heal any tool_calls left orphaned by a previous crash /
                # restart *before* persisting the new user message so the
                # next turn's LLM input is well-formed.  See
                # ``heal_orphaned_tool_calls`` for the full rationale.
                await heal_orphaned_tool_calls(db, lead_uuid)

                lead_row = await db.get(ChatSession, lead_uuid)
                effective_model = model if model_provided else None
                effective_thinking_level = (
                    thinking_level if thinking_level_provided else None
                )
                if lead_row is not None:
                    lead_row.mode = self.mode
                    lead_row.workspace = self.workspace
                    if model_provided:
                        lead_row.model = model
                    if thinking_level_provided:
                        lead_row.thinking_level = thinking_level
                    effective_model = lead_row.model or self.lead.agent.model_id
                    effective_thinking_level = lead_row.thinking_level
                    db.add(lead_row)
                else:
                    effective_model = model or self.lead.agent.model_id

                msg_extra: dict | None = dict(message_extra or {}) or None
                if attachment_metas:
                    parts = build_parts_from_metas(content, attachment_metas)
                    user_msg = HumanMessage(content=content, parts=parts)
                    msg_extra = {**(msg_extra or {}), "attachments": attachment_metas}
                else:
                    user_msg = HumanMessage(content=content)

                if snapshot_hash:
                    extra_with_snapshot = dict(msg_extra or {})
                    extra_with_snapshot["snapshot"] = snapshot_hash
                    msg_extra = extra_with_snapshot

                extra_with_model = dict(msg_extra or {})
                extra_with_model["model"] = effective_model
                if effective_thinking_level:
                    extra_with_model["thinking_level"] = effective_thinking_level
                if service_tier:
                    extra_with_model["service_tier"] = service_tier
                msg_extra = extra_with_model

                if persist_message:
                    saved = await save_message(db, lead_uuid, user_msg, extra=msg_extra)
                    saved_user_message_id = saved.id

                for member in self.members.values():
                    try:
                        member_uuid = UUID(member.session_id)
                        member_row = await db.get(ChatSession, member_uuid)
                        if (
                            member_row is not None
                            and member_row.parent_session_id != lead_uuid
                        ):
                            member_row.parent_session_id = lead_uuid
                            db.add(member_row)
                    except Exception as inner_exc:
                        logger.warning(
                            "team_parent_member_session_failed member={} error={}",
                            member.name,
                            inner_exc,
                        )

                await db.commit()
        except Exception as exc:
            logger.opt(exception=True).warning(
                "team_save_user_message_failed type={} error={}",
                type(exc).__name__,
                repr(exc),
            )
            if source_required:
                raise

        # Initialise a fresh state blob for this turn synchronously before
        # delivering the message to the lead. This guarantees the state key
        # exists by the time the client's GET /team/{sid}/stream arrives.
        try:
            # Deferred HTTP dispatch initialises the turn before returning 202.
            # Preserve any subscriber that connected while snapshot/persistence
            # was still running instead of terminating that fresh SSE stream.
            await stream_store.init_turn(session_id, keep_subscribers=True)
            from app.services import turn_changes as turn_changes_svc

            turn_changes_svc.begin_turn(session_id)
        except Exception as exc:
            logger.warning("team_init_turn_failed error={}", exc)

        if goal_status_pending:
            await publish_goal_status(
                session_id,
                goal_status_value,
                source="command:start",
            )

        if content.startswith("[Scheduled Task: "):
            task_name = (
                content.split("]", 1)[0].removeprefix("[Scheduled Task: ").strip()
            )
            await stream_store.push_event(
                session_id,
                StreamEnvelope.from_parts(
                    "desktop_notification",
                    {
                        "type": "desktop_notification",
                        "kind": "reminder_fired",
                        "title": "Reminder fired",
                        "body": task_name,
                    },
                ),
            )

        # Mark that a turn is now active
        self._has_active_turn = True

        # Deliver user message to lead inbox (on_message callback activates lead)
        msg = Message(
            from_agent="user",
            to_agent=self.lead.name,
            content=f"[user]: {content}",
        )
        await self.mailbox.send(to=self.lead.name, message=msg)
        if saved_user_message_id is not None:
            await asyncio.shield(
                self._mark_channel_source_delivered(session_id, saved_user_message_id)
            )
        await self.dispatch_recovered_coordination()

        return session_id

    async def _mark_channel_source_delivered(
        self, session_id: str, message_id: UUID
    ) -> None:
        """Mark a persisted channel message after mailbox delivery succeeds."""
        try:
            session_uuid = UUID(session_id)
            db_factory = resolve_db_factory(self.lead.db_factory)
            async with db_factory() as db:
                row = await db.get(SessionMessage, message_id)
                if row is None or row.session_id != session_uuid:
                    return
                await mark_channel_source_delivered(db, row)
                await db.commit()
        except Exception as exc:
            logger.warning(
                "team_channel_delivery_mark_failed message_id={} error={}",
                message_id,
                exc,
            )

    async def handle_continue(self, session_id: str) -> str:
        """Continue the prior assistant turn on *session_id* — no new user message.

        Runs the agent against the existing DB history verbatim.  The provider
        sees a trailing assistant message and continues from there; the
        resulting first assistant row is flagged ``extra["is_continuation"]``.

        Preconditions (all raise :class:`ContinuePreconditionError`, HTTP 409):

        * Session must exist and belong to the lead.
        * Lead must not already be working.
        * Last visible message must be an :class:`AssistantMessage` or a
          linked :class:`ToolMessage`. Assistant messages with pending
          ``tool_calls`` are rejected because continuing a half-emitted tool
          call is unsafe — partial JSON args.

        Returns the session_id.  Caller subscribes to
        ``GET /team/{session_id}/stream`` for the SSE feed.
        """
        try:
            lead_uuid = UUID(session_id)
        except ValueError as exc:
            raise ContinuePreconditionError("Invalid session id.") from exc

        # Validate session + load history BEFORE any side effects (no
        # _ensure_db_session, no roster realign) so that 409s leave the
        # team object untouched.  We deliberately use
        # ``get_messages_for_llm`` rather than ``get_messages`` because that
        # is the exact view the agent loop will pass to the LLM — if the
        # session has been auto-compacted such that the LLM-facing tail is
        # a summary row rather than an assistant turn, the precondition
        # must reject regardless of what the broader visible history says.
        db_factory = resolve_db_factory(self.lead.db_factory)
        async with db_factory() as db:
            row = await db.get(ChatSession, lead_uuid)
            if row is None:
                raise ContinuePreconditionError("Session not found.")
            # Session-ownership guard — refuse to continue a session that
            # belongs to a different agent.  Older rows may have
            # ``agent_name`` unset; allow those (back-compat).
            if row.agent_name and row.agent_name != self.lead.name:
                raise ContinuePreconditionError(
                    f"Session belongs to '{row.agent_name}', not '{self.lead.name}'."
                )
            healed = await heal_orphaned_tool_calls(db, lead_uuid)
            if healed:
                await db.commit()
            messages = await get_messages_for_llm(db, lead_uuid)
            if _is_interrupted_thinking_only_tail(messages):
                tail = messages[-1]
                if tail.db_id is not None:
                    row_to_delete = await db.get(SessionMessage, tail.db_id)
                    if row_to_delete is not None:
                        await db.delete(row_to_delete)
                        await db.commit()
                messages = messages[:-1]

        while messages and _is_hidden_continuation_directive(messages[-1]):
            messages.pop()

        if not messages:
            raise ContinuePreconditionError("Session has no messages to continue from.")

        last = messages[-1]
        if isinstance(last, ToolMessage):
            if not _tool_tail_has_matching_assistant_call(messages):
                raise ContinuePreconditionError(
                    "Last tool result is not linked to an assistant tool call — "
                    "cannot safely continue."
                )
        elif not isinstance(last, AssistantMessage):
            raise ContinuePreconditionError(
                "Last message is not an assistant message — nothing to continue. "
                "Send a new message instead."
            )
        else:
            if last.tool_calls:
                raise ContinuePreconditionError(
                    "Last assistant message is mid tool call — cannot safely continue."
                )

        # Preconditions satisfied — now realign the lead onto this session.
        is_new_session = self.lead.session_id != session_id
        if is_new_session:
            self.lead.session_id = session_id
            for bp in self.blueprints.values():
                bp.counter_reconciled_for = None
            await self._restore_or_drop_members_for_lead(session_id)
            await self.refresh_delegations(dispatch=False)

        # Init the SSE stream blob synchronously so client GETs after this
        # find the bucket in place (same contract as handle_user_message).
        try:
            await stream_store.init_turn(session_id)
        except Exception as exc:
            logger.warning("team_init_turn_failed error={}", exc)

        self._has_active_turn = True

        if self.lead.state == "working":
            self._has_active_turn = False
            raise ContinuePreconditionError(
                f"Agent '{self.lead.name}' is already working."
            )

        directive_id: UUID | None = None
        db_factory = resolve_db_factory(self.lead.db_factory)
        async with db_factory() as db:
            directive = await save_message(
                db,
                lead_uuid,
                HumanMessage(content=CONTINUATION_DIRECTIVE),
                exclude_from_context=False,
                extra={
                    "command": "continue",
                    "hidden_from_user": True,
                    "hidden_from_summary": True,
                },
            )
            directive_id = directive.id
            await db.commit()

        logger.info(
            "team_continue_dispatched session_id={} agent={}",
            session_id,
            self.lead.name,
        )

        # Activation enforces the working-state guard atomically — translate
        # its error to our precondition type so the route layer can map it
        # to a 409 like every other precondition violation.
        try:
            self.lead.activate_for_continuation()
        except AlreadyWorkingError as exc:
            self._has_active_turn = False
            if directive_id is not None:
                async with db_factory() as db:
                    directive = await db.get(SessionMessage, directive_id)
                    if directive is not None:
                        await db.delete(directive)
                        await db.commit()
            raise ContinuePreconditionError(str(exc)) from exc
        await self.dispatch_recovered_coordination()
        return session_id

    async def handle_compact(self, session_id: str) -> str:
        """Start a normal lead turn that forces summarization before the model call."""
        if self._has_active_turn:
            raise ContinuePreconditionError("Lead is already working.")

        try:
            lead_uuid = UUID(session_id)
        except ValueError as exc:
            raise ContinuePreconditionError("Invalid session id.") from exc

        db_factory = resolve_db_factory(self.lead.db_factory)
        async with db_factory() as db:
            row = await db.get(ChatSession, lead_uuid)
            if row is None:
                raise ContinuePreconditionError("Session not found.")
            if row.agent_name and row.agent_name != self.lead.name:
                raise ContinuePreconditionError(
                    f"Session belongs to '{row.agent_name}', not '{self.lead.name}'."
                )
            messages = await get_messages_for_llm(db, lead_uuid)

        if not messages:
            raise ContinuePreconditionError("Session has no messages to compact.")

        if self.lead.session_id != session_id:
            self.lead.session_id = session_id
            await self.refresh_delegations(dispatch=False)

        try:
            await stream_store.init_turn(session_id)
        except Exception as exc:
            logger.warning("team_init_turn_failed error={}", exc)

        try:
            self.lead.activate_for_compaction()
        except AlreadyWorkingError as exc:
            raise ContinuePreconditionError(str(exc)) from exc

        self._has_active_turn = True
        await self.dispatch_recovered_coordination()

        logger.info(
            "team_compact_dispatched session_id={} agent={}", session_id, self.lead.name
        )
        return session_id

    async def handle_undo(self, session_id: str) -> tuple[str, BoundaryShift]:
        """Move the revert boundary to the latest visible user turn.

        Returns ``(session_id, shift)`` where ``shift.target`` is the
        user message we landed on and ``shift.added/modified/removed``
        carry the workspace paths the snapshot restore touched. The
        HTTP layer forwards both up to the client so the React store
        can apply the boundary locally *and* splice a scoped Coding
        Workspace diff without a full sidebar refetch.
        """
        if self._has_active_turn:
            raise ContinuePreconditionError("Lead is already working.")
        # A member can still be streaming even when the lead is idle
        # (e.g. delegated turn). Reverting the boundary mid-stream
        # orphans the in-flight assistant tokens on the client, so
        # require the team to be fully quiescent first.
        busy = next(
            (m for m in self.all_members if m.state == "working"),
            None,
        )
        if busy is not None:
            raise ContinuePreconditionError(
                f"Agent '{busy.name}' is still working. Stop it before /undo."
            )

        try:
            lead_uuid = UUID(session_id)
        except ValueError as exc:
            raise ContinuePreconditionError("Invalid session id.") from exc

        # Serialise concurrent /undo (and /redo) on the same session —
        # see ``_command_locks`` rationale above. The lock spans the
        # whole DB read→commit cycle so a burst of clicks sees each
        # other's committed boundary.
        async with _command_lock(session_id):
            db_factory = resolve_db_factory(self.lead.db_factory)
            async with db_factory() as db:
                row = await db.get(ChatSession, lead_uuid)
                if row is None:
                    raise ContinuePreconditionError("Session not found.")
                if row.agent_name and row.agent_name != self.lead.name:
                    raise ContinuePreconditionError(
                        f"Session belongs to '{row.agent_name}', not '{self.lead.name}'."
                    )
                shift = await undo_session_messages(db, lead_uuid)
                if not shift.applied or shift.target is None:
                    raise ContinuePreconditionError("No user message to undo.")
                await db.commit()
                await db.refresh(shift.target)

        logger.info(
            "team_undo_applied session_id={} agent={}", session_id, self.lead.name
        )
        return session_id, shift

    async def handle_redo(self, session_id: str) -> tuple[str, BoundaryShift]:
        """Move the revert boundary forward or clear it.

        Returns ``(session_id, shift)``. ``shift.target`` is the user
        message the boundary now points at, or ``None`` when the
        boundary was cleared back to the live tip. The path partition
        rides along so the HTTP layer can drive scoped cache
        invalidations on the client, skipping a full history *and*
        sidebar refetch.
        """
        if self._has_active_turn:
            raise ContinuePreconditionError("Lead is already working.")

        try:
            lead_uuid = UUID(session_id)
        except ValueError as exc:
            raise ContinuePreconditionError("Invalid session id.") from exc

        # Same per-session serialisation as ``handle_undo`` — two quick
        # /redo clicks must each see the other's committed boundary,
        # otherwise both compute the same ``next_user`` and the
        # boundary moves one step instead of two.
        async with _command_lock(session_id):
            db_factory = resolve_db_factory(self.lead.db_factory)
            async with db_factory() as db:
                row = await db.get(ChatSession, lead_uuid)
                if row is None:
                    raise ContinuePreconditionError("Session not found.")
                if row.agent_name and row.agent_name != self.lead.name:
                    raise ContinuePreconditionError(
                        f"Session belongs to '{row.agent_name}', not '{self.lead.name}'."
                    )
                shift = await redo_session_messages(db, lead_uuid)
                if not shift.applied:
                    raise ContinuePreconditionError("No undone message to redo.")
                await db.commit()
                if shift.target is not None:
                    await db.refresh(shift.target)

        logger.info(
            "team_redo_applied session_id={} agent={}", session_id, self.lead.name
        )
        return session_id, shift

    async def _restore_or_drop_members_for_lead(self, lead_session_id: str) -> None:
        """Realign live spawned instances to child sessions of *lead_session_id*.

        For each currently-live ``blueprint#N`` instance:
          - If a child ``ChatSession`` row with matching ``agent_name``
            exists under this lead, point the member at it (history is
            preserved).
          - Otherwise, dismiss it: the lead can re-spawn it explicitly,
            and we don't want to silently mint a fresh DB session for a
            member that may have been spawned for a different conversation.

        Plain-name eager members (those constructed directly via the
        ``members=`` constructor kwarg, used by tests) are left untouched —
        they own their own session id and are not part of the dynamic
        blueprint roster.
        """
        if not self.members:
            return

        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        try:
            lead_uuid = UUID(lead_session_id)
        except ValueError:
            return  # caller passed a non-UUID; nothing we can do

        try:
            async with db_factory() as db:
                for handle, member in list(self.members.items()):
                    is_spawned = parse_instance_handle(handle) is not None
                    result = await db.exec(
                        select(ChatSession)
                        .where(col(ChatSession.parent_session_id) == lead_uuid)
                        .where(col(ChatSession.agent_name) == handle)
                        .order_by(col(ChatSession.created_at).desc())
                        .limit(1)
                    )
                    existing = result.first()
                    if existing is not None:
                        # Realign to the existing child row regardless of
                        # whether the member was blueprint-spawned or eager:
                        # this preserves the legacy "restart restores
                        # members" behaviour.
                        member.session_id = str(existing.id)
                    elif is_spawned:
                        # No child session for this lead AND it's a
                        # blueprint-spawned instance → drop it.  The lead
                        # can re-spawn explicitly.  Eager / test-injected
                        # members are left in place with their existing
                        # session id.
                        await self._dismiss_live_member(handle)
        except Exception as exc:
            logger.warning("team_restore_members_failed error={}", exc)

    # ------------------------------------------------------------------
    # Spawn / dismiss
    # ------------------------------------------------------------------

    async def spawn(
        self,
        blueprint: str,
        *,
        instance_id: int | None = None,
        confirm: bool = False,
        _refresh_delegations: bool = True,
    ) -> TeamMember:
        """Materialise a member instance from a blueprint and register it.

        Args:
            blueprint: Blueprint name (matches a ``.md`` file's ``name:``).
            instance_id: If given, spawn (or restore) the instance with that
                ``#N``.  If a DB ``ChatSession`` already exists for this
                ``(lead_session, handle)`` it is restored (history preserved).
                Otherwise a fresh session is created.  When omitted, the
                next free ``#N`` is auto-assigned (handles auto-suffixing
                when the same blueprint is spawned multiple times).

        Raises:
            KeyError: blueprint not found.
            ValueError: instance with that handle is already live.
        """
        runtime_config = (
            await self._confirm_spawn_runtime(blueprint) if confirm else None
        )
        try:
            async with asyncio.timeout(30):
                async with self._roster_lock:
                    member = await self._spawn_locked(
                        blueprint,
                        instance_id=instance_id,
                        runtime_config=runtime_config,
                    )
        except TimeoutError:
            raise RuntimeError(
                f"Timed out waiting to spawn '{blueprint}' — roster lock held too long."
            )
        if _refresh_delegations:
            # Reconciliation may materialise other task recipients, which
            # calls spawn() recursively. Keep it outside the non-reentrant
            # roster lock to avoid deadlocking on that nested restoration.
            await self.refresh_delegations()
        return member

    async def _spawn_locked(
        self,
        blueprint: str,
        *,
        instance_id: int | None,
        runtime_config: SpawnRuntimeConfig | None = None,
    ) -> TeamMember:
        bp = self.blueprints.get(blueprint)
        if bp is None:
            idle = sorted(self.blueprints.keys())
            raise KeyError(f"Unknown blueprint '{blueprint}'. Available: {idle}.")
        if not self.blueprint_allowed_this_turn(blueprint):
            allowed = sorted(self.turn_allowed_blueprints or [])
            raise KeyError(
                f"'{blueprint}' is not on this workflow node's roster "
                f"(allowed this turn: {allowed or 'lead only'})."
            )

        # ``spawn`` is also a public runtime/test entry point and can be
        # invoked before the first user turn materializes the lead row. Every
        # child session and delegation references that row, so establish the
        # parent invariant before issuing any FK-backed writes.
        await self.lead._ensure_db_session(
            mode=self.mode,
            workspace=self.workspace,
        )

        # Reconcile counter for this lead session if not yet done.  This
        # ensures auto-assigned ``#N`` values are restart-safe and don't
        # collide with old child sessions.
        await self._reconcile_counter(bp)

        if instance_id is None:
            instance_id = bp.next_instance_id
            # Skip over any handle that's already live for this blueprint.
            while make_instance_handle(blueprint, instance_id) in self.members:
                instance_id += 1
            bp.next_instance_id = instance_id + 1
        else:
            if instance_id < 1:
                raise ValueError(f"instance_id must be >= 1 (got {instance_id}).")
            # Keep the auto-counter ahead of any explicit id so subsequent
            # auto-spawns don't immediately collide.
            if instance_id >= bp.next_instance_id:
                bp.next_instance_id = instance_id + 1

        handle = make_instance_handle(blueprint, instance_id)
        if handle in self.members:
            raise ValueError(f"Instance '{handle}' is already live.")

        # Build the agent from the blueprint's .md file.
        from app.agent.loader import rebuild_agent_from_disk

        agent = rebuild_agent_from_disk(
            bp.source_path,
            provider_factory=self._provider_factory,
            extra_tools=self._extra_tools,
            mode=self.mode,
        )
        # The blueprint name on disk is e.g. ``executor``; the runtime name
        # (mailbox key, DB ``agent_name``) is the instance handle.
        agent.name = handle

        member = TeamMember(agent, db_factory=self._db_factory)

        # Resolve session id: restore if an existing row matches this
        # (lead, handle) — including the legacy "bare blueprint name"
        # adoption for instance #1 (see ``_resolve_session_for_handle``).
        session_id = await self._resolve_session_for_handle(blueprint, handle)
        if session_id is not None:
            member.session_id = session_id
        # Ensure the row exists (idempotent on restore) and parent it
        # under the current lead session so the team-history endpoint
        # and the counter reconciler can find it.
        await member._ensure_db_session(mode=self.mode, workspace=self.workspace)
        await self._parent_member_session(member)
        if runtime_config is not None:
            await self._persist_member_runtime_config(member, runtime_config)

        # Register with mailbox.  The team is currently started iff the
        # lead has a registered inbox; in that case we activate immediately
        # so any queued messages are picked up.
        member.register(self)
        self.members[handle] = member
        self._members_by_name[handle] = member
        await self._emit(
            agent=handle,
            event="agent_status",
            status="idle",
            extra={"blueprint": blueprint},
        )

        logger.info(
            "team_member_spawned blueprint={} handle={} session_id={}",
            blueprint,
            handle,
            member.session_id,
        )
        await self._persist_roster_change(f"Member spawned: {handle}.")
        return member

    async def _confirm_spawn_runtime(self, blueprint: str) -> SpawnRuntimeConfig | None:
        """Ask the user to approve model/effort before an interactive spawn."""

        bp = self.blueprints.get(blueprint)
        if bp is None:
            raise KeyError(
                f"Unknown blueprint '{blueprint}'. Available: {sorted(self.blueprints)}."
            )

        from app.agent.ask_user import get_active_ask_user_service
        from app.agent.config import parse_agent_md
        from app.agent.tools.builtin.ask_user import AgentSpawnSpec, QuestionSpec

        cfg = parse_agent_md(bp.source_path)
        default_model = cfg.model
        if not default_model:
            raise ValueError(f"Member blueprint '{blueprint}' has no model configured.")
        default_thinking = cfg.thinking_level
        service = get_active_ask_user_service()
        if service is None:
            # Recovery, tests, and non-agent callers have no user round-trip.
            return SpawnRuntimeConfig(default_model, default_thinking)

        answers = await service.ask(
            [
                QuestionSpec(
                    kind="agent_spawn",
                    question=(
                        f"Confirm model and thinking effort before spawning "
                        f"'{blueprint}'."
                    ),
                    agent_spawn=AgentSpawnSpec(
                        blueprint=blueprint,
                        default_model=default_model,
                        default_thinking_level=default_thinking,
                    ),
                )
            ]
        )
        raw = answers[0] if answers else ""
        if raw == "__cancel__":
            raise SpawnCancelledError(f"Spawn of '{blueprint}' was cancelled by user.")
        try:
            selection = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Invalid agent spawn selection returned by the UI."
            ) from exc
        if not isinstance(selection, dict):
            raise ValueError("Invalid agent spawn selection returned by the UI.")
        model = selection.get("model")
        thinking_level = selection.get("thinking_level")
        if not isinstance(model, str) or not model.strip() or ":" not in model:
            raise ValueError("Agent spawn requires a valid provider:model selection.")
        if thinking_level is not None and not isinstance(thinking_level, str):
            raise ValueError("Agent spawn thinking_level must be a string or null.")

        from app.agent.providers.model_metadata import get_model_thinking_levels

        supported = get_model_thinking_levels(model)
        if thinking_level and supported and thinking_level not in supported:
            raise ValueError(
                f"Model '{model}' does not support thinking level "
                f"'{thinking_level}'. Supported: {list(supported)}."
            )
        return SpawnRuntimeConfig(model.strip(), thinking_level or None)

    async def _persist_member_runtime_config(
        self,
        member: TeamMember,
        runtime_config: SpawnRuntimeConfig,
    ) -> None:
        """Persist the approved execution model on the child session."""

        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        async with db_factory() as db:
            row = await db.get(ChatSession, UUID(member.session_id))
            if row is None:
                raise RuntimeError(
                    f"Child session '{member.session_id}' disappeared during spawn."
                )
            row.model = runtime_config.model
            row.thinking_level = runtime_config.thinking_level
            db.add(row)
            await db.commit()
        member.runtime_model_id = runtime_config.model
        member.runtime_thinking_level = runtime_config.thinking_level

    async def _persist_roster_change(self, change: str) -> None:
        """Persist an LLM-visible, UI-hidden roster-change marker."""
        try:
            lead_uuid = UUID(self.lead.session_id)
        except (ValueError, AttributeError):
            return

        live = ", ".join(sorted(self.members)) or "none"
        content = f"[system]: Available members changed. {change} Live members: {live}."
        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        try:
            async with db_factory() as db:
                await save_message(
                    db,
                    lead_uuid,
                    HumanMessage(content=content),
                    exclude_from_context=False,
                    extra={
                        "hidden_from_user": True,
                        "hidden_from_summary": True,
                        "roster_change": True,
                    },
                )
                await db.commit()
        except Exception as exc:
            logger.warning("team_roster_change_persist_failed error={}", exc)

    async def _parent_member_session(self, member: TeamMember) -> None:
        """Set ``parent_session_id`` on *member*'s DB row to the lead's session.

        The team's lead session is the canonical parent for all member
        sessions.  ``handle_user_message`` already does this for *every*
        member at the start of a turn, but spawn happens mid-turn so we
        need to set it eagerly so counter reconciliation, history APIs,
        and dismiss-then-respawn all see the row under the right lead.
        """
        try:
            lead_uuid = UUID(self.lead.session_id)
            member_uuid = UUID(member.session_id)
        except (ValueError, AttributeError):
            return

        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        try:
            async with db_factory() as db:
                row = await db.get(ChatSession, member_uuid)
                if row is None:
                    return
                if row.parent_session_id != lead_uuid:
                    row.parent_session_id = lead_uuid
                    db.add(row)
                    await db.commit()
        except Exception as exc:
            logger.warning(
                "team_parent_member_session_failed handle={} error={}",
                member.name,
                exc,
            )

    async def dismiss(self, handle: str) -> bool:
        """Stop and deregister an instance by handle.  Returns ``True`` if found.

        DB session row is preserved so the instance can later be respawned
        with its history intact via ``spawn(blueprint, instance_id=N)``.
        """
        try:
            async with asyncio.timeout(30):
                async with self._roster_lock:
                    return await self._dismiss_live_member(handle)
        except TimeoutError:
            logger.error("team_dismiss_timeout handle={}", handle)
            return False

    async def _dismiss_live_member(self, handle: str) -> bool:
        member = self.members.pop(handle, None)
        if member is None:
            return False
        self._members_by_name.pop(handle, None)
        try:
            await member.stop()
        except Exception as exc:
            logger.warning("team_dismiss_stop_failed handle={} error={}", handle, exc)
        logger.info("team_member_dismissed handle={}", handle)
        await self._persist_roster_change(f"Member dismissed: {handle}.")
        await self._emit(agent=handle, event="agent_status", status="offline")
        return True

    # ------------------------------------------------------------------
    # Counter reconciliation + session resolution
    # ------------------------------------------------------------------

    async def _reconcile_counter(self, bp: "MemberBlueprint") -> None:
        """Seed ``bp.next_instance_id`` from the DB for the current lead session.

        Counter scope is **per-lead-session**: each fresh chat starts a
        blueprint at ``#1``.  The DB is the source of truth — the counter
        becomes ``max(existing #N for this lead) + 1`` so it survives a
        process restart in the middle of a live conversation.

        The first time a session sees a particular blueprint with no
        ``#N`` rows but an existing legacy bare-name row, the bare name is
        adopted as ``#1`` (see ``_resolve_session_for_handle``).
        """
        lead_session_id = self.lead.session_id
        if bp.counter_reconciled_for == lead_session_id:
            return

        try:
            lead_uuid = UUID(lead_session_id)
        except (ValueError, AttributeError):
            bp.counter_reconciled_for = lead_session_id
            return

        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        max_n = 0
        try:
            async with db_factory() as db:
                # Look only at rows that already use the new ``blueprint#N``
                # naming.  Legacy bare-name rows are NOT counted here —
                # they are adopted as ``#1`` on first spawn (see
                # ``_resolve_session_for_handle``), and counting them as
                # ``#1`` ahead of time would cause the first spawn to
                # auto-pick ``#2`` and skip the adoption opportunity.
                result = await db.exec(
                    select(ChatSession.agent_name).where(
                        col(ChatSession.parent_session_id) == lead_uuid
                    )
                )
                names = result.all()
                for name in names:
                    if not name:
                        continue
                    parsed = parse_instance_handle(name)
                    if parsed and parsed[0] == bp.name:
                        max_n = max(max_n, parsed[1])
        except Exception as exc:
            logger.warning(
                "team_counter_reconcile_failed blueprint={} error={}",
                bp.name,
                exc,
            )

        bp.next_instance_id = max_n + 1
        bp.counter_reconciled_for = lead_session_id

    async def _resolve_session_for_handle(
        self,
        blueprint: str,
        handle: str,
    ) -> str | None:
        """Return an existing DB session id for this (lead, handle), if any.

        Adoption rule: the very first time blueprint ``X`` is spawned for a
        given lead session as ``X#1`` AND no row already exists for the
        ``X#1`` agent_name, but a legacy bare-name row ``X`` exists under
        the same lead — adopt that row as ``X#1`` (rewrite ``agent_name``
        in place).  This makes the move from the old single-instance model
        lossless: the lead's existing ``executor`` history shows up under
        ``executor#1`` without manual migration.
        """
        try:
            lead_uuid = UUID(self.lead.session_id)
        except (ValueError, AttributeError):
            return None

        db_factory = resolve_db_factory(self._db_factory or self.lead.db_factory)
        try:
            async with db_factory() as db:
                # 1) Exact handle match (e.g. respawning ``executor#3``).
                result = await db.exec(
                    select(ChatSession)
                    .where(col(ChatSession.parent_session_id) == lead_uuid)
                    .where(col(ChatSession.agent_name) == handle)
                    .order_by(col(ChatSession.created_at).desc())
                    .limit(1)
                )
                row = result.first()
                if row is not None:
                    return str(row.id)

                # 2) Legacy adoption — only for the ``#1`` instance.
                parsed = parse_instance_handle(handle)
                if parsed is not None and parsed == (blueprint, 1):
                    legacy_q = await db.exec(
                        select(ChatSession)
                        .where(col(ChatSession.parent_session_id) == lead_uuid)
                        .where(col(ChatSession.agent_name) == blueprint)
                        .order_by(col(ChatSession.created_at).desc())
                        .limit(1)
                    )
                    legacy = legacy_q.first()
                    if legacy is not None:
                        legacy.agent_name = handle
                        db.add(legacy)
                        await db.commit()
                        logger.info(
                            "team_member_legacy_adopted blueprint={} handle={} "
                            "session_id={}",
                            blueprint,
                            handle,
                            legacy.id,
                        )
                        return str(legacy.id)
        except Exception as exc:
            logger.warning(
                "team_resolve_session_failed handle={} error={}", handle, exc
            )
        return None

    # ------------------------------------------------------------------
    # Recipient resolution (for team_message)
    # ------------------------------------------------------------------

    def blueprint_allowed_this_turn(self, blueprint: str) -> bool:
        """Whether *blueprint* may be spawned/addressed during the current
        turn — unrestricted unless a workflow agent node set an allowlist."""
        return (
            self.turn_allowed_blueprints is None
            or blueprint in self.turn_allowed_blueprints
        )

    def resolve_recipient(self, name: str) -> str | None:
        """Resolve a recipient name to a live mailbox key.

        - Exact handle match (``executor#2``) → returned as-is if live.
        - Bare blueprint name (``executor``) → routes to the unique live
          instance if exactly one exists.  Returns ``None`` to signal
          ambiguity (caller should produce a tailored error) when zero or
          multiple live instances exist.
        - Lead name → returned as-is.
        - During a workflow agent node, recipients outside the node's
          allowlist resolve to ``None`` (plan v5 §6.4).

        Returns the live name to address, or ``None`` if there is no
        unambiguous match.
        """
        if name == self.lead.name:
            return name
        if self.turn_allowed_blueprints is not None:
            parsed = parse_instance_handle(name)
            blueprint = parsed[0] if parsed is not None else name
            if not self.blueprint_allowed_this_turn(blueprint):
                return None
        if name in self.members:
            return name
        # Bare blueprint name: collect all live ``blueprint#N`` instances.
        candidates = [
            handle
            for handle in self.members
            if (parsed := parse_instance_handle(handle)) is not None
            and parsed[0] == name
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def resolve_delegation_recipient(self, name: str) -> str | None:
        """Resolve task assignments with idle-member preference.

        Exact handles remain exact. For a bare blueprint, one idle instance is
        selected even when other instances are busy. A single busy instance is
        still addressable (the task will be reported as queued); multiple busy
        instances stay ambiguous so the lead must choose a handle or spawn.
        """
        exact = self.resolve_recipient(name)
        if exact is not None or parse_instance_handle(name) is not None:
            return exact
        if name not in self.blueprints:
            return None
        live = self.live_instances_for_blueprint(name)
        idle = [handle for handle in live if self.members[handle].state != "working"]
        if len(idle) == 1:
            return idle[0]
        if not idle and len(live) == 1:
            return live[0]
        return None

    def live_instances_for_blueprint(self, blueprint: str) -> list[str]:
        """Return live instance handles for *blueprint* in spawn order."""
        matches: list[tuple[int, str]] = []
        for handle in self.members:
            parsed = parse_instance_handle(handle)
            if parsed is not None and parsed[0] == blueprint:
                matches.append((parsed[1], handle))
        matches.sort(key=lambda x: x[0])
        return [handle for _, handle in matches]

    # ------------------------------------------------------------------
    # Tool injection
    # ------------------------------------------------------------------

    def get_injected_tools(self, agent_name: str) -> list[Tool]:
        """Return runtime tools to inject into agent.run() for the given agent.

        Everyone gets ``team_message`` and ``todo_manage`` so members can claim
        assigned tasks. The lead additionally gets ``team_manage`` (roster
        spawn/dismiss).
        """
        from app.agent.tools.builtin.todo import make_todo_manage_tool

        role = "lead" if agent_name == self.lead.name else "member"
        tools: list[Tool] = [
            make_team_message_tool(
                self.mailbox, agent_name=agent_name, role=role, team=self
            ),
            make_team_handoff_tool(
                self.mailbox, agent_name=agent_name, role=role, team=self
            ),
            make_todo_manage_tool(role),
            make_team_state_tool(agent_name),
        ]
        if self.mode == "coding":
            easd_ctx = EasdContext(
                db_factory=self._db_factory, session_id=self.lead.session_id
            )
            tools.append(
                make_easd_review_tool(easd_ctx, agent_name=agent_name, role=role)
            )

        if agent_name == self.lead.name:
            if self.mode == "coding":
                tools.append(make_easd_spec_tool(easd_ctx, agent_name=agent_name))
                tools.append(make_easd_plan_tool(easd_ctx, agent_name=agent_name))
            tools.append(make_team_manage_tool(self))
            tools.append(
                make_team_delegate_tool(self.mailbox, agent_name=agent_name, team=self)
            )
            tools.append(
                make_team_reject_tool(self.mailbox, agent_name=agent_name, team=self)
            )
            tools.append(make_team_worktree_tool(self))

            deferred_lead_tools = {
                "team_handoff": "Deliver a structured handoff to another team member.",
                "team_state": "Read or update persistent shared team key-value state.",
                "team_reject": "Reject a member handoff with structured corrective feedback.",
                "team_worktree": "Review, merge, discard, or finalize delegated worktrees.",
            }
            for team_tool in tools:
                summary = deferred_lead_tools.get(team_tool.name)
                if summary:
                    team_tool.deferred = True
                    team_tool.deferred_summary = summary

        return tools

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def all_members(self) -> list[TeamMemberBase]:
        """Lead + all live members (instances)."""
        return [self.lead, *self.members.values()]

    def status(self) -> dict:
        """Return current state of all live agents + blueprint roster."""

        def member_status(member: TeamMemberBase) -> dict:
            return {
                "name": member.name,
                "state": member.state,
                "model": member.runtime_model_id or member.agent.llm_provider.model,
                "thinking_level": member.runtime_thinking_level,
                "active_task_id": member._active_delegation_task_id,
                "queue_depth": self.mailbox.inbox_size(member.name),
            }

        return {
            "lead": member_status(self.lead),
            "members": [member_status(m) for m in self.members.values()],
            "blueprints": [
                {
                    "name": bp.name,
                    "description": bp.description,
                    "live_instances": self.live_instances_for_blueprint(bp.name),
                }
                for bp in self.blueprints.values()
            ],
        }
