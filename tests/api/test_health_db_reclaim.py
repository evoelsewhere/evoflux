"""Tests for the Diagnostics database-reclaim action.

The check that reports free pages now carries the button that frees them, so
both the metadata it hands the UI and the guards on the endpoint are part of
the contract.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.health import (
    _AUTO_VACUUM_INCREMENTAL,
    _AUTO_VACUUM_NONE,
    _db_reclaim_action,
    router,
)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/health")
    return TestClient(app, raise_server_exceptions=False)


class TestReclaimActionMetadata:
    def test_incremental_database_is_not_promised_a_rewrite(self):
        action = _db_reclaim_action(_AUTO_VACUUM_INCREMENTAL, 337.5)

        assert action["id"] == "db_reclaim"
        assert "338 MiB" in action["confirm_body"]
        assert "rewrite" not in action["confirm_body"].lower()

    def test_legacy_database_is_told_it_will_be_rewritten(self):
        action = _db_reclaim_action(_AUTO_VACUUM_NONE, 337.5)

        body = action["confirm_body"].lower()
        assert "rewrites the database" in body
        # The one-off nature is the reason the wait is acceptable, so it has
        # to be in the sentence the user actually reads.
        assert "one-off" in body

    def test_every_field_the_button_renders_is_present(self):
        action = _db_reclaim_action(_AUTO_VACUUM_NONE, 12.0)

        for key in (
            "id",
            "label",
            "running_label",
            "confirm_title",
            "confirm_body",
            "confirm_label",
        ):
            assert action[key], f"missing {key}"


class TestReclaimEndpoint:
    def test_refused_while_an_agent_is_working(self):
        # The rewrite holds a write lock for its whole duration; a turn
        # mid-flight would stall on it rather than fail cleanly.
        with (
            patch("app.core.db._is_sqlite", True),
            patch(
                "app.services.team_manager.has_active_team_turn",
                return_value=True,
            ),
        ):
            resp = _client().post("/api/health/diagnostics/actions/db_reclaim")

        assert resp.status_code == 409
        assert "agent is working" in resp.json()["detail"]

    def test_refused_when_the_database_is_not_sqlite(self):
        with (
            patch("app.core.db._is_sqlite", False),
            patch(
                "app.services.team_manager.has_active_team_turn",
                return_value=False,
            ),
        ):
            resp = _client().post("/api/health/diagnostics/actions/db_reclaim")

        assert resp.status_code == 400
        assert "SQLite" in resp.json()["detail"]

    @pytest.mark.parametrize("action_id", ["nope", "db_reclaim_all", "../etc"])
    def test_unknown_actions_have_no_endpoint(self, action_id: str):
        resp = _client().post(f"/api/health/diagnostics/actions/{action_id}")

        assert resp.status_code == 405 or resp.status_code == 404
