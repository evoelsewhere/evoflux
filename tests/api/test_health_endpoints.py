"""Tests for app/api/routes/health.py — /live + /ready split."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routes.health as health_mod
from app.api.routes.health import router
from app.core.db import get_session
from app.core.version import VERSION


@pytest.fixture(autouse=True)
def _reset_agents_health_cache():
    """Keep readiness cases independent from the module's short-lived cache."""
    health_mod._validate_agents_cache = None
    yield
    health_mod._validate_agents_cache = None


def _make_app(*, db_ok: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/health")

    async def fake_session():
        session = MagicMock()

        async def exec_(_q):  # noqa: ANN001
            if not db_ok:
                raise RuntimeError("db down")
            return None

        session.exec = exec_
        yield session

    app.dependency_overrides[get_session] = fake_session
    return app


class TestLive:
    def test_live_always_returns_200(self):
        # Even with DB down.
        client = TestClient(_make_app(db_ok=False))
        resp = client.get("/api/health/live")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "version": VERSION}


class TestReady:
    def test_ready_ok_when_db_and_team_healthy(self):
        # ``validate_agents_dir`` returns True → agents dir is loadable.
        with patch("app.services.team_manager.validate_agents_dir", return_value=True):
            client = TestClient(_make_app(db_ok=True))
            resp = client.get("/api/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["checks"]["db"] == "ok"
        assert body["checks"]["team"] == "ok"

    def test_ready_ok_when_db_healthy_but_team_missing(self):
        """Empty agents dir is tolerable — reported but still ready."""
        with patch("app.services.team_manager.validate_agents_dir", return_value=False):
            client = TestClient(_make_app(db_ok=True))
            resp = client.get("/api/health/ready")
        assert resp.status_code == 200
        body = resp.json()
        assert body["checks"]["team"] == "missing"

    def test_ready_marks_team_invalid_on_parse_error(self):
        """A malformed agent .md surfaces as ``team=invalid``."""
        with patch(
            "app.services.team_manager.validate_agents_dir",
            side_effect=ValueError("bad yaml"),
        ):
            client = TestClient(_make_app(db_ok=True))
            resp = client.get("/api/health/ready")
        # Team validation failure does not flip overall readiness — DB is
        # the gate.  But the per-check value must reflect the parse error.
        body = resp.json()
        assert body["checks"]["team"] == "invalid"


class TestLegacyAliasRemoved:
    def test_bare_health_returns_404(self):
        """The legacy ``GET /api/health`` alias was removed."""
        client = TestClient(_make_app(db_ok=True))
        resp = client.get("/api/health")
        assert resp.status_code == 404
