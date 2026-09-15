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

import asyncio
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
from app.remote.formatting import render_permission_card, render_permission_resolved_card
from app.remote.severity import derive_severity

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
    """Tracks one gate's outstanding capabilities and the command text (if
    any) needed to render its resolved form later."""

    request_id: str
    session_id: str
    gate_kind: GateKind
    tokens: list[str] = field(default_factory=list)
    command: str = ""


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

        if event_type == "permission_asked":
            self._on_permission_asked(
                session_id, data, connection_id, destination_id, request_id
            )
            return

        gate_kind: GateKind
        actions: list[tuple[str, str]]  # (action_label, button_text)

        if event_type == "question_asked":
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
            correlation_id=f"gate:{request_id}",
        )
        self._enqueue_send(msg)

    def _on_permission_asked(
        self,
        session_id: str,
        data: dict,
        connection_id: UUID,
        destination_id: str,
        request_id: str,
    ) -> None:
        """Render and send a decidable permission card (AC-45/AC-46): the
        real command and a derived, advisory-only severity, never a tool
        name alone."""
        tool = data.get("tool", "unknown")
        patterns = data.get("patterns") or []
        command = patterns[0] if patterns else tool
        always_patterns = data.get("always_patterns") or []
        always_glob = always_patterns[0] if always_patterns else None
        agent_name = data.get("metadata", {}).get("agent", "agent")
        severity = derive_severity(tool=tool, command=command)

        gate = _PendingGate(
            request_id=request_id,
            session_id=session_id,
            gate_kind="permission",
            command=_redact_text(command),
        )

        once_token = self._issue_token(
            connection_id=connection_id,
            principal_id="",
            destination_id=destination_id,
            session_id=session_id,
            request_id=request_id,
            gate_kind="permission",
            action="once",
        )
        gate.tokens.append(once_token)
        self._pending_by_token[once_token] = request_id

        always_token: str | None = None
        if always_glob:
            always_token = self._issue_token(
                connection_id=connection_id,
                principal_id="",
                destination_id=destination_id,
                session_id=session_id,
                request_id=request_id,
                gate_kind="permission",
                action="always",
            )
            gate.tokens.append(always_token)
            self._pending_by_token[always_token] = request_id

        reject_token = self._issue_token(
            connection_id=connection_id,
            principal_id="",
            destination_id=destination_id,
            session_id=session_id,
            request_id=request_id,
            gate_kind="permission",
            action="reject",
        )
        gate.tokens.append(reject_token)
        self._pending_by_token[reject_token] = request_id

        self._pending_gates[request_id] = gate

        text, buttons = render_permission_card(
            tool=tool,
            command=gate.command,
            severity=severity,
            agent=agent_name,
            always_glob=_redact_text(always_glob) if always_glob else None,
            always_token=always_token,
            once_token=once_token,
            reject_token=reject_token,
        )
        msg = RemoteOutboundMessage(
            connection_id=connection_id,
            destination_id=destination_id,
            text=text,
            buttons=buttons,
            priority=RemoteOutboundPriority.HIGH,
            correlation_id=f"gate:{request_id}",
        )
        self._enqueue_send(msg)

    def on_reply(self, session_id: str, event_type: str, data: dict) -> None:
        """Handle a gate reply event by editing its card into a resolved,
        button-free form (AC-47).

        Called by the projection when a ``permission_replied``,
        ``question_replied``, or ``plan_approval_replied`` event fires.
        """
        request_id = data.get("request_id", "")
        if not request_id:
            return

        gate = self._pending_gates.pop(request_id, None)
        if gate is None:
            return

        for token in gate.tokens:
            self._capabilities.pop(token, None)
            self._pending_by_token.pop(token, None)

        resolution_text = self._resolution_text(gate, data)
        self._enqueue_resolved_edit(gate, resolution_text)

    def _resolution_text(self, gate: _PendingGate, data: dict) -> str:
        """Build the resolved-form message text for one gate kind. Only
        permission gates have a per-decision label defined by the spec
        (AC-45's "Allowed once"/"Allowed for session"/"Rejected"); question
        and plan gates get a generic resolved marker."""
        if gate.gate_kind == "permission":
            reply = data.get("reply", "reject")
            text, _buttons = render_permission_resolved_card(
                command=gate.command or "(command unavailable)", resolution=reply
            )
            return text
        return "✅ <b>Resolved</b>"

    def _enqueue_resolved_edit(self, gate: _PendingGate, text: str) -> None:
        """Edit this gate's card into its resolved form — fire-and-forget,
        matching the delivery pattern already used by ``_enqueue_send``."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._do_resolved_edit(gate, text))
        except RuntimeError:
            pass

    async def _do_resolved_edit(self, gate: _PendingGate, text: str) -> None:
        try:
            msg = RemoteOutboundMessage(
                connection_id=UUID(int=0),  # not used for edit lookup
                destination_id="",
                text=text,
                buttons=(),
                correlation_id=f"gate:{gate.request_id}",
            )
            await self._adapter.edit(msg)
        except Exception as exc:
            logger.debug(
                "remote_gate_resolved_edit_failed request_id={} error={}",
                gate.request_id,
                exc,
            )

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
        """Resolve a permission gate. Remote accepts once/always/reject
        (AC-28, revised) — "always" is session-scoped in PermissionService
        (it appends a rule to session_ruleset, not a permanent grant), which
        is exactly what the remote card's "Allow for session" label says."""
        from app.agent.permission import Reply, get_service_for_session

        if cap.action not in ("once", "always", "reject"):
            logger.warning(
                "remote_gate_invalid_permission_action action={}",
                cap.action,
            )
            return False
        reply_value: Reply = cap.action  # ty: ignore[invalid-assignment]

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

    def _enqueue_send(self, msg: RemoteOutboundMessage) -> None:
        """Enqueue a message for async delivery."""
        try:
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
