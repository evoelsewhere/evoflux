"""``GET /api/plugins/{id}/files``: the bounded, redacting package reviewer."""

from __future__ import annotations

import json

import pytest

from plugin_helpers import PREVIEW, install, write_plugin

SECRET_SOURCE = """\
password = hunter2
token: abc123
"api_key": "k-123"
Authorization: Bearer xyz
export MY_SECRET_KEY=shh
plain = visible
"""


@pytest.fixture
def installed(client, src):
    root = write_plugin(
        src / "rv",
        "rv",
        skills=("sk",),
        files={
            "README.md": "# Hello\n",
            "docs/notes.txt": SECRET_SOURCE,
            ".env": "A_TOKEN=1\n",
            ".env.local": "B=2\n",
            ".envrc": "C=3\n",
            "key.pem": "-----BEGIN-----\n",
            "id_rsa": "x",
            "credentials.json": "{}",
            "nested/secrets.json": "{}",
            "blob.bin": b"\x00\x01\x02",
            "latin.txt": b"\xff\xfe",
            "config.json": json.dumps(
                {
                    "name": "x",
                    "apiToken": "t",
                    "env": {"A": "1"},
                    "headers": {"H": "v"},
                    "url": "https://u:p@example.com:8443/p?token=1&b=2#frag",
                    "list": [{"password": "p", "ok": 1}],
                }
            ),
            "broken.json": "{not json",
        },
    )
    return install(client, root)["installation"]


def files(client, installation_id: str, **params):
    return client.get(f"/api/plugins/{installation_id}/files", params=params)


def test_listing_hides_sensitive_names_and_classifies_binaries(client, installed) -> None:
    response = files(client, installed["id"])
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"files", "truncated", "readme"}
    listed = {item["path"]: item for item in body["files"]}
    # os.walk order: each directory's files sorted by name, then its subdirectories.
    assert [item["path"] for item in body["files"]] == [
        "README.md", "blob.bin", "broken.json", "config.json", "latin.txt",
        "plugin.json", "docs/notes.txt", "skills/sk/SKILL.md",
    ]  # fmt: skip
    assert set(listed) == {
        "README.md", "blob.bin", "broken.json", "config.json", "docs/notes.txt",
        "latin.txt", "plugin.json", "skills/sk/SKILL.md",
    }  # fmt: skip
    assert listed["blob.bin"] == {"path": "blob.bin", "kind": "binary", "size": 3}
    assert listed["latin.txt"]["kind"] == "binary"
    assert listed["plugin.json"]["kind"] == "text"
    assert body["truncated"] is False
    assert body["readme"] == {"path": "README.md", "content": "# Hello\n", "truncated": False}


def test_listing_without_a_readme(client, src) -> None:
    created = install(client, write_plugin(src / "nr", "nr"))["installation"]
    assert files(client, created["id"]).json()["readme"] is None


def test_reading_redacts_secret_shaped_text(client, installed) -> None:
    body = files(client, installed["id"], path="docs/notes.txt").json()
    assert body["path"] == "docs/notes.txt"
    assert body["truncated"] is False
    assert body["content"] == (
        "password = [REDACTED]\n"
        "token: [REDACTED]\n"
        '"api_key": "[REDACTED]"\n'
        "Authorization: [REDACTED]\n"
        "export MY_SECRET_KEY=[REDACTED]\n"
        "plain = visible\n"
    )


def test_reading_json_redacts_by_structure(client, installed) -> None:
    body = files(client, installed["id"], path="config.json").json()
    assert json.loads(body["content"]) == {
        "name": "x",
        "apiToken": "[REDACTED]",
        "env": {"A": "[REDACTED]"},
        "headers": {"H": "[REDACTED]"},
        "url": "https://example.com:8443/p?token=[REDACTED]",
        "list": [{"password": "[REDACTED]", "ok": 1}],
    }
    assert body["content"].startswith('{\n  "name": "x"')


def test_reading_broken_json_returns_the_redacted_text(client, installed) -> None:
    body = files(client, installed["id"], path="broken.json").json()
    assert body == {"path": "broken.json", "content": "{not json", "truncated": False}


def test_reading_a_malformed_mcp_config_is_refused(client, src) -> None:
    root = write_plugin(src / "bad", "bad", files={"mcp.json": "{nope", ".mcp.json": "{nope"})
    created = install(client, root, mode="link")["installation"]
    for name in ("mcp.json", ".mcp.json"):
        response = files(client, created["id"], path=name)
        assert response.status_code == 400
        assert response.json() == {"detail": "MCP configuration cannot be safely reviewed."}


@pytest.mark.parametrize(
    ("path", "status", "detail"),
    [
        ("", 400, "Invalid package file path."),
        ("../x", 400, "Invalid package file path."),
        ("a/../b", 400, "Invalid package file path."),
        ("docs\\notes.txt", 400, "Invalid package file path."),
        ("a/./b", 404, "Package file not found."),
        ("blob.bin", 400, "Binary files are not reviewable."),
        ("latin.txt", 400, "Binary files are not reviewable."),
        (".env", 404, "Package file not found."),
        (".envrc", 404, "Package file not found."),
        ("key.pem", 404, "Package file not found."),
        ("nested/secrets.json", 404, "Package file not found."),
        ("nope.txt", 404, "Package file not found."),
        ("docs", 404, "Package file not found."),
    ],
)
def test_reading_error_paths(client, installed, path, status, detail) -> None:
    response = files(client, installed["id"], path=path)
    assert response.status_code == status
    assert response.json() == {"detail": detail}


def test_large_files_are_truncated_and_huge_ones_hidden(client, src) -> None:
    root = write_plugin(
        src / "lg",
        "lg",
        files={
            "big.txt": "a" * (600 * 1024),
            "huge.txt": "a" * (2 * 1024 * 1024 + 1),
        },
    )
    created = install(client, root)["installation"]
    listing = files(client, created["id"]).json()
    assert listing["truncated"] is True
    assert "huge.txt" not in [item["path"] for item in listing["files"]]
    body = files(client, created["id"], path="big.txt").json()
    assert body["truncated"] is True
    assert len(body["content"].encode("utf-8")) == 512 * 1024
    assert files(client, created["id"], path="huge.txt").status_code == 404


def test_listing_is_capped_at_500_files(client, src) -> None:
    extra = {f"many/f{index:03d}.txt": "x" for index in range(520)}
    created = install(client, write_plugin(src / "mn", "mn", files=extra))["installation"]
    body = files(client, created["id"]).json()
    assert body["truncated"] is True
    assert len(body["files"]) == 500


def test_unknown_installation_and_preview(client) -> None:
    missing = files(client, "0" * 32)
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Plugin installation not found."}
    preview = client.get(f"/api/plugins/previews/{PREVIEW}/files")
    assert preview.status_code == 404
    assert preview.json() == {"detail": "Plugin preview not found."}
    assert client.get("/api/plugins/previews/not-hex/files").status_code == 404


def test_symlinked_entries_are_skipped(client, src, tmp_path) -> None:
    root = write_plugin(src / "sl", "sl", files={"real.txt": "x"})
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (root / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks need privileges on this host")
    created = install(client, root, mode="link")["installation"]
    listed = [item["path"] for item in files(client, created["id"]).json()["files"]]
    assert "link.txt" not in listed
    assert files(client, created["id"], path="link.txt").status_code == 404
