from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes import plugins as plugin_routes
from app.core.config import settings
from app.plugin_platform.installer import pack_plugin
from app.plugin_platform.runtime import plugin_mcp_runtime


@pytest.mark.asyncio
async def test_plugin_install_defaults_to_disabled_pending_trust_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(plugin_mcp_runtime, "refresh", AsyncMock())
    monkeypatch.setattr(plugin_routes.team_manager, "invalidate_skill_cache", Mock())
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)
    plugin_root = tmp_path / "pending-review"
    plugin_root.mkdir()
    (plugin_root / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                "name": "pending-review",
            }
        ),
        encoding="utf-8",
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/plugins/install",
            json={"path": str(plugin_root), "mode": "link"},
        )

    assert response.status_code == 201
    assert response.json()["installation"]["enabled"] is False
    assert response.json()["inspection"]["trust"] == {
        "executable_commands": [],
        "remote_hosts": [],
        "environment_fields": [],
        "capabilities": [],
    }


@pytest.mark.asyncio
async def test_plugin_api_lists_builtin_capabilities_and_rejects_mutations(
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

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        listed = await client.get("/api/plugins")
        assert listed.status_code == 200
        plugins = listed.json()["plugins"]
        assert len(plugins) == 1
        builtin = plugins[0]
        installation = builtin["installation"]
        assert installation["id"] == "7d76b6df28f0617022e8223d2dda5315"
        assert installation["name"] == "evoflux.documents"
        assert installation["source_type"] == "builtin"
        assert builtin["inspection"]["valid"] is True
        assert builtin["capabilities"] == {
            "can_enable": False,
            "can_edit": False,
            "can_pack": False,
            "can_update": False,
            "can_uninstall": False,
        }

        root = installation["root"]
        manifest_before = Path(root, "plugin.json").read_bytes()
        tree = await client.get("/api/plugins/workspace/tree", params={"root": root})
        assert tree.status_code == 200
        assert "plugin.json" in {entry["path"] for entry in tree.json()}
        manifest = await client.get(
            "/api/plugins/workspace/file",
            params={"root": root, "path": "plugin.json"},
        )
        assert manifest.status_code == 200

        reinstall = await client.post(
            "/api/plugins/install",
            json={"path": root, "mode": "link", "enabled": True},
        )
        assert reinstall.status_code == 422
        update = await client.post(
            f"/api/plugins/{installation['id']}/update",
            json={"path": root},
        )
        assert update.status_code == 422
        disable = await client.patch(
            f"/api/plugins/{installation['id']}/enabled",
            json={"enabled": False},
        )
        assert disable.status_code == 422
        uninstall = await client.delete(f"/api/plugins/{installation['id']}")
        assert uninstall.status_code == 422
        packed = await client.post("/api/plugins/pack", json={"path": root})
        assert packed.status_code == 409

        write = await client.put(
            "/api/plugins/workspace/file",
            json={"root": root, "path": "plugin.json", "content": "{}\n"},
        )
        assert write.status_code == 409
        create = await client.post(
            "/api/plugins/workspace/entry",
            json={"root": root, "path": "forbidden.txt", "kind": "file"},
        )
        assert create.status_code == 409
        remove = await client.request(
            "DELETE",
            "/api/plugins/workspace/entry",
            json={"root": root, "path": "plugin.json"},
        )
        assert remove.status_code == 409

    assert Path(root, "plugin.json").read_bytes() == manifest_before
    assert not Path(root, "forbidden.txt").exists()
    refresh_mock.assert_not_awaited()
    invalidate_mock.assert_not_called()


@pytest.mark.asyncio
async def test_plugin_api_rejects_builtin_create_and_pack_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.plugin_platform import builtins as builtin_module

    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    bundled_root = tmp_path / "release" / "builtin_plugins"
    bundled_root.mkdir(parents=True)
    monkeypatch.setattr(builtin_module, "builtin_plugins_root", lambda: bundled_root)
    source = tmp_path / "pack-source"
    source.mkdir()
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                "name": "pack-source",
            }
        ),
        encoding="utf-8",
    )
    create_target = bundled_root / "generated"
    pack_target = bundled_root / "generated.evoplugin"
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/plugins/create",
            json={"destination": str(create_target), "name": "generated"},
        )
        packed = await client.post(
            "/api/plugins/pack",
            json={"path": str(source), "output": str(pack_target)},
        )

    assert created.status_code == 409
    assert packed.status_code == 409
    assert not create_target.exists()
    assert not pack_target.exists()


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
            "org.evoelsewhere.evoflux.credentials": {
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
        invalid_url = await client.put(
            f"/api/plugins/{installation_id}/credentials",
            json={"values": {"endpoint": "not-a-url"}},
        )
        assert invalid_url.status_code == 422
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
        listed_by_name = {
            item["installation"]["name"]: item for item in listed.json()["plugins"]
        }
        assert set(listed_by_name) == {"api-plugin", "evoflux.documents"}
        assert listed_by_name["api-plugin"]["capabilities"] == {
            "can_enable": True,
            "can_edit": True,
            "can_pack": True,
            "can_update": False,
            "can_uninstall": True,
        }
        assert listed_by_name["evoflux.documents"]["capabilities"] == {
            "can_enable": False,
            "can_edit": False,
            "can_pack": False,
            "can_update": False,
            "can_uninstall": False,
        }

        disabled = await client.patch(
            f"/api/plugins/{installation_id}/enabled",
            json={"enabled": False},
        )
        assert disabled.status_code == 200
        assert disabled.json()["installation"]["enabled"] is False

        removed = await client.delete(f"/api/plugins/{installation_id}")
        assert removed.status_code == 200
        remaining = (await client.get("/api/plugins")).json()["plugins"]
        assert [item["installation"]["name"] for item in remaining] == [
            "evoflux.documents"
        ]

    assert refresh_mock.await_count == 9
    assert invalidate_mock.call_count == 9


@pytest.mark.asyncio
async def test_plugin_api_updates_managed_package_in_place(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    refresh_mock = AsyncMock()
    monkeypatch.setattr(plugin_mcp_runtime, "refresh", refresh_mock)
    monkeypatch.setattr(
        plugin_routes.team_manager,
        "invalidate_skill_cache",
        Mock(),
    )
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)
    source = tmp_path / "authoring" / "updatable"

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/api/plugins/create",
            json={
                "destination": str(source),
                "name": "updatable",
                "version": "1.0.0",
            },
        )
        assert created.status_code == 201
        installed = await client.post(
            "/api/plugins/install",
            json={"path": str(source), "mode": "install", "enabled": True},
        )
        assert installed.status_code == 201
        original = installed.json()["installation"]

        manifest_path = source / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "2.0.0"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (source / "new.txt").write_text("updated\n", encoding="utf-8")

        response = await client.post(
            f"/api/plugins/{original['id']}/update",
            json={"path": str(source)},
        )
        assert response.status_code == 200
        updated = response.json()["installation"]
        assert updated["id"] == original["id"]
        assert updated["version"] == "2.0.0"
        assert updated["root"] != original["root"]
        assert not Path(original["root"]).exists()
        assert (Path(updated["root"]) / "new.txt").read_text() == "updated\n"

        manifest["version"] = "3.0.0"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        archive = pack_plugin(source, tmp_path / "updatable-v3.evoplugin")
        with archive.open("rb") as package:
            uploaded = await client.post(
                f"/api/plugins/{original['id']}/update-upload",
                files={
                    "archive": (
                        archive.name,
                        package,
                        "application/zip",
                    )
                },
            )
        assert uploaded.status_code == 200
        uploaded_installation = uploaded.json()["installation"]
        assert uploaded_installation["id"] == original["id"]
        assert uploaded_installation["version"] == "3.0.0"
        assert uploaded_installation["source_ref"] == f"upload:{archive.name}"

        removed = await client.delete(f"/api/plugins/{original['id']}")
        assert removed.status_code == 200

    assert refresh_mock.await_count == 4
    assert all(call.kwargs == {"force": True} for call in refresh_mock.await_args_list)


@pytest.mark.asyncio
async def test_plugin_upload_rejects_malformed_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    app = FastAPI()
    app.include_router(plugin_routes.router, prefix="/api/plugins")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/plugins/upload",
            files={"archive": ("broken.evoplugin", b"not a zip", "application/zip")},
        )

    assert response.status_code == 422
    assert "Invalid plugin archive" in response.json()["detail"]
