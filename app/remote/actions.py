"""Remote secondary actions — slash commands and More-actions menus.

Handles ``/help``, ``/status``, ``/new``, ``/stop``, ``/unpair``, and the
**More actions** dispatch for Workflows, Coding projects, EASD runs, and
Scheduler tasks.  Each menu loader returns bounded
:class:`RemoteMenuItem` entries with opaque callback tokens; each action
calls one existing service entry point and translates owning exceptions
into safe remote messages.

Design constraints (from spec):
- Do not copy owner validation into this module.
- Every callback token is opaque, connection/principal-bound, and <=64 bytes.
- No command accepts credentials, repository paths, settings changes, or
  arbitrary identifiers.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from loguru import logger

from app.remote import formatting
from app.remote.contracts import (
    RemoteAdapter,
    RemoteButton,
    RemoteInboundAction,
    RemoteOutboundMessage,
    RemoteOutboundPriority,
)
from app.remote.pairing import PairingService

if TYPE_CHECKING:
    from app.remote.contracts import RemoteAdapterStatus
    from app.remote.outbound import RemoteProjection

__all__ = ["RemoteActionResult", "RemoteActionService", "RemoteMenuItem"]

_MAX_CALLBACK_TOKEN_BYTES = 64
_CAPABILITY_TTL_SECONDS = 600
_TELEGRAM_MAX_MESSAGE_LENGTH = 4096

CommandName = Literal["start", "help", "status", "new", "stop", "unpair", "actions"]


@dataclass(frozen=True)
class RemoteActionResult:
    """Bounded, adapter-neutral outcome for one slash command."""

    status: str
    text: str = ""


@dataclass(frozen=True)
class RemoteMenuItem:
    """One bounded menu item for the More-actions list."""

    token: str
    label: str
    description: str = ""


@dataclass
class _ActionCapability:
    """Opaque capability record for a menu action."""

    token: str
    connection_id: UUID
    principal_id: str
    destination_id: str
    session_id: str
    action_kind: str
    action_target: str
    created_at: float = field(default_factory=time.monotonic)


# ── Known commands ────────────────────────────────────────────────────────────

_SLASH_COMMANDS: frozenset[str] = frozenset(
    {"start", "help", "status", "new", "stop", "unpair", "actions"}
)


# ── Help text ─────────────────────────────────────────────────────────────────

_HELP_TEXT = """Available commands:

/help — Show this help
/status — Show connection and current task status
/new — Start a new task (clears current task)
/stop — Stop the current running task
/unpair — Unpair this phone from EvoFlux
/actions — Show more actions (Workflows, Projects, Scheduler)

Or just type a message to chat with your agent."""


class RemoteActionService:
    """Handles slash commands and More-actions dispatch for remote sessions.

    Owned by the runtime.  Each method is called from the inbound handler
    after authorization.
    """

    def __init__(
        self,
        *,
        pairing_service: PairingService | None = None,
        adapter: RemoteAdapter | None = None,
        status_provider: "Callable[[], RemoteAdapterStatus] | None" = None,
    ) -> None:
        self._pairing_service = pairing_service or PairingService()
        self._adapter = adapter
        self._status_provider = status_provider
        self._capabilities: dict[str, _ActionCapability] = {}
        self._pending_by_token: dict[str, str] = {}
        self._projection: "RemoteProjection | None" = None

    def set_adapter(self, adapter: RemoteAdapter | None) -> None:
        self._adapter = adapter

    def set_status_provider(
        self, provider: "Callable[[], RemoteAdapterStatus]"
    ) -> None:
        self._status_provider = provider

    def set_projection(self, projection: "RemoteProjection | None") -> None:
        """Bind the outbound projection so ``/unpair`` can immediately clear
        its active-pairing cache (AC-10: unpair revokes access right away,
        not just callback/menu tokens)."""
        self._projection = projection

    def register_capability(
        self,
        *,
        connection_id: UUID | str,
        principal_id: str,
        destination_id: str,
        session_id: str,
        action_kind: str,
        action_target: str,
    ) -> str:
        """Register one short-lived, principal-bound detail action."""
        return self._issue_token(
            connection_id=UUID(str(connection_id)),
            principal_id=principal_id,
            destination_id=destination_id,
            session_id=session_id,
            action_kind=action_kind,
            action_target=action_target,
        )

    # ── Command dispatch ──────────────────────────────────────────────────

    async def dispatch_command(
        self,
        db: AsyncSession,
        action: RemoteInboundAction,
    ) -> RemoteActionResult:
        """Dispatch a slash command from a remote inbound action.

        ``action.text`` must start with ``/``.  Unknown commands return
        bounded help.
        """
        text = (action.text or "").strip()
        if not text.startswith("/"):
            return RemoteActionResult(status="not_a_command")

        parts = text.split(maxsplit=1)
        command = parts[0][1:].lower()  # strip leading /
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command == "help" or command == "start":
            return await self._cmd_help(db, action)
        elif command == "status":
            return await self._cmd_status(db, action)
        elif command == "new":
            return await self._cmd_new(db, action)
        elif command == "stop":
            return await self._cmd_stop(db, action)
        elif command == "unpair":
            return await self._cmd_unpair(db, action)
        elif command == "actions":
            return await self._cmd_actions(db, action, arg)
        else:
            # Unknown command — return bounded help.
            return await self._cmd_help(db, action)

    async def handle_action_callback(
        self,
        action: RemoteInboundAction,
        db: AsyncSession,
    ) -> bool:
        """Handle a callback from a More-actions menu.

        Returns True if the callback was resolved, False if unknown.
        """
        token = action.callback_token
        if not token:
            return False

        cap = self._capabilities.get(token)
        if cap is None:
            return False

        if (
            cap.connection_id != action.connection_id
            or cap.principal_id != action.principal.principal_id
            or cap.destination_id != action.principal.destination_id
        ):
            return False

        # Acknowledge an authorized callback before any follow-up work so the
        # provider stops showing its loading state even when the token expired.
        if self._adapter is not None:
            await self._adapter.answer_callback(token)

        if time.monotonic() - cap.created_at > _CAPABILITY_TTL_SECONDS:
            self._discard(cap)
            if cap.action_kind in {"diff", "toollog"}:
                await self._send(
                    cap.destination_id,
                    "This expired. Ask me again and I'll fetch it fresh.",
                    connection_id=cap.connection_id,
                )
                return True
            return False

        if cap.action_kind in {"diff", "toollog"}:
            self._discard(cap)
            await self._send_detail(cap)
            return True

        # Dispatch the action.
        resolved = await self._execute_action(cap, action, db)
        if resolved:
            self._discard(cap)
        return resolved

    # ── Command implementations ────────────────────────────────────────────

    async def _cmd_help(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteActionResult:
        return RemoteActionResult(status="ok", text=_HELP_TEXT)

    async def _cmd_status(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteActionResult:
        pairing = await self._pairing_service.authorize(
            db,
            connection_id=action.connection_id,
            principal_id=action.principal.principal_id,
        )
        if pairing is None:
            return RemoteActionResult(status="unauthorized")

        # Connection status.
        status_text = "Connected"
        if self._status_provider is not None:
            adapter_status = self._status_provider()
            status_text = f"Status: {adapter_status.state.value}"

        # Current task.
        task_text = "No current task"
        if pairing.active_session_id is not None:
            from app.models.chat import ChatSession

            session = await db.get(ChatSession, pairing.active_session_id)
            if session is not None and session.title:
                task_text = f"Current task: {session.title}"
            elif session is not None:
                task_text = f"Current task: session {session.id}"

        return RemoteActionResult(
            status="ok",
            text=f"{status_text}\n{task_text}\nPaired: {pairing.label or 'Yes'}",
        )

    async def _cmd_new(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteActionResult:
        from app.remote.inbound import RemoteInboundService

        inbound = RemoteInboundService(pairing_service=self._pairing_service)
        result = await inbound.new_task(db, action)
        if result.status == "unauthorized":
            return RemoteActionResult(status="unauthorized")
        return RemoteActionResult(
            status="ok", text="Current task cleared. Next message starts a new task."
        )

    async def _cmd_stop(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteActionResult:
        from app.remote.inbound import RemoteInboundService

        inbound = RemoteInboundService(pairing_service=self._pairing_service)
        result = await inbound.stop_current(db, action)
        if result.status == "unauthorized":
            return RemoteActionResult(status="unauthorized")
        if result.status == "no_active_turn":
            return RemoteActionResult(status="ok", text="No active task to stop.")
        return RemoteActionResult(status="ok", text="Task stopped.")

    async def _cmd_unpair(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> RemoteActionResult:
        removed = await self._pairing_service.unpair(db, action.connection_id)
        if removed:
            if self._projection is not None:
                self._projection.clear_active_pairing()
            return RemoteActionResult(
                status="ok", text="Phone unpaired. Send /start to pair again."
            )
        return RemoteActionResult(status="ok", text="No active pairing to remove.")

    async def _cmd_actions(
        self, db: AsyncSession, action: RemoteInboundAction, arg: str
    ) -> RemoteActionResult:
        """Show the More-actions menu."""
        items = await self._load_action_menu(db, action)
        if not items:
            return RemoteActionResult(
                status="ok", text="No additional actions available."
            )

        # Format as a numbered list.
        lines = ["More actions:"]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. {item.label}")
            if item.description:
                lines.append(f"   {item.description}")

        # Send the menu with buttons.
        if self._adapter is not None:
            buttons = tuple(
                RemoteButton(text=item.label[:64], token=item.token)
                for item in items[:8]  # bound to 8 buttons
            )
            await self._send(
                action.principal.destination_id,
                "\n".join(lines),
                buttons=buttons,
            )

        return RemoteActionResult(status="ok", text="\n".join(lines))

    # ── Menu loaders ───────────────────────────────────────────────────────

    async def _load_action_menu(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> list[RemoteMenuItem]:
        """Load available actions from all owners."""
        items: list[RemoteMenuItem] = []

        # Workflows
        items.extend(await self._load_workflows(db, action))

        # Coding projects
        items.extend(await self._load_coding_projects(db, action))

        # Scheduled tasks
        items.extend(await self._load_scheduled_tasks(db, action))

        return items[:20]  # bounded to 20 items

    async def _load_workflows(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> list[RemoteMenuItem]:
        """Load available workflows."""
        try:
            from app.services.workflows_fs import discover_workflows

            discovered = discover_workflows(None)
            items: list[RemoteMenuItem] = []
            for found in discovered[:5]:  # bound to 5
                defn = found.definition
                if defn is None:
                    continue
                token = self._issue_token(
                    connection_id=action.connection_id,
                    principal_id=action.principal.principal_id,
                    destination_id=action.principal.destination_id,
                    session_id="",
                    action_kind="workflow_start",
                    action_target=defn.name,
                )
                items.append(
                    RemoteMenuItem(
                        token=token,
                        label=f"Workflow: {defn.name[:50]}",
                        description=defn.description[:100] if defn.description else "",
                    )
                )
            return items
        except Exception as exc:
            logger.debug("remote_actions_load_workflows_failed error={}", exc)
            return []

    async def _load_coding_projects(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> list[RemoteMenuItem]:
        """Load visible coding projects."""
        try:
            from app.services.coding_project_service import list_visible_projects

            projects = await list_visible_projects(db)
            items: list[RemoteMenuItem] = []
            for proj in projects[:5]:  # bound to 5
                token = self._issue_token(
                    connection_id=action.connection_id,
                    principal_id=action.principal.principal_id,
                    destination_id=action.principal.destination_id,
                    session_id="",
                    action_kind="coding_task",
                    action_target=str(proj.id),
                )
                items.append(
                    RemoteMenuItem(
                        token=token,
                        label=f"Project: {proj.name[:50]}",
                        description=(proj.description or "")[:100],
                    )
                )
            return items
        except Exception as exc:
            logger.debug("remote_actions_load_projects_failed error={}", exc)
            return []

    async def _load_scheduled_tasks(
        self, db: AsyncSession, action: RemoteInboundAction
    ) -> list[RemoteMenuItem]:
        """Load manually-triggerable scheduled tasks."""
        try:
            from app.scheduler.scheduler import task_scheduler

            tasks = await task_scheduler.list_tasks()
            items: list[RemoteMenuItem] = []
            for task in tasks[:5]:  # bound to 5
                if not task.enabled:
                    continue
                token = self._issue_token(
                    connection_id=action.connection_id,
                    principal_id=action.principal.principal_id,
                    destination_id=action.principal.destination_id,
                    session_id="",
                    action_kind="schedule_trigger",
                    action_target=str(task.id),
                )
                items.append(
                    RemoteMenuItem(
                        token=token,
                        label=f"Schedule: {task.name[:50]}",
                    )
                )
            return items
        except Exception as exc:
            logger.debug("remote_actions_load_schedules_failed error={}", exc)
            return []

    # ── Action execution ───────────────────────────────────────────────────

    async def _execute_action(
        self, cap: _ActionCapability, action: RemoteInboundAction, db: AsyncSession
    ) -> bool:
        """Execute a menu action by kind."""
        if cap.action_kind == "workflow_start":
            return await self._exec_workflow_start(cap, action, db)
        elif cap.action_kind == "coding_task":
            return await self._exec_coding_task(cap, action, db)
        elif cap.action_kind == "schedule_trigger":
            return await self._exec_schedule_trigger(cap, action, db)
        return False

    async def _exec_workflow_start(
        self, cap: _ActionCapability, action: RemoteInboundAction, db: AsyncSession
    ) -> bool:
        """Start a workflow by name."""
        try:
            from app.services.workflows_fs import discover_workflows

            discovered = discover_workflows(None)
            defn = None
            for found in discovered:
                if found.definition and found.definition.name == cap.action_target:
                    defn = found.definition
                    break

            if defn is None:
                await self._reply_text(
                    action.principal.destination_id,
                    f"Workflow '{cap.action_target}' not found.",
                )
                return True

            # Workflows need a session to run in. We need to create one or
            # use the current task's session.
            pairing = await self._pairing_service.authorize(
                db,
                connection_id=cap.connection_id,
                principal_id=cap.principal_id,
            )
            if pairing is None or pairing.active_session_id is None:
                await self._reply_text(
                    action.principal.destination_id,
                    "No active task. Send a message first to create one, then try again.",
                )
                return True

            session_id = str(pairing.active_session_id)

            from app.workflow.runner import WorkflowRunner

            runner = WorkflowRunner()
            await runner.start(
                defn,
                definition_hash="",
                session_id=session_id,
                inputs={},
                scope_workspace=None,
            )
            await self._reply_text(
                action.principal.destination_id,
                f"Workflow '{cap.action_target}' started.",
            )
            return True
        except RuntimeError as exc:
            await self._reply_text(
                action.principal.destination_id,
                f"Cannot start workflow: {exc}",
            )
            return True
        except Exception as exc:
            logger.warning("remote_workflow_start_failed error={}", exc)
            await self._reply_text(
                action.principal.destination_id,
                "Failed to start workflow.",
            )
            return True

    async def _exec_coding_task(
        self, cap: _ActionCapability, action: RemoteInboundAction, db: AsyncSession
    ) -> bool:
        """Start a coding task for a project."""
        try:
            from app.services.coding_project_service import get_project

            project = await get_project(db, UUID(cap.action_target))
            if project is None:
                await self._reply_text(
                    action.principal.destination_id,
                    "Project not found.",
                )
                return True

            # Create a coding session for this project.
            from app.services.chat_service import create_chat_session

            chat = await create_chat_session(db)
            chat.mode = "coding"
            chat.project_id = project.id
            chat.tags = [
                "remote_origin",
                f"remote_connection:{cap.connection_id}",
            ]
            db.add(chat)
            await db.commit()

            # Update pairing to point to this session.
            pairing = await self._pairing_service.authorize(
                db,
                connection_id=cap.connection_id,
                principal_id=cap.principal_id,
            )
            if pairing is not None:
                pairing.active_session_id = chat.id
                db.add(pairing)
                await db.commit()

            await self._reply_text(
                action.principal.destination_id,
                f"Coding task created for project '{project.name}'. Send your first message.",
            )
            return True
        except Exception as exc:
            logger.warning("remote_coding_task_failed error={}", exc)
            await self._reply_text(
                action.principal.destination_id,
                "Failed to create coding task.",
            )
            return True

    async def _exec_schedule_trigger(
        self, cap: _ActionCapability, action: RemoteInboundAction, db: AsyncSession
    ) -> bool:
        """Trigger a scheduled task manually."""
        try:
            from app.scheduler.scheduler import task_scheduler

            await task_scheduler.trigger(UUID(cap.action_target))
            await self._reply_text(
                action.principal.destination_id,
                "Scheduled task triggered.",
            )
            return True
        except Exception as exc:
            logger.warning("remote_schedule_trigger_failed error={}", exc)
            await self._reply_text(
                action.principal.destination_id,
                f"Failed to trigger task: {exc}",
            )
            return True

    # ── Token management ───────────────────────────────────────────────────

    def _issue_token(
        self,
        *,
        connection_id: UUID,
        principal_id: str,
        destination_id: str,
        session_id: str,
        action_kind: str,
        action_target: str,
    ) -> str:
        token = secrets.token_urlsafe(16)
        assert len(token) <= _MAX_CALLBACK_TOKEN_BYTES
        cap = _ActionCapability(
            token=token,
            connection_id=connection_id,
            principal_id=principal_id,
            destination_id=destination_id,
            session_id=session_id,
            action_kind=action_kind,
            action_target=action_target,
        )
        self._capabilities[token] = cap
        self._pending_by_token[token] = action_kind
        return token

    def _discard(self, cap: _ActionCapability) -> None:
        self._capabilities.pop(cap.token, None)
        self._pending_by_token.pop(cap.token, None)

    # ── Delivery helpers ───────────────────────────────────────────────────

    async def _send(
        self,
        destination_id: str,
        text: str,
        buttons: tuple[RemoteButton, ...] = (),
        *,
        connection_id: UUID | None = None,
        priority: RemoteOutboundPriority = RemoteOutboundPriority.INFORMATIONAL,
    ) -> None:
        if self._adapter is None:
            return
        try:
            msg = RemoteOutboundMessage(
                connection_id=connection_id or UUID(int=0),
                destination_id=destination_id,
                text=text,
                buttons=buttons,
                priority=priority,
            )
            await self._adapter.send(msg)
        except Exception as exc:
            logger.warning("remote_action_send_failed error={}", exc)

    async def _reply_text(self, destination_id: str, text: str) -> None:
        await self._send(destination_id, text)

    async def _send_detail(self, cap: _ActionCapability) -> None:
        """Send redacted, escaped drill-down content in bounded HTML cards."""
        label = "Full diff" if cap.action_kind == "diff" else "Tool log"
        redacted = _redact_text(cap.action_target)
        for text in _render_detail_cards(label, redacted):
            await self._send(
                cap.destination_id,
                text,
                connection_id=cap.connection_id,
                priority=RemoteOutboundPriority.HIGH,
            )


# ── Redaction helper ──────────────────────────────────────────────────────────


def _render_detail_cards(label: str, content: str) -> list[str]:
    """Wrap escaped detail text in independently valid Telegram HTML cards.

    Escaping can expand a source character (``<`` becomes ``&lt;``), so chunk
    the escaped result rather than source text. Every card keeps its own
    heading and ``<pre>`` wrapper and is bounded by Telegram's 4096-character
    provider limit.
    """
    prefix = f"<b>{label}</b>\n\n<pre>"
    suffix = "</pre>"
    content_budget = _TELEGRAM_MAX_MESSAGE_LENGTH - len(prefix) - len(suffix)
    assert content_budget > 0

    cards: list[str] = []
    current: list[str] = []
    current_length = 0
    for character in content:
        escaped = formatting.escape(character)
        if current and current_length + len(escaped) > content_budget:
            cards.append(prefix + "".join(current) + suffix)
            current = []
            current_length = 0
        current.append(escaped)
        current_length += len(escaped)

    cards.append(prefix + "".join(current) + suffix)
    return cards


def _redact_text(text: str) -> str:
    """Apply remote-channel outbound redaction."""
    try:
        from app.agent.outbound_redaction import OutboundContext, protect_outbound_text

        protected, _report = protect_outbound_text(
            text, context=OutboundContext(channel="remote")
        )
        return protected
    except Exception:
        return text


# ── Command validation ────────────────────────────────────────────────────────


def is_slash_command(text: str) -> bool:
    """Check if text is a recognized slash command."""
    if not text.startswith("/"):
        return False
    command = text.split(maxsplit=1)[0][1:].lower()
    return command in _SLASH_COMMANDS


if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlmodel.ext.asyncio.session import AsyncSession
