from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes import plugins as plugin_routes
from app.core.config import settings
from app.plugin_platform.marketplace import MarketplaceIndex


def _index() -> MarketplaceIndex:
    return MarketplaceIndex.model_validate(
        {
            "version": 1,
            "plugins": [
                {
                    "npmPackage": "@example/demo-plugin",
                    "name": "demo-plugin",
                    "version": "1.0.0",
                    "description": "Demo plugin",
                    "license": "Apache-2.0",
                    "portable": True,
                    "portableComponents": ["skills"],
                    "compatibleClients": ["evoflux", "claude"],
                    "hostCapabilities": [],
                    "skills": ["demo"],
                    "mcpServers": [],
                    "connections": [],
                    "artifact": {
                        "url": "https://marketplace.example/demo-plugin.evoplugin",
                        "sha256": "a" * 64,
                    },
                    "publisher": {
                        "id": "example",
                        "signatureAlgorithm": "ed25519",
                    },
                    "verification": {"state": "verified"},
                    "lifecycle": "active",
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_marketplace_listing_returns_safe_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "EVOFLUX_PLUGIN_MARKETPLACE_URL",
        "https://marketplace.example/registry.json",
    )
    monkeypatch.setattr(
        plugin_routes.MarketplaceProvider,
        "fetch_registry",
        AsyncMock(return_value=_index()),
    )
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/plugins/marketplace")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["entry"]["name"] == "demo-plugin"
    assert item["verification_state"] == "verified"
    assert item["readiness"]["state"] == "disabled"
    assert item["readiness"]["can_enable"] is False


@pytest.mark.asyncio
async def test_marketplace_listing_requires_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_PLUGIN_MARKETPLACE_URL", "")
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/plugins/marketplace")

    assert response.status_code == 503
    assert response.json()["detail"] == "Plugin marketplace is not configured."
