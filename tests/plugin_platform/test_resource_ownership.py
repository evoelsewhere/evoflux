from __future__ import annotations

import pytest

from app.plugin_platform.models import PluginRunContext
from app.plugin_platform.policy import ResourceOwnership, enforce_resource_ownership


def _context() -> PluginRunContext:
    return PluginRunContext(
        installation_id="a" * 32,
        content_sha256="b" * 64,
        workspace_id="workspace-a",
        project_id="project-a",
        tenant="tenant-a",
        environment="production",
        run_id="run-1",
        operation="report.render",
        policy_version="1",
        policy_allowed=True,
    )


def test_resource_ownership_covers_cache_report_and_destination() -> None:
    context = _context()
    for kind in ("cache", "report", "destination"):
        enforce_resource_ownership(
            context,
            ResourceOwnership(
                kind=kind,
                installation_id=context.installation_id,
                content_sha256=context.content_sha256,
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                tenant=context.tenant,
            ),
        )


def test_resource_ownership_rejects_unknown_or_cross_tenant_owner() -> None:
    context = _context()
    with pytest.raises(PermissionError, match="tenant"):
        enforce_resource_ownership(
            context,
            ResourceOwnership(
                kind="credential",
                installation_id=context.installation_id,
                content_sha256=context.content_sha256,
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                tenant=None,
            ),
        )
