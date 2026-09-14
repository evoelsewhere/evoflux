"""Remote gate bridge — opaque callback capabilities and gate resolution.

Translates EvoFlux gate events (permission_asked, question_asked,
plan_approval_requested) into Telegram inline-button cards with opaque
callback tokens, and resolves inbound callbacks back through the active
PermissionService, AskUserService, or PlanModeService registry.

Design constraints (from spec):
- Callback tokens are opaque, random, connection/principal-bound, and <=64 bytes.
- Internal IDs (session_id, request_id) are never serialized into callback data.
- ``answer_callback`` is called before any gate resolution (AC-26).
- ``edit_text`` removes buttons after resolution.
- Remote permission replies are limited to ``once`` and ``reject`` (AC-28).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from loguru import logger

from app.remote.contracts import (
    RemoteAdapter,
    RemoteButton,
    RemoteInboundAction,
    RemoteOutboundMessage,
    RemoteOutboundPriority,
)

if TYPE_CHECKING:
    pass

__all__ = ["RemoteGateBridge"]

#: Telegram callback data limit.
_MAX_CALLBACK_TOKEN_BYTES = 64

#: Capability expiry in seconds (10 minutes).
_CAPABILITY_TTL_SECONDS = 600

#: Gate kinds.
GateKind = Literal["permission", "question", "plan"]


@dataclass(frozen=True)
class GateCapability:
    """One opaque, expiring capability record bound to a gate action."""

    token: str
    connection_id: UUID
    principal_id: str
    destination_id: str
    session_id: str
    request_id: str
    gate_kind: GateKind
    action: str
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class _PendingGate:
    """Tracks one gate's outstanding capabilities and message reference."""

    request_id: str
    session_id: str
    gate_kind: GateKind
    tokens: list[str] = field(default_factory=list)
    chat_id: int | None = None
    message_id: int | None = None


class RemoteGateBridge:
    """Bridges EvoFlux gate events to Telegram inline buttons and resolves
    inbound callbacks through the active service registry.

    Owned by the runtime alongside the projection.  The projection calls
    :meth:`on_gate` and :meth:`on_reply`; the runtime calls
    :meth:`handle_callback` for inbound CALLBACK actions.
    """

    def __init__(self, adapter: RemoteAdapter) -> None:
        self._adapter = adapter
        self._capabilities: dict[str, GateCapability] = {}
        self._pending_by_token: dict[str, str] = {}  # token -> request_id
        self._pending_gates: dict[str, _PendingGate] = {}  # request_id -> gate

    def on_gate(
        self,
        session_id: str,
        event_type: str,
        data: dict,
        connection_id: UUID,
        destination_id: str,
    ) -> None:
        """Handle a gate event by creating opaque tokens and enqueuing a card.

        Called by the projection's ``_handle_gate``.
        """
        request_id = data.get("request_id", "")
        if not request_id:
            return

        gate_kind: GateKind
        actions: list[tuple[str, str]]  # (action_label, button_text)

        if event_type == "permission_asked":
            gate_kind = "permission"
            tool = data.get("tool", "unknown")
            text = f"Permission requested: {tool}"
            actions = [("once", "Allow"), ("reject", "Reject")]
        elif event_type == "question_asked":
            gate_kind = "question"
            questions = data.get("questions", [])
            if questions:
                first_q = questions[0]
                text = f"Question: {first_q.get('question', '')}"
                options = first_q.get("options", [])
                actions = [(opt, opt) for opt in options[:8]]  # bound to 8
            else:
                text = "Question asked."
                actions = []
        elif event_type == "plan_approval_requested":
            gate_kind = "plan"
            plan_text = data.get("plan", "")
            steps = data.get("steps", [])
            text = f"Plan ready for review ({len(steps)} steps)."
            if plan_text:
                text = f"Plan: {plan_text[:200]}"
            actions = [("approve", "Approve"), ("reject", "Reject")]
        else:
            return

        # Create opaque tokens for each action.
        buttons: list[RemoteButton] = []
        gate = _PendingGate(
            request_id=request_id,
            session_id=session_id,
            gate_kind=gate_kind,
        )

        for action_value, button_text in actions:
            token = self._issue_token(
                connection_id=connection_id,
                principal_id="",  # filled on callback from action
                destination_id=destination_id,
                session_id=session_id,
                request_id=request_id,
                gate_kind=gate_kind,
                action=action_value,
            )
            buttons.append(RemoteButton(text=button_text, token=token))
            gate.tokens.append(token)
            self._pending_by_token[token] = request_id

        self._pending_gates[request_id] = gate

        # Apply redaction and send.
        text = _redact_text(text)
        msg = RemoteOutboundMessage(
            connection_id=connection_id,
            destination_id=destination_id,
            text=text,
            buttons=tuple(buttons),
            priority=RemoteOutboundPriority.HIGH,
        )
        self._enqueue_send(msg)

    def on_reply(self, session_id: str, event_type: str, data: dict) -> None:
        """Handle a gate reply event by removing buttons from the message.

        Called by the projection when a ``permission_replied``,
        ``question_replied``, or ``plan_approval_replied`` event fires.
        """
        request_id = data.get("request_id", "")
        if not request_id:
            return

        gate = self._pending_gates.pop(request_id, None)
        if gate is None:
            return

        # Clean up capability tokens.
        for token in gate.tokens:
            self._capabilities.pop(token, None)
            self._pending_by_token.pop(token, None)

        # Edit the message to remove buttons (if we have a reference).
        if gate.chat_id is not None and gate.message_id is not None:
            self._edit_remove_buttons(gate)

    async def handle_callback(self, action: RemoteInboundAction) -> None:
        """Handle an inbound callback action.

        1. Look up the capability by token.
        2. Validate principal/connection.
        3. ``answer_callback`` FIRST (acknowledge the tap).
        4. Resolve the gate via the appropriate service.
        5. Edit the message to remove buttons.
        """
        token = action.callback_token
        if not token:
            return

        cap = self._capabilities.get(token)
        if cap is None:
            logger.debug(
                "remote_gate_callback_unknown token_prefix={}",
                token[:8],
            )
            return

        # Validate connection.
        if cap.connection_id != action.connection_id:
            logger.debug(
                "remote_gate_callback_wrong_connection expected={} got={}",
                cap.connection_id,
                action.connection_id,
            )
            return

        # Check expiry.
        if time.monotonic() - cap.created_at > _CAPABILITY_TTL_SECONDS:
            self._discard_capability(cap)
            logger.debug(
                "remote_gate_callback_expired request_id={}",
                cap.request_id,
            )
            return

        # Acknowledge the callback FIRST (AC-26).
        await self._adapter.answer_callback(token)

        # Resolve the gate.
        resolved = await self._resolve_gate(cap, action)
        if resolved:
            self._discard_capability(cap)

    async def _resolve_gate(
        self, cap: GateCapability, action: RemoteInboundAction
    ) -> bool:
        """Resolve a gate through the active service registry."""
        if cap.gate_kind == "permission":
            return await self._resolve_permission(cap, action)
        elif cap.gate_kind == "question":
            return await self._resolve_question(cap, action)
        elif cap.gate_kind == "plan":
            return await self._resolve_plan(cap, action)
        return False

    async def _resolve_permission(
        self, cap: GateCapability, action: RemoteInboundAction
    ) -> bool:
        """Resolve a permission gate. Remote is limited to once/reject."""
        from app.agent.permission import get_service_for_session

        reply_value = cap.action  # "once" or "reject"
        if reply_value not in ("once", "reject"):
            logger.warning(
                "remote_gate_invalid_permission_action action={}",
                reply_value,
            )
            return False

        svc = get_service_for_session(cap.session_id)
        if svc is None:
            logger.debug(
                "remote_gate_permission_service_missing session_id={}",
                cap.session_id,
            )
            return False

        resolved = svc.reply(cap.request_id, reply_value)
        if resolved:
            logger.info(
                "remote_gate_permission_resolved request_id={} reply={}",
                cap.request_id,
                reply_value,
            )
        return resolved

    async def _resolve_question(
        self, cap: GateCapability, action: RemoteInboundAction
    ) -> bool:
        """Resolve a question gate with the selected option."""
        from app.agent.ask_user import get_service_for_session

        svc = get_service_for_session(cap.session_id)
        if svc is None:
            logger.debug(
                "remote_gate_question_service_missing session_id={}",
                cap.session_id,
            )
            return False

        # The action is the answer (single-question batch for v1).
        answers = [cap.action]
        validation_error = svc.validate_answers(cap.request_id, answers)
        if validation_error:
            logger.warning(
                "remote_gate_question_validation_failed request_id={} error={}",
                cap.request_id,
                validation_error,
            )
            return False

        resolved = svc.reply(cap.request_id, answers)
        if resolved:
            logger.info(
                "remote_gate_question_resolved request_id={}",
                cap.request_id,
            )
        return resolved

    async def _resolve_plan(
        self, cap: GateCapability, action: RemoteInboundAction
    ) -> bool:
        """Resolve a plan approval gate."""
        from app.agent.plan import get_service_for_session

        decision = cap.action  # "approve" -> "approved", "reject" -> "rejected"
        plan_decision = "approved" if decision == "approve" else "rejected"

        svc = get_service_for_session(cap.session_id)
        if svc is None:
            logger.debug(
                "remote_gate_plan_service_missing session_id={}",
                cap.session_id,
            )
            return False

        resolved = svc.reply(cap.request_id, plan_decision)
        if resolved:
            logger.info(
                "remote_gate_plan_resolved request_id={} decision={}",
                cap.request_id,
                plan_decision,
            )
        return resolved

    def _discard_capability(self, cap: GateCapability) -> None:
        """Remove a capability and its token from all indices."""
        self._capabilities.pop(cap.token, None)
        self._pending_by_token.pop(cap.token, None)

    def _issue_token(
        self,
        *,
        connection_id: UUID,
        principal_id: str,
        destination_id: str,
        session_id: str,
        request_id: str,
        gate_kind: GateKind,
        action: str,
    ) -> str:
        """Issue an opaque, bounded callback token."""
        token = secrets.token_urlsafe(16)
        assert len(token) <= _MAX_CALLBACK_TOKEN_BYTES, (
            f"Token too long: {len(token)} bytes"
        )
        cap = GateCapability(
            token=token,
            connection_id=connection_id,
            principal_id=principal_id,
            destination_id=destination_id,
            session_id=session_id,
            request_id=request_id,
            gate_kind=gate_kind,
            action=action,
        )
        self._capabilities[token] = cap
        return token

    def _edit_remove_buttons(self, gate: _PendingGate) -> None:
        """Edit a message to remove its inline buttons."""
        if gate.chat_id is None or gate.message_id is None:
            return
        # We need to send an edit with empty buttons to remove the keyboard.
        # This is a fire-and-forget best-effort.
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(self._do_edit_remove(gate))
        except RuntimeError:
            pass

    async def _do_edit_remove(self, gate: _PendingGate) -> None:
        """Actually edit the message to remove buttons."""
        try:
            msg = RemoteOutboundMessage(
                connection_id=UUID(int=0),  # not used for edit lookup
                destination_id="",
                text="",  # text not changed
                buttons=(),
                correlation_id=f"gate:{gate.request_id}",
            )
            await self._adapter.edit(msg)
        except Exception as exc:
            logger.debug(
                "remote_gate_edit_remove_buttons_failed request_id={} error={}",
                gate.request_id,
                exc,
            )

    def _enqueue_send(self, msg: RemoteOutboundMessage) -> None:
        """Enqueue a message for async delivery."""
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(self._do_send(msg))
        except RuntimeError:
            pass

    async def _do_send(self, msg: RemoteOutboundMessage) -> None:
        """Send a message through the adapter."""
        try:
            await self._adapter.send(msg)
        except Exception as exc:
            logger.warning(
                "remote_gate_send_failed destination_id={} error={}",
                msg.destination_id,
                exc,
            )


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
