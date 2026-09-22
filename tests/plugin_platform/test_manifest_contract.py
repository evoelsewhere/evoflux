from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.plugin_platform.models import PluginManifest


def _manifest(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": "management-report-kit",
        "version": "0.1.0",
        "description": "Portable management report workflow.",
        "license": "Apache-2.0",
        "compatibility": {
            "portableComponents": ["skills", "mcp"],
            "compatibleClients": ["evoflux", "claude", "codex"],
            "hostCapabilities": ["scheduler", "artifact-storage", "credential-broker"],
        },
        "connections": [
            {
                "id": "jira-source",
                "transport": "mcp",
                "hosts": ["https://example.invalid/jira"],
                "operations": ["read"],
                "credentialFields": [
                    {"name": "JIRA_API_TOKEN", "type": "secret", "required": False}
                ],
            }
        ],
        "policy": {
            "all": [
                {"attribute": "workspace.authorized", "operator": "eq", "value": True}
            ],
            "deny": [
                {
                    "attribute": "data.classification",
                    "operator": "eq",
                    "value": "restricted",
                }
            ],
        },
        "report": {
            "modelSchema": "schemas/report-output.schema.json",
            "templates": [
                {
                    "id": "management-markdown",
                    "path": "templates/management-report.md",
                    "format": "markdown",
                }
            ],
        },
    }
    payload.update(overrides)
    return payload


def test_manifest_accepts_portable_connection_policy_and_report_contract() -> None:
    manifest = PluginManifest.model_validate(_manifest())

    assert manifest.compatibility is not None
    assert manifest.compatibility.portable_components == ["skills", "mcp"]
    assert manifest.connections[0].credential_fields[0].type == "secret"
    assert manifest.report is not None
    assert manifest.report.templates[0].format == "markdown"


def test_manifest_rejects_native_extensions() -> None:
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(_manifest(nativeExtensions=["python"]))


def test_manifest_rejects_secret_defaults() -> None:
    payload = _manifest()
    payload["connections"] = [
        {
            "id": "jira-source",
            "transport": "mcp",
            "hosts": ["https://example.invalid/jira"],
            "operations": ["read"],
            "credentialFields": [
                {
                    "name": "JIRA_API_TOKEN",
                    "type": "secret",
                    "required": True,
                    "default": "must-not-be-embedded",
                }
            ],
        }
    ]
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(payload)


def test_manifest_rejects_unsafe_report_path() -> None:
    payload = _manifest()
    payload["report"] = {
        "templates": [{"id": "unsafe", "path": "../outside.md", "format": "markdown"}]
    }
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(payload)


def test_legacy_manifest_without_marketplace_metadata_remains_valid() -> None:
    manifest = PluginManifest.model_validate(
        {
            "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
            "name": "legacy-plugin",
            "version": "0.1.0",
            "description": "A legacy portable plugin.",
            "license": "Apache-2.0",
        }
    )

    assert manifest.compatibility is None
    assert manifest.connections == []
