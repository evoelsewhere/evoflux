"""Tests for remote secondary actions — slash commands and More-actions menus."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.remote.actions import (
    RemoteActionService,
    RemoteMenuItem,
    is_slash_command,
    _SLASH_COMMANDS,
)
from app.remote.contracts import (
    RemoteInboundAction,
    RemoteInboundActionKind,
    RemoteOutboundPriority,
    RemotePrincipal,
)
from app.remote.outbound import RemoteProjection


# ── Fixtures ──────────────────────────────────────────────────────────────────


class FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.acked_tokens: list[str] = []
        self.sent_texts: list[str] = []
        self.sent_messages: list = []

    async def answer_callback(self, token: str) -> None:
        self.calls.append("answer_callback")
        self.acked_tokens.append(token)

    async def send(self, msg) -> None:
        self.calls.append("send")
        self.sent_texts.append(msg.text)
        self.sent_messages.append(msg)

    async def edit(self, msg) -> None:
        self.calls.append("edit")


def _make_action(
    *,
    text: str = "/help",
    connection_id=None,
    principal_id: str = "user-1",
    destination_id: str = "chat-1",
    kind=RemoteInboundActionKind.TEXT,
    callback_token: str | None = None,
) -> RemoteInboundAction:
    conn = connection_id or uuid4()
    return RemoteInboundAction(
        connection_id=conn,
        kind=kind,
        principal=RemotePrincipal(
            connection_id=conn,
            principal_id=principal_id,
            destination_id=destination_id,
        ),
        source_key="test:source",
        text=text,
        callback_token=callback_token,
    )


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def service(adapter: FakeAdapter) -> RemoteActionService:
    return RemoteActionService(adapter=adapter)  # type: ignore[arg-type]


# ── Command validation ────────────────────────────────────────────────────────


class TestCommandValidation:
    def test_is_slash_command_recognized(self) -> None:
        for cmd in _SLASH_COMMANDS:
            assert is_slash_command(f"/{cmd}")

    def test_is_slash_command_unknown(self) -> None:
        assert not is_slash_command("/unknown")
        assert not is_slash_command("/hack")

    def test_is_slash_command_not_command(self) -> None:
        assert not is_slash_command("hello")
        assert not is_slash_command("")

    def test_no_command_accepts_credentials(self) -> None:
        """No command should accept credential-like arguments."""
        for cmd in _SLASH_COMMANDS:
            _make_action(text=f"/{cmd} sk-secret-token-12345")

    def test_no_command_accepts_paths(self) -> None:
        """No command should accept repository paths."""
        for cmd in _SLASH_COMMANDS:
            _make_action(text=f"/{cmd} /etc/passwd")


# ── Slash commands ────────────────────────────────────────────────────────────


class TestSlashCommands:
    @pytest.mark.asyncio
    async def test_help_returns_help_text(self, service: RemoteActionService) -> None:
        action = _make_action(text="/help")
        result = await service.dispatch_command(MagicMock(), action)
        assert result.status == "ok"
        assert "/help" in result.text
        assert "/status" in result.text
        assert "/new" in result.text
        assert "/stop" in result.text
        assert "/unpair" in result.text
        assert "/actions" in result.text

    @pytest.mark.asyncio
    async def test_start_returns_help(self, service: RemoteActionService) -> None:
        action = _make_action(text="/start")
        result = await service.dispatch_command(MagicMock(), action)
        assert result.status == "ok"
        assert "/help" in result.text

    @pytest.mark.asyncio
    async def test_unknown_command_returns_help(
        self, service: RemoteActionService
    ) -> None:
        action = _make_action(text="/unknown")
        result = await service.dispatch_command(MagicMock(), action)
        assert result.status == "ok"
        assert "/help" in result.text

    @pytest.mark.asyncio
    async def test_status_requires_authorization(
        self, service: RemoteActionService
    ) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/status")

        with patch.object(service._pairing_service, "authorize", return_value=None):
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "unauthorized"

    @pytest.mark.asyncio
    async def test_status_shows_connection_info(
        self, service: RemoteActionService
    ) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/status")

        mock_pairing = MagicMock()
        mock_pairing.active_session_id = None
        mock_pairing.label = "My Phone"

        with patch.object(
            service._pairing_service, "authorize", return_value=mock_pairing
        ):
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "ok"
        assert "Paired: My Phone" in result.text

    @pytest.mark.asyncio
    async def test_new_clears_current_task(self, service: RemoteActionService) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/new")

        with patch("app.remote.inbound.RemoteInboundService") as MockInbound:
            mock_inbound = MockInbound.return_value
            mock_result = MagicMock(status="current_task_cleared")

            async def _mock_new_task(*a, **k):
                return mock_result

            mock_inbound.new_task = _mock_new_task
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "ok"
        assert "cleared" in result.text.lower()

    @pytest.mark.asyncio
    async def test_stop_unauthorized(self, service: RemoteActionService) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/stop")

        with patch("app.remote.inbound.RemoteInboundService") as MockInbound:
            mock_inbound = MockInbound.return_value
            mock_result = MagicMock(status="unauthorized")

            async def _mock_stop(*a, **k):
                return mock_result

            mock_inbound.stop_current = _mock_stop
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "unauthorized"

    @pytest.mark.asyncio
    async def test_stop_no_active_turn(self, service: RemoteActionService) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/stop")

        with patch("app.remote.inbound.RemoteInboundService") as MockInbound:
            mock_inbound = MockInbound.return_value
            mock_result = MagicMock(status="no_active_turn")

            async def _mock_stop(*a, **k):
                return mock_result

            mock_inbound.stop_current = _mock_stop
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "ok"
        assert "No active task" in result.text

    @pytest.mark.asyncio
    async def test_unpair_removes_pairing(self, service: RemoteActionService) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/unpair")

        with patch.object(service._pairing_service, "unpair", return_value=True):
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "ok"
        assert "unpair" in result.text.lower()

    @pytest.mark.asyncio
    async def test_unpair_clears_the_active_pairing_cache(
        self, service: RemoteActionService
    ) -> None:
        """AC-10 (immediate revocation): /unpair must stop all communication
        to the former principal right away — including notifications routed
        through the projection's active-pairing cache, not just callback and
        menu tokens."""
        projection = RemoteProjection()
        connection_id = uuid4()
        projection.set_active_pairing(
            connection_id=str(connection_id),
            destination_id="chat-1",
            notify_scope="all",
            principal_id="user-1",
        )
        service.set_projection(projection)
        action = _make_action(text="/unpair", connection_id=connection_id)
        mock_db = MagicMock()

        with patch.object(service._pairing_service, "unpair", return_value=True):
            await service.dispatch_command(mock_db, action)

        assert projection.active_pairing() is None

    @pytest.mark.asyncio
    async def test_unpair_with_no_projection_bound_does_not_raise(
        self, service: RemoteActionService
    ) -> None:
        """set_projection defaults to None — /unpair must stay safe before
        the runtime ever binds a projection."""
        action = _make_action(text="/unpair")
        mock_db = MagicMock()

        with patch.object(service._pairing_service, "unpair", return_value=True):
            result = await service.dispatch_command(mock_db, action)

        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_unpair_with_no_existing_pairing_leaves_cache_untouched(
        self, service: RemoteActionService
    ) -> None:
        """A no-op unpair (nothing to remove) must not clear an unrelated
        active pairing."""
        projection = RemoteProjection()
        projection.set_active_pairing(
            connection_id=str(uuid4()),
            destination_id="chat-1",
            notify_scope="all",
            principal_id="user-1",
        )
        service.set_projection(projection)
        action = _make_action(text="/unpair")
        mock_db = MagicMock()

        with patch.object(service._pairing_service, "unpair", return_value=False):
            await service.dispatch_command(mock_db, action)

        assert projection.active_pairing() is not None


# ── Callback handling ─────────────────────────────────────────────────────────


class TestCallbackHandling:
    def test_register_capability_returns_usable_token(
        self, service: RemoteActionService
    ) -> None:
        token = service.register_capability(
            connection_id=uuid4(),
            principal_id="user-1",
            destination_id="chat-1",
            session_id="sess-1",
            action_kind="toollog",
            action_target="log text",
        )

        assert isinstance(token, str)
        assert token
        assert len(token.encode("utf-8")) <= 64

    @pytest.mark.asyncio
    async def test_toollog_capability_sends_escaped_stored_content(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        connection_id = uuid4()
        token = service.register_capability(
            connection_id=connection_id,
            principal_id="user-1",
            destination_id="chat-1",
            session_id="sess-1",
            action_kind="toollog",
            action_target="write <script>alert(1)</script>",
        )
        action = _make_action(
            kind=RemoteInboundActionKind.CALLBACK,
            callback_token=token,
            connection_id=connection_id,
        )

        handled = await service.handle_action_callback(action, MagicMock())

        assert handled is True
        assert adapter.calls == ["answer_callback", "send"]
        assert "&lt;script&gt;" in adapter.sent_texts[0]
        assert "<script>" not in adapter.sent_texts[0]
        assert adapter.sent_messages[0].priority == RemoteOutboundPriority.HIGH

    @pytest.mark.asyncio
    async def test_detail_capability_splits_escaped_content_with_valid_html(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        connection_id = uuid4()
        token = service.register_capability(
            connection_id=connection_id,
            principal_id="user-1",
            destination_id="chat-1",
            session_id="sess-1",
            action_kind="toollog",
            action_target="<" * 5_000,
        )
        action = _make_action(
            kind=RemoteInboundActionKind.CALLBACK,
            callback_token=token,
            connection_id=connection_id,
        )

        handled = await service.handle_action_callback(action, MagicMock())

        assert handled is True
        assert len(adapter.sent_texts) > 1
        assert all(len(text) <= 4096 for text in adapter.sent_texts)
        assert all(text.count("<pre>") == 1 for text in adapter.sent_texts)
        assert all(text.endswith("</pre>") for text in adapter.sent_texts)
        assert all("&lt;" in text for text in adapter.sent_texts)

    @pytest.mark.asyncio
    async def test_detail_capability_refuses_a_different_principal(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        connection_id = uuid4()
        token = service.register_capability(
            connection_id=connection_id,
            principal_id="user-1",
            destination_id="chat-1",
            session_id="sess-1",
            action_kind="diff",
            action_target="diff text",
        )
        action = _make_action(
            kind=RemoteInboundActionKind.CALLBACK,
            callback_token=token,
            connection_id=connection_id,
            principal_id="other-user",
        )

        handled = await service.handle_action_callback(action, MagicMock())

        assert handled is False
        assert adapter.calls == []

    @pytest.mark.asyncio
    async def test_detail_capability_refuses_a_different_destination(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        connection_id = uuid4()
        token = service.register_capability(
            connection_id=connection_id,
            principal_id="user-1",
            destination_id="chat-1",
            session_id="sess-1",
            action_kind="diff",
            action_target="diff text",
        )
        action = _make_action(
            kind=RemoteInboundActionKind.CALLBACK,
            callback_token=token,
            connection_id=connection_id,
            destination_id="other-chat",
        )

        handled = await service.handle_action_callback(action, MagicMock())

        assert handled is False
        assert adapter.calls == []

    @pytest.mark.asyncio
    async def test_expired_detail_capability_replies_with_a_friendly_message(
        self, service: RemoteActionService, adapter: FakeAdapter, monkeypatch
    ) -> None:
        connection_id = uuid4()
        token = service.register_capability(
            connection_id=connection_id,
            principal_id="user-1",
            destination_id="chat-1",
            session_id="sess-1",
            action_kind="diff",
            action_target="diff text",
        )
        issued_at = service._capabilities[token].created_at
        monkeypatch.setattr(
            "app.remote.actions.time.monotonic",
            lambda: issued_at + 601,
        )
        action = _make_action(
            kind=RemoteInboundActionKind.CALLBACK,
            callback_token=token,
            connection_id=connection_id,
        )

        handled = await service.handle_action_callback(action, MagicMock())

        assert handled is True
        assert adapter.calls == ["answer_callback", "send"]
        assert "expired" in adapter.sent_texts[0].lower()

    @pytest.mark.asyncio
    async def test_unknown_callback_returns_false(
        self, service: RemoteActionService
    ) -> None:
        action = _make_action(
            kind=RemoteInboundActionKind.CALLBACK,
            callback_token="nonexistent",
        )
        result = await service.handle_action_callback(action, MagicMock())
        assert result is False

    @pytest.mark.asyncio
    async def test_expired_callback_returns_false(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        token = service._issue_token(
            connection_id=conn_id,
            principal_id="u1",
            destination_id="c1",
            session_id="",
            action_kind="workflow_start",
            action_target="test",
        )
        # Expire the capability.
        cap = service._capabilities[token]
        from app.remote.actions import _ActionCapability

        expired = _ActionCapability(
            token=cap.token,
            connection_id=cap.connection_id,
            principal_id=cap.principal_id,
            destination_id=cap.destination_id,
            session_id=cap.session_id,
            action_kind=cap.action_kind,
            action_target=cap.action_target,
            created_at=time.monotonic() - 700,
        )
        service._capabilities[token] = expired

        action = _make_action(
            kind=RemoteInboundActionKind.CALLBACK,
            callback_token=token,
            connection_id=conn_id,
            principal_id="u1",
            destination_id="c1",
        )
        result = await service.handle_action_callback(action, MagicMock())
        assert result is False

    @pytest.mark.asyncio
    async def test_wrong_connection_returns_false(
        self, service: RemoteActionService
    ) -> None:
        token = service._issue_token(
            connection_id=uuid4(),
            principal_id="u1",
            destination_id="c1",
            session_id="",
            action_kind="workflow_start",
            action_target="test",
        )
        action = _make_action(
            kind=RemoteInboundActionKind.CALLBACK,
            callback_token=token,
            connection_id=uuid4(),  # different connection
        )
        result = await service.handle_action_callback(action, MagicMock())
        assert result is False

    @pytest.mark.asyncio
    async def test_no_callback_token_returns_false(
        self, service: RemoteActionService
    ) -> None:
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
        result = await service.handle_action_callback(action, MagicMock())
        assert result is False


# ── Token constraints ─────────────────────────────────────────────────────────


class TestTokenConstraints:
    def test_tokens_under_64_bytes(self, service: RemoteActionService) -> None:
        for _ in range(50):
            token = service._issue_token(
                connection_id=uuid4(),
                principal_id="u1",
                destination_id="c1",
                session_id="",
                action_kind="test",
                action_target="target",
            )
            assert len(token.encode("utf-8")) <= 64

    def test_tokens_are_unique(self, service: RemoteActionService) -> None:
        tokens = set()
        for _ in range(100):
            token = service._issue_token(
                connection_id=uuid4(),
                principal_id="u1",
                destination_id="c1",
                session_id="",
                action_kind="test",
                action_target="target",
            )
            tokens.add(token)
        assert len(tokens) == 100


# ── Menu loading ──────────────────────────────────────────────────────────────


class TestMenuLoading:
    @pytest.mark.asyncio
    async def test_actions_command_loads_menu(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/actions")

        with patch.object(service, "_load_action_menu", return_value=[]):
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "ok"
        assert "No additional actions" in result.text

    @pytest.mark.asyncio
    async def test_actions_with_items_sends_buttons(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/actions")

        items = [
            RemoteMenuItem(token="t1", label="Item 1", description="Desc 1"),
            RemoteMenuItem(token="t2", label="Item 2"),
        ]

        with patch.object(service, "_load_action_menu", return_value=items):
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "ok"
        assert "Item 1" in result.text
        assert "Item 2" in result.text
