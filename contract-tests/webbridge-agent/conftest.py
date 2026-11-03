"""Fixtures for the ``webbridge-agent`` contract (temp data dirs, loopback sockets only)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

import httpx
import pytest

from wa_helpers import EXTENSION_ORIGIN, Pairing


@pytest.fixture
def pairing(backend, client: httpx.Client) -> Pairing:
    """A pairing created through the native bootstrap, as the bundled extension does."""
    discovery = client.get("/api/team/webbridge/native-discovery")
    assert discovery.status_code == 200, discovery.text
    with httpx.Client(base_url=backend.base_url, timeout=30.0) as anonymous:
        response = anonymous.post(
            "/api/team/webbridge/pairing/native",
            headers={"Origin": EXTENSION_ORIGIN},
            json={
                "label": "Contract Chrome",
                "browser": "chrome",
                "version": "120",
                "discovery_token": discovery.json()["discovery_token"],
            },
        )
    assert response.status_code == 201, response.text
    body = response.json()
    return Pairing(body["pairing_id"], body["credential"], body["scopes"])


@pytest.fixture
def paired(backend, pairing: Pairing) -> httpx.Client:
    with httpx.Client(
        base_url=backend.base_url,
        headers={"Authorization": f"Bearer {pairing.credential}"},
        timeout=30.0,
    ) as http:
        yield http


@pytest.fixture
def db_path(backend, tmp_path: Path) -> Path:
    return tmp_path / "data" / "evoflux.db"


@pytest.fixture
def make_session(db_path: Path):
    """Insert a chat session row (the way the documents-preview contract does)."""

    def make(
        title: str = "Contract",
        workspace: Path | None = None,
        mode: str | None = None,
    ) -> str:
        session = uuid.uuid4()
        columns = ["id", "title", "created_at", "updated_at"]
        values: list[object] = [session.hex, title, "2026-01-01", "2026-01-01"]
        if workspace is not None:
            columns.append("workspace")
            values.append(str(workspace))
        if mode is not None:
            columns.append("mode")
            values.append(mode)
        with sqlite3.connect(db_path, timeout=30) as db:
            db.execute(
                f"INSERT INTO chat_sessions ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                values,
            )
        return str(session)

    return make


@pytest.fixture
def insert_message(db_path: Path):
    """Insert a session message row; ``created`` orders rows within a session."""

    def insert(
        session_id: str,
        role: str,
        content: str,
        *,
        extra: dict | None = None,
        exclude: bool = False,
        created: str = "2026-01-01 00:00:00.000000",
    ) -> str:
        message = uuid.uuid4()
        with sqlite3.connect(db_path, timeout=30) as db:
            db.execute(
                "INSERT INTO session_messages (id, session_id, role, content, extra, "
                "is_summary, exclude_from_context, created_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    message.hex,
                    session_id.replace("-", ""),
                    role,
                    content,
                    json.dumps(extra) if extra is not None else None,
                    1 if exclude else 0,
                    created,
                ),
            )
        return str(message)

    return insert


@pytest.fixture
def insert_pairing(db_path: Path):
    """Insert a pairing row with an exact scope set (a historical or restricted grant)."""

    def insert(scopes: list[str], credential: str = "restricted-credential") -> Pairing:
        pairing_id = uuid.uuid4()
        with sqlite3.connect(db_path, timeout=30) as db:
            db.execute(
                "INSERT INTO webbridge_pairings (id, label, browser, version, credential_hash, "
                "scopes, created_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pairing_id.hex,
                    "Inserted",
                    "chrome",
                    "1",
                    hashlib.sha256(credential.encode()).hexdigest(),
                    json.dumps(scopes),
                    "2026-01-01 00:00:00",
                    "2026-01-01 00:00:00",
                ),
            )
        return Pairing(str(pairing_id), credential, scopes)

    return insert


@pytest.fixture
def panel(client: httpx.Client, pairing: Pairing, paired: httpx.Client, make_session):
    """A session assigned to the pairing with tab 5 bound to https://example.com."""
    sid = make_session(title="Panel")
    assert (
        client.put(
            f"/api/team/webbridge/pairings/{pairing.id}/sessions/{sid}"
        ).status_code
        == 200
    )
    bound = paired.put(
        "/api/team/webbridge/bindings/5",
        json={"session_id": sid, "origin": "https://example.com"},
    )
    assert bound.status_code == 200, bound.text
    return sid
