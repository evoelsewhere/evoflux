from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.plugin_platform.models import PluginConnectionProfile


def test_connection_profile_is_installation_and_digest_scoped() -> None:
    profile = PluginConnectionProfile(
        id="jira-read",
        installation_id="a" * 32,
        workspace_id="workspace-a",
        project_id="project-a",
        tenant="tenant-a",
        environment="production",
        package_digest="b" * 64,
        endpoint="https://example.invalid/jira",
        resources=["issues:read"],
        operations=["read"],
        credential_refs=["jira-token"],
    )

    assert profile.tenant == "tenant-a"
    assert profile.operations == ["read"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("installation_id", "not-an-installation"),
        ("package_digest", "not-a-digest"),
        ("operations", []),
    ],
)
def test_connection_profile_rejects_unscoped_values(field: str, value: object) -> None:
    payload = {
        "id": "jira-read",
        "installation_id": "a" * 32,
        "package_digest": "b" * 64,
        "endpoint": "https://example.invalid/jira",
        "operations": ["read"],
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        PluginConnectionProfile.model_validate(payload)
