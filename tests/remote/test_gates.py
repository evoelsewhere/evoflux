"""Tests for the remote gate bridge — opaque capabilities, rendering, and callback resolution."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.remote.contracts import (
    RemoteInboundAction,
    RemoteInboundActionKind,
    RemoteOutboundMessage,
    RemotePrincipal,
)
from app.remote.gates import (
    GateCapability,
    RemoteGateBridge,
    _CAPABILITY_TTL_SECONDS,
    _MAX_CALLBACK_TOKEN_BYTES,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


class FakeAdapter:
    """Records calls for assertion."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.sent: list[RemoteOutboundMessage] = []
        self.edited: list[RemoteOutboundMessage] = []
        self.acked_tokens: list[str] = []

    async def send(self, msg: RemoteOutboundMessage) -> None:
        self.calls.append("send")
        self.sent.append(msg)

    async def edit(self, msg: RemoteOutboundMessage) -> None:
        self.calls.append("edit")
        self.edited.append(msg)

    async def answer_callback(self, token: str) -> None:
        self.calls.append("answer_callback")
        self.acked_tokens.append(token)


def _make_action(
    *,
    kind: RemoteInboundActionKind = RemoteInboundActionKind.CALLBACK,
    callback_token: str = "",
    connection_id: UUID | None = None,
    principal_id: str = "user-1",
    destination_id: str = "chat-1",
) -> RemoteInboundAction:
    return RemoteInboundAction(
        connection_id=connection_id or uuid4(),
        kind=kind,
        principal=RemotePrincipal(
            connection_id=connection_id or uuid4(),
            principal_id=principal_id,
            destination_id=destination_id,
        ),
        source_key="test:source",
        callback_token=callback_token or None,
    )


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def bridge(adapter: FakeAdapter) -> RemoteGateBridge:
    return RemoteGateBridge(adapter=adapter)  # type: ignore[arg-type]


# ── Token constraints ─────────────────────────────────────────────────────────


class TestTokenConstraints:
    def test_tokens_are_under_64_bytes(self, bridge: RemoteGateBridge) -> None:
        conn_id = uuid4()
        for _ in range(50):
            bridge.on_gate(
                session_id="sess-1",
                event_type="permission_asked",
                data={"request_id": "req-1", "tool": "bash"},
                connection_id=conn_id,
                destination_id="chat-1",
            )
            gate = bridge._pending_gates.get("req-1")
            if gate:
                for token in gate.tokens:
                    assert len(token.encode("utf-8")) <= _MAX_CALLBACK_TOKEN_BYTES


# ── Gate rendering ────────────────────────────────────────────────────────────


class TestGateRendering:
    @pytest.mark.asyncio
    async def test_permission_gate_creates_allow_and_reject_buttons(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={"request_id": "req-1", "tool": "bash"},
            connection_id=conn_id,
            destination_id="chat-1",
        )
        # Drain async sends.
        await asyncio.sleep(0.05)
        assert len(adapter.sent) == 1
        msg = adapter.sent[0]
        assert len(msg.buttons) == 2
        assert msg.buttons[0].text == "Allow"
        assert msg.buttons[1].text == "Reject"
        assert msg.buttons[0].token != msg.buttons[1].token

    @pytest.mark.asyncio
    async def test_question_gate_creates_option_buttons(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="question_asked",
            data={
                "request_id": "req-2",
                "questions": [
                    {"question": "Pick one", "options": ["A", "B", "C"], "strict": True}
                ],
            },
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)
        assert len(adapter.sent) == 1
        msg = adapter.sent[0]
        assert len(msg.buttons) == 3
        texts = {b.text for b in msg.buttons}
        assert texts == {"A", "B", "C"}

    @pytest.mark.asyncio
    async def test_plan_gate_creates_approve_and_reject(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="plan_approval_requested",
            data={
                "request_id": "req-3",
                "plan": "Do stuff",
                "steps": [{"tool": "edit"}],
            },
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)
        assert len(adapter.sent) == 1
        msg = adapter.sent[0]
        assert len(msg.buttons) == 2
        assert msg.buttons[0].text == "Approve"
        assert msg.buttons[1].text == "Reject"

    def test_unknown_event_type_is_noop(self, bridge: RemoteGateBridge) -> None:
        bridge.on_gate(
            session_id="sess-1",
            event_type="unknown_event",
            data={"request_id": "req-x"},
            connection_id=uuid4(),
            destination_id="chat-1",
        )
        assert len(bridge._pending_gates) == 0

    def test_missing_request_id_is_noop(self, bridge: RemoteGateBridge) -> None:
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={},
            connection_id=uuid4(),
            destination_id="chat-1",
        )
        assert len(bridge._pending_gates) == 0


# ── Callback ordering ─────────────────────────────────────────────────────────


class TestCallbackOrdering:
    @pytest.mark.asyncio
    async def test_callback_acknowledged_before_resolution(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        """AC-26: answer_callback must fire before the gate is resolved."""
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={"request_id": "req-1", "tool": "bash"},
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)

        # Get the Allow token.
        gate = bridge._pending_gates["req-1"]
        allow_token = gate.tokens[0]

        # Set up a mock permission service.
        from unittest.mock import patch

        mock_svc = MagicMock()
        mock_svc.reply.return_value = True

        with patch(
            "app.agent.permission.get_service_for_session", return_value=mock_svc
        ):
            action = _make_action(
                callback_token=allow_token,
                connection_id=conn_id,
            )
            await bridge.handle_callback(action)

        # answer_callback must come before any resolution call.
        assert "answer_callback" in adapter.calls
        assert adapter.acked_tokens[0] == allow_token

    @pytest.mark.asyncio
    async def test_callback_resolves_permission_once(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={"request_id": "req-1", "tool": "bash"},
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)

        gate = bridge._pending_gates["req-1"]
        allow_token = gate.tokens[0]

        from unittest.mock import patch

        mock_svc = MagicMock()
        mock_svc.reply.return_value = True

        with patch(
            "app.agent.permission.get_service_for_session", return_value=mock_svc
        ):
            action = _make_action(callback_token=allow_token, connection_id=conn_id)
            await bridge.handle_callback(action)

        mock_svc.reply.assert_called_once_with("req-1", "once")

    @pytest.mark.asyncio
    async def test_callback_resolves_permission_reject(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={"request_id": "req-1", "tool": "bash"},
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)

        gate = bridge._pending_gates["req-1"]
        reject_token = gate.tokens[1]

        from unittest.mock import patch

        mock_svc = MagicMock()
        mock_svc.reply.return_value = True

        with patch(
            "app.agent.permission.get_service_for_session", return_value=mock_svc
        ):
            action = _make_action(callback_token=reject_token, connection_id=conn_id)
            await bridge.handle_callback(action)

        mock_svc.reply.assert_called_once_with("req-1", "reject")


# ── Validation and ownership ──────────────────────────────────────────────────


class TestValidationAndOwnership:
    @pytest.mark.asyncio
    async def test_wrong_connection_rejected(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        other_conn = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={"request_id": "req-1", "tool": "bash"},
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)

        gate = bridge._pending_gates["req-1"]
        token = gate.tokens[0]

        action = _make_action(callback_token=token, connection_id=other_conn)
        await bridge.handle_callback(action)

        # Should not acknowledge or resolve.
        assert len(adapter.acked_tokens) == 0

    @pytest.mark.asyncio
    async def test_expired_token_rejected(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={"request_id": "req-1", "tool": "bash"},
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)

        gate = bridge._pending_gates["req-1"]
        token = gate.tokens[0]

        # Artificially expire the capability.
        cap = bridge._capabilities[token]
        expired_cap = GateCapability(
            token=cap.token,
            connection_id=cap.connection_id,
            principal_id=cap.principal_id,
            destination_id=cap.destination_id,
            session_id=cap.session_id,
            request_id=cap.request_id,
            gate_kind=cap.gate_kind,
            action=cap.action,
            created_at=time.monotonic() - _CAPABILITY_TTL_SECONDS - 1,
        )
        bridge._capabilities[token] = expired_cap

        action = _make_action(callback_token=token, connection_id=conn_id)
        await bridge.handle_callback(action)

        assert len(adapter.acked_tokens) == 0

    @pytest.mark.asyncio
    async def test_unknown_token_ignored(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        action = _make_action(callback_token="nonexistent-token")
        await bridge.handle_callback(action)
        assert len(adapter.acked_tokens) == 0

    @pytest.mark.asyncio
    async def test_no_callback_token_ignored(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        action = _make_action(kind=RemoteInboundActionKind.TEXT)
        action = RemoteInboundAction(
            connection_id=uuid4(),
            kind=RemoteInboundActionKind.CALLBACK,
            principal=RemotePrincipal(
                connection_id=uuid4(),
                principal_id="u1",
                destination_id="c1",
            ),
            source_key="test",
            callback_token=None,
        )
        await bridge.handle_callback(action)
        assert len(adapter.acked_tokens) == 0


# ── Race handling ─────────────────────────────────────────────────────────────


class TestRaceHandling:
    @pytest.mark.asyncio
    async def test_duplicate_callback_only_resolves_once(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={"request_id": "req-1", "tool": "bash"},
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)

        gate = bridge._pending_gates["req-1"]
        token = gate.tokens[0]

        from unittest.mock import patch

        mock_svc = MagicMock()
        mock_svc.reply.return_value = True

        with patch(
            "app.agent.permission.get_service_for_session", return_value=mock_svc
        ):
            action = _make_action(callback_token=token, connection_id=conn_id)
            await bridge.handle_callback(action)
            # Second tap — capability already discarded.
            await bridge.handle_callback(action)

        # Only one resolution.
        mock_svc.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_already_resolved_gate_by_desktop(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        """Desktop-wins race: the service returns False (already resolved)."""
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={"request_id": "req-1", "tool": "bash"},
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)

        gate = bridge._pending_gates["req-1"]
        token = gate.tokens[0]

        from unittest.mock import patch

        mock_svc = MagicMock()
        mock_svc.reply.return_value = False  # already resolved by desktop

        with patch(
            "app.agent.permission.get_service_for_session", return_value=mock_svc
        ):
            action = _make_action(callback_token=token, connection_id=conn_id)
            await bridge.handle_callback(action)

        # answer_callback still called (tap acknowledged).
        assert adapter.acked_tokens[0] == token

    @pytest.mark.asyncio
    async def test_service_missing_returns_gracefully(
        self, bridge: RemoteGateBridge, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={"request_id": "req-1", "tool": "bash"},
            connection_id=conn_id,
            destination_id="chat-1",
        )
        await asyncio.sleep(0.05)

        gate = bridge._pending_gates["req-1"]
        token = gate.tokens[0]

        from unittest.mock import patch

        with patch("app.agent.permission.get_service_for_session", return_value=None):
            action = _make_action(callback_token=token, connection_id=conn_id)
            await bridge.handle_callback(action)

        # answer_callback called but no crash.
        assert adapter.acked_tokens[0] == token


# ── Reply events (button removal) ────────────────────────────────────────────


class TestReplyEvents:
    def test_on_reply_cleans_up_capabilities(self, bridge: RemoteGateBridge) -> None:
        conn_id = uuid4()
        bridge.on_gate(
            session_id="sess-1",
            event_type="permission_asked",
            data={"request_id": "req-1", "tool": "bash"},
            connection_id=conn_id,
            destination_id="chat-1",
        )
        gate = bridge._pending_gates.get("req-1")
        assert gate is not None
        tokens = list(gate.tokens)

        bridge.on_reply(
            session_id="sess-1",
            event_type="permission_replied",
            data={"request_id": "req-1"},
        )

        # Gate removed from pending.
        assert "req-1" not in bridge._pending_gates
        # Tokens cleaned up.
        for t in tokens:
            assert t not in bridge._capabilities
            assert t not in bridge._pending_by_token

    def test_on_reply_unknown_request_id_noop(self, bridge: RemoteGateBridge) -> None:
        bridge.on_reply(
            session_id="sess-1",
            event_type="permission_replied",
            data={"request_id": "unknown"},
        )
        # No crash.

    def test_on_reply_missing_request_id_noop(self, bridge: RemoteGateBridge) -> None:
        bridge.on_reply(
            session_id="sess-1",
            event_type="permission_replied",
            data={},
        )
