from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes import plugins as plugin_routes
from app.core.config import settings
from app.plugin_platform.runtime import plugin_mcp_runtime


@pytest.mark.asyncio
async def test_plugin_api_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    refresh_mock = AsyncMock()
    invalidate_mock = Mock()
    monkeypatch.setattr(plugin_mcp_runtime, "refresh", refresh_mock)
    monkeypatch.setattr(
        plugin_routes.team_manager,
        "invalidate_skill_cache",
        invalidate_mock,
    )
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)

    plugin_root = tmp_path / "authoring" / "api-plugin"
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/plugins/create",
            json={
                "destination": str(plugin_root),
                "name": "api-plugin",
                "description": "API lifecycle",
                "version": "0.1.0",
                "author": "EvoFlux test",
                "license": "MIT",
                "skill_name": "api-skill",
                "mcp_name": "api-plugin",
            },
        )
        assert created.status_code == 201

        inspected = await client.get(
            "/api/plugins/inspect",
            params={"path": str(plugin_root)},
        )
        assert inspected.status_code == 200
        assert inspected.json()["manifest"]["$schema"].endswith("/plugin.schema.json")
        assert inspected.json()["manifest"]["version"] == "0.1.0"
        assert inspected.json()["manifest"]["author"]["name"] == "EvoFlux test"
        assert inspected.json()["mcp_servers"][0]["name"] == "api-plugin"

        tree = await client.get(
            "/api/plugins/workspace/tree",
            params={"root": str(plugin_root)},
        )
        assert tree.status_code == 200
        assert {entry["path"] for entry in tree.json()} >= {
            "plugin.json",
            "server.py",
            "skills/api-skill/SKILL.md",
        }

        created_file = await client.post(
            "/api/plugins/workspace/entry",
            json={
                "root": str(plugin_root),
                "path": "README.md",
                "kind": "file",
            },
        )
        assert created_file.status_code == 201
        saved_file = await client.put(
            "/api/plugins/workspace/file",
            json={
                "root": str(plugin_root),
                "path": "README.md",
                "content": "# Edited in Plugin Center\n",
            },
        )
        assert saved_file.status_code == 200
        read_file = await client.get(
            "/api/plugins/workspace/file",
            params={"root": str(plugin_root), "path": "README.md"},
        )
        assert read_file.json()["content"] == "# Edited in Plugin Center\n"
        traversal = await client.get(
            "/api/plugins/workspace/file",
            params={"root": str(plugin_root), "path": "../secret.txt"},
        )
        assert traversal.status_code == 422
        protected_manifest = await client.request(
            "DELETE",
            "/api/plugins/workspace/entry",
            json={"root": str(plugin_root), "path": "plugin.json"},
        )
        assert protected_manifest.status_code == 422
        removed_file = await client.request(
            "DELETE",
            "/api/plugins/workspace/entry",
            json={"root": str(plugin_root), "path": "README.md"},
        )
        assert removed_file.status_code == 200

        manifest = json.loads((plugin_root / "plugin.json").read_text(encoding="utf-8"))
        manifest["extensions"] = {
            "evoflux.credentials": {
                "fields": [
                    {
                        "key": "endpoint",
                        "label": "Endpoint",
                        "type": "url",
                        "env": "API_ENDPOINT",
                        "required": True,
                    },
                    {
                        "key": "token",
                        "label": "Token",
                        "type": "secret",
                        "env": "API_TOKEN",
                        "required": True,
                    },
                ]
            }
        }
        saved_manifest = await client.put(
            "/api/plugins/workspace/file",
            json={
                "root": str(plugin_root),
                "path": "plugin.json",
                "content": json.dumps(manifest, indent=2) + "\n",
            },
        )
        assert saved_manifest.status_code == 200

        imported = await client.post(
            "/api/plugins/install",
            json={"path": str(plugin_root), "mode": "link", "enabled": True},
        )
        assert imported.status_code == 201
        installation_id = imported.json()["installation"]["id"]

        credential_state = await client.get(
            f"/api/plugins/{installation_id}/credentials"
        )
        assert credential_state.status_code == 200
        assert credential_state.json()["configured"] is False
        configured = await client.put(
            f"/api/plugins/{installation_id}/credentials",
            json={
                "values": {
                    "endpoint": "https://service.example.test",
                    "token": "test-secret",
                }
            },
        )
        assert configured.status_code == 200
        assert configured.json()["configured"] is True
        token_field = next(
            field for field in configured.json()["fields"] if field["key"] == "token"
        )
        assert token_field["value"] == "********"
        credential_file = (
            tmp_path
            / "data"
            / "agent-plugins"
            / "data"
            / installation_id
            / "credentials.json"
        )
        assert credential_file.stat().st_mode & 0o777 == 0o600
        cleared = await client.delete(f"/api/plugins/{installation_id}/credentials")
        assert cleared.status_code == 200
        assert cleared.json()["configured"] is False

        listed = await client.get("/api/plugins")
        assert listed.status_code == 200
        assert listed.json()["plugins"][0]["installation"]["name"] == "api-plugin"

        disabled = await client.patch(
            f"/api/plugins/{installation_id}/enabled",
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        assert disabled.json()["installation"]["enabled"] is False

        removed = await client.delete(f"/api/plugins/{installation_id}")
        assert removed.status_code == 200
        assert (await client.get("/api/plugins")).json()["plugins"] == []

    assert refresh_mock.await_count == 9
    assert invalidate_mock.call_count == 9
