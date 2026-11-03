"""Fixtures for the ``webbridge-browser`` contract (temp data dirs, loopback sockets only)."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import httpx
import pytest

from wb_helpers import EXTENSION_ORIGIN, Pairing


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

    def make(title: str = "Contract", tags: list[str] | None = None) -> str:
        import json

        session = uuid.uuid4()
        with sqlite3.connect(db_path, timeout=30) as db:
            db.execute(
                "INSERT INTO chat_sessions (id, title, created_at, updated_at, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session.hex,
                    title,
                    "2026-01-01",
                    "2026-01-01",
                    json.dumps(tags) if tags else None,
                ),
            )
        return str(session)

    return make


@pytest.fixture
def insert_pairing(db_path: Path):
    """Insert a pairing row with an exact scope set (a historical or restricted grant)."""

    def insert(scopes: list[str], credential: str = "restricted-credential") -> Pairing:
        import hashlib
        import json

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
