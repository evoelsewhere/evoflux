"""The Plugin Center development workspace: ``/api/plugins/workspace/*``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugin_helpers import HERE, install, tree, write_plugin

BUNDLED = HERE.parents[1] / "app" / "agent" / "builtin_plugins" / "probe"
ENTRY_KEYS = {"path", "name", "kind", "size"}


@pytest.fixture
def plugin(src) -> Path:
    return write_plugin(
        src / "ws",
        "ws",
        skills=("sk",),
        files={"notes/readme.txt": "hello\n", "Zeta.txt": "z"},
    )


def tree_of(client, root: Path):
    response = client.get("/api/plugins/workspace/tree", params={"root": str(root)})
    assert response.status_code == 200, response.text
    return response.json()


def put(client, root: Path, path: str, content: str):
    return client.put(
        "/api/plugins/workspace/file", json={"root": str(root), "path": path, "content": content}
    )


def entry(client, method: str, root: Path, path: str, **extra):
    return client.request(
        method, "/api/plugins/workspace/entry", json={"root": str(root), "path": path, **extra}
    )


def test_tree_lists_files_and_directories_sorted_case_insensitively(client, plugin) -> None:
    (plugin / ".git").mkdir()
    (plugin / ".git" / "HEAD").write_text("x", encoding="utf-8")
    (plugin / "__pycache__").mkdir()
    body = tree_of(client, plugin)
    assert [(e["path"], e["kind"]) for e in body] == [
        ("notes", "directory"),
        ("notes/readme.txt", "file"),
        ("plugin.json", "file"),
        ("skills", "directory"),
        ("skills/sk", "directory"),
        ("skills/sk/SKILL.md", "file"),
        ("Zeta.txt", "file"),
    ]
    assert all(set(e) == ENTRY_KEYS for e in body)
    sizes = {e["path"]: e["size"] for e in body}
    assert sizes["Zeta.txt"] == 1
    assert sizes["notes"] == 0
    assert {e["path"]: e["name"] for e in body}["skills/sk/SKILL.md"] == "SKILL.md"


def test_tree_requires_a_plugin_json_root(client, tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    response = client.get("/api/plugins/workspace/tree", params={"root": str(empty)})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Plugin workspace root must contain a regular plugin.json file."
    }
    handle = tmp_path / "file.txt"
    handle.write_text("x", encoding="utf-8")
    response = client.get("/api/plugins/workspace/tree", params={"root": str(handle)})
    assert response.status_code == 422
    assert response.json() == {"detail": "Plugin workspace root must be a directory."}
    assert client.get("/api/plugins/workspace/tree", params={"root": str(tmp_path / "no")}).status_code == 422
    assert client.get("/api/plugins/workspace/tree", params={"root": ""}).status_code == 422
    assert client.get("/api/plugins/workspace/tree").status_code == 422


def test_tree_over_the_entry_limit_is_422(client, src) -> None:
    root = write_plugin(src / "big", "big")
    bulk = root / "bulk"
    bulk.mkdir()
    for index in range(2000):
        (bulk / f"f{index}.txt").write_bytes(b"")
    response = client.get("/api/plugins/workspace/tree", params={"root": str(root)})
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Plugin workspace exceeds the 2000-entry editor limit."
    }


def test_read_file(client, plugin) -> None:
    response = client.get(
        "/api/plugins/workspace/file", params={"root": str(plugin), "path": "notes/readme.txt"}
    )
    assert response.status_code == 200
    assert response.json() == {"root": str(plugin), "path": "notes/readme.txt", "content": "hello\n"}


def test_read_file_errors(client, plugin) -> None:
    def read(path: str):
        return client.get("/api/plugins/workspace/file", params={"root": str(plugin), "path": path})

    missing = read("nope.txt")
    assert missing.status_code == 422
    assert missing.json() == {"detail": "nope.txt"}
    directory = read("notes")
    assert directory.status_code == 422
    assert directory.json() == {"detail": "notes"}
    (plugin / "bin.dat").write_bytes(b"\xff\xfe\x00")
    binary = read("bin.dat")
    assert binary.status_code == 422
    assert binary.json() == {"detail": "Only UTF-8 text files can be edited in Plugin Center."}
    (plugin / "huge.txt").write_bytes(b"a" * (1024 * 1024 + 1))
    huge = read("huge.txt")
    assert huge.status_code == 422
    assert huge.json() == {"detail": "File exceeds the 1048576-byte editor limit."}
    assert client.get("/api/plugins/workspace/file", params={"root": str(plugin)}).status_code == 422


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        ("../outside.txt", "Workspace path must be a normalized relative path."),
        ("a/../b.txt", "Workspace path must be a normalized relative path."),
        ("/abs.txt", "Workspace path must be a normalized relative path."),
        ("a\\b.txt", "Workspace paths must use forward slashes."),
        (".", "Workspace path is required."),
    ],
)
def test_path_validation_applies_to_every_operation(client, plugin, path, detail) -> None:
    root = str(plugin)
    responses = [
        client.get("/api/plugins/workspace/file", params={"root": root, "path": path}),
        put(client, plugin, path, "x"),
        entry(client, "POST", plugin, path, kind="file"),
        entry(client, "DELETE", plugin, path),
    ]
    for response in responses:
        assert response.status_code == 422
        assert response.json() == {"detail": detail}
    assert not (plugin.parent / "outside.txt").exists()


def test_dot_and_empty_segments_are_normalized_not_rejected(client, plugin) -> None:
    """Pinned: ``PurePosixPath`` removes ``.`` and empty parts before the check."""
    assert put(client, plugin, "./notes//new.txt", "x").status_code == 200
    assert (plugin / "notes" / "new.txt").read_text(encoding="utf-8") == "x"


def test_write_file_is_exact_and_returns_the_inspection(client, plugin, scrub) -> None:
    content = "line1\r\nline2\né"
    response = put(client, plugin, "notes/readme.txt", content)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"ok", "inspection"}
    assert body["ok"] is True
    assert body["inspection"]["valid"] is True
    assert body["inspection"]["root"] == str(plugin.resolve())
    assert (plugin / "notes" / "readme.txt").read_bytes() == content.encode("utf-8")
    assert [p.name for p in (plugin / "notes").iterdir()] == ["readme.txt"]


def test_write_file_errors(client, plugin) -> None:
    parent = put(client, plugin, "missing-dir/x.txt", "x")
    assert parent.status_code == 422
    assert parent.json() == {"detail": "Parent directory does not exist."}
    directory = put(client, plugin, "notes", "x")
    assert directory.status_code == 422
    assert directory.json() == {"detail": "Workspace path is not a regular file."}
    huge = put(client, plugin, "x.txt", "a" * (1024 * 1024 + 1))
    assert huge.status_code == 422
    assert huge.json() == {"detail": "File exceeds the 1048576-byte editor limit."}
    exact = put(client, plugin, "exact.txt", "a" * (1024 * 1024))
    assert exact.status_code == 200
    assert not (plugin / "x.txt").exists()
    for body in (
        {},
        {"root": str(plugin), "path": "x"},
        {"root": str(plugin), "path": "x", "content": "", "extra": 1},
        {"root": "", "path": "x", "content": ""},
    ):
        assert client.put("/api/plugins/workspace/file", json=body).status_code == 422


def test_write_over_a_manifest_reports_the_new_diagnostics(client, plugin) -> None:
    response = put(client, plugin, "plugin.json", "{}")
    assert response.status_code == 200
    inspection = response.json()["inspection"]
    assert inspection["valid"] is False
    assert [d["code"] for d in inspection["diagnostics"]] == ["manifest-schema-invalid"]
    follow_up = client.get("/api/plugins/workspace/tree", params={"root": str(plugin)})
    assert follow_up.status_code == 200


def test_create_entries(client, plugin) -> None:
    created_file = entry(client, "POST", plugin, "notes/new.txt", kind="file")
    created_dir = entry(client, "POST", plugin, "notes/sub", kind="directory")
    assert created_file.status_code == created_dir.status_code == 201
    assert created_file.json()["ok"] is True
    assert (plugin / "notes" / "new.txt").read_bytes() == b""
    assert (plugin / "notes" / "sub").is_dir()


def test_create_entry_errors(client, plugin) -> None:
    exists = entry(client, "POST", plugin, "notes", kind="directory")
    assert exists.status_code == 422
    assert exists.json() == {"detail": "Workspace entry already exists."}
    parent = entry(client, "POST", plugin, "nope/x.txt", kind="file")
    assert parent.status_code == 422
    assert parent.json() == {"detail": "Parent directory does not exist."}
    for body in ({"kind": "link"}, {}, {"kind": "file", "extra": 1}):
        response = client.post(
            "/api/plugins/workspace/entry", json={"root": str(plugin), "path": "q", **body}
        )
        assert response.status_code == 422


def test_delete_entries(client, plugin) -> None:
    (plugin / "empty").mkdir()
    assert entry(client, "DELETE", plugin, "notes/readme.txt").status_code == 200
    assert entry(client, "DELETE", plugin, "empty").status_code == 200
    assert not (plugin / "notes" / "readme.txt").exists()
    assert not (plugin / "empty").exists()


def test_delete_entry_errors(client, plugin) -> None:
    full = entry(client, "DELETE", plugin, "skills")
    assert full.status_code == 422
    assert full.json() == {"detail": "Only empty directories can be deleted."}
    manifest = entry(client, "DELETE", plugin, "plugin.json")
    assert manifest.status_code == 422
    assert manifest.json() == {"detail": "plugin.json cannot be deleted from a plugin workspace."}
    missing = entry(client, "DELETE", plugin, "nope.txt")
    assert missing.status_code == 422
    assert missing.json() == {"detail": "nope.txt"}
    assert (plugin / "skills" / "sk" / "SKILL.md").exists()
    assert (plugin / "plugin.json").exists()


def test_a_nested_plugin_json_may_be_deleted(client, plugin) -> None:
    (plugin / "notes" / "plugin.json").write_text("{}", encoding="utf-8")
    assert entry(client, "DELETE", plugin, "notes/plugin.json").status_code == 200


def test_symlinks_are_refused(client, plugin, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (plugin / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks need privileges on this host")
    read = client.get("/api/plugins/workspace/file", params={"root": str(plugin), "path": "link.txt"})
    assert read.status_code == 422
    assert read.json()["detail"] in {
        "Symbolic links cannot be edited in Plugin Center.",
        "Workspace path escapes the plugin root.",
    }
    assert put(client, plugin, "link.txt", "pwn").status_code == 422
    assert outside.read_text(encoding="utf-8") == "secret"
    assert "link.txt" not in [e["path"] for e in tree_of(client, plugin)]


def test_the_root_is_any_directory_with_a_manifest(client, plugin, tmp_path) -> None:
    """Pinned (S2): ``root`` is not restricted to installed or linked plugins.

    Any folder on the machine that holds a regular ``plugin.json`` can be listed,
    read, written, extended and pruned through this API.
    """
    elsewhere = write_plugin(tmp_path / "unrelated" / "deep", "elsewhere")
    assert put(client, elsewhere, "pwned.txt", "x").status_code == 200
    assert (elsewhere / "pwned.txt").read_text(encoding="utf-8") == "x"
    assert entry(client, "DELETE", elsewhere, "pwned.txt").status_code == 200


def test_writes_inside_the_bundled_tree_are_409_before_any_check(client, tmp_path) -> None:
    for response in (
        put(client, BUNDLED, "x.txt", "x"),
        entry(client, "POST", BUNDLED, "x.txt", kind="file"),
        entry(client, "DELETE", BUNDLED, "x.txt"),
    ):
        assert response.status_code == 409
        assert response.json() == {
            "detail": "Bundled Agent Plugins are read-only and update with EvoFlux."
        }
    reading = client.get("/api/plugins/workspace/tree", params={"root": str(BUNDLED)})
    assert reading.status_code == 422


def test_editing_an_installed_plugin_leaves_its_recorded_digest_stale(
    client, src, platform_dir
) -> None:
    """Suspected bug B2: the workspace edits an installed package in place.

    ``registry.json`` keeps the install-time ``content_sha256`` while the
    package on disk (and its inspection) changes.
    """
    created = install(client, write_plugin(src / "inst", "inst"))["installation"]
    root = Path(created["root"])
    assert put(client, root, "added.txt", "x").status_code == 200
    got = client.get(f"/api/plugins/{created['id']}").json()
    assert got["installation"]["content_sha256"] == created["content_sha256"]
    assert got["inspection"]["content_sha256"] != created["content_sha256"]
    assert json.loads((platform_dir / "registry.json").read_text(encoding="utf-8"))[
        "installations"
    ][0]["content_sha256"] == created["content_sha256"]


def test_failed_operations_change_nothing(client, plugin) -> None:
    before = tree(plugin)
    put(client, plugin, "../x", "x")
    entry(client, "POST", plugin, "notes", kind="file")
    entry(client, "DELETE", plugin, "skills")
    put(client, plugin, "missing/x", "x")
    assert tree(plugin) == before
