"""Tests for app/api/routes/health.py — /live + /ready split."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.health import router
from app.core.db import get_session
from app.core.version import VERSION


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
        import app.api.routes.health as health_mod

        health_mod._validate_agents_cache = None  # clear cache
        with patch("app.services.team_manager.validate_agents_dir", return_value=False):
            client = TestClient(_make_app(db_ok=True))
            resp = client.get("/api/health/ready")
        health_mod._validate_agents_cache = None
        assert resp.status_code == 200
        body = resp.json()
        assert body["checks"]["team"] == "missing"

    def test_ready_marks_team_invalid_on_parse_error(self):
        """A malformed agent .md surfaces as ``team=invalid``."""
        import app.api.routes.health as health_mod

        health_mod._validate_agents_cache = None  # clear cache
        with patch(
            "app.services.team_manager.validate_agents_dir",
            side_effect=ValueError("bad yaml"),
        ):
            client = TestClient(_make_app(db_ok=True))
            resp = client.get("/api/health/ready")
        health_mod._validate_agents_cache = None
        # Team validation failure does not flip overall readiness — DB is
        # the gate.  But the per-check value must reflect the parse error.
        body = resp.json()
        assert body["checks"]["team"] == "invalid"


class TestValidateAgentsDirCache:
    """The 30s cache must key on the validator, not just on elapsed time.

    Health endpoints are polled, so the result is cached — but a swapped
    validator (tests, or a reloaded ``team_manager``) has to be observed
    immediately instead of serving a stale answer for up to 30 seconds.
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        import app.api.routes.health as health_mod

        health_mod._validate_agents_cache = None
        yield
        health_mod._validate_agents_cache = None

    @pytest.mark.asyncio
    async def test_swapped_validator_is_not_served_from_cache(self):
        import app.api.routes.health as health_mod

        with patch("app.services.team_manager.validate_agents_dir", return_value=True):
            assert await health_mod.validate_agents_dir_cached() is True
        with patch("app.services.team_manager.validate_agents_dir", return_value=False):
            assert await health_mod.validate_agents_dir_cached() is False

    @pytest.mark.asyncio
    async def test_cached_error_is_not_replayed_for_a_new_validator(self):
        import app.api.routes.health as health_mod

        with patch(
            "app.services.team_manager.validate_agents_dir",
            side_effect=ValueError("bad yaml"),
        ):
            with pytest.raises(ValueError):
                await health_mod.validate_agents_dir_cached()
        with patch("app.services.team_manager.validate_agents_dir", return_value=True):
            assert await health_mod.validate_agents_dir_cached() is True

    @pytest.mark.asyncio
    async def test_repeat_calls_reuse_the_cache_for_the_same_validator(self):
        import app.api.routes.health as health_mod

        validator = MagicMock(return_value=True)
        with patch("app.services.team_manager.validate_agents_dir", validator):
            assert await health_mod.validate_agents_dir_cached() is True
            assert await health_mod.validate_agents_dir_cached() is True
        assert validator.call_count == 1


class TestLegacyAliasRemoved:
    def test_bare_health_returns_404(self):
        """The legacy ``GET /api/health`` alias was removed."""
        client = TestClient(_make_app(db_ok=True))
        resp = client.get("/api/health")
        assert resp.status_code == 404
