from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.plugin_platform.models import PluginRunContext


def test_run_context_is_immutable_and_provenance_bound() -> None:
    context = PluginRunContext(
        installation_id="a" * 32,
        content_sha256="b" * 64,
        workspace_id="workspace-a",
        project_id="project-a",
        tenant="tenant-a",
        environment="production",
        run_id="run-1",
        operation="jira.read",
        policy_version="1",
        policy_allowed=True,
    )

    with pytest.raises(ValidationError):
        context.tenant = "tenant-b"
    assert context.content_sha256 == "b" * 64


def test_run_context_rejects_unknown_provenance_shape() -> None:
    with pytest.raises(ValidationError):
        PluginRunContext(
            installation_id="a" * 32,
            content_sha256="not-a-digest",
            workspace_id="workspace-a",
            tenant="tenant-a",
            environment="production",
            run_id="run-1",
            operation="report.render",
            policy_version="1",
            policy_allowed=False,
        )
