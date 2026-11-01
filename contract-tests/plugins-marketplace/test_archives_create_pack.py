"""Archive upload and update-upload, ``create`` and ``pack``."""

from __future__ import annotations

import json
import os
import re
import stat
import zipfile
from pathlib import Path

import pytest

from plugin_helpers import (
    PLUGIN_SCHEMA,
    ID,
    install,
    tree,
    write_plugin,
    zip_bytes,
    zip_dir,
)

MANIFEST = json.dumps({"$schema": PLUGIN_SCHEMA, "name": "up", "version": "1.0.0"})
ARCHIVE_ERROR = "Upload a .evoplugin or .zip archive."


def upload(client, name: str, data: bytes, **params):
    return client.post(
        "/api/plugins/upload",
        files={"archive": (name, data, "application/octet-stream")},
        params=params,
    )


def test_upload_installs_a_zip_disabled_by_default(client, src, platform_dir, staging_dir) -> None:
    root = write_plugin(src / "up", "up", skills=("sk",))
    archive = zip_dir(root, src / "up.zip").read_bytes()
    response = upload(client, "up.zip", archive)
    assert response.status_code == 201
    installation = response.json()["installation"]
    assert installation["enabled"] is False
    assert installation["source_type"] == "installed"
    assert installation["source_ref"] == "upload:up.zip"
    assert installation["origin"] == {
        "kind": "import_archive",
        "marketplace_id": None,
        "marketplace_name": None,
        "source_ref": "upload:up.zip",
    }
    assert tree(Path(installation["root"])) == tree(root)
    assert list(staging_dir.iterdir()) == []


def test_upload_enabled_query_flag_and_extension_case(client, src) -> None:
    archive = zip_dir(write_plugin(src / "up", "up"), src / "up.zip").read_bytes()
    response = upload(client, "UP.EVOPLUGIN", archive, enabled="true")
    assert response.status_code == 201
    assert response.json()["installation"]["enabled"] is True
    assert response.json()["installation"]["source_ref"] == "upload:UP.EVOPLUGIN"


def test_upload_rejects_other_extensions_before_reading(client, src, staging_dir) -> None:
    response = upload(client, "up.tar", b"x")
    assert response.status_code == 422
    assert response.json() == {"detail": ARCHIVE_ERROR}
    assert not staging_dir.exists() or list(staging_dir.iterdir()) == []


def test_upload_requires_the_archive_part(client) -> None:
    response = client.post("/api/plugins/upload")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "archive"]


def test_upload_not_a_zip(client) -> None:
    response = upload(client, "up.zip", b"definitely not a zip")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Invalid plugin archive: ")


def test_upload_requires_plugin_json_at_the_archive_root(client) -> None:
    response = upload(client, "up.zip", zip_bytes({"inner/plugin.json": MANIFEST}))
    assert response.status_code == 422
    assert response.json() == {"detail": "Archive root must contain plugin.json directly."}


@pytest.mark.parametrize(
    "name",
    ["../evil.txt", "/abs.txt", "a/../../b.txt", "c:/x.txt"],
)
def test_upload_rejects_unsafe_entry_names(client, src, name) -> None:
    response = upload(client, "up.zip", zip_bytes({"plugin.json": MANIFEST, name: "x"}))
    assert response.status_code == 422
    assert response.json() == {"detail": f"Unsafe archive path: {name!r}"}
    assert not (src.parent / "evil.txt").exists()


@pytest.mark.parametrize("name", ["a/./b.txt", "a//b.txt"])
def test_upload_normalizes_dot_and_empty_segments_instead_of_rejecting(client, name) -> None:
    """Pinned (suspected bug B1): ``PurePosixPath`` drops ``.`` and empty parts first."""
    response = upload(client, "up.zip", zip_bytes({"plugin.json": MANIFEST, name: "x"}))
    assert response.status_code == 201
    root = Path(response.json()["installation"]["root"])
    assert (root / "a" / "b.txt").read_text(encoding="utf-8") == "x"


@pytest.mark.skipif(
    os.name == "nt",
    reason="zipfile folds a backslash into / when it reads names on Windows",
)
def test_upload_rejects_backslash_names(client) -> None:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", MANIFEST)
        info = zipfile.ZipInfo("placeholder")
        info.filename = "a\\b.txt"  # ZipInfo() would fold the separator on Windows
        archive.writestr(info, "x")
    response = upload(client, "up.zip", buffer.getvalue())
    assert response.status_code == 422
    assert response.json() == {"detail": "Unsafe archive path: 'a\\\\b.txt'"}


def test_upload_rejects_case_insensitive_duplicates(client) -> None:
    data = zip_bytes({"plugin.json": MANIFEST, "A.txt": "1", "a.txt": "2"})
    response = upload(client, "up.zip", data)
    assert response.status_code == 422
    assert response.json() == {"detail": "Duplicate archive path: a.txt"}


def test_upload_rejects_symlink_entries(client) -> None:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", MANIFEST)
        link = zipfile.ZipInfo("link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "plugin.json")
    response = upload(client, "up.zip", buffer.getvalue())
    assert response.status_code == 422
    assert response.json() == {"detail": "Archive symlinks are not allowed: link"}


def test_upload_rejects_a_compression_bomb(client) -> None:
    data = zip_bytes({"plugin.json": MANIFEST, "zeros.bin": b"\0" * (4 * 1024 * 1024)})
    response = upload(client, "up.zip", data)
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Suspicious compression ratio for archive entry: zeros.bin"
    }


def test_upload_strips_unsafe_modes_and_keeps_the_exec_bit_signal(client, src) -> None:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", MANIFEST)
        for name, mode in (("run.sh", 0o4777), ("data.txt", 0o666)):
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, "x")
    response = upload(client, "up.zip", buffer.getvalue())
    assert response.status_code == 201
    root = Path(response.json()["installation"]["root"])
    if root.drive:
        pytest.skip("POSIX file modes are not observable on Windows")
    assert stat.S_IMODE((root / "run.sh").stat().st_mode) == 0o755
    assert stat.S_IMODE((root / "data.txt").stat().st_mode) == 0o644


def test_upload_installing_the_same_archive_twice_is_422(client, src) -> None:
    data = zip_dir(write_plugin(src / "up", "up"), src / "up.zip").read_bytes()
    assert upload(client, "up.zip", data).status_code == 201
    second = upload(client, "up.zip", data)
    assert second.status_code == 422
    assert second.json() == {"detail": "Plugin 'up' is already installed from this source."}


def test_install_accepts_an_archive_path_too(client, src) -> None:
    archive = zip_dir(write_plugin(src / "up", "up"), src / "from-disk.evoplugin")
    body = install(client, archive)
    assert body["installation"]["source_ref"] == str(archive.resolve())


def test_update_upload_replaces_the_package(client, src, platform_dir) -> None:
    created = install(client, write_plugin(src / "up", "up", version="1.0.0"))["installation"]
    newer = zip_dir(write_plugin(src / "up2", "up", version="3.0.0"), src / "up2.zip")
    response = client.post(
        f"/api/plugins/{created['id']}/update-upload",
        files={"archive": ("up2.zip", newer.read_bytes(), "application/zip")},
    )
    assert response.status_code == 200
    updated = response.json()["installation"]
    assert updated["version"] == "3.0.0"
    assert updated["source_ref"] == "upload:up2.zip"
    assert Path(updated["root"]) == platform_dir / "installed" / created["id"] / "3.0.0"


def test_update_upload_error_paths(client, src) -> None:
    created = install(client, write_plugin(src / "up", "up"))["installation"]
    bad = client.post(
        f"/api/plugins/{created['id']}/update-upload",
        files={"archive": ("x.txt", b"x", "text/plain")},
    )
    assert bad.status_code == 422
    assert bad.json() == {"detail": ARCHIVE_ERROR}
    unknown = client.post(
        f"/api/plugins/{ID}/update-upload",
        files={"archive": ("x.zip", zip_bytes({"plugin.json": MANIFEST}), "application/zip")},
    )
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Plugin installation not found."}


def test_create_scaffolds_a_plugin(client, src, snapshot, scrub) -> None:
    target = src / "fresh"
    response = client.post(
        "/api/plugins/create",
        json={
            "destination": str(target),
            "name": "fresh",
            "description": "Fresh.",
            "version": "0.1.0",
            "author": "Ada",
            "license": "MIT",
            "skill_name": "do-it",
        },
    )
    assert response.status_code == 201
    assert response.json() == {"path": str(target)}
    assert (target / "plugin.json").read_bytes().replace(b"\r\n", b"\n") == (
        json.dumps(
            {
                "$schema": PLUGIN_SCHEMA,
                "name": "fresh",
                "description": "Fresh.",
                "version": "0.1.0",
                "author": {"name": "Ada"},
                "license": "MIT",
            },
            indent=2,
        )
        + "\n"
    ).encode()
    snapshot.check(
        "create_tree.json",
        {k: (v.decode().replace("\r\n", "\n") if v is not None else None) for k, v in tree(target).items()},
    )


def test_create_without_a_skill_writes_only_the_manifest(client, src) -> None:
    target = src / "bare"
    assert client.post("/api/plugins/create", json={"destination": str(target), "name": "bare"}).status_code == 201
    assert sorted(tree(target)) == ["plugin.json"]
    assert json.loads((target / "plugin.json").read_text(encoding="utf-8")) == {
        "$schema": PLUGIN_SCHEMA,
        "name": "bare",
    }


def test_create_destination_may_be_any_path_and_parents_are_created(client, src) -> None:
    """Pinned: ``destination`` is an arbitrary server path; missing parents are created."""
    response = client.post(
        "/api/plugins/create", json={"destination": str(src / "no" / "parent"), "name": "x"}
    )
    assert response.status_code == 201
    assert (src / "no" / "parent" / "plugin.json").is_file()


def test_create_existing_destination_is_422(client, src) -> None:
    (src / "taken").mkdir()
    response = client.post("/api/plugins/create", json={"destination": str(src / "taken"), "name": "x"})
    assert response.status_code == 422
    assert response.json()["detail"].startswith("Destination already exists: ")
    assert (src / "taken").is_dir()


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"name": "Bad Name"}, "plugin.json"),
        ({"name": "ok", "skill_name": "Bad_Skill"}, "name"),
    ],
)
def test_create_invalid_input_rolls_back(client, src, body, fragment) -> None:
    target = src / "rolled"
    response = client.post("/api/plugins/create", json={"destination": str(target), **body})
    assert response.status_code == 422
    assert fragment in response.json()["detail"]
    assert not target.exists()


def test_create_inside_the_bundled_tree_is_409_and_writes_nothing(client) -> None:
    from plugin_helpers import HERE

    bundled = HERE.parents[1] / "app" / "agent" / "builtin_plugins" / "contract-probe"
    response = client.post("/api/plugins/create", json={"destination": str(bundled), "name": "probe"})
    assert response.status_code == 409
    assert response.json() == {
        "detail": "Bundled Agent Plugins are read-only and update with EvoFlux."
    }
    assert not bundled.exists()


def test_create_validation(client) -> None:
    for body in ({}, {"destination": "x"}, {"destination": "", "name": "x"}, {"destination": "x", "name": "x", "extra": 1}):
        assert client.post("/api/plugins/create", json=body).status_code == 422


def test_relative_create_destination_resolves_against_the_backend_cwd(client, tmp_path) -> None:
    response = client.post("/api/plugins/create", json={"destination": "rel-plugin", "name": "rel"})
    assert response.status_code == 201
    assert (tmp_path / "cwd" / "rel-plugin" / "plugin.json").is_file()
    assert Path(response.json()["path"]) == (tmp_path / "cwd" / "rel-plugin")


def test_pack_default_output_is_next_to_the_plugin(client, src) -> None:
    root = write_plugin(src / "pk", "pk", version="2.0.0", skills=("sk",))
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"x")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x", encoding="utf-8")
    (root / ".DS_Store").write_bytes(b"x")
    (root / "mod.pyc").write_bytes(b"x")
    response = client.post("/api/plugins/pack", json={"path": str(root)})
    assert response.status_code == 200
    target = src / "pk-2.0.0.evoplugin"
    assert response.json() == {"path": str(target)}
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["plugin.json", "skills/sk/SKILL.md"]
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert (info.external_attr >> 16) == (stat.S_IFREG | 0o644)


def test_pack_is_byte_reproducible(client, src) -> None:
    root = write_plugin(src / "pk", "pk", skills=("sk",))
    first = client.post("/api/plugins/pack", json={"path": str(root), "output": str(src / "one.evoplugin")})
    second = client.post("/api/plugins/pack", json={"path": str(root), "output": str(src / "two.evoplugin")})
    assert first.status_code == second.status_code == 200
    assert (src / "one.evoplugin").read_bytes() == (src / "two.evoplugin").read_bytes()


def test_pack_unversioned_name(client, src) -> None:
    root = write_plugin(src / "pk", "pk", version=None)
    response = client.post("/api/plugins/pack", json={"path": str(root)})
    assert Path(response.json()["path"]).name == "pk-unversioned.evoplugin"


def test_pack_output_may_be_any_path_and_creates_parents(client, src) -> None:
    """Pinned: ``output`` is an arbitrary server path; missing parents are created."""
    root = write_plugin(src / "pk", "pk")
    target = src / "deep" / "er" / "out.zip"
    response = client.post("/api/plugins/pack", json={"path": str(root), "output": str(target)})
    assert response.status_code == 200
    assert zipfile.is_zipfile(target)


def test_pack_refuses_to_overwrite_or_write_inside_the_plugin(client, src) -> None:
    root = write_plugin(src / "pk", "pk")
    taken = src / "taken.evoplugin"
    taken.write_bytes(b"keep")
    existing = client.post("/api/plugins/pack", json={"path": str(root), "output": str(taken)})
    assert existing.status_code == 422
    assert existing.json()["detail"].startswith("Output already exists: ")
    assert taken.read_bytes() == b"keep"
    inside = client.post("/api/plugins/pack", json={"path": str(root), "output": str(root / "out.evoplugin")})
    assert inside.status_code == 422
    assert inside.json() == {"detail": "Output archive must be outside the plugin root."}


def test_pack_invalid_plugin_and_validation(client, src) -> None:
    (src / "empty").mkdir()
    response = client.post("/api/plugins/pack", json={"path": str(src / "empty")})
    assert response.status_code == 422
    assert response.json() == {"detail": "plugin.json is required."}
    for body in ({}, {"path": ""}, {"path": "x", "extra": 1}):
        assert client.post("/api/plugins/pack", json=body).status_code == 422


def test_pack_inside_the_bundled_tree_is_409(client) -> None:
    from plugin_helpers import HERE

    bundled = HERE.parents[1] / "app" / "agent" / "builtin_plugins" / "probe"
    response = client.post("/api/plugins/pack", json={"path": str(bundled)})
    assert response.status_code == 409
    out = client.post(
        "/api/plugins/pack",
        json={"path": str(bundled.parent.parent), "output": str(bundled / "o.evoplugin")},
    )
    assert out.status_code in {409, 422}


def test_pack_then_install_round_trips(client, src) -> None:
    root = write_plugin(src / "pk", "pk", skills=("sk",))
    packed = Path(client.post("/api/plugins/pack", json={"path": str(root)}).json()["path"])
    body = install(client, packed)
    assert body["installation"]["content_sha256"] == client.get(
        "/api/plugins/inspect", params={"path": str(root)}
    ).json()["content_sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", body["installation"]["content_sha256"])
