from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.plugin_platform.connections import (
    ConnectionDeniedError,
    authorize_connection,
    redact_outbound,
)
from app.plugin_platform.models import PluginConnectionProfile, PluginRunContext


INSTALLATION = "a" * 32
DIGEST = "b" * 64


def _context() -> PluginRunContext:
    return PluginRunContext(
        installation_id=INSTALLATION,
        content_sha256=DIGEST,
        workspace_id="workspace-a",
        project_id="project-a",
        tenant="tenant-a",
        environment="production",
        run_id="run-connection",
        operation="jira.read",
        policy_version="1",
        policy_allowed=True,
    )


def _profile(**overrides: object) -> PluginConnectionProfile:
    payload: dict[str, object] = {
        "id": "jira-read",
        "installation_id": INSTALLATION,
        "workspace_id": "workspace-a",
        "project_id": "project-a",
        "tenant": "tenant-a",
        "environment": "production",
        "package_digest": DIGEST,
        "endpoint": "https://jira.example.invalid",
        "resources": ["project:ABC", "issue:*"],
        "operations": ["read"],
        "enabled": True,
        "approval": "approved",
        "redacted_fields": ["token", "authorization"],
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    payload.update(overrides)
    return PluginConnectionProfile.model_validate(payload)


def test_connection_requires_approval_allowlists_and_provenance() -> None:
    decision = authorize_connection(
        _profile(),
        _context(),
        endpoint="https://jira.example.invalid/rest/api/2/search",
        operation="read",
        resource="project:ABC",
    )
    assert decision.allowed

    with pytest.raises(ConnectionDeniedError, match="operation"):
        authorize_connection(
            _profile(),
            _context(),
            endpoint="https://jira.example.invalid",
            operation="write",
            resource="project:ABC",
        )
    with pytest.raises(ConnectionDeniedError, match="resource"):
        authorize_connection(
            _profile(),
            _context(),
            endpoint="https://jira.example.invalid",
            operation="read",
            resource="project:SECRET",
        )
    with pytest.raises(ConnectionDeniedError, match="provenance"):
        authorize_connection(
            _profile(package_digest="c" * 64),
            _context(),
            endpoint="https://jira.example.invalid",
            operation="read",
            resource="project:ABC",
        )


def test_connection_rejects_budget_and_lifecycle_failures() -> None:
    profile = _profile(rateLimit=2, quota=5)
    with pytest.raises(ConnectionDeniedError, match="rate limit"):
        authorize_connection(
            profile,
            _context(),
            endpoint="https://jira.example.invalid",
            operation="read",
            resource="project:ABC",
            usage={"rate": 2},
        )
    with pytest.raises(ConnectionDeniedError, match="unapproved"):
        authorize_connection(
            _profile(approval="pending"),
            _context(),
            endpoint="https://jira.example.invalid",
            operation="read",
            resource="project:ABC",
        )


def test_outbound_redaction_does_not_mutate_input() -> None:
    payload = {"token": "secret", "nested": {"Authorization": "bearer secret"}}

    redacted = redact_outbound(payload, ["token", "authorization"])

    assert redacted == {
        "token": "[redacted]",
        "nested": {"Authorization": "[redacted]"},
    }
    assert payload["token"] == "secret"
