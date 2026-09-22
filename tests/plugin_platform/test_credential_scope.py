from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.plugin_platform.credentials import (
    CredentialAccessError,
    CredentialMetadata,
    enforce_credential_scope,
)


def _metadata() -> CredentialMetadata:
    return CredentialMetadata(
        installation_id="a" * 32,
        workspace_id="workspace-a",
        project_id="project-a",
        tenant="tenant-a",
        package_digest="b" * 64,
        created_at=datetime.now(UTC).isoformat(),
        expires_at=(datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    )


def test_credential_scope_rejects_wrong_tenant_and_broader_package() -> None:
    metadata = _metadata()
    enforce_credential_scope(
        metadata,
        installation_id="a" * 32,
        workspace_id="workspace-a",
        project_id="project-a",
        tenant="tenant-a",
        package_digest="b" * 64,
    )

    with pytest.raises(CredentialAccessError, match="tenant"):
        enforce_credential_scope(metadata, installation_id="a" * 32, tenant="tenant-b")
    with pytest.raises(CredentialAccessError, match="package_digest"):
        enforce_credential_scope(
            metadata,
            installation_id="a" * 32,
            package_digest="c" * 64,
        )
