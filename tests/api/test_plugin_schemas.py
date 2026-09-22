from __future__ import annotations

from app.api.schemas.plugins import (
    PluginMarketplaceItem,
    PluginMarketplaceResponse,
    PluginReadiness,
)


def _entry() -> dict[str, object]:
    return {
        "npmPackage": "@evoflux/management-report-kit",
        "name": "management-report-kit",
        "version": "0.1.0",
        "description": "Weekly management report templates.",
        "license": "Apache-2.0",
        "portable": True,
        "portableComponents": ["skills", "mcp"],
        "compatibleClients": ["evoflux", "claude", "codex"],
        "hostCapabilities": ["scheduler"],
        "skills": ["weekly-management-report"],
        "mcpServers": [],
        "connections": [],
        "artifact": {
            "url": "https://marketplace.example/plugins/management-report-kit.evoplugin",
            "sha256": "a" * 64,
            "size": 1024,
        },
        "publisher": {
            "id": "evoflux",
            "signatureAlgorithm": "ed25519",
            "publicKey": None,
            "signature": None,
        },
        "verification": {
            "state": "unverified",
            "verifiedAt": None,
            "reason": "publisher key is not configured",
        },
        "lifecycle": "active",
        "reportTemplates": [],
    }


def test_marketplace_contract_preserves_safe_install_readiness() -> None:
    item = PluginMarketplaceItem.model_validate(
        {
            "entry": _entry(),
            "verification_state": "unverified",
            "trust_review": None,
            "readiness": {
                "state": "pending-approval",
                "can_enable": False,
                "reasons": ["trust review required"],
                "missing_credentials": [],
                "pending_connections": [],
            },
        }
    )

    response = PluginMarketplaceResponse(items=[item])

    assert response.items[0].readiness.can_enable is False
    assert response.items[0].verification_state == "unverified"
    assert response.provider_available is True


def test_readiness_contract_defaults_to_safe_lists() -> None:
    readiness = PluginReadiness(state="missing-credentials")

    assert readiness.can_enable is False
    assert readiness.reasons == []
    assert readiness.missing_credentials == []
    assert readiness.pending_connections == []
