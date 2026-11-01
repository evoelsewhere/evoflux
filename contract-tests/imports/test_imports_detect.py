"""``/api/import`` contract: auth, detect for every importer, preview."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from import_sources import (
    CHATGPT_CONVERSATIONS,
    CLAUDE_WEB_CONVERSATIONS,
    CLAUDE_WEB_PROJECTS,
    SECRET,
    UNAUTHORIZED_BODY,
    build_claude_code_dir,
    build_codex_dir,
    build_cursor_dir,
    build_generic_dir,
    detect,
    detect_ok,
    write,
    write_json,
    write_zip,
)

ROUTES = [
    ("GET", "/api/import/scan", None),
    ("GET", "/api/import/auto-sync", None),
    ("PUT", "/api/import/auto-sync", {"enabled": True}),
    ("POST", "/api/import/detect", {"path": "."}),
    ("GET", "/api/import/preview/abc", None),
    ("PATCH", "/api/import/preview/abc/items/0", {"action": "skip"}),
    ("PATCH", "/api/import/preview/abc/items", {"indexes": [0], "action": "skip"}),
    ("POST", "/api/import/execute/abc", None),
    ("DELETE", "/api/import/abc", None),
    ("GET", "/api/import/history", None),
    ("GET", "/api/import/history/abc", None),
    ("POST", "/api/import/history/abc/undo", None),
]


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_every_route_requires_auth(backend, token) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for method, path, body in ROUTES:
        response = httpx.request(
            method,
            f"{backend.base_url}{path}",
            json=body,
            headers=headers,
            timeout=30.0,
        )
        assert response.status_code == 401, (method, path)
        assert response.json() == UNAUTHORIZED_BODY, (method, path)


# ── detect: validation and errors ──────────────────────────────────────────


def test_detect_missing_path_field_is_422(client, snapshot) -> None:
    response = client.post("/api/import/detect", json={"source": "generic"})
    assert response.status_code == 422
    snapshot.check("detect_missing_path.json", response.json())


def test_detect_non_object_body_is_422(client, snapshot) -> None:
    response = client.post("/api/import/detect", json=["x"])
    assert response.status_code == 422
    snapshot.check("detect_list_body.json", response.json())


def test_detect_path_not_found_is_400(client, tmp_path, scrub) -> None:
    response = detect(client, tmp_path / "missing" / "export.json")
    assert response.status_code == 400
    assert scrub(response.json()) == {
        "detail": "Path not found: <tmp>/missing/export.json"
    }


def test_detect_unrecognised_file_is_422(client, tmp_path, scrub) -> None:
    target = write(tmp_path / "src" / "data.txt", "hello")
    response = detect(client, target)
    assert response.status_code == 422
    assert scrub(response.json()) == {
        "detail": {
            "error": "Could not detect import format",
            "warnings": [
                "Could not detect source format for: <tmp>/src/data.txt. "
                "Please specify the source explicitly."
            ],
        }
    }


def test_detect_unknown_explicit_source_is_422(client, tmp_path) -> None:
    target = write(tmp_path / "src" / "data.txt", "hello")
    response = detect(client, target, source="notion")
    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "error": "Could not detect import format",
            "warnings": [
                "Parser for source 'notion' is not yet implemented. "
                "Supported: claude_web, chatgpt, claude_code, codex, cursor, generic."
            ],
        }
    }


def test_detect_empty_directory_is_422(client, tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    response = detect(client, empty, source="generic")
    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "error": "Could not detect import format",
            "warnings": ["No importable items found"],
        }
    }


def test_detect_bad_zip_is_422(client, tmp_path) -> None:
    target = write(tmp_path / "src" / "conversations.zip", "not a zip")
    response = detect(client, target)
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "Could not detect import format"


# ── detect: one fixture per importer ───────────────────────────────────────


def _checked(client, scrub, snapshot, name: str, path: Path, source=None) -> dict:
    body = detect_ok(client, path, source)
    import_id = body["import_id"]
    assert len(import_id) == 16 and int(import_id, 16) >= 0
    assert SECRET not in str(body)
    snapshot.check(f"detect_{name}.json", scrub(body, import_id))
    preview = client.get(f"/api/import/preview/{import_id}")
    assert preview.status_code == 200
    snapshot.check(f"preview_{name}.json", scrub(preview.json(), import_id))
    return body


def test_detect_claude_web_json(client, tmp_path, scrub, snapshot) -> None:
    path = write_json(tmp_path / "src" / "claude.json", CLAUDE_WEB_CONVERSATIONS)
    body = _checked(client, scrub, snapshot, "claude_web_json", path)
    assert body["detected_source"] == "claude_web"


def test_detect_claude_web_projects_object(client, tmp_path, scrub, snapshot) -> None:
    path = write_json(
        tmp_path / "src" / "claude-all.json",
        {"conversations": CLAUDE_WEB_CONVERSATIONS, "projects": CLAUDE_WEB_PROJECTS},
    )
    _checked(client, scrub, snapshot, "claude_web_object", path, "claude_web")


def test_detect_claude_web_zip(client, tmp_path, scrub, snapshot) -> None:
    path = write_zip(
        tmp_path / "src" / "claude-export.zip",
        {
            "conversations.json": CLAUDE_WEB_CONVERSATIONS,
            "projects.json": CLAUDE_WEB_PROJECTS,
            "broken.json": "{not json",
        },
    )
    body = _checked(client, scrub, snapshot, "claude_web_zip", path)
    assert body["detected_source"] == "claude_web"


def test_detect_chatgpt_json(client, tmp_path, scrub, snapshot) -> None:
    path = write_json(tmp_path / "src" / "chatgpt.json", CHATGPT_CONVERSATIONS)
    body = _checked(client, scrub, snapshot, "chatgpt_json", path)
    assert body["detected_source"] == "chatgpt"


def test_detect_chatgpt_zip(client, tmp_path, scrub, snapshot) -> None:
    path = write_zip(
        tmp_path / "src" / "chatgpt-export.zip",
        {
            "conversations.json": CHATGPT_CONVERSATIONS,
            "gpts.json": [
                {
                    "name": "Chef Bot",
                    "description": "",
                    "instructions": "Cook.",
                    "tools": [{"type": "browser", "metadata": {"name": "web"}}],
                }
            ],
            "user.json": {"user_memory": ["Likes tea", "  "]},
        },
    )
    body = _checked(client, scrub, snapshot, "chatgpt_zip", path)
    assert body["detected_source"] == "chatgpt"


def test_detect_claude_code_dir(client, home, scrub, snapshot) -> None:
    claude = build_claude_code_dir(home)
    body = _checked(client, scrub, snapshot, "claude_code", claude, "claude_code")
    assert body["detected_source"] == "claude_code"


def test_detect_claude_code_autodetects_parent(client, home) -> None:
    build_claude_code_dir(home)
    assert detect_ok(client, home)["detected_source"] == "claude_code"


def test_detect_codex_dir(client, home, scrub, snapshot) -> None:
    codex = build_codex_dir(home)
    body = _checked(client, scrub, snapshot, "codex", codex, "codex")
    assert body["detected_source"] == "codex"


def test_detect_cursor_dir(client, tmp_path, scrub, snapshot) -> None:
    workspace = build_cursor_dir(tmp_path)
    body = _checked(client, scrub, snapshot, "cursor", workspace)
    assert body["detected_source"] == "cursor"


def test_detect_generic_dir(client, tmp_path, scrub, snapshot) -> None:
    source = build_generic_dir(tmp_path)
    body = _checked(client, scrub, snapshot, "generic_dir", source, "generic")
    assert body["detected_source"] == "generic"


def test_detect_generic_single_files(client, tmp_path, scrub, snapshot) -> None:
    source = build_generic_dir(tmp_path)
    results = {}
    for name in ("mcp.json", "agent.md", "notes.md", "keys.env"):
        body = detect_ok(client, source / name, "generic")
        results[name] = scrub(body, body["import_id"])
    skill = detect_ok(client, source / "pdf-tools" / "SKILL.md")
    results["SKILL.md"] = scrub(skill, skill["import_id"])
    snapshot.check("detect_generic_files.json", results)


def test_detect_generic_plugin_dir_is_not_importable(client, tmp_path) -> None:
    plugin = tmp_path / "plug"
    write_json(plugin / "plugin.json", {"name": "my-plugin"})
    body = detect_ok(client, plugin)
    assert body["detected_source"] == "generic"
    assert body["summary"]["not_importable"] == 1
    assert body["items"][0]["action"] == "skip"
    assert body["items"][0]["reason"] == "Plugin items are not supported for import"


def test_detect_relative_path_resolves_against_backend_cwd(client, tmp_path, scrub):
    write(tmp_path / "cwd" / "rel" / "notes.md", "# Rel\nx")
    body = detect_ok(client, "rel/notes.md", "generic")
    assert scrub(body["path"]) == "<tmp>/cwd/rel/notes.md"


# ── preview ────────────────────────────────────────────────────────────────


def test_preview_unknown_import_is_404(client) -> None:
    response = client.get("/api/import/preview/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "Import not found"}


def test_delete_unknown_import_still_cancels(client) -> None:
    response = client.delete("/api/import/nope")
    assert response.status_code == 200
    assert response.json() == {"status": "cancelled"}


def test_delete_removes_pending_preview(client, tmp_path) -> None:
    body = detect_ok(client, write(tmp_path / "n.md", "# N\nx"), "generic")
    response = client.delete(f"/api/import/{body['import_id']}")
    assert response.json() == {"status": "cancelled"}
    assert client.get(f"/api/import/preview/{body['import_id']}").status_code == 404
