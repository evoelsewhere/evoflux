from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes import plugins as plugin_routes
from app.core.config import settings
from app.plugin_platform.marketplaces import (
    MarketplacePlugin,
    MarketplacePluginPreview,
    sync_marketplace,
)
from app.plugin_platform.models import (
    PluginInspection,
    PluginInstallation,
    PluginMCPComponent,
)


@pytest.mark.asyncio
async def test_marketplace_preview_serializes_platform_models_and_redacts_secrets(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    secret = "secret-" + "value"
    marketplace_id = "a" * 16
    preview = MarketplacePluginPreview(
        preview_id="b" * 32,
        plugin=MarketplacePlugin(
            id="source-review",
            marketplace_id=marketplace_id,
            name="source-review",
            source_type="artifact",
            compatibility="compatible",
            installable=True,
            verification="verified",
        ),
        inspection=PluginInspection(
            root=str(tmp_path / "plugin"),
            valid=True,
            mcp_servers=[
                PluginMCPComponent(
                    name="private-server",
                    transport="stdio",
                    valid=True,
                    config=dict(type="stdio", command="server", env={"TOKEN": secret}),
                )
            ],
        ),
    )
    monkeypatch.setattr(
        plugin_routes, "prepare_marketplace_plugin", lambda *_args: preview
    )
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/plugins/marketplaces/{marketplace_id}/plugins/source-review/prepare"
        )

    assert response.status_code == 200
    assert response.json()["plugin"]["id"] == "source-review"
    assert (
        response.json()["inspection"]["mcp_servers"][0]["config"]["env"]["TOKEN"]
        == "[REDACTED]"
    )
    assert secret not in response.text


@pytest.mark.asyncio
async def test_marketplace_api_add_sync_search_and_remove(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/plugins/marketplaces",
            json={
                "kind": "agent_plugins",
                "name": "EvoFlux plugins",
                "url": "https://plugins.example/registry.json",
            },
        )
        assert created.status_code == 201
        source_id = created.json()["id"]

        monkeypatch.setattr(
            plugin_routes,
            "sync_marketplace",
            lambda marketplace_id: sync_marketplace(
                marketplace_id,
                fetcher=lambda _url: {
                    "version": 1,
                    "plugins": [
                        {
                            "name": "source-review",
                            "version": "1.0.0",
                            "description": "Search and review sources",
                            "portable": True,
                            "portableComponents": ["skills"],
                            "compatibleClients": ["evoflux"],
                            "artifact": {
                                "url": "https://plugins.example/source-review.evoplugin",
                                "sha256": "c" * 64,
                                "size": 64,
                            },
                        }
                    ],
                },
            ),
        )
        synced = await client.post(f"/api/plugins/marketplaces/{source_id}/sync")
        assert synced.status_code == 200
        assert synced.json()["last_synced_at"]

        results = await client.get(
            "/api/plugins/marketplaces/plugins",
            params={"q": "review", "marketplace_id": source_id},
        )
        assert results.status_code == 200
        assert [item["name"] for item in results.json()] == ["source-review"]

        listed = await client.get("/api/plugins/marketplaces")
        assert [item["id"] for item in listed.json()] == [source_id]
        removed = await client.delete(f"/api/plugins/marketplaces/{source_id}")
        assert removed.status_code == 200
        assert (await client.get("/api/plugins/marketplaces")).json() == []


@pytest.mark.asyncio
async def test_marketplace_api_rejects_http_source(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/plugins/marketplaces",
            json={
                "kind": "agent_plugins",
                "name": "Unsafe",
                "url": "http://plugins.example/registry.json",
            },
        )

    assert response.status_code == 422
    assert "HTTPS" in response.text


@pytest.mark.asyncio
async def test_marketplace_install_requires_and_forwards_partial_consent(
    monkeypatch,
) -> None:
    installation = PluginInstallation(
        id="1" * 32,
        name="research-skills",
        root="/tmp/plugin",
        source_type="installed",
        source_ref="marketplace:0123456789abcdef/research-skills@main",
        content_sha256="a" * 64,
        enabled=False,
        installed_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
    )
    inspection = PluginInspection(root="/tmp/plugin", valid=True)
    calls: list[tuple[str, bool]] = []

    def install(preview_id: str, *, allow_partial: bool = False) -> PluginInstallation:
        calls.append((preview_id, allow_partial))
        if not allow_partial:
            raise ValueError(
                "Partial marketplace installation requires explicit consent."
            )
        return installation

    monkeypatch.setattr(plugin_routes, "install_marketplace_preview", install)
    monkeypatch.setattr(
        plugin_routes, "_inspection_for", lambda _installation: inspection
    )
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)
    preview_id = "a" * 32

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        refused = await client.post(
            "/api/plugins/marketplaces/install",
            json={"preview_id": preview_id, "allow_partial": False},
        )
        accepted = await client.post(
            "/api/plugins/marketplaces/install",
            json={"preview_id": preview_id, "allow_partial": True},
        )

    assert refused.status_code == 422
    assert "explicit consent" in refused.text
    assert accepted.status_code == 200
    assert accepted.json()["installation"]["enabled"] is False
    assert calls == [(preview_id, False), (preview_id, True)]


@pytest.mark.asyncio
async def test_preview_file_review_requires_known_preview_and_redacts_content(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "package"
    root.mkdir()
    (root / "README.md").write_text("readme", encoding="utf-8")
    key = "to" + "ken"
    (root / "server.json").write_text(
        json.dumps({key: "private-value"}), encoding="utf-8"
    )
    env_name = "SERVICE" + "_VALUE"
    header_name = "X-Custom-" + "Auth"
    env_value = "fixture" + "-env-value"
    header_value = "fixture" + "-header-value"
    query_value = "fixture" + "-query-value"
    password_value = "fixture" + "-url-value"
    (root / ".mcp.json").write_text('{"mcpServers": ', encoding="utf-8")
    (root / "mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "stdio": {
                        "type": "stdio",
                        "command": "node",
                        "args": [],
                        "env": {env_name: env_value},
                    },
                    "remote": {
                        "type": "streamable-http",
                        "url": "https://review-user:"
                        + password_value
                        + "@example.test/mcp?x="
                        + query_value,
                        "headers": {header_name: header_value},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        plugin_routes,
        "marketplace_preview_root",
        lambda value: root if value == "known-id" else None,
    )
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get("/api/plugins/previews/known-id/files")
        file = await client.get(
            "/api/plugins/previews/known-id/files", params={"path": "server.json"}
        )
        mcp_file = await client.get(
            "/api/plugins/previews/known-id/files", params={"path": "mcp.json"}
        )
        malformed = await client.get(
            "/api/plugins/previews/known-id/files", params={"path": ".mcp.json"}
        )
        unknown = await client.get("/api/plugins/previews/not-known/files")
        traversal = await client.get(
            "/api/plugins/previews/known-id/files", params={"path": "../outside"}
        )

    assert listing.status_code == 200
    assert listing.json()["readme"] == {
        "path": "README.md",
        "content": "readme",
        "truncated": False,
    }
    assert file.status_code == 200
    assert "private-value" not in file.json()["content"]
    assert mcp_file.status_code == 200
    assert malformed.status_code == 400
    mcp_content = mcp_file.json()["content"]
    assert isinstance(mcp_content, str)
    assert env_name in mcp_content and "[REDACTED]" in mcp_content
    for secret in (env_value, header_value, query_value, password_value):
        assert secret not in mcp_content
    assert unknown.status_code == 404
    assert traversal.status_code == 400


@pytest.mark.asyncio
async def test_installed_file_review_returns_bounded_listing(
    tmp_path, monkeypatch
) -> None:
    from types import SimpleNamespace

    root = tmp_path / "installed"
    root.mkdir()
    (root / "plugin.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        plugin_routes,
        "get_installation",
        lambda installation_id: (
            SimpleNamespace(root=str(root))
            if installation_id == "a" * 32
            else (_ for _ in ()).throw(KeyError(installation_id))
        ),
    )
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await client.get(f"/api/plugins/{'a' * 32}/files")
        missing = await client.get(f"/api/plugins/{'b' * 32}/files")

    assert listing.status_code == 200
    assert listing.json()["files"] == [
        {"path": "plugin.json", "kind": "text", "size": 2}
    ]
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_inspection_api_redacts_mcp_values_but_keeps_environment_names(
    tmp_path,
) -> None:
    from app.plugin_platform.models import MCP_SCHEMA_ID, PLUGIN_SCHEMA_ID

    (tmp_path / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": PLUGIN_SCHEMA_ID,
                "name": "api-review-test",
                "version": "1.0.0",
                "description": "API review test",
            }
        ),
        encoding="utf-8",
    )
    env_name = "PRIVATE" + "_TOKEN"
    (tmp_path / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": MCP_SCHEMA_ID,
                "mcpServers": {
                    "local": {
                        "type": "stdio",
                        "command": "node",
                        "args": [],
                        "env": {env_name: "env-secret-value"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/plugins/inspect", params={"path": str(tmp_path)}
        )

    assert response.status_code == 200
    result = response.json()
    config = result["mcp_servers"][0]["config"]
    assert env_name in config["env"]
    assert config["env"][env_name] == "[REDACTED]"
    assert "env-secret-value" not in response.text
