"""Tests for remote secondary actions — slash commands and More-actions menus."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

import app.core.db as db_module
from app.models.chat import ChatSession
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
        self.cleared_destinations: list[str] = []
        self.clear_history_return_value: int = 3

    async def answer_callback(self, token: str) -> None:
        self.calls.append("answer_callback")
        self.acked_tokens.append(token)

    async def send(self, msg) -> None:
        self.calls.append("send")
        self.sent_texts.append(msg.text)
        self.sent_messages.append(msg)

    async def edit(self, msg) -> None:
        self.calls.append("edit")

    async def clear_history(self, destination_id: str) -> int:
        self.calls.append("clear_history")
        self.cleared_destinations.append(destination_id)
        return self.clear_history_return_value


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
        mock_db = MagicMock()
        action = _make_action(text="/help")
        with patch.object(
            service._pairing_service, "authorize", return_value=MagicMock()
        ):
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "ok"
        assert "/help" in result.text
        assert "/status" in result.text
        assert "/new" in result.text
        assert "/stop" in result.text
        assert "/settings" in result.text
        assert "/health" in result.text
        assert "/changes" in result.text
        assert "/unpair" in result.text
        assert "/actions" in result.text

    @pytest.mark.asyncio
    async def test_help_shows_pairing_prompt_when_unpaired(
        self, service: RemoteActionService
    ) -> None:
        """When no pairing exists, /help shows pairing prompt instead of help."""
        mock_db = MagicMock()
        action = _make_action(text="/help")
        with patch.object(service._pairing_service, "authorize", return_value=None):
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "pair_prompt"
        assert "pairing code" in result.text.lower()

    @pytest.mark.asyncio
    async def test_start_returns_help(self, service: RemoteActionService) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/start")
        with patch.object(
            service._pairing_service, "authorize", return_value=MagicMock()
        ):
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "ok"
        assert "/help" in result.text

    @pytest.mark.asyncio
    async def test_unknown_command_returns_help(
        self, service: RemoteActionService
    ) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/unknown")
        with patch.object(
            service._pairing_service, "authorize", return_value=MagicMock()
        ):
            result = await service.dispatch_command(mock_db, action)
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

        with (
            patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ),
            patch("app.remote.control.count_configured_providers", return_value=0),
            patch("app.remote.control.list_model_ids", return_value=[]),
            patch("app.remote.control.list_models_by_provider", return_value={}),
        ):
            result = await service.dispatch_command(mock_db, action)
        assert result.status == "ok"
        assert "My Phone" in result.text
        assert "EvoFlux Status" in result.text

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


# ── Settings ──────────────────────────────────────────────────────────────────


class TestSettings:
    @pytest.fixture(autouse=True)
    def _mock_home(self, tmp_path: Path) -> Iterator[None]:
        """``Path.home()`` fails on some CI Windows images; stub it with
        *tmp_path* so skill-discovery ``_iter_skill_roots`` does not crash."""
        with patch("pathlib.Path.home", return_value=tmp_path):
            yield

    @pytest.mark.asyncio
    async def test_settings_command_shows_current_mode_model_and_agent(
        self, service: RemoteActionService
    ) -> None:
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Settings test",
                mode="work",
                session_type="main",
                permission_mode="ask",
                model="anthropic:claude-sonnet-5",
                agent_name="evoflux",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            mock_pairing = MagicMock()
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"

            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                action = _make_action(text="/settings")
                result = await service.dispatch_command(db, action)

        assert result.status == "ok"
        assert "ask" in result.text
        assert "anthropic:claude-sonnet-5" in result.text
        assert "evoflux" in result.text

    @pytest.mark.asyncio
    async def test_settings_command_without_active_session_is_friendly(
        self, service: RemoteActionService
    ) -> None:
        mock_db = MagicMock()
        mock_pairing = MagicMock()
        mock_pairing.active_session_id = None

        with patch.object(
            service._pairing_service, "authorize", return_value=mock_pairing
        ):
            action = _make_action(text="/settings")
            result = await service.dispatch_command(mock_db, action)

        assert result.status == "ok"
        assert "no active task yet" in result.text.lower()

    @pytest.mark.asyncio
    async def test_mode_callback_applies_the_selected_mode(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Settings test",
                mode="work",
                session_type="main",
                permission_mode="auto",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            mock_pairing = MagicMock()
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"

            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                settings_action = _make_action(text="/settings", connection_id=conn_id)
                await service.dispatch_command(db, settings_action)

            sent_buttons = adapter.sent_messages[-1].buttons
            ask_token = next(
                b.token for b in sent_buttons if b.text == "Permission mode: ask"
            )

            callback_action = _make_action(
                kind=RemoteInboundActionKind.CALLBACK,
                callback_token=ask_token,
                connection_id=conn_id,
            )
            handled = await service.handle_action_callback(callback_action, db)

            assert handled is True
            refreshed = await db.get(ChatSession, session.id)
            assert refreshed is not None
            assert refreshed.permission_mode == "ask"

    @pytest.mark.asyncio
    async def test_response_mode_callback_applies_the_selected_mode(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        from app.models.remote import RemoteConnection, RemotePairing

        conn_id = uuid4()
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Settings test",
                mode="work",
                session_type="main",
                permission_mode="auto",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            connection = RemoteConnection(
                adapter="telegram",
                label="My phone",
                enabled=True,
                adapter_principal_id="bot-1",
                adapter_username="my_evoflux_bot",
            )
            db.add(connection)
            await db.commit()
            await db.refresh(connection)

            real_pairing = RemotePairing(
                connection_id=connection.id,
                principal_id="user-1",
                destination_id="chat-1",
                label="My Phone",
            )
            db.add(real_pairing)
            await db.commit()
            await db.refresh(real_pairing)

            mock_pairing = MagicMock()
            mock_pairing.id = real_pairing.id
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"
            mock_pairing.response_mode = "summary"

            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                settings_action = _make_action(text="/settings", connection_id=conn_id)
                await service.dispatch_command(db, settings_action)

            sent_buttons = adapter.sent_messages[-1].buttons
            live_token = next(
                b.token for b in sent_buttons if b.text == "Updates: live"
            )

            callback_action = _make_action(
                kind=RemoteInboundActionKind.CALLBACK,
                callback_token=live_token,
                connection_id=conn_id,
            )
            handled = await service.handle_action_callback(callback_action, db)

            assert handled is True
            refreshed = await db.get(RemotePairing, real_pairing.id)
            assert refreshed is not None
            assert refreshed.response_mode == "live"

    @pytest.mark.asyncio
    async def test_settings_command_shows_configured_provider_count(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Settings test",
                mode="work",
                session_type="main",
                permission_mode="ask",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            mock_pairing = MagicMock()
            mock_pairing.id = uuid4()
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"
            mock_pairing.response_mode = "summary"

            with (
                patch.object(
                    service._pairing_service, "authorize", return_value=mock_pairing
                ),
                patch(
                    "app.remote.control.count_configured_providers",
                    new=AsyncMock(return_value=2),
                ),
            ):
                settings_action = _make_action(text="/settings")
                await service.dispatch_command(db, settings_action)

            sent_text = adapter.sent_messages[-1].text
            assert "2 configured" in sent_text


# ── Health ────────────────────────────────────────────────────────────────────


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_command_shows_checks(
        self, service: RemoteActionService
    ) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/health")

        fake_diagnostics = {
            "checks": [
                {
                    "id": "db",
                    "label": "Database",
                    "status": "ok",
                    "detail": "connected",
                },
            ],
            "summary": "ok",
        }

        async def _fake_get_health_diagnostics():
            return fake_diagnostics

        with (
            patch.object(
                service._pairing_service, "authorize", return_value=MagicMock()
            ),
            patch(
                "app.remote.control.get_health_diagnostics",
                _fake_get_health_diagnostics,
            ),
        ):
            result = await service.dispatch_command(mock_db, action)

        assert result.status == "ok"
        assert "Database" in result.text

    @pytest.mark.asyncio
    async def test_health_requires_authorization(
        self, service: RemoteActionService
    ) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/health")

        with patch.object(service._pairing_service, "authorize", return_value=None):
            result = await service.dispatch_command(mock_db, action)

        assert result.status == "unauthorized"


# ── Clear ─────────────────────────────────────────────────────────────────────


class TestClear:
    @pytest.mark.asyncio
    async def test_clear_command_deletes_history_and_reports_the_count(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/clear")
        adapter.clear_history_return_value = 5

        with patch.object(
            service._pairing_service, "authorize", return_value=MagicMock()
        ):
            result = await service.dispatch_command(mock_db, action)

        assert result.status == "ok"
        assert "5" in result.text
        assert adapter.cleared_destinations == [action.principal.destination_id]

    @pytest.mark.asyncio
    async def test_clear_requires_authorization(
        self, service: RemoteActionService
    ) -> None:
        mock_db = MagicMock()
        action = _make_action(text="/clear")

        with patch.object(service._pairing_service, "authorize", return_value=None):
            result = await service.dispatch_command(mock_db, action)

        assert result.status == "unauthorized"

    @pytest.mark.asyncio
    async def test_clear_on_an_adapter_without_clear_support_says_so(self) -> None:
        class _NoClearAdapter:
            async def send(self, msg) -> None:
                pass

            async def edit(self, msg) -> None:
                pass

            async def answer_callback(self, token: str) -> None:
                pass

        service = RemoteActionService(adapter=_NoClearAdapter())  # type: ignore[arg-type]
        mock_db = MagicMock()
        action = _make_action(text="/clear")

        with patch.object(
            service._pairing_service, "authorize", return_value=MagicMock()
        ):
            result = await service.dispatch_command(mock_db, action)

        assert result.status == "ok"
        assert "clear" in result.text.lower()


# ── Changes ───────────────────────────────────────────────────────────────────


class TestChanges:
    @pytest.mark.asyncio
    async def test_changes_command_lists_files_with_counts(
        self, service: RemoteActionService
    ) -> None:
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Fix auth tests",
                mode="work",
                session_type="main",
                workspace="/tmp/fake-workspace",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            mock_pairing = MagicMock()
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"

            from app.services.turn_changes import ChangedFile, TurnChangesSnapshot

            fake_snapshot = TurnChangesSnapshot(
                session_id=str(session.id),
                files=[
                    ChangedFile(
                        path="app/auth.py", status="modified", additions=10, deletions=2
                    )
                ],
                additions=10,
                deletions=2,
            )

            with (
                patch.object(
                    service._pairing_service, "authorize", return_value=mock_pairing
                ),
                patch(
                    "app.services.turn_changes.get_latest",
                    return_value=fake_snapshot,
                ),
            ):
                action = _make_action(text="/changes")
                result = await service.dispatch_command(db, action)

        assert result.status == "ok"
        assert "app/auth.py" in result.text
        assert "+10" in result.text

    @pytest.mark.asyncio
    async def test_changes_command_without_active_session_is_friendly(
        self, service: RemoteActionService
    ) -> None:
        mock_db = MagicMock()
        mock_pairing = MagicMock()
        mock_pairing.active_session_id = None

        with patch.object(
            service._pairing_service, "authorize", return_value=mock_pairing
        ):
            action = _make_action(text="/changes")
            result = await service.dispatch_command(mock_db, action)

        assert result.status == "ok"
        assert "no active task yet" in result.text.lower()

    @pytest.mark.asyncio
    async def test_changes_diff_callback_fetches_and_sends_the_diff(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Fix auth tests",
                mode="work",
                session_type="main",
                workspace="/tmp/fake-workspace",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            mock_pairing = MagicMock()
            mock_pairing.active_session_id = session.id
            mock_pairing.label = "My Phone"

            from app.services.turn_changes import ChangedFile, TurnChangesSnapshot

            fake_snapshot = TurnChangesSnapshot(
                session_id=str(session.id),
                files=[
                    ChangedFile(
                        path="app/auth.py", status="modified", additions=10, deletions=2
                    )
                ],
                additions=10,
                deletions=2,
            )

            async def _fake_get_file_diff(workspace: str, path: str) -> str:
                return "--- a/app/auth.py\n+++ b/app/auth.py\n+fixed"

            with (
                patch.object(
                    service._pairing_service, "authorize", return_value=mock_pairing
                ),
                patch(
                    "app.services.turn_changes.get_latest",
                    return_value=fake_snapshot,
                ),
            ):
                changes_action = _make_action(text="/changes", connection_id=conn_id)
                await service.dispatch_command(db, changes_action)

            sent_buttons = adapter.sent_messages[-1].buttons
            file_token = next(b.token for b in sent_buttons if "app/auth.py" in b.text)

            with patch("app.remote.control.get_file_diff", _fake_get_file_diff):
                callback_action = _make_action(
                    kind=RemoteInboundActionKind.CALLBACK,
                    callback_token=file_token,
                    connection_id=conn_id,
                )
                handled = await service.handle_action_callback(callback_action, db)

            assert handled is True
            assert any("fixed" in text for text in adapter.sent_texts)


# ── Onboarding ────────────────────────────────────────────────────────────────


class TestOnboarding:
    @pytest.mark.asyncio
    async def test_build_onboarding_card_mints_three_distinct_tokens(
        self, service: RemoteActionService
    ) -> None:
        action = _make_action(text="/start")

        text, buttons = service.build_onboarding_card(action, label="My Phone")

        assert "My Phone" in text
        assert len(buttons) == 3
        tokens = {b.token for b in buttons}
        assert len(tokens) == 3  # all distinct

    @pytest.mark.asyncio
    async def test_onboarding_setup_button_behaves_like_settings(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        onboarding_action = _make_action(text="/start", connection_id=conn_id)
        _text, buttons = service.build_onboarding_card(
            onboarding_action, label="My Phone"
        )
        setup_token = next(b.token for b in buttons if "Set up" in b.text)

        mock_pairing = MagicMock()
        mock_pairing.active_session_id = None
        mock_pairing.label = "My Phone"

        async with db_module.async_session_factory() as db:
            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                callback_action = _make_action(
                    kind=RemoteInboundActionKind.CALLBACK,
                    callback_token=setup_token,
                    connection_id=conn_id,
                )
                handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        assert "No active task yet" in adapter.sent_messages[-1].text

    @pytest.mark.asyncio
    async def test_onboarding_health_button_sends_health_diagnostics(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        onboarding_action = _make_action(text="/start", connection_id=conn_id)
        _text, buttons = service.build_onboarding_card(
            onboarding_action, label="My Phone"
        )
        health_token = next(b.token for b in buttons if "Health" in b.text)

        mock_pairing = MagicMock()

        async with db_module.async_session_factory() as db:
            with (
                patch.object(
                    service._pairing_service, "authorize", return_value=mock_pairing
                ),
                patch(
                    "app.remote.control.get_health_diagnostics",
                    new=AsyncMock(return_value={"checks": []}),
                ),
            ):
                callback_action = _make_action(
                    kind=RemoteInboundActionKind.CALLBACK,
                    callback_token=health_token,
                    connection_id=conn_id,
                )
                handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        assert "Health" in adapter.sent_messages[-1].text

    @pytest.mark.asyncio
    async def test_onboarding_start_button_sends_a_friendly_prompt(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        onboarding_action = _make_action(text="/start", connection_id=conn_id)
        _text, buttons = service.build_onboarding_card(
            onboarding_action, label="My Phone"
        )
        start_token = next(b.token for b in buttons if "start" in b.text.lower())

        async with db_module.async_session_factory() as db:
            callback_action = _make_action(
                kind=RemoteInboundActionKind.CALLBACK,
                callback_token=start_token,
                connection_id=conn_id,
            )
            handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        assert adapter.sent_messages  # something was sent


# ── Session history (/history) ────────────────────────────────────────────────


class TestHistoryCommand:
    """Regression tests for /history, session_detail, session_switch,
    session_summarize — and the _issue_token parameter contract that caused
    repeated crashes when fields were missing."""

    @pytest.mark.asyncio
    async def test_history_returns_sessions_with_buttons(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        async with db_module.async_session_factory() as db:
            for i in range(3):
                db.add(
                    ChatSession(
                        title=f"Session {i}",
                        mode="work",
                        session_type="main",
                    )
                )
            await db.commit()

            mock_pairing = MagicMock()
            mock_pairing.active_session_id = None

            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                action = _make_action(text="/history")
                result = await service.dispatch_command(db, action)

        assert result.status == "ok"
        assert adapter.sent_messages, "history should send a message with buttons"
        sent = adapter.sent_messages[-1]
        assert len(sent.buttons) == 3, f"expected 3 buttons, got {len(sent.buttons)}"
        assert "Recent sessions" in sent.text

    @pytest.mark.asyncio
    async def test_history_with_no_sessions(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        async with db_module.async_session_factory() as db:
            mock_pairing = MagicMock()
            mock_pairing.active_session_id = None

            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                action = _make_action(text="/history")
                result = await service.dispatch_command(db, action)

        assert result.status == "ok"
        assert "no session" in result.text.lower()

    @pytest.mark.asyncio
    async def test_history_issue_token_contract(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        """Regression: _issue_token requires all fields — missing any causes
        TypeError that breaks chat until restart."""
        async with db_module.async_session_factory() as db:
            db.add(ChatSession(title="S1", mode="work", session_type="main"))
            await db.commit()

            mock_pairing = MagicMock()
            mock_pairing.active_session_id = None

            with patch.object(
                service._pairing_service, "authorize", return_value=mock_pairing
            ):
                action = _make_action(text="/history")
                result = await service.dispatch_command(db, action)

        assert result.status == "ok"
        assert adapter.sent_messages

    @pytest.mark.asyncio
    async def test_session_detail_shows_metadata(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Fix login bug",
                mode="coding",
                session_type="main",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            token = service._issue_token(
                action_kind="session_detail",
                action_target=str(session.id),
                connection_id=conn_id,
                principal_id="user-1",
                destination_id="chat-1",
                session_id="",
            )

            callback_action = _make_action(
                kind=RemoteInboundActionKind.CALLBACK,
                callback_token=token,
                connection_id=conn_id,
            )
            handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        assert adapter.sent_messages
        sent = adapter.sent_messages[-1]
        assert "Fix login bug" in sent.text
        button_texts = [b.text for b in sent.buttons]
        assert any("Switch" in t for t in button_texts)
        assert any("Summarize" in t for t in button_texts)

    @pytest.mark.asyncio
    async def test_session_switch_updates_active_session(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        from app.models.remote import RemoteConnection, RemotePairing

        conn_id = uuid4()
        async with db_module.async_session_factory() as db:
            # Create the connection first (FK dependency for pairing).
            connection = RemoteConnection(
                id=conn_id,
                adapter="telegram",
                label="TestConn",
                enabled=True,
                adapter_principal_id="user-1",
            )
            db.add(connection)

            session = ChatSession(
                title="Target",
                mode="work",
                session_type="main",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            pairing = RemotePairing(
                connection_id=conn_id,
                principal_id="user-1",
                destination_id="chat-1",
                label="Test",
            )
            db.add(pairing)
            await db.commit()
            await db.refresh(pairing)

            token = service._issue_token(
                action_kind="session_switch",
                action_target=str(session.id),
                connection_id=conn_id,
                principal_id="user-1",
                destination_id="chat-1",
                session_id="",
            )

            with patch.object(
                service._pairing_service, "authorize", return_value=pairing
            ):
                callback_action = _make_action(
                    kind=RemoteInboundActionKind.CALLBACK,
                    callback_token=token,
                    connection_id=conn_id,
                )
                handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        assert pairing.active_session_id == session.id
        assert "Switched" in adapter.sent_texts[-1]

    @pytest.mark.asyncio
    async def test_session_summarize_shows_transcript(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        from app.models.chat import SessionMessage

        conn_id = uuid4()
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Chat",
                mode="work",
                session_type="main",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            for role, content in [
                ("user", "Fix the login bug"),
                ("assistant", "I found the issue in auth.ts"),
                ("user", "Also check the tests"),
                ("assistant", "Tests pass now"),
            ]:
                db.add(
                    SessionMessage(session_id=session.id, role=role, content=content)
                )
            await db.commit()

            token = service._issue_token(
                action_kind="session_summarize",
                action_target=str(session.id),
                connection_id=conn_id,
                principal_id="user-1",
                destination_id="chat-1",
                session_id="",
            )

            callback_action = _make_action(
                kind=RemoteInboundActionKind.CALLBACK,
                callback_token=token,
                connection_id=conn_id,
            )
            handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        text = adapter.sent_texts[-1]
        assert "Session transcript" in text
        assert "Fix the login bug" in text
        assert "auth.ts" in text

    @pytest.mark.asyncio
    async def test_session_summarize_empty_session(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        async with db_module.async_session_factory() as db:
            session = ChatSession(
                title="Empty",
                mode="work",
                session_type="main",
            )
            db.add(session)
            await db.commit()
            await db.refresh(session)

            token = service._issue_token(
                action_kind="session_summarize",
                action_target=str(session.id),
                connection_id=conn_id,
                principal_id="user-1",
                destination_id="chat-1",
                session_id="",
            )

            callback_action = _make_action(
                kind=RemoteInboundActionKind.CALLBACK,
                callback_token=token,
                connection_id=conn_id,
            )
            handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        assert "No messages" in adapter.sent_texts[-1]

    @pytest.mark.asyncio
    async def test_session_detail_deleted_session(
        self, service: RemoteActionService, adapter: FakeAdapter
    ) -> None:
        conn_id = uuid4()
        token = service._issue_token(
            action_kind="session_detail",
            action_target=str(uuid4()),
            connection_id=conn_id,
            principal_id="user-1",
            destination_id="chat-1",
            session_id="",
        )

        async with db_module.async_session_factory() as db:
            callback_action = _make_action(
                kind=RemoteInboundActionKind.CALLBACK,
                callback_token=token,
                connection_id=conn_id,
            )
            handled = await service.handle_action_callback(callback_action, db)

        assert handled is True
        assert "not found" in adapter.sent_texts[-1].lower()

    def test_issue_token_requires_all_fields(
        self, service: RemoteActionService
    ) -> None:
        conn_id = uuid4()

        with pytest.raises(TypeError, match="principal_id"):
            service._issue_token(
                action_kind="session_detail",
                action_target="x",
                connection_id=conn_id,
                destination_id="d",
                session_id="",
            )

        with pytest.raises(TypeError, match="destination_id"):
            service._issue_token(
                action_kind="session_detail",
                action_target="x",
                connection_id=conn_id,
                principal_id="p",
                session_id="",
            )

        with pytest.raises(TypeError, match="session_id"):
            service._issue_token(
                action_kind="session_detail",
                action_target="x",
                connection_id=conn_id,
                principal_id="p",
                destination_id="d",
            )

    def test_history_is_in_slash_commands(self) -> None:
        assert "history" in _SLASH_COMMANDS
        assert is_slash_command("/history")
