"""Inspect, install, link, enable, update and uninstall for ``/api/plugins``."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from plugin_helpers import (
    ID,
    install,
    tree,
    write_mcp_plugin,
    write_plugin,
)

INSTALLATION_KEYS = {
    "id", "name", "version", "description", "root", "source_type", "source_ref",
    "content_sha256", "enabled", "managed_by", "managed_project_id",
    "managed_resource_id", "managed_version_id", "origin", "installed_at",
    "updated_at",
}  # fmt: skip
INSPECTION_KEYS = {
    "root", "valid", "manifest", "diagnostics", "skills", "mcp_servers", "trust",
    "extension_namespaces", "content_sha256",
}  # fmt: skip
ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00$")


def registry(platform_dir: Path) -> dict:
    return json.loads((platform_dir / "registry.json").read_text(encoding="utf-8"))


def test_empty_list_has_no_plugins_and_no_servers(client) -> None:
    response = client.get("/api/plugins")
    assert response.status_code == 200
    assert response.json() == {"plugins": [], "mcp_servers": []}


def test_inspect_reports_a_valid_package_and_redacts_secrets(client, src, snapshot, scrub) -> None:
    root = write_plugin(
        src / "alpha",
        "alpha",
        skills=("sk",),
        mcp={
            "remote": {
                "type": "streamable-http",
                "url": "https://example.com/mcp?token=abc&x=1",
                "headers": {"Authorization": "Bearer secret"},
            },
            "local": {
                "type": "stdio",
                "command": "node",
                "args": ["server.js", "--token", "hunter2", "--api-key=k"],
                "env": {"API_TOKEN": "t0ken"},
            },
        },
    )
    response = client.get("/api/plugins/inspect", params={"path": str(root)})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == INSPECTION_KEYS
    assert body["valid"] is True
    servers = {item["name"]: item for item in body["mcp_servers"]}
    assert servers["remote"]["config"] == {
        "type": "streamable-http",
        "url": "https://example.com/mcp?token=%5BREDACTED%5D&x=%5BREDACTED%5D",
        "headers": {"Authorization": "[REDACTED]"},
    }
    assert servers["local"]["config"] == {
        "type": "stdio",
        "command": "node",
        "args": ["server.js", "--token", "[REDACTED]", "--api-key=[REDACTED]"],
        "env": {"API_TOKEN": "[REDACTED]"},
        "cwd": None,
    }
    snapshot.check("inspect_valid.json", scrub(body))


def test_inspect_trust_review_is_not_redacted(client, src) -> None:
    """Suspected bug F1: ``redact_inspection`` only rewrites ``mcp_servers``.

    The trust review is built from the unredacted config, so a URL query token
    and ``--token`` arguments come back in the clear.
    """
    root = write_plugin(
        src / "leaky",
        "leaky",
        mcp={
            "remote": {"type": "streamable-http", "url": "https://example.com/mcp?token=abc"},
            "local": {"type": "stdio", "command": "node", "args": ["--token", "hunter2"]},
        },
    )
    body = client.get("/api/plugins/inspect", params={"path": str(root)}).json()
    trust = body["trust"]
    assert trust["remote_hosts"] == [
        {
            "server": "remote",
            "transport": "streamable-http",
            "host": "example.com",
            "url": "https://example.com/mcp?token=abc",
        }
    ]
    assert trust["executable_commands"] == [
        {"server": "local", "executable": "node", "args": ["--token", "hunter2"]}
    ]


def test_inspect_missing_directory_is_200_with_a_diagnostic(client, src) -> None:
    response = client.get("/api/plugins/inspect", params={"path": str(src / "nope")})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["manifest"] is None
    assert [d["code"] for d in body["diagnostics"]] == ["plugin-root-invalid"]
    assert body["diagnostics"][0]["message"].startswith("Not a plugin directory: ")
    assert body["content_sha256"] is None


def test_inspect_requires_a_path(client) -> None:
    assert client.get("/api/plugins/inspect").status_code == 422
    response = client.get("/api/plugins/inspect", params={"path": ""})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "path"]


@pytest.mark.parametrize(
    ("manifest", "code"),
    [
        ({"$schema": "https://example.com/x", "name": "bad"}, "manifest-schema-invalid"),
        ({"name": "bad"}, "manifest-schema-invalid"),
    ],
)
def test_inspect_rejects_a_bad_manifest(client, src, manifest, code) -> None:
    root = src / "bad"
    root.mkdir()
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    body = client.get("/api/plugins/inspect", params={"path": str(root)}).json()
    assert body["valid"] is False
    assert code in [d["code"] for d in body["diagnostics"]]


def test_inspect_any_directory_on_the_machine(client, tmp_path, src) -> None:
    """Pinned: ``path`` is any server-side directory, not only plugin roots."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    body = client.get("/api/plugins/inspect", params={"path": str(outside)}).json()
    assert [d["code"] for d in body["diagnostics"]] == ["manifest-missing"]
    assert body["diagnostics"][0]["message"] == "plugin.json is required."


def test_install_copies_the_package_and_records_it(client, src, platform_dir, scrub) -> None:
    root = write_plugin(src / "alpha", "alpha", skills=("sk",))
    body = install(client, root)
    installation = body["installation"]
    assert set(installation) == INSTALLATION_KEYS
    assert set(body["inspection"]) == INSPECTION_KEYS
    assert re.fullmatch(r"[0-9a-f]{32}", installation["id"])
    assert installation["name"] == "alpha"
    assert installation["version"] == "1.0.0"
    assert installation["description"] == "The alpha plugin."
    assert installation["source_type"] == "installed"
    assert installation["enabled"] is False
    assert installation["managed_by"] is None
    assert ISO.match(installation["installed_at"])
    assert installation["installed_at"] == installation["updated_at"]
    assert installation["source_ref"] == str(root.resolve())
    assert installation["origin"] == {
        "kind": "import_directory",
        "marketplace_id": None,
        "marketplace_name": None,
        "source_ref": str(root.resolve()),
    }
    final = platform_dir / "installed" / installation["id"] / "1.0.0"
    assert Path(installation["root"]) == final
    assert tree(final) == tree(root)
    assert body["inspection"]["root"] == str(final)
    assert body["inspection"]["content_sha256"] == installation["content_sha256"]
    document = registry(platform_dir)
    assert document == {"version": 1, "installations": [installation]}


def test_registry_file_bytes(client, src, platform_dir) -> None:
    install(client, write_plugin(src / "alpha", "alpha"))
    raw = (platform_dir / "registry.json").read_bytes().replace(b"\r\n", b"\n")
    document = json.loads(raw)
    assert raw == (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()


def test_install_enabled_flag_and_listing_order(client, src) -> None:
    install(client, write_plugin(src / "zulu", "zulu"), enabled=False)
    install(client, write_plugin(src / "alpha", "alpha"), enabled=False)
    body = client.get("/api/plugins").json()
    assert [item["installation"]["name"] for item in body["plugins"]] == ["alpha", "zulu"]
    item = body["plugins"][0]
    assert set(item) == {"installation", "inspection", "credentials", "capabilities", "provider"}
    assert item["capabilities"] == {
        "can_enable": True,
        "can_edit": True,
        "can_pack": True,
        "can_update": True,
        "can_uninstall": True,
    }
    assert item["credentials"] == {"supported": False, "configured": True, "fields": [], "error": None}
    assert item["provider"] is None


def test_linked_plugins_cannot_be_updated_through_the_capability_flag(client, src) -> None:
    root = write_plugin(src / "dev", "dev")
    install(client, root, mode="link")
    item = client.get("/api/plugins").json()["plugins"][0]
    assert item["installation"]["source_type"] == "linked"
    assert item["capabilities"]["can_update"] is False
    assert item["capabilities"]["can_edit"] is True


def test_link_keeps_the_source_in_place(client, src, platform_dir) -> None:
    root = write_plugin(src / "dev", "dev", skills=("sk",))
    body = install(client, root, mode="link", enabled=False)
    installation = body["installation"]
    assert installation["source_type"] == "linked"
    assert installation["root"] == str(root.resolve())
    assert installation["source_ref"] == str(root.resolve())
    assert installation["origin"]["kind"] == "development_link"
    assert not (platform_dir / "installed").exists()


def test_install_expands_a_home_relative_path(client, tmp_path) -> None:
    home = tmp_path / "home"
    root = write_plugin(home / "plugins" / "tilde", "tilde")
    body = install(client, Path("~") / "plugins" / "tilde")
    assert body["installation"]["source_ref"] == str(root.resolve())


def test_install_twice_from_the_same_source_is_422(client, src, platform_dir) -> None:
    root = write_plugin(src / "alpha", "alpha")
    install(client, root)
    response = client.post("/api/plugins/install", json={"path": str(root)})
    assert response.status_code == 422
    assert response.json() == {"detail": "Plugin 'alpha' is already installed from this source."}
    assert len(registry(platform_dir)["installations"]) == 1
    assert len(list((platform_dir / "installed").iterdir())) == 1


def test_install_invalid_package_names_every_error(client, src, platform_dir) -> None:
    root = src / "bad"
    root.mkdir()
    response = client.post("/api/plugins/install", json={"path": str(root)})
    assert response.status_code == 422
    assert response.json() == {"detail": "plugin.json is required."}
    assert not (platform_dir / "registry.json").exists()


def test_install_missing_path_and_plain_file_are_422(client, src) -> None:
    missing = client.post("/api/plugins/install", json={"path": str(src / "nope")})
    assert missing.status_code == 422
    assert missing.json() == {
        "detail": "Source must be a plugin directory or .evoplugin/.zip file."
    }
    plain = src / "notes.txt"
    plain.write_text("x", encoding="utf-8")
    response = client.post("/api/plugins/install", json={"path": str(plain)})
    assert response.status_code == 422
    assert response.json() == missing.json()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"path": ""},
        {"path": "x", "mode": "copy"},
        {"path": "x", "enabled": "maybe"},
        {"path": "x", "extra": 1},
    ],
)
def test_install_request_validation(client, body) -> None:
    response = client.post("/api/plugins/install", json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_install_rejects_a_package_with_symlinks_but_link_may_use_one(client, src) -> None:
    root = write_plugin(src / "sym", "sym", files={"real.txt": "x"})
    try:
        (root / "alias.txt").symlink_to(root / "real.txt")
    except OSError:
        pytest.skip("symlinks need privileges on this host")
    response = client.post("/api/plugins/install", json={"path": str(root)})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Managed installs reject symlinks; use developer link for a contained symlink package."
    }
    linked = client.post("/api/plugins/install", json={"path": str(root), "mode": "link"})
    assert linked.status_code == 201


def test_get_plugin_and_unknown_id(client, src) -> None:
    created = install(client, write_plugin(src / "alpha", "alpha"))
    got = client.get(f"/api/plugins/{created['installation']['id']}")
    assert got.status_code == 200
    assert got.json()["installation"] == created["installation"]
    missing = client.get(f"/api/plugins/{ID}")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Plugin installation not found."}
    assert client.get("/api/plugins/not-an-id").status_code == 404


def test_enable_and_disable(client, src, platform_dir) -> None:
    created = install(client, write_plugin(src / "alpha", "alpha"))["installation"]
    on = client.patch(f"/api/plugins/{created['id']}/enabled", json={"enabled": True})
    assert on.status_code == 200
    assert on.json()["installation"]["enabled"] is True
    assert on.json()["installation"]["updated_at"] > created["updated_at"]
    assert on.json()["installation"]["installed_at"] == created["installed_at"]
    assert registry(platform_dir)["installations"][0]["enabled"] is True
    off = client.patch(f"/api/plugins/{created['id']}/enabled", json={"enabled": False})
    assert off.json()["installation"]["enabled"] is False


def test_enable_unknown_is_404_and_bad_bodies_are_422(client, src) -> None:
    response = client.patch(f"/api/plugins/{ID}/enabled", json={"enabled": True})
    assert response.status_code == 404
    assert response.json() == {"detail": "Plugin installation not found."}
    created = install(client, write_plugin(src / "alpha", "alpha"))["installation"]
    for body in ({}, {"enabled": True, "x": 1}, {"enabled": "perhaps"}):
        assert client.patch(f"/api/plugins/{created['id']}/enabled", json=body).status_code == 422


def test_uninstall_removes_the_install_but_keeps_data_by_default(client, src, platform_dir) -> None:
    created = install(client, write_plugin(src / "alpha", "alpha"))["installation"]
    data = platform_dir / "data" / created["id"]
    data.mkdir(parents=True)
    (data / "keep.txt").write_text("x", encoding="utf-8")
    response = client.delete(f"/api/plugins/{created['id']}")
    assert response.status_code == 200
    assert response.json()["installation"] == created
    assert response.json()["inspection"]["valid"] is True
    assert not (platform_dir / "installed" / created["id"]).exists()
    assert registry(platform_dir)["installations"] == []
    assert (data / "keep.txt").exists()
    assert client.get(f"/api/plugins/{created['id']}").status_code == 404


def test_uninstall_with_remove_data(client, src, platform_dir) -> None:
    created = install(client, write_plugin(src / "alpha", "alpha"))["installation"]
    data = platform_dir / "data" / created["id"]
    data.mkdir(parents=True)
    (data / "x.txt").write_text("x", encoding="utf-8")
    client.delete(f"/api/plugins/{created['id']}", params={"remove_data": "true"})
    assert not data.exists()


def test_uninstall_unknown_is_404(client) -> None:
    response = client.delete(f"/api/plugins/{ID}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Plugin installation not found."}


def test_uninstall_linked_keeps_the_source_folder(client, src) -> None:
    root = write_plugin(src / "dev", "dev")
    created = install(client, root, mode="link")["installation"]
    assert client.delete(f"/api/plugins/{created['id']}").status_code == 200
    assert (root / "plugin.json").exists()


def test_uninstall_refuses_an_install_path_outside_the_managed_root(client, src, platform_dir) -> None:
    """Pinned: the registry is trusted, but the managed-root check still guards deletion."""
    created = install(client, write_plugin(src / "alpha", "alpha"))["installation"]
    victim = write_plugin(src / "victim", "victim")
    document = registry(platform_dir)
    document["installations"][0]["root"] = str(victim)
    (platform_dir / "registry.json").write_text(json.dumps(document), encoding="utf-8")
    response = client.delete(f"/api/plugins/{created['id']}")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Refusing to delete an unowned install path: ")
    assert (victim / "plugin.json").exists()


def test_update_from_a_directory_replaces_the_package(client, src, platform_dir) -> None:
    created = install(client, write_plugin(src / "alpha", "alpha", version="1.0.0"))["installation"]
    newer = write_plugin(src / "alpha2", "alpha", version="2.0.0", skills=("added",))
    response = client.post(f"/api/plugins/{created['id']}/update", json={"path": str(newer)})
    assert response.status_code == 200
    updated = response.json()["installation"]
    assert updated["id"] == created["id"]
    assert updated["version"] == "2.0.0"
    assert updated["source_ref"] == str(newer.resolve())
    assert updated["installed_at"] == created["installed_at"]
    assert updated["updated_at"] > created["updated_at"]
    assert updated["origin"] == created["origin"]
    assert Path(updated["root"]) == platform_dir / "installed" / created["id"] / "2.0.0"
    assert not (platform_dir / "installed" / created["id"] / "1.0.0").exists()
    assert (Path(updated["root"]) / "skills" / "added" / "SKILL.md").exists()


def test_update_in_place_when_the_version_is_unchanged(client, src, platform_dir) -> None:
    created = install(client, write_plugin(src / "alpha", "alpha", version="1.0.0"))["installation"]
    same = write_plugin(src / "alpha2", "alpha", version="1.0.0", files={"extra.txt": "x"})
    response = client.post(f"/api/plugins/{created['id']}/update", json={"path": str(same)})
    assert response.status_code == 200
    assert response.json()["installation"]["root"] == created["root"]
    assert (Path(created["root"]) / "extra.txt").read_text(encoding="utf-8") == "x"
    assert [p.name for p in (platform_dir / "installed" / created["id"]).iterdir()] == ["1.0.0"]


def test_update_rejects_a_different_name(client, src) -> None:
    created = install(client, write_plugin(src / "alpha", "alpha"))["installation"]
    other = write_plugin(src / "beta", "beta")
    response = client.post(f"/api/plugins/{created['id']}/update", json={"path": str(other)})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Update package name 'beta' does not match installed plugin 'alpha'."
    }


def test_update_linked_and_unknown(client, src) -> None:
    linked = install(client, write_plugin(src / "dev", "dev"), mode="link")["installation"]
    response = client.post(f"/api/plugins/{linked['id']}/update", json={"path": str(src / "dev")})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Linked development plugins update directly from their source folder."
    }
    missing = client.post(f"/api/plugins/{ID}/update", json={"path": str(src / "dev")})
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Plugin installation not found."}


def test_install_leaves_no_staging_directories(client, src, staging_dir) -> None:
    install(client, write_plugin(src / "alpha", "alpha"))
    client.post("/api/plugins/install", json={"path": str(src / "nope")})
    assert [p for p in staging_dir.iterdir()] == []


def test_corrupt_registry_reads_as_empty_but_blocks_writes(client, src, platform_dir) -> None:
    """Pinned: reads fall back to an empty registry; every write re-reads strictly."""
    platform_dir.mkdir(parents=True)
    (platform_dir / "registry.json").write_text("not json", encoding="utf-8")
    assert client.get("/api/plugins").json() == {"plugins": [], "mcp_servers": []}
    response = client.post("/api/plugins/install", json={"path": str(write_plugin(src / "a", "a"))})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Could not read plugin registry ")
    assert (platform_dir / "registry.json").read_text(encoding="utf-8") == "not json"


def test_a_plugin_with_an_mcp_server_in_a_disabled_install_starts_nothing(client, src, platform_dir) -> None:
    root = write_mcp_plugin(src / "m", "m")
    created = install(client, root)["installation"]
    assert client.get("/api/plugins").json()["mcp_servers"] == []
    assert not (platform_dir / "data" / created["id"] / "started.json").exists()
