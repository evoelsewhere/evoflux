"""WebBridge — manager, relay WS endpoints, auth, and tool-level tests.

The relay endpoints run in a real (in-process) app via ``TestClient``; the
manager is exercised directly with a fake ``send`` callable for the
correlation/timeout paths that are awkward to drive over the wire.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlmodel import select
from starlette.websockets import WebSocketDisconnect

from app.agent.schemas.chat import ImageDataBlock, TextBlock, ToolResult
from app.agent.tools.builtin.webbridge_tool import AnyAction, webbridge
from app.api.routes.team.webbridge import InteractionRequest, router
from app.models.chat import SessionMessage
from app.models.webbridge import WebBridgeInteraction, WebBridgeTeachDraft
from app.services.webbridge_pairing_service import (
    PairingGrant,
    WebBridgePairingCodeStore,
    WebBridgeRateLimiter,
    WebBridgeTicketStore,
    authenticate_pairing,
    claim_interaction_dispatch,
    create_or_get_interaction,
    create_pairing,
    list_tab_bindings,
    upsert_tab_binding,
    webbridge_pairing_code_store,
    webbridge_ticket_store,
)
from app.services.webbridge_service import WebBridgeManager
from app.services.interactive_message_service import (
    InteractiveMessageResult,
    submit_persisted_interactive_message,
)

_PREFIX = "/api/team/webbridge"

_ACTION = TypeAdapter(AnyAction)


def _action(payload: dict):
    """Build an action model the way the LLM-facing schema would."""
    return _ACTION.validate_python(payload)


def test_tool_and_extension_action_contracts_match():
    background = (
        Path(__file__).resolve().parents[2]
        / "extensions"
        / "webbridge"
        / "background.js"
    ).read_text(encoding="utf-8")
    command_switch = background[
        background.index("async function handleCommand") : background.index(
            "function sendResponse"
        )
    ]
    extension_actions = set(re.findall(r'case "([a-z_]+)":', command_switch))
    tool_actions = set(_ACTION.json_schema()["discriminator"]["mapping"])

    # crawl is a backend orchestration action composed from extension commands.
    assert tool_actions - {"crawl"} == extension_actions


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> WebBridgeManager:
    """Fresh manager per test, swapped into every module that holds a reference."""
    mgr = WebBridgeManager()
    monkeypatch.setattr("app.services.webbridge_service.webbridge_manager", mgr)
    monkeypatch.setattr("app.api.routes.team.webbridge.webbridge_manager", mgr)
    monkeypatch.setattr("app.agent.tools.builtin.webbridge_tool.webbridge_manager", mgr)
    return mgr


@pytest.fixture
def client(manager: WebBridgeManager) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix=_PREFIX)
    return TestClient(app)


def _register(ws, extension_id: str = "ext-1") -> dict:
    ws.send_text(
        json.dumps(
            {
                "type": "register",
                "extension_id": extension_id,
                "browser": "chrome",
                "version": "120.0",
            }
        )
    )
    return json.loads(ws.receive_text())


def _pair_extension(client: TestClient, label: str = "Work Chrome") -> dict:
    code = webbridge_pairing_code_store.issue(label)
    exchange = client.post(
        f"{_PREFIX}/pairing/exchange",
        json={
            "code": code,
            "browser": "chrome",
            "version": "1.2.0",
        },
    )
    assert exchange.status_code == 201
    return exchange.json()


def _assign_pairing_session(
    client: TestClient, pairing: dict, session_id: UUID | str
) -> dict:
    response = client.put(
        f"{_PREFIX}/pairings/{pairing['pairing_id']}/sessions/{session_id}"
    )
    assert response.status_code == 200
    return response.json()


async def _persist_delivered_interactive_message(
    db,
    *,
    session,
    content: str,
    message_extra: dict | None = None,
    persisted_message: SessionMessage | None = None,
    **kwargs,
) -> InteractiveMessageResult:
    async with db.begin():
        row = persisted_message or SessionMessage(
            session_id=session.id,
            role="user",
            content=content,
        )
        extra = dict(row.extra or message_extra or {})
        source = extra.get("webbridge_source")
        if isinstance(source, dict):
            source = dict(source)
            source["state"] = "delivered"
            extra["webbridge_source"] = source
        row.extra = extra or None
        db.add(row)
        await db.flush()
    return InteractiveMessageResult(
        status="accepted",
        session_id=str(session.id),
        message_id=row.id,
    )


# ── REST status + registration ────────────────────────────────────────────────


def test_register_then_status_shows_connected(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/relay") as ws:
        ack = _register(ws)
        assert ack == {"type": "registered", "extension_id": "ext-1"}

        status = client.get(f"{_PREFIX}/status").json()
        assert status["connected"] is True
        [ext] = status["extensions"]
        assert ext["extension_id"] == "ext-1"
        assert ext["browser"] == "chrome"
        assert ext["version"] == "120.0"

    # After disconnect the status flips back.
    assert client.get(f"{_PREFIX}/status").json()["connected"] is False


def test_protocol_capabilities_are_reported_in_status(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/relay") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "register",
                    "protocol_version": 2,
                    "extension_id": "ext-v2",
                    "browser": "chrome",
                    "version": "2.0.0",
                    "capabilities": {
                        "commands": ["snapshot"],
                        "interactions": ["context.share"],
                    },
                }
            )
        )
        assert json.loads(ws.receive_text())["type"] == "registered"

        [extension] = client.get(f"{_PREFIX}/status").json()["extensions"]
        assert extension["protocol_version"] == 2
        assert extension["capabilities"] == {
            "commands": ["snapshot"],
            "interactions": ["context.share"],
        }
        assert extension["paired"] is False


def test_event_updates_extension_state(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/relay") as ws:
        _register(ws)
        ws.send_text(
            json.dumps(
                {
                    "type": "event",
                    "event": "tab_updated",
                    "data": {
                        "url": "https://example.com",
                        "title": "Example",
                        "tabs": [{"index": 0, "title": "Example", "active": True}],
                    },
                }
            )
        )
        # Give the relay a beat to process the frame, then read status.
        for _ in range(50):
            ext = client.get(f"{_PREFIX}/status").json()["extensions"][0]
            if ext["current_url"]:
                break
            time.sleep(0.01)
        assert ext["current_url"] == "https://example.com"
        assert ext["current_title"] == "Example"
        assert ext["tabs"] == [{"index": 0, "title": "Example", "active": True}]


def test_relay_rejects_oversized_frames(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/relay") as ws:
        _register(ws)
        ws.send_text("x" * 1_000_001)
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
        assert exc_info.value.code == 1009


# ── Command roundtrip over the wire ───────────────────────────────────────────


def test_command_roundtrip_agent_ws(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/agent/s1") as agent_ws:
        with client.websocket_connect(f"{_PREFIX}/relay") as ext_ws:
            _register(ext_ws)

            agent_ws.send_text(
                json.dumps({"action": "navigate", "url": "https://x.dev"})
            )
            command = json.loads(ext_ws.receive_text())
            assert command["type"] == "command"
            assert command["action"] == "navigate"
            assert command["params"] == {"url": "https://x.dev"}
            assert command["request_id"]

            ext_ws.send_text(
                json.dumps(
                    {
                        "type": "response",
                        "request_id": command["request_id"],
                        "success": True,
                        "data": {"url": "https://x.dev"},
                        "error": None,
                    }
                )
            )
            response = json.loads(agent_ws.receive_text())
            assert response["type"] == "response"
            assert response["request_id"] == command["request_id"]
            assert response["success"] is True
            assert response["data"] == {"url": "https://x.dev"}


def test_sequential_commands_correlate_by_request_id(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/agent/s1") as agent_ws:
        with client.websocket_connect(f"{_PREFIX}/relay") as ext_ws:
            _register(ext_ws)
            seen_ids: list[str] = []

            for action in ("back", "forward"):
                agent_ws.send_text(json.dumps({"action": action}))
                command = json.loads(ext_ws.receive_text())
                assert command["action"] == action
                seen_ids.append(command["request_id"])
                ext_ws.send_text(
                    json.dumps(
                        {
                            "type": "response",
                            "request_id": command["request_id"],
                            "success": True,
                            "data": {"did": action},
                            "error": None,
                        }
                    )
                )
                response = json.loads(agent_ws.receive_text())
                assert response["request_id"] == command["request_id"]
                assert response["data"] == {"did": action}

            assert len(set(seen_ids)) == 2


def test_agent_ws_no_extension(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/agent/s1") as agent_ws:
        agent_ws.send_text(json.dumps({"action": "navigate", "url": "https://x.dev"}))
        msg = json.loads(agent_ws.receive_text())
        assert msg["type"] == "no_extension"
        assert "no browser extension" in msg["error"].lower()


def test_extension_disconnect_fails_pending_command(client: TestClient):
    with client.websocket_connect(f"{_PREFIX}/agent/s1") as agent_ws:
        with client.websocket_connect(f"{_PREFIX}/relay") as ext_ws:
            _register(ext_ws)
            agent_ws.send_text(
                json.dumps({"action": "navigate", "url": "https://x.dev"})
            )
            assert json.loads(ext_ws.receive_text())["type"] == "command"
        # Extension socket closed while the command is still pending.
        response = json.loads(agent_ws.receive_text())
        assert response["type"] == "response"
        assert response["success"] is False
        assert "disconnected" in response["error"]


# ── Heartbeat ─────────────────────────────────────────────────────────────────


def test_ping_refreshes_last_seen(client: TestClient, manager: WebBridgeManager):
    with client.websocket_connect(f"{_PREFIX}/relay") as ws:
        _register(ws)

        # Simulate an idle extension: status must report it as gone.
        conn = manager.get_extension("ext-1")
        assert conn is not None
        conn.last_seen = time.time() - 1000
        assert client.get(f"{_PREFIX}/status").json()["connected"] is False

        # A heartbeat brings it back and is answered with a pong.
        ws.send_text(json.dumps({"type": "ping"}))
        assert json.loads(ws.receive_text()) == {"type": "pong"}
        assert client.get(f"{_PREFIX}/status").json()["connected"] is True


# ── Manager unit-level paths ──────────────────────────────────────────────────


async def test_manager_send_command_roundtrip(manager: WebBridgeManager):
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    manager.register_extension(
        extension_id="e1", browser="chrome", version="1", send=fake_send
    )

    task = asyncio.create_task(
        manager.send_command("sess", "navigate", {"url": "https://x"})
    )
    await asyncio.sleep(0)

    command = json.loads(sent[0])
    assert command["type"] == "command"
    assert command["action"] == "navigate"
    assert command["params"] == {"url": "https://x"}
    assert command["request_id"]

    assert manager.handle_response(
        command["request_id"], success=True, data={"ok": 1}, error=None
    )
    result = await task
    assert result["request_id"] == command["request_id"]
    assert result["success"] is True
    assert result["data"] == {"ok": 1}


async def test_bound_session_pins_tab_unless_command_overrides_it(
    manager: WebBridgeManager,
):
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    manager.register_extension(
        extension_id="e1", browser="chrome", version="1", send=fake_send
    )
    manager.bind_session_tab("sess", "e1", 42)

    bound = asyncio.create_task(
        manager.send_command("sess", "navigate", {"url": "https://bound.dev"})
    )
    await asyncio.sleep(0)
    bound_command = json.loads(sent.pop(0))
    assert bound_command["params"]["tab_id"] == 42
    manager.handle_response(
        bound_command["request_id"], success=True, data={}, error=None
    )
    await bound

    explicit = asyncio.create_task(
        manager.send_command(
            "sess", "navigate", {"url": "https://explicit.dev", "tab_id": 9}
        )
    )
    await asyncio.sleep(0)
    explicit_command = json.loads(sent.pop(0))
    assert explicit_command["params"]["tab_id"] == 9
    manager.handle_response(
        explicit_command["request_id"], success=True, data={}, error=None
    )
    await explicit


async def test_live_binding_refuses_commands_after_cross_origin_navigation(
    manager: WebBridgeManager,
):
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    manager.register_extension(
        extension_id="e1", browser="chrome", version="1", send=fake_send
    )
    extension = manager.get_extension("e1")
    assert extension is not None
    extension.tabs = [{"id": 42, "url": "https://docs.example.com/start"}]
    manager.bind_session_tab("sess", "e1", 42, "https://docs.example.com")

    allowed = asyncio.create_task(
        manager.send_command(
            "sess", "navigate", {"url": "https://docs.example.com/next"}
        )
    )
    await asyncio.sleep(0)
    command = json.loads(sent.pop())
    assert command["params"]["tab_id"] == 42
    assert command["params"]["_webbridge_expected_origin"] == "https://docs.example.com"
    manager.handle_response(command["request_id"], success=True, data={}, error=None)
    assert (await allowed)["success"] is True

    extension.tabs = [{"id": 42, "url": "https://mail.example.net/inbox"}]
    refused = await manager.send_command("sess", "extract", {})
    assert refused["success"] is False
    assert "changed origin" in refused["error"]
    assert manager.session_tab_binding("sess") is None
    assert sent == []
    refused_again = await manager.send_command("sess", "click", {"x": 1, "y": 2})
    assert refused_again["success"] is False
    assert "changed origin" in refused_again["error"]
    assert sent == []
    assert manager.unbind_session_tab("sess", extension_id="e1") is True


async def test_rehydrated_binding_fails_closed_until_tab_origin_is_validated(
    manager: WebBridgeManager,
):
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    manager.register_extension(
        extension_id="pairing-1", browser="chrome", version="1", send=fake_send
    )
    manager.stage_session_tab_binding("sess", "pairing-1", 42, "https://example.com")

    pending = await manager.send_command(
        "sess", "navigate", {"url": "https://example.com/next"}
    )
    assert pending["success"] is False
    assert "pending validation" in pending["error"]
    assert sent == []

    stale = manager.validate_pending_tab_bindings(
        "pairing-1", [{"id": 42, "url": "https://example.com/current"}]
    )
    assert stale == []
    assert manager.session_tab_binding("sess") == ("pairing-1", 42)
    extension = manager.get_extension("pairing-1")
    assert extension is not None
    extension.tabs = [{"id": 42, "url": "https://example.com/current"}]

    command_task = asyncio.create_task(
        manager.send_command("sess", "navigate", {"url": "https://example.com/next"})
    )
    await asyncio.sleep(0)
    command = json.loads(sent.pop())
    assert command["params"]["tab_id"] == 42
    manager.handle_response(command["request_id"], success=True, data={}, error=None)
    assert (await command_task)["success"] is True


def test_reloading_same_binding_keeps_live_tab_active(manager: WebBridgeManager):
    manager.bind_session_tab("sess", "pairing-1", 42, "https://example.com")

    manager.stage_session_tab_binding("sess", "pairing-1", 42, "https://example.com")

    assert manager.session_tab_binding("sess") == ("pairing-1", 42)
    assert manager.session_tab_binding_pending("sess") is False


def test_rebinding_tab_evicts_previous_session(manager: WebBridgeManager):
    manager.bind_session_tab("session-a", "pairing-1", 42, "https://example.com")

    manager.bind_session_tab("session-b", "pairing-1", 42, "https://example.com")

    assert manager.session_tab_binding("session-a") is None
    assert manager.session_tab_binding("session-b") == ("pairing-1", 42)


async def test_expired_manager_binding_fails_closed(manager: WebBridgeManager):
    sent: list[str] = []

    async def fake_send(frame: str) -> None:
        sent.append(frame)

    extension = manager.register_extension(
        extension_id="pairing-1",
        browser="chrome",
        version="1.6.0",
        send=fake_send,
    )
    extension.tabs = [{"id": 42, "url": "https://example.com/page"}]
    manager.bind_session_tab(
        "session-1",
        "pairing-1",
        42,
        "https://example.com",
        expires_at=time.time() - 1,
    )

    result = await manager.send_command("session-1", "click", {"x": 1, "y": 2})

    assert result["success"] is False
    assert "expired" in result["error"]
    assert sent == []
    assert manager.session_tab_binding("session-1") is None
    second = await manager.send_command("session-1", "click", {"x": 1, "y": 2})
    assert second["success"] is False
    assert "expired" in second["error"]
    assert sent == []
    assert manager.unbind_session_tab("session-1", extension_id="pairing-1") is True


async def test_manager_commands_correlate_by_request_id(manager: WebBridgeManager):
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    manager.register_extension(
        extension_id="e1", browser="chrome", version="1", send=fake_send
    )

    t1 = asyncio.create_task(manager.send_command("sess", "click", {"x": 1, "y": 2}))
    t2 = asyncio.create_task(manager.send_command("sess", "type", {"text": "hi"}))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    id1 = json.loads(sent[0])["request_id"]
    id2 = json.loads(sent[1])["request_id"]
    assert id1 != id2

    # Answer out of order — each future must still get its own response.
    manager.handle_response(id2, success=True, data={"for": "type"}, error=None)
    manager.handle_response(id1, success=True, data={"for": "click"}, error=None)

    assert (await t1)["data"] == {"for": "click"}
    assert (await t2)["data"] == {"for": "type"}


async def test_manager_no_extension(manager: WebBridgeManager):
    result = await manager.send_command("sess", "navigate", {"url": "https://x"})
    assert result["success"] is False
    assert "no browser extension" in result["error"].lower()


async def test_manager_disconnect_fails_pending(manager: WebBridgeManager):
    async def fake_send(text: str) -> None:
        pass

    manager.register_extension(
        extension_id="e1", browser="chrome", version="1", send=fake_send
    )
    task = asyncio.create_task(manager.send_command("sess", "click", {"x": 1, "y": 2}))
    await asyncio.sleep(0)

    manager.unregister_extension("e1")
    result = await asyncio.wait_for(task, timeout=1)
    assert result["success"] is False
    assert result["error"] == "extension disconnected"


def test_stale_connection_cannot_unregister_its_replacement(
    manager: WebBridgeManager,
):
    async def first_send(text: str) -> None:
        pass

    async def second_send(text: str) -> None:
        pass

    first = manager.register_extension(
        extension_id="pairing-1", browser="chrome", version="1", send=first_send
    )
    second = manager.register_extension(
        extension_id="pairing-1", browser="chrome", version="2", send=second_send
    )

    manager.unregister_extension("pairing-1", connection=first)
    manager.handle_event(
        "pairing-1",
        "tab_updated",
        {"url": "https://stale.example", "title": "Stale"},
        connection=first,
    )

    assert manager.get_extension("pairing-1") is second
    assert second.current_url == ""


async def test_manager_status_action_is_local(manager: WebBridgeManager):
    result = await manager.send_command("sess", "status")
    assert result["success"] is True
    assert result["data"] == {"connected": False, "extensions": []}


async def test_manager_cleanup_stale(manager: WebBridgeManager):
    async def fake_send(text: str) -> None:
        pass

    manager.register_extension(
        extension_id="e1", browser="chrome", version="1", send=fake_send
    )
    conn = manager.get_extension("e1")
    assert conn is not None
    conn.last_seen = time.time() - 1000

    assert manager.cleanup_stale() == ["e1"]
    assert manager.get_extension("e1") is None


# ── WS token auth ─────────────────────────────────────────────────────────────


def test_relay_ticket_is_single_use_and_expires():
    tickets = WebBridgeTicketStore(ttl_seconds=10)

    ticket = tickets.issue("pairing-1", now=100.0)
    assert tickets.consume(ticket, now=109.0) == "pairing-1"
    assert tickets.consume(ticket, now=109.0) is None

    expired = tickets.issue("pairing-2", now=200.0)
    assert tickets.consume(expired, now=211.0) is None

    revoked = tickets.issue("pairing-3", now=300.0)
    tickets.revoke("pairing-3")
    assert tickets.is_revoked("pairing-3")
    assert tickets.consume(revoked, now=301.0) is None
    with pytest.raises(ValueError, match="revoked"):
        tickets.issue("pairing-3", now=302.0)


def test_pairing_code_is_single_use_case_insensitive_and_expires():
    codes = WebBridgePairingCodeStore(ttl_seconds=10)

    code = codes.issue("Work Chrome", now=100.0)
    grant = codes.consume(code.lower(), now=109.0)
    assert grant is not None
    assert grant.label == "Work Chrome"
    assert "relay" in grant.scopes
    assert codes.consume(code, now=109.0) is None

    expired = codes.issue("Expired", now=200.0)
    assert codes.consume(expired, now=211.0) is None


def test_interaction_rate_limiter_uses_sliding_window():
    limiter = WebBridgeRateLimiter(window_seconds=10)

    assert limiter.allow("pairing-1", 2, now=100.0)
    assert limiter.allow("pairing-1", 2, now=101.0)
    assert not limiter.allow("pairing-1", 2, now=109.0)
    assert limiter.allow("pairing-1", 2, now=111.0)


async def test_pairing_credential_is_hashed_and_scoped():
    from app.core import db as db_module

    async with db_module.async_session_factory() as db:
        pairing, credential = await create_pairing(
            db,
            grant=PairingGrant(
                label="Work Chrome",
                scopes=frozenset({"relay"}),
            ),
            browser="chrome",
            version="1.2.0",
        )
        await db.commit()

        assert pairing.credential_hash != credential
        assert credential not in repr(pairing)
        assert await authenticate_pairing(db, credential, required_scope="relay")
        assert (
            await authenticate_pairing(
                db, credential, required_scope="interactions:write"
            )
            is None
        )


async def test_pairing_data_cleanup_preserves_chat_session():
    from app.core import db as db_module
    from app.models.chat import ChatSession
    from app.models.webbridge import WebBridgeTeachDraft
    from app.services.webbridge_pairing_service import delete_pairing_data

    async with db_module.async_session_factory() as db:
        pairing, _ = await create_pairing(
            db,
            grant=PairingGrant(
                label="Disposable Chrome",
                scopes=frozenset({"bindings:write", "interactions:write"}),
            ),
            browser="chrome",
            version="1.6.0",
        )
        session = ChatSession(title="Keep this chat", tags=["webbridge"])
        db.add(session)
        await db.flush()
        binding = await upsert_tab_binding(
            db,
            pairing_id=pairing.id,
            tab_id=42,
            session_id=session.id,
            origin="https://example.com",
            page_instance_id="page-42",
        )
        interaction, _ = await create_or_get_interaction(
            db,
            pairing_id=pairing.id,
            interaction_id="cleanup-interaction",
            request_payload={"delivery": "draft"},
            kind="context.share",
            delivery="draft",
            status="draft",
            target_session_id=session.id,
            origin="https://example.com",
            tab_id=42,
            page_instance_id="page-42",
            payload_metadata={},
        )
        draft = WebBridgeTeachDraft(
            pairing_id=pairing.id,
            session_id=session.id,
            tab_id=42,
            title="Disposable draft",
            origin="https://example.com",
            start_url="https://example.com/start",
            actions=[{"kind": "click", "selector": "#go"}],
        )
        db.add(draft)
        session.tags = ["webbridge", f"webbridge_pairing:{pairing.id}"]
        db.add(session)
        await db.commit()

        await delete_pairing_data(db, pairing.id)
        await db.commit()

        kept_session = await db.get(ChatSession, session.id)
        assert kept_session is not None
        assert kept_session.tags == ["webbridge"]
        assert await db.get(type(binding), binding.id) is None
        assert await db.get(type(interaction), interaction.id) is None
        assert await db.get(WebBridgeTeachDraft, draft.id) is None


@pytest.mark.parametrize(
    "historical_scopes,required_scope",
    [
        (
            {
                "relay",
                "interactions:write",
                "bindings:write",
                "sessions:list",
                "session-stream:read",
            },
            "sessions:create",
        ),
        (
            {
                "relay",
                "interactions:write",
                "bindings:write",
                "sessions:list",
                "sessions:create",
                "session-stream:read",
            },
            "teach:drafts:write",
        ),
        (
            {
                "relay",
                "interactions:write",
                "bindings:write",
                "sessions:list",
                "sessions:create",
                "session-stream:read",
                "teach:drafts:write",
            },
            "session:messages:write",
        ),
    ],
)
async def test_historical_pairing_scopes_upgrade_for_new_capabilities(
    historical_scopes: set[str], required_scope: str
):
    from app.core import db as db_module

    async with db_module.async_session_factory() as db:
        pairing, credential = await create_pairing(
            db,
            grant=PairingGrant(
                label="Existing Chrome", scopes=frozenset(historical_scopes)
            ),
            browser="chrome",
            version="1.3.0",
        )
        await db.commit()

        upgraded = await authenticate_pairing(
            db, credential, required_scope=required_scope
        )
        assert upgraded is not None
        assert required_scope in upgraded.scopes
        assert pairing.id == upgraded.id


async def test_interaction_idempotency_replays_same_request_and_rejects_conflict():
    from app.core import db as db_module

    async with db_module.async_session_factory() as db:
        pairing, _ = await create_pairing(
            db,
            grant=PairingGrant(
                label="Work Chrome",
                scopes=frozenset({"interactions:write"}),
            ),
            browser="chrome",
            version="1.2.0",
        )
        request_payload = {
            "kind": "context.share",
            "delivery": "draft",
            "payload": {"prompt": "Explain this"},
        }
        first, created = await create_or_get_interaction(
            db,
            pairing_id=pairing.id,
            interaction_id="interaction-1",
            request_payload=request_payload,
            kind="context.share",
            delivery="draft",
            status="draft",
            target_session_id=None,
            origin="https://example.com",
            tab_id=7,
            page_instance_id="page-1",
            payload_metadata={"context_type": "selection"},
        )
        replay, replay_created = await create_or_get_interaction(
            db,
            pairing_id=pairing.id,
            interaction_id="interaction-1",
            request_payload=request_payload,
            kind="context.share",
            delivery="draft",
            status="draft",
            target_session_id=None,
            origin="https://example.com",
            tab_id=7,
            page_instance_id="page-1",
            payload_metadata={"context_type": "selection"},
        )

        assert created is True
        assert replay_created is False
        assert replay.id == first.id

        with pytest.raises(ValueError, match="already used"):
            await create_or_get_interaction(
                db,
                pairing_id=pairing.id,
                interaction_id="interaction-1",
                request_payload={**request_payload, "payload": {"prompt": "Changed"}},
                kind="context.share",
                delivery="draft",
                status="draft",
                target_session_id=None,
                origin="https://example.com",
                tab_id=7,
                page_instance_id="page-1",
                payload_metadata={"context_type": "selection"},
            )


async def test_pending_submit_dispatch_claim_is_atomic():
    from app.core import db as db_module

    async with db_module.async_session_factory() as setup_db:
        pairing, _ = await create_pairing(
            setup_db,
            grant=PairingGrant(
                label="Work Chrome", scopes=frozenset({"interactions:write"})
            ),
            browser="chrome",
            version="1.2.0",
        )
        interaction, _ = await create_or_get_interaction(
            setup_db,
            pairing_id=pairing.id,
            interaction_id="claim-1",
            request_payload={"delivery": "submit"},
            kind="prompt.submit",
            delivery="submit",
            status="pending",
            target_session_id=None,
            origin="https://example.com",
            tab_id=7,
            page_instance_id=None,
            payload_metadata={},
            prompt="Prompt",
        )
        await setup_db.commit()
        interaction_id = interaction.id

    async def claim() -> bool:
        async with db_module.async_session_factory() as db:
            row = await db.get(WebBridgeInteraction, interaction_id)
            assert row is not None
            return await claim_interaction_dispatch(db, row)

    results = await asyncio.gather(claim(), claim())
    assert results.count(True) == 1
    assert results.count(False) == 1


async def test_tab_binding_upserts_one_tab_to_a_new_session():
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        pairing, _ = await create_pairing(
            db,
            grant=PairingGrant(
                label="Work Chrome",
                scopes=frozenset({"bindings:write"}),
            ),
            browser="chrome",
            version="1.2.0",
        )
        first_session = ChatSession(title="First")
        second_session = ChatSession(title="Second")
        db.add(first_session)
        db.add(second_session)
        await db.flush()

        first = await upsert_tab_binding(
            db,
            pairing_id=pairing.id,
            tab_id=42,
            session_id=first_session.id,
            origin="https://first.example",
            page_instance_id="page-1",
        )
        second = await upsert_tab_binding(
            db,
            pairing_id=pairing.id,
            tab_id=42,
            session_id=second_session.id,
            origin="https://second.example",
            page_instance_id="page-2",
        )
        bindings = await list_tab_bindings(db, pairing.id)

        assert second.id == first.id
        assert len(bindings) == 1
        assert bindings[0].session_id == second_session.id
        assert bindings[0].origin == "https://second.example"


async def test_tab_binding_keeps_only_newest_tab_for_one_session():
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        pairing, _ = await create_pairing(
            db,
            grant=PairingGrant(
                label="Work Chrome",
                scopes=frozenset({"bindings:write"}),
            ),
            browser="chrome",
            version="1.6.0",
        )
        session = ChatSession(title="One primary browser tab")
        db.add(session)
        await db.flush()

        await upsert_tab_binding(
            db,
            pairing_id=pairing.id,
            tab_id=41,
            session_id=session.id,
            origin="https://example.com",
            page_instance_id="page-41",
        )
        newest = await upsert_tab_binding(
            db,
            pairing_id=pairing.id,
            tab_id=42,
            session_id=session.id,
            origin="https://example.com",
            page_instance_id="page-42",
        )
        bindings = await list_tab_bindings(db, pairing.id)

        assert [(binding.tab_id, binding.id) for binding in bindings] == [
            (42, newest.id)
        ]


def test_pending_tab_binding_can_be_unbound(manager: WebBridgeManager):
    manager.stage_session_tab_binding(
        "session-1", "pairing-1", 42, "https://example.com"
    )

    assert manager.session_tab_binding_pending("session-1") is True
    assert manager.unbind_session_tab("session-1", extension_id="pairing-1") is True
    assert manager.session_tab_binding_pending("session-1") is False
    assert manager.session_tab_binding("session-1") is None


async def test_prepared_interactive_message_queues_when_session_is_busy():
    from app.core import db as db_module
    from app.models.chat import ChatSession, SessionMessage

    team = SimpleNamespace(
        user_message_lock=asyncio.Lock(),
        session_tags=frozenset(),
        permission_mode="auto",
        lead=SimpleNamespace(agent=SimpleNamespace(model_id="model:test")),
        has_active_user_turn=lambda: True,
        _activate_queued_user_messages=AsyncMock(return_value=False),
    )
    async with db_module.async_session_factory() as db:
        session = ChatSession(
            title="Busy",
            tags=["webbridge"],
            permission_mode="accept-edits",
            model="model:persisted",
        )
        db.add(session)
        await db.commit()

        result = await submit_persisted_interactive_message(
            db, session=session, team=team, content="Browser follow-up"
        )
        queued = await db.get(SessionMessage, result.message_id)

        assert result.status == "queued"
        assert queued is not None
        assert queued.extra["queue_status"] == "queued"
        assert queued.extra["model"] == "model:persisted"
        assert team.session_tags == frozenset({"webbridge"})
        assert team.permission_mode == "accept-edits"


async def test_prepared_interactive_message_dispatches_when_idle(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    dispatch = AsyncMock(return_value=("session-id", 0))
    monkeypatch.setattr(
        "app.services.interactive_message_service.agent_service.dispatch_user_message",
        dispatch,
    )
    team = SimpleNamespace(
        user_message_lock=asyncio.Lock(),
        session_tags=frozenset(),
        permission_mode="auto",
        lead=SimpleNamespace(agent=SimpleNamespace(model_id="model:test")),
        has_active_user_turn=lambda: False,
    )
    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Idle", mode="coding", workspace="/tmp/project")
        db.add(session)
        await db.commit()

        result = await submit_persisted_interactive_message(
            db, session=session, team=team, content="Browser prompt"
        )

    assert result.status == "accepted"
    dispatch.assert_awaited_once_with(
        team,
        content="Browser prompt",
        session_id=str(session.id),
        mode="coding",
        workspace="/tmp/project",
    )


async def test_interactive_message_rechecks_source_inside_team_lock(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession, SessionMessage

    team = SimpleNamespace(
        user_message_lock=asyncio.Lock(),
        session_tags=frozenset(),
        permission_mode="auto",
        lead=SimpleNamespace(agent=SimpleNamespace(model_id="model:test")),
        has_active_user_turn=lambda: False,
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(
        "app.services.interactive_message_service.agent_service.dispatch_user_message",
        dispatch,
    )
    source_key = "webbridge-panel:pairing-1:request-1"
    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Concurrent panel message")
        db.add(session)
        await db.flush()
        existing = SessionMessage(
            session_id=session.id,
            role="user",
            content="Send once",
            extra={
                "webbridge_source": {
                    "key": source_key,
                    "request_hash": "a" * 64,
                    "state": "delivered",
                }
            },
        )
        db.add(existing)
        await db.commit()

        result = await submit_persisted_interactive_message(
            db,
            session=session,
            team=team,
            content="Send once",
            message_extra={
                "webbridge_source": {
                    "key": source_key,
                    "request_hash": "a" * 64,
                    "state": "persisted",
                }
            },
            source_key=source_key,
            source_request_hash="a" * 64,
        )

    assert result.status == "accepted"
    assert result.message_id == existing.id
    dispatch.assert_not_awaited()


async def test_submit_interaction_dispatches_once_and_replays_ack(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Browser target", tags=["webbridge"])
        db.add(session)
        await db.commit()

    fake_team = SimpleNamespace()

    async def resolve(db, session_id: str, *, require_existing: bool):
        assert require_existing
        async with db.begin():
            persisted = await db.get(ChatSession, UUID(session_id))
        assert persisted is not None
        return persisted, fake_team

    submit = AsyncMock(side_effect=_persist_delivered_interactive_message)
    monkeypatch.setattr(
        "app.api.routes.team.webbridge.resolve_team_for_session", resolve
    )
    monkeypatch.setattr(
        "app.api.routes.team.webbridge.submit_persisted_interactive_message", submit
    )

    pairing = _pair_extension(client)
    _assign_pairing_session(client, pairing, session.id)
    headers = {
        "Authorization": f"Bearer {pairing['credential']}",
        "Idempotency-Key": "submit-1",
    }
    payload = {
        "kind": "prompt.submit",
        "delivery": "submit",
        "source": {
            "tab_id": 7,
            "origin": "https://example.com",
            "user_gesture": True,
        },
        "target": {"session_id": str(session.id)},
        "payload": {
            "prompt": "Use this browser context",
            "metadata": {
                "context_type": "selection",
                "page_url": "https://example.com/docs?token=secret#selected",
                "page_title": "Example docs",
                "selection_text": "Selected browser text",
            },
        },
    }

    first = client.post(f"{_PREFIX}/interactions", headers=headers, json=payload)
    replay = client.post(f"{_PREFIX}/interactions", headers=headers, json=payload)

    assert first.status_code == 202
    assert first.json()["status"] == "accepted"
    assert replay.status_code == 200
    assert replay.json() == first.json()
    submit.assert_awaited_once()
    dispatched = submit.await_args.kwargs
    assert "[Untrusted browser context" in dispatched["content"]
    assert "Selected browser text" in dispatched["content"]
    assert dispatched["message_extra"] == {
        "webbridge_context": {
            "type": "selection",
            "origin": "https://example.com",
            "page_url": "https://example.com/docs",
            "page_title": "Example docs",
            "selection_text": "Selected browser text",
        },
        "webbridge_source": {
            "key": f"webbridge-interaction:{pairing['pairing_id']}:submit-1",
            "state": "persisted",
        },
    }
    async with db_module.async_session_factory() as db:
        interaction = await db.get(
            WebBridgeInteraction, UUID(first.json()["interaction_record_id"])
        )
    assert interaction is not None
    assert interaction.origin == "https://example.com"
    assert interaction.payload_metadata["page_url"] == "https://example.com/docs"
    assert "token" not in interaction.payload_metadata["page_url"]


async def test_teach_draft_is_pairing_scoped_reviewed_and_replayed(
    client: TestClient,
    manager: WebBridgeManager,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Recorded browser flow", tags=["webbridge"])
        db.add(session)
        await db.commit()

    owner = _pair_extension(client, "Work Chrome")
    other = _pair_extension(client, "Personal Edge")
    _assign_pairing_session(client, owner, session.id)
    owner_headers = {"Authorization": f"Bearer {owner['credential']}"}
    bind = client.put(
        f"{_PREFIX}/bindings/42",
        headers=owner_headers,
        json={"session_id": str(session.id), "origin": "https://example.com"},
    )
    assert bind.status_code == 200

    payload = {
        "session_id": str(session.id),
        "tab_id": 42,
        "title": "Create report",
        "origin": "https://example.com",
        "start_url": "https://example.com/reports?private=1",
        "actions": [
            {"kind": "fill", "selector": "#name", "value": "Quarterly report"},
            {
                "kind": "fill",
                "selector": "#password",
                "secret": True,
                "parameter": "report_password",
            },
            {"kind": "click", "selector": "button[type=submit]"},
        ],
        "warnings": ["Recording reached the action limit."],
    }
    denied = client.post(
        f"{_PREFIX}/teach-drafts",
        headers={"Authorization": f"Bearer {other['credential']}"},
        json=payload,
    )
    assert denied.status_code == 403

    created = client.post(
        f"{_PREFIX}/teach-drafts", headers=owner_headers, json=payload
    )
    assert created.status_code == 201
    draft = created.json()
    assert draft["origin"] == "https://example.com"
    assert draft["start_url"] == "https://example.com/reports"
    assert draft["parameter_names"] == ["report_password"]
    assert draft["capture_warnings"] == ["Recording reached the action limit."]
    assert "value" not in draft["actions"][1]

    unapproved = client.post(f"{_PREFIX}/teach-drafts/{draft['id']}/replay", json={})
    assert unapproved.status_code == 409

    approved = client.post(f"{_PREFIX}/teach-drafts/{draft['id']}/approve")
    assert approved.status_code == 200
    from app.api.routes.team import webbridge as webbridge_routes

    webbridge_routes._active_teach_replays.add(str(session.id))
    try:
        concurrent = client.post(
            f"{_PREFIX}/teach-drafts/{draft['id']}/replay",
            json={"parameters": {"report_password": "never-persisted"}},
        )
    finally:
        webbridge_routes._active_teach_replays.discard(str(session.id))
    assert concurrent.status_code == 409
    assert "already running" in concurrent.text
    commands: list[tuple[str, dict]] = []

    async def send_command(session_id: str, action: str, params: dict, **kwargs):
        commands.append((action, params))
        return {"success": True, "data": {}, "error": None}

    monkeypatch.setattr(manager, "send_command", send_command)
    replay = client.post(
        f"{_PREFIX}/teach-drafts/{draft['id']}/replay",
        json={"parameters": {"report_password": "never-persisted"}},
    )
    assert replay.status_code == 200
    assert [action for action, _ in commands] == [
        "navigate",
        "fill",
        "fill",
        "click_selector",
    ]
    assert commands[0][1]["url"] == "https://example.com/reports"
    assert commands[2][1]["value"] == "never-persisted"
    assert replay.json()["draft"]["replay_count"] == 1
    async with db_module.async_session_factory() as db:
        persisted = await db.get(WebBridgeTeachDraft, UUID(draft["id"]))
    assert persisted is not None
    assert persisted.status == "approved"
    assert persisted.last_error is None


async def test_side_panel_transcript_composer_and_handoff_are_pairing_scoped(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession, SessionMessage

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Panel target", tags=["webbridge"])
        db.add(session)
        await db.flush()
        db.add_all(
            [
                SessionMessage(
                    session_id=session.id, role="user", content="Earlier user"
                ),
                SessionMessage(
                    session_id=session.id,
                    role="assistant",
                    content="Earlier assistant",
                    name="forge",
                ),
                SessionMessage(
                    session_id=session.id, role="tool", content="Hidden tool"
                ),
            ]
        )
        await db.commit()

    owner = _pair_extension(client, "Work Chrome")
    other = _pair_extension(client, "Personal Edge")
    _assign_pairing_session(client, owner, session.id)
    owner_headers = {"Authorization": f"Bearer {owner['credential']}"}
    bind = client.put(
        f"{_PREFIX}/bindings/42",
        headers=owner_headers,
        json={"session_id": str(session.id), "origin": "https://example.com"},
    )
    assert bind.status_code == 200

    history = client.get(
        f"{_PREFIX}/sessions/{session.id}/history", headers=owner_headers
    )
    assert history.status_code == 200
    assert [message["content"] for message in history.json()["messages"]] == [
        "Earlier user",
        "Earlier assistant",
    ]
    denied_history = client.get(
        f"{_PREFIX}/sessions/{session.id}/history",
        headers={"Authorization": f"Bearer {other['credential']}"},
    )
    assert denied_history.status_code == 403

    fake_team = SimpleNamespace()

    async def resolve(db, session_id: str, *, require_existing: bool):
        assert require_existing
        async with db.begin():
            persisted = await db.get(ChatSession, UUID(session_id))
        assert persisted is not None
        return persisted, fake_team

    submit = AsyncMock(side_effect=_persist_delivered_interactive_message)
    monkeypatch.setattr(
        "app.api.routes.team.webbridge.resolve_team_for_session", resolve
    )
    monkeypatch.setattr(
        "app.api.routes.team.webbridge.submit_persisted_interactive_message", submit
    )
    message_payload = {
        "content": "Side Panel follow-up",
        "tab_id": 42,
        "origin": "https://example.com",
        "user_gesture": True,
        "element": {
            "page_url": "https://example.com/page?private=1",
            "selector": "button[data-testid=save]",
            "tag": "button",
            "role": "button",
            "name": "Save changes",
            "text": "Save",
        },
    }
    message = client.post(
        f"{_PREFIX}/sessions/{session.id}/messages",
        headers={**owner_headers, "Idempotency-Key": "panel-message-1"},
        json=message_payload,
    )
    assert message.status_code == 202
    assert message.json()["status"] == "accepted"
    dispatched_extra = submit.await_args.kwargs["message_extra"]
    assert dispatched_extra["webbridge_side_panel"] == {
        "tab_id": 42,
        "element": {
            "page_url": "https://example.com/page",
            "selector": "button[data-testid=save]",
            "tag": "button",
            "role": "button",
            "name": "Save changes",
            "text": "Save",
        },
    }
    assert dispatched_extra["webbridge_source"]["key"] == (
        f"webbridge-panel:{owner['pairing_id']}:panel-message-1"
    )
    assert len(dispatched_extra["webbridge_source"]["request_hash"]) == 64
    assert dispatched_extra["webbridge_source"]["state"] == "persisted"
    assert "[Untrusted browser element" in submit.await_args.kwargs["content"]
    assert "Selector: button[data-testid=save]" in submit.await_args.kwargs["content"]
    replayed_message = client.post(
        f"{_PREFIX}/sessions/{session.id}/messages",
        headers={**owner_headers, "Idempotency-Key": "panel-message-1"},
        json=message_payload,
    )
    assert replayed_message.status_code == 202
    assert replayed_message.json() == message.json()
    submit.assert_awaited_once()
    conflict = client.post(
        f"{_PREFIX}/sessions/{session.id}/messages",
        headers={**owner_headers, "Idempotency-Key": "panel-message-1"},
        json={**message_payload, "content": "Different follow-up"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"
    stale_origin = client.post(
        f"{_PREFIX}/sessions/{session.id}/messages",
        headers={**owner_headers, "Idempotency-Key": "panel-message-2"},
        json={**message_payload, "origin": "https://other.example"},
    )
    assert stale_origin.status_code == 409

    reply_calls: list[tuple[str, list[str]]] = []
    pending = SimpleNamespace(
        questions=[SimpleNamespace(question="Continue?", options=["yes", "no"])]
    )
    service = SimpleNamespace(
        session_id=str(session.id),
        stream_session_id=str(session.id),
        _pending={"question-1": pending},
        validate_answers=lambda request_id, answers: None,
        reply=lambda request_id, answers: (
            reply_calls.append((request_id, answers)) or True
        ),
    )
    monkeypatch.setattr(
        "app.agent.ask_user.get_services_for_stream",
        lambda stream_session_id: (
            [service] if stream_session_id == str(session.id) else []
        ),
    )
    monkeypatch.setattr(
        "app.agent.ask_user.get_service_for_session",
        lambda request_session_id: (
            service if request_session_id == str(session.id) else None
        ),
    )
    pending_questions = client.get(
        f"{_PREFIX}/sessions/{session.id}/questions/pending", headers=owner_headers
    )
    assert pending_questions.status_code == 200
    assert pending_questions.json()["questions"][0]["request_id"] == "question-1"
    answer = client.post(
        f"{_PREFIX}/sessions/{session.id}/questions/question-1/reply",
        headers=owner_headers,
        json={"request_session_id": str(session.id), "answers": ["yes"]},
    )
    assert answer.status_code == 200
    assert reply_calls == [("question-1", ["yes"])]

    interrupt = AsyncMock(return_value=["forge"])
    monkeypatch.setattr("app.api.routes.team.webbridge.interrupt_team", interrupt)
    stopped = client.post(
        f"{_PREFIX}/sessions/{session.id}/interrupt", headers=owner_headers
    )
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "interrupted"
    interrupt.assert_awaited_once_with(fake_team, str(session.id))


async def test_interaction_retry_recovers_persisted_message_after_dispatch_crash(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession, SessionMessage

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Crash-safe interaction", tags=["webbridge"])
        db.add(session)
        await db.commit()

    pairing = _pair_extension(client)
    _assign_pairing_session(client, pairing, session.id)
    payload = {
        "kind": "prompt.submit",
        "delivery": "submit",
        "source": {
            "tab_id": 7,
            "origin": "https://example.com",
            "user_gesture": True,
        },
        "target": {"session_id": str(session.id)},
        "payload": {"prompt": "Recover once", "metadata": {}},
    }
    request_payload = InteractionRequest.model_validate(payload).model_dump(mode="json")
    async with db_module.async_session_factory() as db:
        interaction, _ = await create_or_get_interaction(
            db,
            pairing_id=UUID(pairing["pairing_id"]),
            interaction_id="post-persist-crash",
            request_payload=request_payload,
            kind="prompt.submit",
            delivery="submit",
            status="pending",
            target_session_id=session.id,
            origin="https://example.com",
            tab_id=7,
            page_instance_id=None,
            payload_metadata={},
            prompt="Recover once",
        )
        interaction.dispatch_lease_until = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
        persisted = SessionMessage(
            session_id=session.id,
            role="user",
            content="Recover once",
            extra={
                "webbridge_source": {
                    "key": (
                        f"webbridge-interaction:{pairing['pairing_id']}:"
                        "post-persist-crash"
                    ),
                    "state": "persisted",
                }
            },
        )
        db.add(interaction)
        db.add(persisted)
        await db.commit()

    async def redeliver_existing(db, *, session, persisted_message, **kwargs):
        assert persisted_message.id == persisted.id
        async with db.begin():
            row = await db.get(SessionMessage, persisted.id)
            assert row is not None
            extra = dict(row.extra or {})
            source = dict(extra["webbridge_source"])
            source["state"] = "delivered"
            extra["webbridge_source"] = source
            row.extra = extra
            db.add(row)
        return InteractiveMessageResult(
            status="accepted",
            session_id=str(session.id),
            message_id=persisted.id,
        )

    submit = AsyncMock(side_effect=redeliver_existing)
    monkeypatch.setattr(
        "app.api.routes.team.webbridge.resolve_team_for_session",
        AsyncMock(return_value=(session, SimpleNamespace())),
    )
    monkeypatch.setattr(
        "app.api.routes.team.webbridge.submit_persisted_interactive_message", submit
    )
    response = client.post(
        f"{_PREFIX}/interactions",
        headers={
            "Authorization": f"Bearer {pairing['credential']}",
            "Idempotency-Key": "post-persist-crash",
        },
        json=payload,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert response.json()["message_id"] == str(persisted.id)
    submit.assert_awaited_once()
    assert submit.await_args.kwargs["persisted_message"].id == persisted.id
    async with db_module.async_session_factory() as db:
        rows = (
            await db.exec(
                select(SessionMessage).where(SessionMessage.session_id == session.id)
            )
        ).all()
    assert [row.id for row in rows] == [persisted.id]


def test_browser_interaction_rejects_mislabeled_selection_context(
    client: TestClient,
):
    pairing = _pair_extension(client)
    response = client.post(
        f"{_PREFIX}/interactions",
        headers={
            "Authorization": f"Bearer {pairing['credential']}",
            "Idempotency-Key": "mislabeled-selection",
        },
        json={
            "kind": "context.share",
            "delivery": "draft",
            "source": {"origin": "https://example.com", "user_gesture": True},
            "target": {"session_id": None},
            "payload": {
                "prompt": "Draft",
                "metadata": {
                    "context_type": "page_metadata",
                    "selection_text": "This must not bypass selection policy",
                },
            },
        },
    )

    assert response.status_code == 422
    assert "selection_text requires" in response.text


async def test_submit_retry_reclaims_stale_pending_interaction(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Crash recovery target", tags=["webbridge"])
        db.add(session)
        await db.commit()

    pairing = _pair_extension(client)
    _assign_pairing_session(client, pairing, session.id)
    payload = {
        "kind": "prompt.submit",
        "delivery": "submit",
        "source": {
            "tab_id": 7,
            "origin": "https://example.com",
            "user_gesture": True,
        },
        "target": {"session_id": str(session.id)},
        "payload": {"prompt": "Recover this prompt", "metadata": {}},
    }
    request_payload = InteractionRequest.model_validate(payload).model_dump(mode="json")
    async with db_module.async_session_factory() as db:
        interaction, _ = await create_or_get_interaction(
            db,
            pairing_id=UUID(pairing["pairing_id"]),
            interaction_id="stale-submit-1",
            request_payload=request_payload,
            kind="prompt.submit",
            delivery="submit",
            status="pending",
            target_session_id=session.id,
            origin="https://example.com",
            tab_id=7,
            page_instance_id=None,
            payload_metadata={},
            prompt="Recover this prompt",
        )
        interaction.dispatch_lease_until = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
        db.add(interaction)
        await db.commit()

    submit = AsyncMock(side_effect=_persist_delivered_interactive_message)
    monkeypatch.setattr(
        "app.api.routes.team.webbridge.resolve_team_for_session",
        AsyncMock(return_value=(session, SimpleNamespace())),
    )
    monkeypatch.setattr(
        "app.api.routes.team.webbridge.submit_persisted_interactive_message", submit
    )
    headers = {
        "Authorization": f"Bearer {pairing['credential']}",
        "Idempotency-Key": "stale-submit-1",
    }

    recovered = client.post(f"{_PREFIX}/interactions", headers=headers, json=payload)
    replay = client.post(f"{_PREFIX}/interactions", headers=headers, json=payload)

    assert recovered.status_code == 200
    assert recovered.json()["status"] == "accepted"
    assert replay.json() == recovered.json()
    submit.assert_awaited_once()


@pytest.mark.parametrize(
    ("source", "target", "prompt", "status", "code"),
    [
        (
            {"origin": "https://example.com", "user_gesture": False},
            {"session_id": None},
            "Prompt",
            403,
            "user_gesture_required",
        ),
        (
            {"origin": "https://example.com", "user_gesture": True},
            {"session_id": None},
            "Prompt",
            422,
            "session_required",
        ),
        (
            {"origin": "https://example.com", "user_gesture": True},
            {"session_id": "00000000-0000-0000-0000-000000000001"},
            "   ",
            422,
            "prompt_required",
        ),
    ],
)
def test_submit_interaction_guardrails(
    client: TestClient,
    source: dict,
    target: dict,
    prompt: str,
    status: int,
    code: str,
):
    pairing = _pair_extension(client)
    response = client.post(
        f"{_PREFIX}/interactions",
        headers={
            "Authorization": f"Bearer {pairing['credential']}",
            "Idempotency-Key": f"guard-{code}",
        },
        json={
            "kind": "prompt.submit",
            "delivery": "submit",
            "source": source,
            "target": target,
            "payload": {"prompt": prompt},
        },
    )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code


async def test_tab_binding_crud_is_scoped_and_updates_manager(
    client: TestClient,
    manager: WebBridgeManager,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Bound session", tags=["webbridge"])
        db.add(session)
        await db.commit()

    pairing = _pair_extension(client)
    _assign_pairing_session(client, pairing, session.id)
    headers = {"Authorization": f"Bearer {pairing['credential']}"}
    bound = client.put(
        f"{_PREFIX}/bindings/42",
        headers=headers,
        json={
            "session_id": str(session.id),
            "origin": "https://example.com",
            "page_instance_id": "page-1",
        },
    )
    assert bound.status_code == 200
    assert bound.json()["tab_id"] == 42
    assert manager.session_tab_binding(str(session.id)) == (
        pairing["pairing_id"],
        42,
    )

    bindings = client.get(f"{_PREFIX}/bindings", headers=headers)
    assert bindings.status_code == 200
    assert [item["tab_id"] for item in bindings.json()] == [42]

    removed = client.delete(f"{_PREFIX}/bindings/42", headers=headers)
    assert removed.status_code == 204
    assert manager.session_tab_binding(str(session.id)) is None


async def test_paired_relay_rehydrates_binding_without_client_get(
    client: TestClient,
    manager: WebBridgeManager,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Recovered binding", tags=["webbridge"])
        db.add(session)
        await db.commit()

    pairing = _pair_extension(client)
    _assign_pairing_session(client, pairing, session.id)
    headers = {"Authorization": f"Bearer {pairing['credential']}"}
    bound = client.put(
        f"{_PREFIX}/bindings/42",
        headers=headers,
        json={
            "session_id": str(session.id),
            "origin": "https://example.com",
            "page_instance_id": "page-1",
        },
    )
    assert bound.status_code == 200
    assert manager.unbind_session_tab(str(session.id)) is True

    ticket = client.post(f"{_PREFIX}/relay-ticket", headers=headers).json()["ticket"]
    with client.websocket_connect(f"{_PREFIX}/relay?_ticket={ticket}") as ws:
        _register(ws)
        assert manager.session_tab_binding_pending(str(session.id)) is True
        assert manager.session_tab_binding(str(session.id)) is None

        ws.send_text(
            json.dumps(
                {
                    "type": "event",
                    "event": "tab_updated",
                    "data": {
                        "url": "https://example.com/current",
                        "title": "Example",
                        "tabs": [
                            {
                                "id": 42,
                                "url": "https://example.com/current",
                                "title": "Example",
                            }
                        ],
                    },
                }
            )
        )
        ws.send_text(json.dumps({"type": "ping"}))
        assert json.loads(ws.receive_text())["type"] == "pong"

        assert manager.session_tab_binding_pending(str(session.id)) is False
        assert manager.session_tab_binding(str(session.id)) == (
            pairing["pairing_id"],
            42,
        )


def test_pair_exchange_mints_scoped_credential_and_consumes_code(client: TestClient):
    code = webbridge_pairing_code_store.issue("Work Chrome")
    payload = {"code": code, "browser": "chrome", "version": "1.2.0"}

    response = client.post(f"{_PREFIX}/pairing/exchange", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["pairing_id"]
    assert data["credential"]
    assert {"relay", "interactions:write"} <= set(data["scopes"])

    replay = client.post(f"{_PREFIX}/pairing/exchange", json=payload)
    assert replay.status_code == 401


async def test_paired_extension_lists_and_creates_browser_sessions(
    client: TestClient,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        existing = ChatSession(title="Existing WebBridge session", tags=["webbridge"])
        hidden = ChatSession(title="Private normal session")
        db.add(existing)
        db.add(hidden)
        await db.commit()

    pairing = _pair_extension(client)
    headers = {"Authorization": f"Bearer {pairing['credential']}"}

    _assign_pairing_session(client, pairing, existing.id)

    sessions = client.get(f"{_PREFIX}/sessions", headers=headers)
    assert sessions.status_code == 200
    assert sessions.json() == [
        {
            "id": str(existing.id),
            "title": "Existing WebBridge session",
            "mode": "forge",
            "running": False,
        }
    ]

    created = client.post(
        f"{_PREFIX}/sessions",
        headers=headers,
        json={"title": "Browser: Example docs"},
    )
    assert created.status_code == 422

    headers["Idempotency-Key"] = "browser-session-1"
    created = client.post(
        f"{_PREFIX}/sessions",
        headers=headers,
        json={"title": "Browser: Example docs"},
    )
    replay = client.post(
        f"{_PREFIX}/sessions",
        headers=headers,
        json={"title": "Changed title should not matter"},
    )
    assert created.status_code == 201
    assert created.json() == replay.json()
    assert created.json()["title"] == "Browser: Example docs"
    async with db_module.async_session_factory() as db:
        created_row = await db.get(ChatSession, UUID(created.json()["id"]))
    assert created_row is not None
    assert "webbridge" in (created_row.tags or ())
    assert f"webbridge_pairing:{pairing['pairing_id']}" in (created_row.tags or ())


async def test_browser_pairings_cannot_enumerate_or_target_each_others_sessions(
    client: TestClient,
):
    owner = _pair_extension(client, "Work Chrome")
    other = _pair_extension(client, "Personal Edge")
    owner_headers = {
        "Authorization": f"Bearer {owner['credential']}",
        "Idempotency-Key": "owner-browser-session",
    }
    other_headers = {"Authorization": f"Bearer {other['credential']}"}

    created = client.post(
        f"{_PREFIX}/sessions",
        headers=owner_headers,
        json={"title": "Browser: Work task"},
    )
    assert created.status_code == 201
    session_id = created.json()["id"]

    owner_sessions = client.get(f"{_PREFIX}/sessions", headers=owner_headers)
    other_sessions = client.get(f"{_PREFIX}/sessions", headers=other_headers)
    assert [session["id"] for session in owner_sessions.json()] == [session_id]
    assert other_sessions.json() == []

    bind = client.put(
        f"{_PREFIX}/bindings/42",
        headers=other_headers,
        json={"session_id": session_id, "origin": "https://example.com"},
    )
    assert bind.status_code == 403
    assert bind.json()["detail"]["code"] == "session_not_pairing_assigned"

    interaction = client.post(
        f"{_PREFIX}/interactions",
        headers={**other_headers, "Idempotency-Key": "other-injection"},
        json={
            "kind": "context.share",
            "delivery": "submit",
            "source": {
                "tab_id": 42,
                "origin": "https://example.com",
                "user_gesture": True,
            },
            "target": {"session_id": session_id},
            "payload": {"prompt": "Inject context", "metadata": {}},
        },
    )
    assert interaction.status_code == 403
    assert interaction.json()["detail"]["code"] == "session_not_pairing_assigned"

    _assign_pairing_session(client, other, session_id)
    granted_sessions = client.get(f"{_PREFIX}/sessions", headers=other_headers)
    assert [session["id"] for session in granted_sessions.json()] == [session_id]


async def test_browser_session_bridge_excludes_side_chats(
    client: TestClient,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        main = ChatSession(title="Main session")
        side_chat = ChatSession(
            title="Hidden side chat",
            session_type="side_chat",
            source_session_id=main.id,
            source_session_ref=main.id,
        )
        db.add(main)
        db.add(side_chat)
        await db.commit()

    pairing = _pair_extension(client)
    response = client.get(
        f"{_PREFIX}/sessions",
        headers={"Authorization": f"Bearer {pairing['credential']}"},
    )

    assert response.status_code == 200
    assert response.json() == []


async def test_browser_binding_rejects_session_without_webbridge_tag(
    client: TestClient,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Private normal session")
        db.add(session)
        await db.commit()

    pairing = _pair_extension(client)
    response = client.put(
        f"{_PREFIX}/bindings/42",
        headers={"Authorization": f"Bearer {pairing['credential']}"},
        json={
            "session_id": str(session.id),
            "origin": "https://example.com",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "session_not_webbridge_enabled"


async def test_browser_interaction_rejects_session_without_webbridge_tag(
    client: TestClient,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Private normal session")
        db.add(session)
        await db.commit()

    pairing = _pair_extension(client)
    response = client.post(
        f"{_PREFIX}/interactions",
        headers={
            "Authorization": f"Bearer {pairing['credential']}",
            "Idempotency-Key": "private-session-submit",
        },
        json={
            "kind": "context.share",
            "delivery": "submit",
            "source": {
                "tab_id": 42,
                "origin": "https://example.com",
                "user_gesture": True,
            },
            "target": {"session_id": str(session.id)},
            "payload": {"prompt": "Do not enter private session", "metadata": {}},
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "session_not_webbridge_enabled"


async def test_browser_interaction_requires_http_origin(client: TestClient):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Bound", tags=["webbridge"])
        db.add(session)
        await db.commit()

    pairing = _pair_extension(client)
    response = client.post(
        f"{_PREFIX}/interactions",
        headers={
            "Authorization": f"Bearer {pairing['credential']}",
            "Idempotency-Key": "non-http-origin",
        },
        json={
            "kind": "context.share",
            "delivery": "submit",
            "source": {"origin": "chrome://settings", "user_gesture": True},
            "target": {"session_id": str(session.id)},
            "payload": {"prompt": "No restricted page", "metadata": {}},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "http_origin_required"


async def test_browser_binding_normalizes_origin_and_rejects_non_http(
    client: TestClient,
):
    from app.core import db as db_module
    from app.models.chat import ChatSession

    async with db_module.async_session_factory() as db:
        session = ChatSession(title="Bound", tags=["webbridge"])
        db.add(session)
        await db.commit()
    pairing = _pair_extension(client)
    _assign_pairing_session(client, pairing, session.id)
    headers = {"Authorization": f"Bearer {pairing['credential']}"}
    bad = client.put(
        f"{_PREFIX}/bindings/42",
        headers=headers,
        json={"session_id": str(session.id), "origin": "chrome://settings"},
    )
    assert bad.status_code == 422

    ok = client.put(
        f"{_PREFIX}/bindings/42",
        headers=headers,
        json={
            "session_id": str(session.id),
            "origin": "https://example.com/path?secret=1",
        },
    )
    assert ok.status_code == 200
    assert ok.json()["origin"] == "https://example.com"


def test_pairing_code_allows_unkeyed_loopback_but_rejects_remote_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "app.api.routes.team.webbridge.expected_desktop_token", lambda: ""
    )
    loopback_client = TestClient(client.app, client=("127.0.0.1", 5173))
    response = loopback_client.post(
        f"{_PREFIX}/pairing/code", json={"label": "Work Chrome"}
    )
    assert response.status_code == 201
    assert response.json()["code"]

    remote_client = TestClient(client.app, client=("203.0.113.10", 5173))
    response = remote_client.post(
        f"{_PREFIX}/pairing/code", json={"label": "Work Chrome"}
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "pairing_requires_auth"

    hostile_origin = loopback_client.post(
        f"{_PREFIX}/pairing/code",
        headers={"Origin": "https://attacker.example"},
        json={"label": "Stolen browser"},
    )
    assert hostile_origin.status_code == 403
    assert hostile_origin.json()["detail"]["code"] == "pairing_origin_refused"

    local_origin = loopback_client.post(
        f"{_PREFIX}/pairing/code",
        headers={"Origin": "http://localhost:5173"},
        json={"label": "Local browser"},
    )
    assert local_origin.status_code == 201


def test_local_pairing_needs_no_code_but_stays_loopback_origin_scoped(
    client: TestClient,
):
    local_client = TestClient(client.app, client=("127.0.0.1", 5173))
    paired = local_client.post(
        f"{_PREFIX}/pairing/local",
        headers={"Origin": "chrome-extension://abcdefghijklmnop"},
        json={"label": "Local Chrome", "browser": "chrome", "version": "1.6.0"},
    )
    assert paired.status_code == 201
    assert paired.json()["credential"]
    assert "relay" in paired.json()["scopes"]

    hostile = local_client.post(
        f"{_PREFIX}/pairing/local",
        headers={"Origin": "https://attacker.example"},
        json={"label": "Hostile", "browser": "chrome", "version": "1.6.0"},
    )
    assert hostile.status_code == 403
    localhost_page = local_client.post(
        f"{_PREFIX}/pairing/local",
        headers={"Origin": "http://localhost:5173"},
        json={"label": "Local page", "browser": "chrome", "version": "1.6.0"},
    )
    assert localhost_page.status_code == 403
    missing_origin = local_client.post(
        f"{_PREFIX}/pairing/local",
        json={"label": "No Origin", "browser": "chrome", "version": "1.6.0"},
    )
    assert missing_origin.status_code == 403
    remote_client = TestClient(client.app, client=("203.0.113.10", 5173))
    remote = remote_client.post(
        f"{_PREFIX}/pairing/local",
        json={"label": "Remote", "browser": "chrome", "version": "1.6.0"},
    )
    assert remote.status_code == 403


def test_pairing_credential_mints_single_use_authoritative_relay_ticket(
    client: TestClient,
):
    pairing = _pair_extension(client)
    ticket_response = client.post(
        f"{_PREFIX}/relay-ticket",
        headers={"Authorization": f"Bearer {pairing['credential']}"},
    )
    assert ticket_response.status_code == 201
    ticket = ticket_response.json()["ticket"]

    with client.websocket_connect(f"{_PREFIX}/relay?_ticket={ticket}") as ws:
        ack = _register(ws, extension_id="spoofed-extension-id")
        assert ack["extension_id"] == pairing["pairing_id"]
        assert ack["pairing_id"] == pairing["pairing_id"]
        assert ack["protocol_version"] == 2
        [extension] = client.get(f"{_PREFIX}/status").json()["extensions"]
        assert extension["paired"] is True

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"{_PREFIX}/relay?_ticket={ticket}"):
            pass
    assert exc_info.value.code == 4401


def test_revoking_pairing_invalidates_credential_and_outstanding_tickets(
    client: TestClient,
):
    pairing = _pair_extension(client)
    from app.api.routes.team import webbridge as webbridge_routes

    revocation_event = webbridge_routes._pairing_revocation_event(pairing["pairing_id"])
    assert revocation_event.is_set() is False
    headers = {"Authorization": f"Bearer {pairing['credential']}"}
    ticket_response = client.post(f"{_PREFIX}/relay-ticket", headers=headers)
    assert ticket_response.status_code == 201
    ticket = ticket_response.json()["ticket"]

    pairings = client.get(f"{_PREFIX}/pairings")
    assert pairing["pairing_id"] in {item["pairing_id"] for item in pairings.json()}
    revoked = client.delete(f"{_PREFIX}/pairings/{pairing['pairing_id']}")
    assert revoked.status_code == 204
    assert revocation_event.is_set() is True

    assert client.post(f"{_PREFIX}/relay-ticket", headers=headers).status_code == 401
    assert pairing["pairing_id"] not in {
        item["pairing_id"] for item in client.get(f"{_PREFIX}/pairings").json()
    }
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"{_PREFIX}/relay?_ticket={ticket}"):
            pass
    assert exc_info.value.code == 4401


def test_ticket_mint_revoke_race_returns_auth_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    pairing = _pair_extension(client)
    monkeypatch.setattr(
        webbridge_ticket_store,
        "issue",
        lambda pairing_id: (_ for _ in ()).throw(ValueError("pairing is revoked")),
    )

    response = client.post(
        f"{_PREFIX}/relay-ticket",
        headers={"Authorization": f"Bearer {pairing['credential']}"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_pairing"


def test_draft_interaction_is_idempotent_and_conflicts_on_payload_change(
    client: TestClient,
):
    pairing = _pair_extension(client)
    headers = {
        "Authorization": f"Bearer {pairing['credential']}",
        "Idempotency-Key": "interaction-1",
    }
    payload = {
        "kind": "context.share",
        "delivery": "draft",
        "source": {
            "tab_id": 7,
            "page_instance_id": "page-1",
            "origin": "https://example.com",
            "user_gesture": True,
        },
        "target": {"session_id": None},
        "payload": {
            "prompt": "Explain this",
            "metadata": {"context_type": "selection"},
        },
    }

    first = client.post(f"{_PREFIX}/interactions", headers=headers, json=payload)
    replay = client.post(f"{_PREFIX}/interactions", headers=headers, json=payload)
    assert first.status_code == 202
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == "draft"

    changed = {
        **payload,
        "payload": {**payload["payload"], "prompt": "Changed"},
    }
    conflict = client.post(f"{_PREFIX}/interactions", headers=headers, json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"


def test_interaction_rate_limit_does_not_charge_idempotent_replay(
    client: TestClient,
    manager: WebBridgeManager,
):
    _set_policy(manager, interactions={"max_per_minute": 1})
    pairing = _pair_extension(client)
    headers = {
        "Authorization": f"Bearer {pairing['credential']}",
        "Idempotency-Key": "rate-1",
    }
    payload = {
        "kind": "context.share",
        "delivery": "draft",
        "source": {"origin": "https://example.com", "user_gesture": True},
        "target": {"session_id": None},
        "payload": {"prompt": "Draft", "metadata": {}},
    }

    assert (
        client.post(
            f"{_PREFIX}/interactions", headers=headers, json=payload
        ).status_code
        == 202
    )
    assert (
        client.post(
            f"{_PREFIX}/interactions", headers=headers, json=payload
        ).status_code
        == 200
    )

    headers["Idempotency-Key"] = "rate-2"
    limited = client.post(f"{_PREFIX}/interactions", headers=headers, json=payload)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert limited.json()["detail"]["code"] == "rate_limited"


def test_ws_rejected_without_token(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret-token")
    for path in (f"{_PREFIX}/relay", f"{_PREFIX}/agent/s1"):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(path):
                pass
        assert exc_info.value.code == 4401


def test_ws_rejected_with_wrong_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret-token")
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(f"{_PREFIX}/relay?_token=nope"):
            pass
    assert exc_info.value.code == 4401


def test_ws_accepted_with_token(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOFLUX_DESKTOP_TOKEN", "secret-token")
    with client.websocket_connect(f"{_PREFIX}/relay?_token=secret-token") as ws:
        assert _register(ws)["type"] == "registered"
    with client.websocket_connect(
        f"{_PREFIX}/agent/s1?_token=secret-token"
    ) as agent_ws:
        agent_ws.send_text(json.dumps({"action": "status"}))
        msg = json.loads(agent_ws.receive_text())
        assert msg["type"] == "response"
        assert msg["success"] is True


def test_ws_open_when_no_token_configured(client: TestClient):
    # conftest deletes EVOFLUX_DESKTOP_TOKEN for the whole session.
    with client.websocket_connect(f"{_PREFIX}/relay") as ws:
        assert _register(ws)["type"] == "registered"


def test_open_local_ws_rejects_hostile_browser_origin(client: TestClient):
    for path in (f"{_PREFIX}/relay", f"{_PREFIX}/agent/s1"):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                path, headers={"Origin": "https://attacker.example"}
            ):
                pass
        assert exc_info.value.code == 4401

    with client.websocket_connect(
        f"{_PREFIX}/relay",
        headers={"Origin": "chrome-extension://abcdefghijklmnop"},
    ) as ws:
        assert _register(ws)["type"] == "registered"


# ── Tool-level (manager's send_command stubbed) ───────────────────────────────


def _stub_send(monkeypatch: pytest.MonkeyPatch, manager: WebBridgeManager, handler):
    async def fake_send_command(
        session_id: str, action: str, params: dict | None = None
    ):
        return handler(action, params or {})

    monkeypatch.setattr(manager, "send_command", fake_send_command)


async def test_tool_status_when_disconnected(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _stub_send(
        monkeypatch,
        manager,
        lambda action, params: {
            "success": True,
            "data": {"connected": False, "extensions": []},
            "error": None,
        },
    )
    result = await webbridge(actions=[_action({"action": "status"})])
    assert isinstance(result, str)
    assert "No browser extension connected" in result


async def test_tool_navigate_success_text(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[_action({"action": "navigate", "url": "https://example.com"})]
    )
    assert result == "Navigated to https://example.com"
    assert seen == [("navigate", {"url": "https://example.com"})]


async def test_tool_screenshot_returns_image_block(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    raw = b"fake-png-bytes"
    b64 = base64.b64encode(raw).decode()
    _stub_send(
        monkeypatch,
        manager,
        lambda action, params: {
            "success": True,
            "data": {"data": b64, "format": "png"},
            "error": None,
        },
    )
    result = await webbridge(actions=[_action({"action": "screenshot"})])
    assert isinstance(result, ToolResult)
    image = next(p for p in result.parts if isinstance(p, ImageDataBlock))
    assert image.data == b64
    assert image.media_type == "image/png"
    text = next(p for p in result.parts if isinstance(p, TextBlock))
    assert "Screenshot captured" in text.text
    assert f"{len(raw)} bytes" in text.text
    assert "CSS pixels" in text.text
    assert "Untrusted browser content" in text.text


async def test_tool_aggregates_action_errors(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    def handler(action: str, params: dict):
        if action == "click":
            return {"success": False, "data": None, "error": "boom"}
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action({"action": "click", "x": 10, "y": 20}),
            _action({"action": "type", "text": "abc"}),
        ]
    )
    assert isinstance(result, str)
    assert "Click failed: boom" in result
    assert "Typed 3 characters" in result
    assert "\n---\n" in result


# ── Session routing ───────────────────────────────────────────────────────────


def _recorder_ext(manager: WebBridgeManager, ext_id: str) -> list[str]:
    """Register *ext_id* with a send() that records the wire commands it gets."""
    sent: list[str] = []

    async def fake_send(text: str) -> None:
        sent.append(text)

    manager.register_extension(
        extension_id=ext_id, browser="chrome", version="1", send=fake_send
    )
    return sent


async def _run(manager: WebBridgeManager, coro_factory, sent: list[str]):
    """Drive a send_command task: start it, answer the pending request, await."""
    task = asyncio.create_task(coro_factory())
    for _ in range(4):
        await asyncio.sleep(0)
        if sent:
            break
    request_id = json.loads(sent[-1])["request_id"]
    manager.handle_response(request_id, success=True, data={"ok": 1}, error=None)
    return await task


async def test_session_sticks_to_first_extension(manager: WebBridgeManager):
    s1 = _recorder_ext(manager, "e1")
    s2 = _recorder_ext(manager, "e2")  # e2 registered last → currently "active"

    # First command binds session "sess" to the active extension (e2).
    await _run(
        manager, lambda: manager.send_command("sess", "click", {"x": 1, "y": 2}), s2
    )
    assert len(s2) == 1 and len(s1) == 0

    # Make e1 look most-recently-seen; the session must still target e2.
    manager.get_extension("e1").last_seen = time.time() + 100
    await _run(
        manager, lambda: manager.send_command("sess", "click", {"x": 3, "y": 4}), s2
    )
    assert len(s2) == 2 and len(s1) == 0


async def test_explicit_extension_id_overrides_binding(manager: WebBridgeManager):
    s1 = _recorder_ext(manager, "e1")
    s2 = _recorder_ext(manager, "e2")

    await _run(
        manager,
        lambda: manager.send_command(
            "sess", "click", {"x": 1, "y": 2}, extension_id="e1"
        ),
        s1,
    )
    assert len(s1) == 1 and len(s2) == 0


async def test_explicit_unknown_extension_errors(manager: WebBridgeManager):
    _recorder_ext(manager, "e1")
    result = await manager.send_command("sess", "click", {"x": 1}, extension_id="ghost")
    assert result["success"] is False
    assert "no browser extension" in result["error"].lower()


def test_events_only_reach_bound_session(manager: WebBridgeManager):
    _recorder_ext(manager, "e1")
    _recorder_ext(manager, "e2")
    manager.resolve_target("s1", "e1")  # bind s1 → e1
    manager.resolve_target("s2", "e2")  # bind s2 → e2
    q1 = manager.subscribe_agent("s1")
    q2 = manager.subscribe_agent("s2")

    manager.handle_event("e1", "tab_updated", {"url": "https://a", "title": "A"})

    assert q1.qsize() == 1
    assert q2.qsize() == 0  # s2 is pinned to e2 — must not see e1's event


# ── Per-action timeouts ─────────────────────────────────────────────────────


def test_timeout_navigate_exceeds_extension_internal_wait(manager: WebBridgeManager):
    # Manager must wait longer than the extension's own 25s navigation wait.
    assert manager._timeout_for("navigate", {}) > 30.0
    assert manager._timeout_for("click", {}) == 30.0


def test_timeout_derives_from_caller_timeout_ms(manager: WebBridgeManager):
    assert manager._timeout_for("wait_for_selector", {"timeout_ms": 5000}) == 15.0


# ── Domain policy + evaluate gate ─────────────────────────────────────────────


def _set_policy(manager: WebBridgeManager, **kwargs) -> None:
    """Inject a WebBridge policy straight into the manager's in-memory cache.

    Mirrors what ``reload_policy()`` does at runtime, without the disk read —
    the command path only ever consults the cache.
    """
    from app.core.runtime_settings import WebBridgeSettings

    manager._policy_cache = WebBridgeSettings(**kwargs)


def test_interaction_policy_blocks_domains_background_and_disabled_capture(
    manager: WebBridgeManager,
):
    _set_policy(
        manager,
        sharing={
            "blocked_domains": ["private.example"],
            "allow_selection": False,
        },
    )

    assert (
        "blocked"
        in manager.check_interaction_policy(
            origin="https://app.private.example/path",
            user_gesture=True,
            context_type="selection",
        ).lower()
    )
    assert (
        "user gesture"
        in manager.check_interaction_policy(
            origin="https://safe.example",
            user_gesture=False,
            context_type=None,
        ).lower()
    )
    assert (
        "selection"
        in manager.check_interaction_policy(
            origin="https://safe.example",
            user_gesture=True,
            context_type="selection",
        ).lower()
    )


async def test_policy_blocks_navigate_to_blocked_domain(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, blocked_domains=["evil.com"])
    _recorder_ext(manager, "e1")
    result = await manager.send_command(
        "sess", "navigate", {"url": "https://sub.evil.com/x"}
    )
    assert result["success"] is False
    assert "blocked" in result["error"].lower()


async def test_sharing_policy_blocks_command_page_reads_only(
    manager: WebBridgeManager,
):
    _set_policy(manager, sharing={"blocked_domains": ["private.example"]})
    sent = _recorder_ext(manager, "e1")
    manager.get_extension("e1").current_url = "https://private.example/account"

    refused = await manager.send_command("sess", "extract", {})
    assert refused["success"] is False
    assert "sharing policy" in refused["error"].lower()
    assert sent == []

    click = asyncio.create_task(manager.send_command("sess", "click", {"x": 1, "y": 2}))
    await asyncio.sleep(0)
    command = json.loads(sent.pop())
    manager.handle_response(command["request_id"], success=True, data={}, error=None)
    assert (await click)["success"] is True


async def test_policy_allowlist_refuses_other_domains(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, allowed_domains=["example.com"])
    sent = _recorder_ext(manager, "e1")
    refused = await manager.send_command(
        "sess", "navigate", {"url": "https://other.com"}
    )
    assert refused["success"] is False and "allowlist" in refused["error"].lower()
    assert sent == []  # never reached the extension

    ok = await _run(
        manager,
        lambda: manager.send_command(
            "sess", "navigate", {"url": "https://example.com/p"}
        ),
        sent,
    )
    assert ok["success"] is True


async def test_policy_gates_page_action_by_current_url(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, blocked_domains=["evil.com"])
    _recorder_ext(manager, "e1")
    manager.get_extension("e1").current_url = "https://evil.com/dashboard"
    result = await manager.send_command("sess", "click", {"x": 1, "y": 2})
    assert result["success"] is False and "blocked" in result["error"].lower()


async def test_policy_gates_page_action_by_target_tab_url(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, blocked_domains=["evil.com"])
    sent = _recorder_ext(manager, "e1")
    conn = manager.get_extension("e1")
    assert conn is not None
    conn.current_url = "https://example.com/allowed-active-tab"
    conn.tabs = [
        {"id": 7, "url": "https://evil.com/private"},
        {"id": 8, "url": "https://example.com/other"},
    ]

    result = await manager.send_command(
        "sess", "extract", {"tab_id": 7, "format": "text"}
    )

    assert result["success"] is False
    assert "evil.com" in result["error"]
    assert sent == []


async def test_policy_fails_closed_for_unknown_target_tab(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, blocked_domains=["evil.com"])
    sent = _recorder_ext(manager, "e1")
    conn = manager.get_extension("e1")
    assert conn is not None
    conn.current_url = "https://example.com/allowed-active-tab"

    result = await manager.send_command(
        "sess", "click_selector", {"tab_id": 999, "selector": "button"}
    )

    assert result["success"] is False
    assert "unknown" in result["error"].lower()
    assert sent == []


async def test_policy_disables_evaluate(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, allow_evaluate=False)
    _recorder_ext(manager, "e1")
    result = await manager.send_command("sess", "evaluate", {"script": "1+1"})
    assert result["success"] is False and "evaluate" in result["error"].lower()


async def test_policy_disabled_refuses_all(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, enabled=False)
    _recorder_ext(manager, "e1")
    result = await manager.send_command(
        "sess", "navigate", {"url": "https://example.com"}
    )
    assert result["success"] is False and "disabled" in result["error"].lower()


# ── Audit trail ───────────────────────────────────────────────────────────────


async def test_audit_records_refusals_and_endpoint(
    client: TestClient, manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _set_policy(manager, blocked_domains=["evil.com"])
    _recorder_ext(manager, "e1")
    await manager.send_command("sess", "navigate", {"url": "https://evil.com"})

    entries = manager.audit_entries()
    assert entries and entries[0]["action"] == "navigate"
    assert entries[0]["success"] is False
    assert entries[0]["url"] == "https://evil.com"

    resp = client.get(f"{_PREFIX}/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body["entries"][0]["action"] == "navigate"
    assert body["entries"][0]["error"]


# ── Tool-level: new element/wait/tab actions ──────────────────────────────────


async def test_tool_snapshot_lists_elements(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _stub_send(
        monkeypatch,
        manager,
        lambda action, params: {
            "success": True,
            "data": {
                "title": "Account settings",
                "url": "https://example.com/settings",
                "viewport": {"width": 1280, "height": 720, "scrollX": 0, "scrollY": 40},
                "elements": [
                    {
                        "role": "checkbox",
                        "name": "Email alerts",
                        "selector": "#alerts",
                        "state": {"checked": False, "disabled": False},
                        "attributes": {"type": "checkbox"},
                        "box": {"x": 100, "y": 40},
                    },
                ],
            },
            "error": None,
        },
    )
    result = await webbridge(actions=[_action({"action": "snapshot"})])
    assert isinstance(result, str)
    assert "Page snapshot: Account settings" in result
    assert "Untrusted browser content" in result
    assert "https://example.com/settings" in result
    assert "1280x720 css-px at (0, 40)" in result
    assert "Email alerts" in result and "#alerts" in result and "@(100,40)" in result
    assert "checked=false" in result and "type='checkbox'" in result


async def test_tool_click_selector_maps_params(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[_action({"action": "click_selector", "selector": "#go", "index": 2})]
    )
    assert "Clicked '#go'" in result
    assert seen == [("click_selector", {"selector": "#go", "index": 2})]


async def test_tool_fill_submit_and_tab_id(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    await webbridge(
        actions=[
            _action(
                {
                    "action": "fill",
                    "selector": "#q",
                    "value": "hello",
                    "submit": True,
                    "tab_id": 7,
                }
            )
        ]
    )
    assert seen[0][0] == "fill"
    assert seen[0][1] == {
        "selector": "#q",
        "value": "hello",
        "clear": True,
        "submit": True,
        "tab_id": 7,
    }


async def test_tool_rich_interaction_actions_map_params(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        data = (
            {"selected": [{"value": "vn", "label": "Vietnam", "index": 1}]}
            if action == "select_option"
            else {}
        )
        return {"success": True, "data": data, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action({"action": "hover", "selector": ".menu", "index": 1, "tab_id": 7}),
            _action({"action": "focus", "selector": "#search", "tab_id": 7}),
            _action(
                {
                    "action": "select_option",
                    "selector": "#country",
                    "values": ["Vietnam"],
                    "match": "label",
                    "tab_id": 7,
                }
            ),
            _action(
                {
                    "action": "set_checked",
                    "selector": "#terms",
                    "checked": True,
                    "tab_id": 7,
                }
            ),
            _action(
                {
                    "action": "drag",
                    "source_selector": "#card",
                    "target_selector": "#done",
                    "steps": 12,
                    "tab_id": 7,
                }
            ),
            _action(
                {
                    "action": "wait_for_text",
                    "text": "Saved",
                    "selector": "#toast",
                    "exact": True,
                    "tab_id": 7,
                }
            ),
            _action(
                {
                    "action": "key",
                    "key": "a",
                    "modifiers": ["Meta", "Shift"],
                    "tab_id": 7,
                }
            ),
        ]
    )

    assert isinstance(result, str)
    assert "Hovered '.menu'" in result
    assert '"label": "Vietnam"' in result
    assert "Meta+Shift+a" in result
    assert seen == [
        ("hover", {"selector": ".menu", "index": 1, "tab_id": 7}),
        ("focus", {"selector": "#search", "index": 0, "tab_id": 7}),
        (
            "select_option",
            {
                "selector": "#country",
                "values": ["Vietnam"],
                "match": "label",
                "tab_id": 7,
            },
        ),
        (
            "set_checked",
            {"selector": "#terms", "checked": True, "index": 0, "tab_id": 7},
        ),
        (
            "drag",
            {
                "source_selector": "#card",
                "target_selector": "#done",
                "source_index": 0,
                "target_index": 0,
                "steps": 12,
                "tab_id": 7,
            },
        ),
        (
            "wait_for_text",
            {
                "text": "Saved",
                "selector": "#toast",
                "state": "visible",
                "exact": True,
                "timeout_ms": 10000,
                "tab_id": 7,
            },
        ),
        ("key", {"key": "a", "modifiers": ["Meta", "Shift"], "tab_id": 7}),
    ]


async def test_tool_open_and_close_tab(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    def handler(action: str, params: dict):
        if action == "open_tab":
            return {"success": True, "data": {"tab_id": 42}, "error": None}
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action({"action": "open_tab", "url": "https://x.test"}),
            _action({"action": "close_tab", "id": 42}),
        ]
    )
    assert "id=42" in result
    assert "Closed tab" in result


async def test_tool_switch_tab_accepts_id_without_index(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []
    _stub_send(
        monkeypatch,
        manager,
        lambda action, params: (
            seen.append((action, params))
            or {"success": True, "data": {}, "error": None}
        ),
    )

    result = await webbridge(actions=[_action({"action": "switch_tab", "id": 42})])

    assert result == "Switched to tab id=42"
    assert seen == [("switch_tab", {"id": 42})]


async def test_tool_tab_id_omitted_when_unset(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []
    _stub_send(
        monkeypatch,
        manager,
        lambda a, p: (
            seen.append((a, p)) or {"success": True, "data": {}, "error": None}
        ),
    )
    await webbridge(actions=[_action({"action": "back"})])
    assert seen == [
        ("back", {})
    ]  # tab_id omitted entirely when the model didn't set one

    seen.clear()
    await webbridge(actions=[_action({"action": "extract"})])
    assert "tab_id" not in seen[0][1]  # still omitted; other extract params present
    assert seen[0][1]["format"] == "text"


# ── Tool-level: crawl actions ─────────────────────────────────────────────────


async def test_tool_extract_markdown_maps_params(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {
            "success": True,
            "data": {"title": "T", "url": "u", "content": "# Hi", "format": "markdown"},
            "error": None,
        }

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action(
                {
                    "action": "extract",
                    "format": "markdown",
                    "selector": "article",
                    "max_chars": 500,
                }
            )
        ]
    )
    assert seen[0][0] == "extract"
    assert seen[0][1] == {"format": "markdown", "selector": "article", "max_chars": 500}
    assert "# Hi" in result and "markdown" in result


async def test_tool_extract_elements_returns_records(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {
            "success": True,
            "data": {
                "records": [
                    {"title": "A", "url": "https://x/a"},
                    {"title": "B", "url": "https://x/b"},
                ]
            },
            "error": None,
        }

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action(
                {
                    "action": "extract_elements",
                    "selector": ".card",
                    "fields": {"title": "h3", "url": "a@href"},
                }
            )
        ]
    )
    assert seen[0][0] == "extract_elements"
    assert seen[0][1]["selector"] == ".card"
    assert seen[0][1]["fields"] == {"title": "h3", "url": "a@href"}
    assert "2 record" in result and "https://x/a" in result


async def test_tool_extract_elements_empty(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _stub_send(
        monkeypatch,
        manager,
        lambda a, p: {"success": True, "data": {"records": []}, "error": None},
    )
    result = await webbridge(
        actions=[_action({"action": "extract_elements", "selector": ".none"})]
    )
    assert "No elements matched" in result


async def test_tool_scroll_to_bottom(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {
            "success": True,
            "data": {"scrolls": 3, "final_height": 4200, "at_bottom": True},
            "error": None,
        }

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[_action({"action": "scroll_to_bottom", "max_scrolls": 5})]
    )
    assert seen[0][0] == "scroll_to_bottom"
    assert seen[0][1]["max_scrolls"] == 5
    assert "3 step" in result and "reached bottom" in result


# ── Tool-level: wait_for_network_idle + crawl ─────────────────────────────────


async def test_tool_wait_for_network_idle_reports_idle(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, params))
        return {"success": True, "data": {"idle": True, "inflight": 0}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[_action({"action": "wait_for_network_idle", "idle_ms": 800})]
    )
    assert seen[0] == ("wait_for_network_idle", {"idle_ms": 800, "timeout_ms": 20000})
    assert "Network idle" in result


async def test_tool_wait_for_network_idle_reports_timeout(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    _stub_send(
        monkeypatch,
        manager,
        lambda a, p: {
            "success": True,
            "data": {"idle": False, "inflight": 2, "timed_out": True},
            "error": None,
        },
    )
    result = await webbridge(actions=[_action({"action": "wait_for_network_idle"})])
    assert "still active" in result and "2 request" in result


async def test_tool_crawl_requires_urls(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []
    _stub_send(
        monkeypatch,
        manager,
        lambda a, p: (
            seen.append((a, p)) or {"success": True, "data": {}, "error": None}
        ),
    )
    result = await webbridge(actions=[_action({"action": "crawl", "urls": []})])
    assert "at least one URL" in result
    assert seen == []  # no commands issued for an empty url list


async def test_tool_crawl_runs_pages_concurrently(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    """The whole point of `crawl` is real overlap across tabs, not a serial

    loop dressed up as one — so this drives the semaphore with a handler that
    actually suspends (asyncio.sleep) and records the high-water mark of
    simultaneously in-flight ``wait_for_load`` calls.
    """
    tab_counter = 0
    concurrent = 0
    max_concurrent = 0

    async def fake_send_command(
        session_id: str, action: str, params: dict | None = None
    ):
        nonlocal tab_counter, concurrent, max_concurrent
        params = params or {}
        if action == "open_tab":
            tab_counter += 1
            return {"success": True, "data": {"tab_id": tab_counter}, "error": None}
        if action == "wait_for_load":
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            await asyncio.sleep(0.02)
            concurrent -= 1
            return {"success": True, "data": {}, "error": None}
        if action == "extract":
            return {
                "success": True,
                "data": {"title": "T", "content": f"body-{params['tab_id']}"},
                "error": None,
            }
        return {"success": True, "data": {}, "error": None}  # close_tab

    monkeypatch.setattr(manager, "send_command", fake_send_command)

    urls = [f"https://example.com/{i}" for i in range(6)]
    result = await webbridge(
        actions=[_action({"action": "crawl", "urls": urls, "concurrency": 3})]
    )

    assert (
        max_concurrent == 3
    )  # genuinely overlapped, capped exactly at the semaphore size
    assert "Crawled 6 URL(s) (3 at a time): 6 ok, 0 failed" in result
    # asyncio.gather preserves input order in the result regardless of completion order
    assert result.index(urls[0]) < result.index(urls[-1])
    for url in urls:
        assert url in result


async def test_tool_crawl_networkidle_and_elements_mode(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[tuple[str, dict]] = []

    def handler(action: str, params: dict):
        seen.append((action, dict(params)))
        if action == "open_tab":
            return {"success": True, "data": {"tab_id": 9}, "error": None}
        if action == "extract_elements":
            return {
                "success": True,
                "data": {"records": [{"title": "A"}]},
                "error": None,
            }
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action(
                {
                    "action": "crawl",
                    "urls": ["https://example.com/a"],
                    "wait": "networkidle",
                    "elements_selector": ".card",
                    "fields": {"title": "h3"},
                }
            )
        ]
    )
    actions_seen = [a for a, _ in seen]
    assert "wait_for_network_idle" in actions_seen
    assert "wait_for_load" not in actions_seen
    extract_elements_call = next(p for a, p in seen if a == "extract_elements")
    assert extract_elements_call == {
        "tab_id": 9,
        "selector": ".card",
        "fields": {"title": "h3"},
        "limit": 100,
    }
    assert "1 record" in result and '"title": "A"' in result


async def test_tool_crawl_isolates_per_page_errors(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    def handler(action: str, params: dict):
        if action == "open_tab":
            if params["url"].endswith("/bad"):
                return {"success": False, "data": None, "error": "boom"}
            return {"success": True, "data": {"tab_id": 1}, "error": None}
        if action == "extract":
            return {
                "success": True,
                "data": {"title": "Good", "content": "all fine"},
                "error": None,
            }
        return {"success": True, "data": {}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    result = await webbridge(
        actions=[
            _action({"action": "crawl", "urls": ["https://x/good", "https://x/bad"]})
        ]
    )
    assert "1 ok, 1 failed" in result
    assert "ERROR: open_tab failed: boom" in result
    assert "Title: Good" in result and "all fine" in result


async def test_tool_crawl_close_tabs_false_skips_close(
    manager: WebBridgeManager, monkeypatch: pytest.MonkeyPatch
):
    seen: list[str] = []

    def handler(action: str, params: dict):
        seen.append(action)
        if action == "open_tab":
            return {"success": True, "data": {"tab_id": 1}, "error": None}
        return {"success": True, "data": {"content": "ok"}, "error": None}

    _stub_send(monkeypatch, manager, handler)
    await webbridge(
        actions=[
            _action({"action": "crawl", "urls": ["https://x/a"], "close_tabs": False})
        ]
    )
    assert "close_tab" not in seen


# ── POST /launch-browser ─────────────────────────────────────────────────────


class _PopenRecorder:
    """subprocess.Popen stand-in that records argv/kwargs, never spawns."""

    instances: list[dict] = []

    def __init__(self, argv, **kwargs):
        _PopenRecorder.instances.append({"argv": list(argv), "kwargs": kwargs})


@pytest.fixture
def ext_dir(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Point the extension-dir override at a real (empty) tmp directory."""
    d = tmp_path / "webbridge-ext"
    d.mkdir()
    monkeypatch.setenv("EVOFLUX_WEBBRIDGE_EXTENSION_DIR", str(d))
    return d


class TestLaunchBrowser:
    @pytest.fixture(autouse=True)
    def _record_popen(self, monkeypatch: pytest.MonkeyPatch):
        _PopenRecorder.instances = []
        monkeypatch.setattr(subprocess, "Popen", _PopenRecorder)

    def test_darwin_argv(self, client, ext_dir, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["browser"] == "chrome"
        # Caveats the UI must surface.
        assert "FULLY quit" in data["message"]
        assert "developer-mode" in data["message"]
        [call] = _PopenRecorder.instances
        assert call["argv"] == [
            "open",
            "-na",
            "Google Chrome",
            "--args",
            f"--load-extension={ext_dir}",
            "--silent-debugger-extension-api",
        ]
        assert call["kwargs"]["start_new_session"] is True

    def test_linux_argv_google_chrome(
        self, client, ext_dir, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None,
        )
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 200
        assert resp.json()["browser"] == "chrome"
        [call] = _PopenRecorder.instances
        assert call["argv"] == [
            "/usr/bin/google-chrome",
            f"--load-extension={ext_dir}",
            "--silent-debugger-extension-api",
        ]

    def test_linux_argv_chromium_label(
        self, client, ext_dir, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: "/usr/bin/chromium" if name == "chromium" else None,
        )
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 200
        assert resp.json()["browser"] == "chromium"
        [call] = _PopenRecorder.instances
        assert call["argv"] == [
            "/usr/bin/chromium",
            f"--load-extension={ext_dir}",
            "--silent-debugger-extension-api",
        ]

    def test_linux_no_browser_500(
        self, client, ext_dir, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(shutil, "which", lambda name: None)
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 500
        assert "google-chrome" in resp.json()["detail"]
        assert _PopenRecorder.instances == []

    def test_win32_argv_with_creationflags(
        self, client, ext_dir, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(
            shutil,
            "which",
            lambda name: r"C:\chrome\chrome.exe" if name == "chrome" else None,
        )
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 200
        assert resp.json()["browser"] == "chrome"
        [call] = _PopenRecorder.instances
        assert call["argv"] == [
            r"C:\chrome\chrome.exe",
            f"--load-extension={ext_dir}",
            "--silent-debugger-extension-api",
        ]
        assert "creationflags" in call["kwargs"]

    def test_missing_extension_dir_404(
        self, client, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv(
            "EVOFLUX_WEBBRIDGE_EXTENSION_DIR", str(tmp_path / "does-not-exist")
        )
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert "EVOFLUX_WEBBRIDGE_EXTENSION_DIR" in detail
        # Manual-install instructions are part of the pinned contract.
        assert "chrome://extensions" in detail
        assert _PopenRecorder.instances == []

    def test_popen_failure_500(self, client, ext_dir, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(sys, "platform", "darwin")

        def _boom(*args, **kwargs):
            raise OSError("no opener")

        monkeypatch.setattr(subprocess, "Popen", _boom)
        resp = client.post(f"{_PREFIX}/launch-browser")
        assert resp.status_code == 500
        assert "no opener" in resp.json()["detail"]


# ── GET /download (extension package) ─────────────────────────────────────────


def test_download_extension_zip(client: TestClient, ext_dir):
    (ext_dir / "manifest.json").write_text('{"name":"x"}', encoding="utf-8")
    (ext_dir / "background.js").write_text("// bg", encoding="utf-8")
    icons = ext_dir / "icons"
    icons.mkdir()
    (icons / "icon16.png").write_bytes(b"\x89PNG\r\n")
    (ext_dir / ".DS_Store").write_bytes(b"junk")  # must be skipped

    resp = client.get(f"{_PREFIX}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "evoflux-webbridge.zip" in resp.headers["content-disposition"]

    names = set(zipfile.ZipFile(io.BytesIO(resp.content)).namelist())
    assert "webbridge/manifest.json" in names
    assert "webbridge/background.js" in names
    assert "webbridge/icons/icon16.png" in names
    assert not any(".DS_Store" in n for n in names)


def test_download_missing_dir_404(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("EVOFLUX_WEBBRIDGE_EXTENSION_DIR", str(tmp_path / "nope"))
    resp = client.get(f"{_PREFIX}/download")
    assert resp.status_code == 404
