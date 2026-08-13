from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agent.skills.discovery import builtin_skills_dir
from app.core.config import settings
from app.core.skill_settings import skill_settings_id, write_skill_runtime_settings
from app.plugin_platform.builtins import (
    builtin_plugins_root,
    list_builtin_installations,
)
from app.plugin_platform.installer import (
    PluginInstallError,
    create_plugin,
    install_plugin,
    link_plugin,
    pack_plugin,
    uninstall_plugin,
    update_plugin,
)
from app.plugin_platform.credentials import credential_definition
from app.plugin_platform.extensions import CREDENTIALS_EXTENSION, MCP_EXTENSION
from app.plugin_platform.models import (
    MCP_SCHEMA_ID,
    PLUGIN_SCHEMA_ID,
    PluginInstallation,
)
from app.plugin_platform.registry import (
    add_installation,
    list_effective_installations,
    list_installations,
    plugin_data_root,
    registry_path,
    set_enabled,
)
from app.plugin_platform.runtime import (
    PluginMCPRuntime,
    _expand,
    _linked_tree_signature,
    build_plugin_mcp_config,
)
from app.plugin_platform.skills import (
    discover_plugin_skill_records,
    discover_skill_records_with_plugins,
)
from app.plugin_platform.validator import inspect_plugin
from app.plugin_platform.workspace import list_workspace, write_workspace_file


@pytest.fixture
def isolated_platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    return tmp_path


def _plugin(
    root: Path,
    *,
    name: str = "example-plugin",
    skill: str | None = "portable-skill",
) -> Path:
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": PLUGIN_SCHEMA_ID,
                "name": name,
                "version": "1.2.3",
                "description": "Test plugin",
            }
        ),
        encoding="utf-8",
    )
    if skill:
        skill_dir = root / "skills" / skill
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill}\ndescription: Portable test skill\n---\n\n# Instructions\n\nRun the test workflow.\n",
            encoding="utf-8",
        )
    return root


def test_manifest_failure_boundaries_continue_for_special_fields(
    isolated_platform: Path,
) -> None:
    root = _plugin(isolated_platform / "plugin")
    manifest_path = root / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["unknown"] = {"ignored": True}
    manifest["extensions"] = "invalid-but-ignorable"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    inspection = inspect_plugin(root)

    assert inspection.valid is True
    assert inspection.manifest is not None
    assert inspection.manifest.extensions == {}
    assert {item.code for item in inspection.diagnostics} == {
        "manifest-invalid-extensions",
        "manifest-unknown-field",
    }


def test_manifest_other_schema_errors_are_fatal(isolated_platform: Path) -> None:
    root = _plugin(isolated_platform / "plugin")
    manifest_path = root / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["name"] = "Invalid Name"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    inspection = inspect_plugin(root)

    assert inspection.valid is False
    assert inspection.manifest is None
    assert any(
        item.code == "manifest-schema-invalid" for item in inspection.diagnostics
    )
    assert inspection.skills == []


def test_skill_discovery_is_immediate_and_component_errors_are_isolated(
    isolated_platform: Path,
) -> None:
    root = _plugin(isolated_platform / "plugin")
    nested = root / "skills" / "group" / "nested"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text(
        "---\nname: nested\ndescription: Must not be discovered\n---\n\nNo.\n",
        encoding="utf-8",
    )
    invalid = root / "skills" / "broken"
    invalid.mkdir()
    (invalid / "SKILL.md").write_text("No frontmatter", encoding="utf-8")

    inspection = inspect_plugin(root)

    assert inspection.valid is True
    assert {skill.name for skill in inspection.skills} == {
        "portable-skill",
        "broken",
    }
    assert (
        next(skill for skill in inspection.skills if skill.name == "broken").valid
        is False
    )


@pytest.mark.parametrize("namespace", [MCP_EXTENSION, "evoflux.mcp"])
def test_mcp_entries_fail_independently_and_runtime_expands_only_plugin_tokens(
    isolated_platform: Path,
    namespace: str,
) -> None:
    root = _plugin(isolated_platform / "plugin", skill=None)
    manifest_path = root / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["extensions"] = {
        namespace: {"servers": {"local": {"capabilities": ["webbridge-safe"]}}}
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (root / "run.py").write_text("print('server')\n", encoding="utf-8")
    (root / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": MCP_SCHEMA_ID,
                "mcpServers": {
                    "local": {
                        "type": "stdio",
                        "command": "./run.py",
                        "args": ["${PLUGIN_ROOT}/config", "${OTHER}"],
                        "env": {"CACHE": "${PLUGIN_DATA}/cache", "LITERAL": "$HOME"},
                        "cwd": "${PLUGIN_DATA}/work",
                    },
                    "remote": {
                        "type": "streamable-http",
                        "url": "https://example.com/mcp",
                        "headers": {"X-Literal": "${TOKEN}"},
                    },
                    "broken": {"type": "unknown"},
                    "legacy": {"type": "sse", "url": "https://example.com/sse"},
                },
            }
        ),
        encoding="utf-8",
    )

    installation = link_plugin(root)
    inspection = inspect_plugin(root, data_root=plugin_data_root(installation.id))
    config, descriptors = build_plugin_mcp_config()

    assert inspection.valid is True
    assert {server.name: server.valid for server in inspection.mcp_servers} == {
        "local": True,
        "remote": True,
        "broken": False,
        "legacy": True,
    }
    assert {item.server_name for item in descriptors} == {"local", "remote"}
    local_name = next(
        item.runtime_name for item in descriptors if item.server_name == "local"
    )
    remote_name = next(
        item.runtime_name for item in descriptors if item.server_name == "remote"
    )
    local = config.servers[local_name]
    remote = config.servers[remote_name]
    data = plugin_data_root(installation.id).resolve()
    assert local.transport == "stdio"
    assert local.command == str(root.resolve() / "run.py")
    assert local.args == [f"{root.resolve()}/config", "${OTHER}"]
    assert local.env["CACHE"] == f"{data}/cache"
    assert local.env["LITERAL"] == "$HOME"
    assert local.env["PLUGIN_ROOT"] == str(root.resolve())
    assert local.cwd == str(data / "work")
    assert local.capabilities == ["webbridge-safe"]
    assert remote.transport == "http"
    assert remote.headers == {"X-Literal": "${TOKEN}"}
    assert remote.resolve_header_refs is False
    assert remote.follow_redirects is False


def test_plugin_placeholder_expansion_is_single_pass() -> None:
    root = Path("/tmp/${PLUGIN_DATA}/plugin")
    data = Path("/tmp/plugin-data")

    assert _expand("${PLUGIN_ROOT}", root=root, data_root=data) == str(root)
    assert _expand("${PLUGIN_DATA}/${PLUGIN_ROOT}", root=root, data_root=data) == (
        f"{data}/{root}"
    )


def test_trust_review_discloses_access_without_environment_values(
    isolated_platform: Path,
) -> None:
    root = _plugin(isolated_platform / "trust-review-plugin")
    manifest_path = root / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["extensions"] = {
        CREDENTIALS_EXTENSION: {
            "fields": [
                {
                    "key": "token",
                    "label": "Token",
                    "type": "secret",
                    "env": "SERVICE_TOKEN",
                }
            ]
        },
        MCP_EXTENSION: {"servers": {"local": {"capabilities": ["webbridge-safe"]}}},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (root / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": MCP_SCHEMA_ID,
                "mcpServers": {
                    "local": {
                        "type": "stdio",
                        "command": "python",
                        "args": ["./server.py"],
                        "env": {"SERVICE_MODE": "private-environment-value"},
                    },
                    "remote": {
                        "type": "streamable-http",
                        "url": "https://api.example.test:8443/mcp",
                        "headers": {"Authorization": "private-header-value"},
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    inspection = inspect_plugin(root)
    review = inspection.trust

    assert [command.model_dump() for command in review.executable_commands] == [
        {"server": "local", "executable": "python", "args": ["./server.py"]}
    ]
    assert [remote.model_dump() for remote in review.remote_hosts] == [
        {
            "server": "remote",
            "transport": "streamable-http",
            "host": "api.example.test:8443",
            "url": "https://api.example.test:8443/mcp",
        }
    ]
    assert review.environment_fields == ["SERVICE_MODE", "SERVICE_TOKEN"]
    assert {(item.name, item.source) for item in review.capabilities} == {
        ("agent-skill", "portable-skill"),
        ("mcp-stdio", "local"),
        ("mcp-streamable-http", "remote"),
        ("webbridge-safe", "local"),
    }
    serialized = review.model_dump_json()
    assert "private-environment-value" not in serialized
    assert "private-header-value" not in serialized


def test_registry_rejects_unsafe_installation_ids() -> None:
    with pytest.raises(ValidationError):
        PluginInstallation(
            id="../escape",
            name="unsafe",
            root="/tmp/plugin",
            source_type="linked",
            source_ref="/tmp/plugin",
            content_sha256="0" * 64,
            installed_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )


def test_builtin_discovery_is_stable_and_effective_list_keeps_registry_managed_only(
    isolated_platform: Path,
) -> None:
    list_builtin_installations.cache_clear()
    first = list_builtin_installations()
    list_builtin_installations.cache_clear()
    second = list_builtin_installations()

    assert [item.id for item in first] == ["7d76b6df28f0617022e8223d2dda5315"]
    assert [item.model_dump(mode="json") for item in second] == [
        item.model_dump(mode="json") for item in first
    ]
    builtin = first[0]
    assert builtin.name == "evoflux.documents"
    assert builtin.source_type == "builtin"
    assert builtin.source_ref == "evoflux://builtin/documents"
    assert builtin.enabled is True
    assert Path(builtin.root).is_dir()
    assert len(builtin.content_sha256) == 64

    # Bundled records are virtual package metadata. They must not leak into the
    # user-owned registry document or make an empty registry appear non-empty.
    assert list_installations() == []
    assert list_effective_installations() == [builtin]

    managed_root = _plugin(isolated_platform / "managed-plugin")
    managed = link_plugin(managed_root)

    assert list_installations() == [managed]
    assert {item.id for item in list_effective_installations()} == {
        builtin.id,
        managed.id,
    }
    assert {item.id for item in list_effective_installations(enabled_only=True)} == {
        builtin.id,
        managed.id,
    }


def test_builtin_plugin_lifecycle_is_read_only(isolated_platform: Path) -> None:
    list_builtin_installations.cache_clear()
    builtin = list_builtin_installations()[0]
    replacement = _plugin(
        isolated_platform / "replacement",
        name=builtin.name,
        skill=None,
    )

    with pytest.raises(PluginInstallError, match="cannot be linked or reinstalled"):
        link_plugin(builtin.root)
    with pytest.raises(PluginInstallError, match="cannot be reinstalled"):
        install_plugin(builtin.root)
    with pytest.raises(PluginInstallError, match="cannot be packed separately"):
        pack_plugin(builtin.root, isolated_platform / "builtin.evoplugin")
    with pytest.raises(PluginInstallError):
        update_plugin(builtin.id, replacement)
    with pytest.raises(ValueError, match="always enabled"):
        set_enabled(builtin.id, False)
    with pytest.raises(ValueError, match="cannot be uninstalled"):
        uninstall_plugin(builtin.id)

    assert list_installations() == []
    assert list_effective_installations() == [builtin]


def test_documents_builtin_declares_preview_only_native_runtime() -> None:
    manifest = json.loads(
        (builtin_plugins_root() / "documents" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )
    native = manifest["extensions"]["org.evoelsewhere.evoflux.builtin"]

    assert manifest["version"] == "1.2.0"
    assert "read-only previews" in manifest["description"]
    assert native["preview_provider"].endswith(":preview_provider")
    assert "artifact_provider" not in native
    assert "api_router_provider" not in native


def test_builtin_tree_rejects_create_and_pack_targets(
    isolated_platform: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.plugin_platform import builtins as builtin_module

    bundled_root = isolated_platform / "release" / "builtin_plugins"
    bundled_root.mkdir(parents=True)
    monkeypatch.setattr(builtin_module, "builtin_plugins_root", lambda: bundled_root)
    create_target = bundled_root / "generated"
    pack_target = bundled_root / "generated.evoplugin"
    source = _plugin(isolated_platform / "pack-source")

    with pytest.raises(PluginInstallError, match="cannot be created"):
        create_plugin(create_target, name="generated")
    with pytest.raises(PluginInstallError, match="cannot be written"):
        pack_plugin(source, pack_target)

    assert not create_target.exists()
    assert not pack_target.exists()


def test_registry_rejects_and_filters_persisted_builtin_records(
    isolated_platform: Path,
) -> None:
    list_builtin_installations.cache_clear()
    builtin = list_builtin_installations()[0]

    with pytest.raises(ValueError, match="cannot be persisted"):
        add_installation(builtin)

    managed = link_plugin(_plugin(isolated_platform / "managed"))
    path = registry_path()
    document = json.loads(path.read_text(encoding="utf-8"))
    document["installations"].append(builtin.model_dump(mode="json"))
    path.write_text(json.dumps(document), encoding="utf-8")

    assert list_installations() == [managed]
    assert {item.id for item in list_effective_installations()} == {
        builtin.id,
        managed.id,
    }

    updated = set_enabled(managed.id, False)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert updated.enabled is False
    assert [item["id"] for item in persisted["installations"]] == [managed.id]
    assert persisted["installations"][0]["source_type"] == "linked"


def test_managed_plugin_skill_precedes_bundled_plugin_skill(
    isolated_platform: Path,
) -> None:
    plugin = _plugin(
        isolated_platform / "documents-override",
        name="documents-override",
        skill="docx",
    )
    managed = link_plugin(plugin)

    selected = discover_plugin_skill_records()["docx"]

    assert selected.source == f"plugin:{managed.id}"
    assert selected.alternates
    assert selected.alternates[0].source.startswith("plugin:")
    assert selected.alternates[0].source != selected.source


def test_plugin_skill_applies_persisted_runtime_settings(
    isolated_platform: Path,
) -> None:
    plugin = _plugin(isolated_platform / "settings-plugin")
    managed = link_plugin(plugin)
    inherited = discover_plugin_skill_records()["portable-skill"]

    assert inherited.source == f"plugin:{managed.id}"
    assert inherited.settings_editable is True
    assert inherited.settings_overridden is False

    write_skill_runtime_settings(
        inherited.settings_id,
        name=inherited.name,
        source=inherited.source,
        modes=["coding"],
        allow_implicit_invocation=False,
        user_invocable=False,
    )
    overridden = discover_plugin_skill_records()["portable-skill"]

    assert overridden.modes == ("coding",)
    assert overridden.allow_implicit_invocation is False
    assert overridden.user_invocable is False
    assert overridden.settings_overridden is True


def test_documents_plugin_preserves_legacy_builtin_skill_settings_identity(
    isolated_platform: Path,
) -> None:
    list_builtin_installations.cache_clear()
    record = discover_plugin_skill_records()["docx"]
    legacy_id = skill_settings_id(
        source="builtin",
        root=builtin_skills_dir(),
        stem="docx",
    )

    assert record.source.startswith("plugin:")
    assert record.settings_id == legacy_id

    write_skill_runtime_settings(
        legacy_id,
        name=record.name,
        source="builtin",
        modes=["coding"],
        allow_implicit_invocation=False,
        user_invocable=False,
    )
    migrated = discover_plugin_skill_records()["docx"]

    assert migrated.settings_overridden is True
    assert migrated.modes == ("coding",)


@pytest.mark.parametrize(
    "namespace",
    [CREDENTIALS_EXTENSION, "evoflux.credentials"],
)
def test_credential_schema_validates_defaults_and_urls(
    isolated_platform: Path,
    namespace: str,
) -> None:
    root = _plugin(isolated_platform / "credential-plugin", skill=None)
    manifest_path = root / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["extensions"] = {
        namespace: {
            "fields": [
                {
                    "key": "endpoint",
                    "label": "Endpoint",
                    "type": "url",
                    "env": "API_ENDPOINT",
                    "default": "not-a-url",
                }
            ]
        }
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValidationError, match="absolute HTTP\\(S\\) URL"):
        credential_definition(inspect_plugin(root))


def test_canonical_extensions_take_precedence_over_legacy_aliases(
    isolated_platform: Path,
) -> None:
    root = _plugin(isolated_platform / "canonical-extension-plugin", skill=None)
    manifest_path = root / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["extensions"] = {
        "evoflux.credentials": {
            "fields": [
                {
                    "key": "legacy",
                    "label": "Legacy",
                    "env": "LEGACY_TOKEN",
                }
            ]
        },
        CREDENTIALS_EXTENSION: {
            "fields": [
                {
                    "key": "canonical",
                    "label": "Canonical",
                    "env": "CANONICAL_TOKEN",
                }
            ]
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    definition = credential_definition(inspect_plugin(root))

    assert definition is not None
    assert [field.key for field in definition.fields] == ["canonical"]


def test_workspace_save_preserves_executable_mode_and_enforces_entry_limit(
    isolated_platform: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _plugin(isolated_platform / "workspace-plugin", skill=None)
    executable = root / "server.py"
    executable.write_text("print('old')\n", encoding="utf-8")
    executable.chmod(0o755)

    write_workspace_file(root, "server.py", "print('new')\n")

    assert executable.read_text(encoding="utf-8") == "print('new')\n"
    assert executable.stat().st_mode & 0o777 == 0o755

    (root / "extra.txt").write_text("extra\n", encoding="utf-8")
    monkeypatch.setattr("app.plugin_platform.workspace.MAX_EDITOR_ENTRIES", 2)
    with pytest.raises(ValueError, match="2-entry editor limit"):
        list_workspace(root)


def test_linked_signature_and_digest_track_directory_symlink_target(
    isolated_platform: Path,
) -> None:
    root = _plugin(isolated_platform / "linked-symlink", skill=None)
    first = root / "first"
    second = root / "second"
    first.mkdir()
    second.mkdir()
    link = root / "backend"
    link.symlink_to(first, target_is_directory=True)
    initial_signature = _linked_tree_signature(root)
    initial_digest = inspect_plugin(root).content_sha256

    link.unlink()
    link.symlink_to(second, target_is_directory=True)

    assert _linked_tree_signature(root) != initial_signature
    assert inspect_plugin(root).content_sha256 != initial_digest


@pytest.mark.asyncio
async def test_linked_runtime_preserves_last_good_server_during_invalid_edit(
    isolated_platform: Path,
) -> None:
    root = _plugin(isolated_platform / "linked-runtime", skill=None)
    mcp_path = root / "mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "$schema": MCP_SCHEMA_ID,
                "mcpServers": {
                    "service": {
                        "type": "stdio",
                        "command": "python",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    installation = link_plugin(root)
    runtime = PluginMCPRuntime()
    runtime._manager.apply_config = AsyncMock()  # type: ignore[method-assign]

    await runtime.refresh()
    first = runtime._manager.apply_config.await_args_list[-1].args[0]
    assert len(first.servers) == 1

    mcp_path.write_text('{"mcpServers": ', encoding="utf-8")
    await runtime.refresh(force=True)
    preserved = runtime._manager.apply_config.await_args_list[-1].args[0]
    assert set(preserved.servers) == set(first.servers)
    assert runtime._descriptors[0].installation_id == installation.id

    mcp_path.unlink()
    await runtime.refresh(force=True)
    removed = runtime._manager.apply_config.await_args_list[-1].args[0]
    assert removed.servers == {}


def test_install_pack_and_uninstall_managed_package(isolated_platform: Path) -> None:
    source = _plugin(isolated_platform / "source")
    cache = source / "backend" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "server.cpython-312.pyc").write_bytes(b"generated")
    (source / ".DS_Store").write_bytes(b"generated")
    executable = source / "bin" / "server"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    archive = pack_plugin(source, isolated_platform / "package.evoplugin")

    installation = install_plugin(archive)

    assert installation.source_type == "installed"
    installed_root = Path(installation.root)
    assert installed_root.is_dir()
    assert (installed_root / "bin" / "server").stat().st_mode & 0o111
    assert not (installed_root / "backend" / "__pycache__").exists()
    assert not (installed_root / ".DS_Store").exists()
    assert [item.id for item in list_installations()] == [installation.id]

    removed = uninstall_plugin(installation.id)
    assert removed.id == installation.id
    assert not installed_root.exists()
    assert list_installations() == []


def test_update_managed_package_preserves_identity_data_and_enabled_state(
    isolated_platform: Path,
) -> None:
    source = _plugin(isolated_platform / "source")
    first_archive = pack_plugin(source, isolated_platform / "first.evoplugin")
    installation = install_plugin(first_archive, enabled=False)
    original_root = Path(installation.root)
    data_file = plugin_data_root(installation.id) / "state.json"
    data_file.parent.mkdir(parents=True)
    data_file.write_text('{"keep": true}\n', encoding="utf-8")

    manifest_path = source / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "2.0.0"
    manifest["description"] = "Updated plugin"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (source / "updated.txt").write_text("new package\n", encoding="utf-8")
    second_archive = pack_plugin(source, isolated_platform / "second.evoplugin")

    updated = update_plugin(installation.id, second_archive)

    assert updated.id == installation.id
    assert updated.installed_at == installation.installed_at
    assert updated.updated_at != installation.updated_at
    assert updated.version == "2.0.0"
    assert updated.description == "Updated plugin"
    assert updated.enabled is False
    assert Path(updated.root) != original_root
    assert (Path(updated.root) / "updated.txt").read_text() == "new package\n"
    assert not original_root.exists()
    assert data_file.read_text(encoding="utf-8") == '{"keep": true}\n'
    assert list_installations() == [updated]


def test_update_managed_package_replaces_same_version_atomically(
    isolated_platform: Path,
) -> None:
    source = _plugin(isolated_platform / "source")
    installation = install_plugin(source)
    installed_root = Path(installation.root)
    (source / "implementation.py").write_text("VALUE = 2\n", encoding="utf-8")

    updated = update_plugin(installation.id, source)

    assert updated.id == installation.id
    assert updated.version == installation.version
    assert Path(updated.root) == installed_root
    assert (installed_root / "implementation.py").read_text(encoding="utf-8") == (
        "VALUE = 2\n"
    )
    assert not list(installed_root.parent.glob(".update-backup-*"))
    assert list_installations() == [updated]


def test_archive_traversal_is_rejected(isolated_platform: Path) -> None:
    archive = isolated_platform / "unsafe.evoplugin"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "plugin.json", json.dumps({"$schema": PLUGIN_SCHEMA_ID, "name": "unsafe"})
        )
        bundle.writestr("../escape", "no")

    with pytest.raises(PluginInstallError, match="Unsafe archive path"):
        install_plugin(archive)

    assert not (isolated_platform / "escape").exists()
    assert list_installations() == []


@pytest.mark.parametrize("unsafe_name", ["../escape", "C:/escape"])
def test_archive_rejects_cross_platform_unsafe_paths(
    isolated_platform: Path,
    unsafe_name: str,
) -> None:
    archive = isolated_platform / f"unsafe-{len(unsafe_name)}.evoplugin"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(
            "plugin.json", json.dumps({"$schema": PLUGIN_SCHEMA_ID, "name": "unsafe"})
        )
        bundle.writestr(unsafe_name, "no")

    with pytest.raises(PluginInstallError, match="Unsafe archive path"):
        install_plugin(archive)


def test_invalid_zip_is_reported_as_plugin_install_error(
    isolated_platform: Path,
) -> None:
    archive = isolated_platform / "broken.evoplugin"
    archive.write_bytes(b"not a zip archive")

    with pytest.raises(PluginInstallError, match="Invalid plugin archive"):
        install_plugin(archive)


def test_plugin_skills_precede_builtins_but_not_project_skills(
    isolated_platform: Path,
) -> None:
    plugin = _plugin(
        isolated_platform / "plugin",
        name="skill-precedence",
        skill="algorithmic-art",
    )
    link_plugin(plugin)

    plugin_over_builtin = discover_skill_records_with_plugins([builtin_skills_dir()])
    assert plugin_over_builtin["algorithmic-art"].source.startswith("plugin:")
    assert any(
        item.source == "builtin"
        for item in plugin_over_builtin["algorithmic-art"].alternates
    )

    project_root = isolated_platform / "workspace" / ".agents" / "skills"
    project_skill = project_root / "algorithmic-art"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text(
        "---\nname: algorithmic-art\ndescription: Project override\n---\n\nProject workflow.\n",
        encoding="utf-8",
    )
    project_over_plugin = discover_skill_records_with_plugins(
        [project_root, builtin_skills_dir()]
    )
    assert project_over_plugin["algorithmic-art"].source == "project-agents"
    assert (
        project_over_plugin["algorithmic-art"]
        .alternates[0]
        .source.startswith("plugin:")
    )
