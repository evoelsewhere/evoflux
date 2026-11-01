"""``POST/PUT/PATCH/DELETE /api/skills``: bundle writes, toggles, errors, paths."""

from __future__ import annotations

import base64
import os

import pytest

from registry_helpers import (
    SKILL_BODY,
    lf,
    managed_state,
    skill_md,
    tree,
    write_skill,
)


def create(client, name="alpha", content=None, files=(), **params):
    return client.post(
        "/api/skills",
        params=params,
        json={
            "name": name,
            "content": skill_md(name) if content is None else content,
            "files": list(files),
        },
    )


def settings_file(config_dir) -> bytes | None:
    path = config_dir / "skill-settings.json"
    return lf(path.read_bytes()) if path.exists() else None


# ── create ──────────────────────────────────────────────────────────────────


def test_create_writes_the_bundle_byte_for_byte_and_returns_the_detail(
    client, skills_dir, scrub
) -> None:
    binary = bytes(range(256))
    content = skill_md("alpha", body="Line one.\r\nLine two.\n")
    response = create(
        client,
        content=content,
        files=[
            {"path": "scripts/run.py", "content": "print(1)\n"},
            {"path": "assets/blob.bin", "content": base64.b64encode(binary).decode(), "encoding": "base64"},
            {"path": "notes.txt", "content": "caf\u00e9\r\n"},
        ],
    )
    assert response.status_code == 201
    body = response.json()
    assert scrub(body["location"]) == "<tmp>/config/skills/alpha/SKILL.md"
    assert (body["source"], body["editable"], body["enabled"], body["valid"]) == (
        "user", True, True, True,
    )
    assert body["resource_count"] == 3
    assert body["content"] == content.replace("\r\n", "\n")  # read back normalized
    assert [f["path"] for f in body["files"]] == ["notes.txt", "assets/blob.bin", "scripts/run.py"]
    written = tree(skills_dir)
    # SKILL.md and bundle files are written with exact bytes (no newline translation).
    assert written == {
        "alpha": None,
        "alpha/SKILL.md": content.encode("utf-8"),
        "alpha/scripts": None,
        "alpha/scripts/run.py": b"print(1)\n",
        "alpha/assets": None,
        "alpha/assets/blob.bin": binary,
        "alpha/notes.txt": "caf\u00e9\r\n".encode("utf-8"),
    }


def test_create_leaves_no_staging_or_backup_directories(client, skills_dir) -> None:
    assert create(client).status_code == 201
    assert sorted(p.name for p in skills_dir.iterdir()) == ["alpha"]


def test_create_without_files_defaults_to_an_empty_bundle(client, skills_dir) -> None:
    response = client.post("/api/skills", json={"name": "plain", "content": skill_md("plain")})
    assert response.status_code == 201
    assert response.json()["files"] == []
    assert sorted(tree(skills_dir)) == ["plain", "plain/SKILL.md"]


def test_create_does_not_touch_the_enabled_state(client, config_dir) -> None:
    assert create(client).status_code == 201
    assert settings_file(config_dir) is None


def test_create_conflicts(client, skills_dir) -> None:
    assert create(client).status_code == 201
    again = create(client)
    assert again.status_code == 409
    assert again.json() == {"detail": "Skill 'alpha' already exists."}
    # An empty directory may be reused; a directory holding anything may not.
    (skills_dir / "empty").mkdir()
    assert create(client, "empty").status_code == 201
    (skills_dir / "full").mkdir()
    (skills_dir / "full" / "keep.txt").write_text("k", encoding="utf-8")
    full = create(client, "full")
    assert full.status_code == 409
    assert full.json() == {"detail": "Skill bundle directory for 'full' already contains files."}
    assert (skills_dir / "full" / "keep.txt").read_text(encoding="utf-8") == "k"
    (skills_dir / "afile").write_text("x", encoding="utf-8")
    afile = create(client, "afile")
    assert afile.status_code == 409
    assert afile.json() == {"detail": "Skill bundle path for 'afile' is not an editable directory."}


@pytest.mark.parametrize(
    ("name", "detail"),
    [
        ("My_Skill", "name may contain only lowercase letters, digits and single hyphens, and must not start or end with a hyphen."),
        ("", "name may contain only lowercase letters, digits and single hyphens, and must not start or end with a hyphen."),
        ("-a", "name may contain only lowercase letters, digits and single hyphens, and must not start or end with a hyphen."),
        ("a--b", "name may contain only lowercase letters, digits and single hyphens, and must not start or end with a hyphen."),
        ("../evil", "name may contain only lowercase letters, digits and single hyphens, and must not start or end with a hyphen."),
        ("a/b", "name may contain only lowercase letters, digits and single hyphens, and must not start or end with a hyphen."),
        ("a\\b", "name may contain only lowercase letters, digits and single hyphens, and must not start or end with a hyphen."),
        (".", "name may contain only lowercase letters, digits and single hyphens, and must not start or end with a hyphen."),
        ("claude-helper", "name must not contain 'claude'."),
        ("my-anthropic", "name must not contain 'anthropic'."),
        ("a" * 65, "name exceeds 64 characters."),
    ],
)
def test_create_rejects_bad_names_before_touching_the_disk(
    client, skills_dir, config_dir, name, detail
) -> None:
    response = client.post("/api/skills", json={"name": name, "content": skill_md("x")})
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert tree(skills_dir) == {}
    assert not (config_dir.parent / "evil").exists()


@pytest.mark.parametrize(
    ("content", "detail"),
    [
        ("plain text", "SKILL.md must start with YAML frontmatter between '---' lines."),
        ("---\n- a\n---\nBody", "Frontmatter must be a YAML mapping."),
        (skill_md("other"), "name 'other' does not match its directory 'alpha'."),
        ("---\nname: alpha\n---\n\nBody\n", "Frontmatter requires a non-empty description."),
        ("---\nname: alpha\ndescription: d\n---\n", "SKILL.md instructions must not be empty."),
        (skill_md("alpha", extra="foo: 1\n"), "Frontmatter field 'foo' is not supported and is ignored."),
        (skill_md("alpha", "has <b>tags</b>"), "description must not contain XML tags."),
        (skill_md("alpha", "d" * 1025), "description exceeds 1024 characters."),
        (skill_md("alpha", extra="user-invocable: maybe\n"), "user-invocable must be true or false; it is ignored."),
        (skill_md("alpha", extra="metadata:\n  a: 1\n"), "metadata must map string keys to string values; it is ignored."),
        (skill_md("alpha", body="x" * (512 * 1024)), "SKILL.md exceeds 524288 bytes."),
    ],
    ids=[
        "no-frontmatter", "not-a-mapping", "name-mismatch", "no-description",
        "empty-body", "unknown-field", "xml-tag", "long-description",
        "bad-bool", "bad-metadata", "too-large",
    ],
)
def test_create_validates_skill_md_strictly(client, skills_dir, content, detail) -> None:
    response = create(client, content=content)
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert tree(skills_dir) == {}


def test_create_joins_every_blocking_message_with_a_semicolon(client) -> None:
    response = create(client, content="---\nname: alpha\nfoo: 1\n---\n")
    assert response.status_code == 422
    assert response.json() == {
        "detail": "Frontmatter requires a non-empty description.; "
        "Frontmatter field 'foo' is not supported and is ignored.; "
        "SKILL.md instructions must not be empty."
    }


def test_advisory_warnings_do_not_block_a_write(client) -> None:
    long_body = "\n".join("line" for _ in range(600))
    response = create(client, content=skill_md("alpha", body=long_body))
    assert response.status_code == 201
    assert [d["code"] for d in response.json()["diagnostics"]] == ["body-too-long"]
    assert response.json()["valid"] is True


@pytest.mark.parametrize(
    ("files", "detail"),
    [
        ([{"path": "../x", "content": "a"}], "Invalid skill resource path '../x'."),
        ([{"path": "a/../b", "content": "a"}], "Invalid skill resource path 'a/../b'."),
        ([{"path": "/etc/x", "content": "a"}], "Invalid skill resource path '/etc/x'."),
        ([{"path": "a\\b", "content": "a"}], "Invalid skill resource path 'a\\b'."),
        ([{"path": "", "content": "a"}], "Invalid skill resource path ''."),
        ([{"path": "SKILL.md", "content": "a"}], "Invalid skill resource path 'SKILL.md'."),
        ([{"path": "sub/SKILL.md", "content": "a"}], "Invalid skill resource path 'sub/SKILL.md'."),
        ([{"path": "a", "content": "1"}, {"path": "a", "content": "2"}], "Duplicate skill resource path 'a'."),
        ([{"path": "a", "content": "!!", "encoding": "base64"}], "Invalid base64 content for 'a'."),
        ([{"path": "big", "content": "x" * (2 * 1024 * 1024 + 1)}], "Skill resource 'big' exceeds the 2 MiB per-file limit."),
    ],
)
def test_create_rejects_unsafe_bundle_files_and_leaves_nothing_behind(
    client, skills_dir, tmp_path, files, detail
) -> None:
    response = create(client, files=files)
    assert response.status_code == 400
    assert response.json() == {"detail": detail}
    assert tree(skills_dir) == {}
    assert not (tmp_path / "config" / "x").exists()
    assert not (tmp_path / "x").exists()


def test_redundant_separators_and_dot_segments_are_normalized_not_rejected(
    client, skills_dir
) -> None:
    """``PurePosixPath`` folds ``./a`` to ``a`` and ``d//b`` to ``d/b`` before the checks."""
    response = create(
        client,
        files=[{"path": "./a", "content": "1"}, {"path": "d//b", "content": "2"}],
    )
    assert response.status_code == 201
    assert [f["path"] for f in response.json()["files"]] == ["a", "d/b"]
    assert (skills_dir / "alpha" / "d" / "b").read_bytes() == b"2"


def test_more_than_200_files_is_a_validation_error(client) -> None:
    files = [{"path": f"f{i}", "content": "x"} for i in range(201)]
    response = create(client, files=files)
    assert response.status_code == 422
    error = response.json()["detail"][0]
    assert (error["type"], error["loc"]) == ("too_long", ["body", "files"])


def test_create_validates_the_request_body(client) -> None:
    for body in ({}, {"name": "a"}, {"content": "x"}, {"name": 1, "content": "x"}, {"name": "a", "content": "x", "files": [{"path": "p"}]}):
        response = client.post("/api/skills", json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


def test_create_ignores_the_workspace_and_always_writes_to_the_user_root(
    client, skills_dir, workspace
) -> None:
    response = create(client, workspace=str(workspace))
    assert response.status_code == 201
    assert response.json()["source"] == "user"
    assert (skills_dir / "alpha" / "SKILL.md").is_file()
    assert not (workspace / ".claude").exists()


def test_a_created_skill_shadowed_by_a_project_skill_is_still_returned(
    client, workspace
) -> None:
    write_skill(workspace / ".claude" / "skills", "alpha", skill_md("alpha", "project copy"))
    response = create(client, workspace=str(workspace))
    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "user"
    assert body["description"] == "Does a thing."  # the file just written, not the winner


# ── update ──────────────────────────────────────────────────────────────────


def test_update_replaces_skill_md_merges_files_and_prunes_deleted_ones(
    client, skills_dir
) -> None:
    write_skill(
        skills_dir,
        "alpha",
        **{"scripts/run.py": "old\n", "deep/a/b.txt": "b\n", "keep.txt": "k\n"},
    )
    new = skill_md("alpha", "Changed.", body="New body\n")
    response = client.put(
        "/api/skills/alpha",
        json={
            "content": new,
            "files": [{"path": "scripts/run.py", "content": "new\n"}, {"path": "fresh.txt", "content": "f\n"}],
            "deleted_files": ["deep/a/b.txt", "ghost.txt"],
        },
    )
    assert response.status_code == 200
    assert response.json()["description"] == "Changed."
    assert tree(skills_dir) == {
        "alpha": None,
        "alpha/SKILL.md": new.encode("utf-8"),
        "alpha/scripts": None,
        "alpha/scripts/run.py": b"new\n",
        "alpha/keep.txt": b"k\n",
        "alpha/fresh.txt": b"f\n",
    }  # the emptied deep/a and deep/ directories are removed with their last file


def test_update_requires_content_and_defaults_the_lists(client, skills_dir) -> None:
    write_skill(skills_dir, "alpha", **{"keep.txt": "k"})
    assert client.put("/api/skills/alpha", json={}).status_code == 422
    ok = client.put("/api/skills/alpha", json={"content": skill_md("alpha", "Only text.")})
    assert ok.status_code == 200
    assert (skills_dir / "alpha" / "keep.txt").read_text(encoding="utf-8") == "k"


def test_update_errors_do_not_change_the_bundle(client, skills_dir) -> None:
    write_skill(skills_dir, "alpha", **{"keep.txt": "k\n"})
    before = tree(skills_dir)
    cases = [
        ({"content": "nope"}, 422, "SKILL.md must start with YAML frontmatter between '---' lines."),
        ({"content": skill_md("zzz")}, 422, "name 'zzz' does not match its directory 'alpha'."),
        ({"content": skill_md("alpha"), "files": [{"path": "a/../b", "content": "x"}]}, 400, "Invalid skill resource path 'a/../b'."),
        ({"content": skill_md("alpha"), "files": [{"path": "SKILL.md", "content": "x"}]}, 400, "Invalid skill resource path 'SKILL.md'."),
        ({"content": skill_md("alpha"), "deleted_files": ["../x"]}, 400, "Invalid skill resource path '../x'."),
        ({"content": skill_md("alpha"), "deleted_files": ["SKILL.md"]}, 400, "Invalid skill resource path 'SKILL.md'."),
        ({"content": skill_md("alpha"), "files": [{"path": "a", "content": "!!", "encoding": "base64"}]}, 400, "Invalid base64 content for 'a'."),
        ({"content": skill_md("alpha"), "files": [{"path": "big", "content": "x" * (2 * 1024 * 1024 + 1)}]}, 400, "Skill resource 'big' exceeds the 2 MiB per-file limit."),
    ]
    for body, status, detail in cases:
        response = client.put("/api/skills/alpha", json=body)
        assert (response.status_code, response.json()) == (status, {"detail": detail}), body
        assert tree(skills_dir) == before


def test_update_can_delete_a_directory_resource_only_as_a_file(client, skills_dir) -> None:
    write_skill(skills_dir, "alpha", **{"dir/f.txt": "x"})
    response = client.put(
        "/api/skills/alpha", json={"content": skill_md("alpha"), "deleted_files": ["dir"]}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Skill resource 'dir' is not a regular file."}


def test_update_unknown_builtin_and_unwritable_skills(client, skills_dir, home) -> None:
    missing = client.put("/api/skills/ghost", json={"content": skill_md("ghost")})
    assert (missing.status_code, missing.json()) == (404, {"detail": "Skill 'ghost' not found."})
    builtin = client.put("/api/skills/browser-use", json={"content": skill_md("browser-use")})
    assert builtin.status_code == 403
    assert builtin.json() == {"detail": "Skill 'browser-use' is read-only because it is a builtin Skill."}


def test_update_edits_the_selected_winner_in_the_project_root(
    client, skills_dir, workspace
) -> None:
    write_skill(workspace / ".claude" / "skills", "alpha", skill_md("alpha", "project"))
    write_skill(skills_dir, "alpha", skill_md("alpha", "user"))
    response = client.put(
        "/api/skills/alpha",
        params={"workspace": str(workspace)},
        json={"content": skill_md("alpha", "project edited")},
    )
    assert response.status_code == 200
    assert response.json()["source"] == "project"
    assert "project edited" in (workspace / ".claude/skills/alpha/SKILL.md").read_text(encoding="utf-8")
    assert "user" in (skills_dir / "alpha/SKILL.md").read_text(encoding="utf-8")
    without = client.put("/api/skills/alpha", json={"content": skill_md("alpha", "user edited")})
    assert without.status_code == 200 and without.json()["source"] == "user"


def test_update_edits_a_skill_in_a_home_root(client, home) -> None:
    write_skill(home / ".claude" / "skills", "homey")
    response = client.put("/api/skills/homey", json={"content": skill_md("homey", "edited")})
    assert response.status_code == 200
    assert "edited" in (home / ".claude/skills/homey/SKILL.md").read_text(encoding="utf-8")


def test_update_uses_the_directory_of_a_skill_whose_frontmatter_name_differs(
    client, skills_dir
) -> None:
    write_skill(skills_dir, "bad-dir", skill_md("other-name"))
    response = client.put(
        "/api/skills/other-name", json={"content": skill_md("other-name", "edited")}
    )
    # The directory name is part of strict validation, so the rename is refused.
    assert response.status_code == 422
    assert response.json() == {"detail": "name 'other-name' does not match its directory 'bad-dir'."}


def test_update_may_leave_a_skill_that_was_invalid_valid(client, skills_dir) -> None:
    write_skill(skills_dir, "alpha", "garbage")
    response = client.put("/api/skills/alpha", json={"content": skill_md("alpha")})
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_update_keeps_the_existing_file_mode(client, skills_dir) -> None:
    if os.name == "nt":
        pytest.skip("POSIX permission bits")
    directory = write_skill(skills_dir, "alpha", **{"run.sh": "#!/bin/sh\n"})
    (directory / "run.sh").chmod(0o755)
    assert client.put(
        "/api/skills/alpha",
        json={"content": skill_md("alpha"), "files": [{"path": "run.sh", "content": "#!/bin/sh\necho\n"}]},
    ).status_code == 200
    assert (directory / "run.sh").stat().st_mode & 0o777 == 0o755


# ── enabled switch ──────────────────────────────────────────────────────────


def test_patch_writes_the_settings_file_and_removes_it_when_nothing_is_disabled(
    client, skills_dir, config_dir
) -> None:
    write_skill(skills_dir, "alpha")
    off = client.patch("/api/skills/alpha", json={"enabled": False})
    assert off.status_code == 200
    assert off.json()["enabled"] is False
    assert settings_file(config_dir) == b'{\n  "version": 2,\n  "disabled": [\n    "alpha"\n  ]\n}\n'
    builtin = client.patch("/api/skills/browser-use", json={"enabled": False})
    assert builtin.status_code == 200 and builtin.json()["enabled"] is False
    assert settings_file(config_dir) == (
        b'{\n  "version": 2,\n  "disabled": [\n    "alpha",\n    "browser-use"\n  ]\n}\n'
    )
    assert client.patch("/api/skills/alpha", json={"enabled": False}).status_code == 200
    again = settings_file(config_dir)
    assert again is not None and again.count(b"alpha") == 1
    assert client.patch("/api/skills/alpha", json={"enabled": True}).json()["enabled"] is True
    assert client.patch("/api/skills/browser-use", json={"enabled": True}).status_code == 200
    assert settings_file(config_dir) is None
    # The write lock file stays behind; it is part of the folder contract.
    assert (config_dir / ".skill-settings.json.lock").exists()


def test_patch_does_not_change_the_skill_files(client, skills_dir) -> None:
    write_skill(skills_dir, "alpha", **{"f.txt": "x"})
    before = tree(skills_dir)
    client.patch("/api/skills/alpha", json={"enabled": False})
    assert tree(skills_dir) == before


def test_patch_errors(client) -> None:
    missing = client.patch("/api/skills/ghost", json={"enabled": True})
    assert (missing.status_code, missing.json()) == (404, {"detail": "Skill 'ghost' not found."})
    for body in ({}, {"enabled": "maybe"}, {"enabled": None}):
        response = client.patch("/api/skills/browser-use", json=body)
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], list)


def test_patch_with_a_corrupt_settings_file_is_409_and_keeps_the_file(
    client, config_dir, scrub
) -> None:
    (config_dir / "skill-settings.json").write_bytes(b"{broken")
    response = client.patch("/api/skills/browser-use", json={"enabled": False})
    assert response.status_code == 409
    detail = scrub(response.json()["detail"])
    assert detail.startswith(
        "Could not save the enabled state of Skill 'browser-use': <tmp>/config/skill-settings.json is not valid JSON:"
    )
    assert (config_dir / "skill-settings.json").read_bytes() == b"{broken"


def test_patch_replaces_a_foreign_or_old_settings_document(client, config_dir) -> None:
    (config_dir / "skill-settings.json").write_text('{"version": 1, "disabled": ["x"]}', encoding="utf-8")
    assert client.patch("/api/skills/browser-use", json={"enabled": False}).status_code == 200
    assert settings_file(config_dir) == b'{\n  "version": 2,\n  "disabled": [\n    "browser-use"\n  ]\n}\n'


def test_patch_can_switch_a_project_skill_selected_by_workspace(
    client, workspace, config_dir
) -> None:
    write_skill(workspace / ".claude" / "skills", "proj")
    assert client.patch("/api/skills/proj", json={"enabled": False}).status_code == 404
    response = client.patch(
        "/api/skills/proj", params={"workspace": str(workspace)}, json={"enabled": False}
    )
    assert response.status_code == 200
    # The switch is keyed by name only, so it follows the name into every workspace.
    assert b'"proj"' in (settings_file(config_dir) or b"")


# ── delete ──────────────────────────────────────────────────────────────────


def test_delete_removes_the_whole_bundle_and_the_disabled_entry(
    client, skills_dir, config_dir
) -> None:
    write_skill(skills_dir, "alpha", **{"scripts/run.py": "x", "ref/a.md": "y"})
    write_skill(skills_dir, "beta")
    client.patch("/api/skills/alpha", json={"enabled": False})
    client.patch("/api/skills/browser-use", json={"enabled": False})
    response = client.delete("/api/skills/alpha")
    assert response.status_code == 200
    assert response.json() == {"name": "alpha"}
    assert sorted(tree(skills_dir)) == ["beta", "beta/SKILL.md"]
    assert settings_file(config_dir) == b'{\n  "version": 2,\n  "disabled": [\n    "browser-use"\n  ]\n}\n'
    assert client.get("/api/skills/alpha").status_code == 404
    assert client.delete("/api/skills/alpha").status_code == 404


def test_delete_errors(client, skills_dir) -> None:
    missing = client.delete("/api/skills/ghost")
    assert (missing.status_code, missing.json()) == (404, {"detail": "Skill 'ghost' not found."})
    builtin = client.delete("/api/skills/browser-use")
    assert builtin.status_code == 403
    assert builtin.json() == {"detail": "Skill 'browser-use' is read-only because it is a builtin Skill."}
    assert client.get("/api/skills/browser-use").status_code == 200


def test_delete_removes_a_project_skill_selected_by_workspace(client, workspace) -> None:
    write_skill(workspace / ".claude" / "skills", "proj", **{"f": "x"})
    assert client.delete("/api/skills/proj").status_code == 404
    response = client.delete("/api/skills/proj", params={"workspace": str(workspace)})
    assert response.status_code == 200
    assert not (workspace / ".claude" / "skills" / "proj").exists()
    assert (workspace / ".claude" / "skills").is_dir()


def test_delete_removes_an_invalid_skill_so_it_can_be_cleaned_up(client, skills_dir) -> None:
    write_skill(skills_dir, "broken", "garbage")
    assert client.delete("/api/skills/broken").status_code == 200
    assert not (skills_dir / "broken").exists()


def test_write_routes_validate_the_workspace_first(client, tmp_path) -> None:
    missing = str(tmp_path / "nope")
    for response in (
        client.post("/api/skills", params={"workspace": missing}, json={"name": "a", "content": skill_md("a")}),
        client.put("/api/skills/a", params={"workspace": missing}, json={"content": skill_md("a")}),
        client.patch("/api/skills/a", params={"workspace": missing}, json={"enabled": True}),
        client.delete("/api/skills/a", params={"workspace": missing}),
    ):
        assert response.status_code == 422
        assert response.json()["detail"].startswith("Workspace does not exist or is not a directory:")


# ── request paths that become file paths ────────────────────────────────────


def test_traversal_in_names_and_resource_paths_never_leaves_the_skill_folder(
    client, skills_dir, tmp_path
) -> None:
    """``name`` is matched against ``[a-z0-9-]`` and resource paths are checked
    segment by segment; neither reaches the file system unchecked."""
    write_skill(skills_dir, "alpha")
    victim = tmp_path / "config" / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    for path in ("../victim.txt", "../../victim.txt", "x/../../victim.txt", "..", "a/..", ".\\victim.txt", "..\\victim.txt"):
        for field in ("files", "deleted_files"):
            body = {"content": skill_md("alpha")}
            body[field] = [{"path": path, "content": "pwn"}] if field == "files" else [path]
            response = client.put("/api/skills/alpha", json=body)
            assert response.status_code == 400, (field, path)
    for name in ("..", "../alpha", "alpha/..", "%2e%2e"):
        assert client.put(f"/api/skills/{name}", json={"content": skill_md("alpha")}).status_code in (404, 405)
        assert client.delete(f"/api/skills/{name}").status_code in (404, 405)
    assert victim.read_text(encoding="utf-8") == "keep"
    assert (skills_dir / "alpha" / "SKILL.md").is_file()


def test_a_workspace_names_where_project_skills_are_written_and_deleted(
    client, tmp_path
) -> None:
    """NOTES finding S1: any existing directory is accepted as ``workspace`` and
    its ``.claude/skills`` bundles can then be edited and deleted."""
    elsewhere = tmp_path / "elsewhere"
    write_skill(elsewhere / ".claude" / "skills", "target", skill_md("target"), **{"x.txt": "x"})
    edit = client.put(
        "/api/skills/target",
        params={"workspace": str(elsewhere)},
        json={"content": skill_md("target", "overwritten")},
    )
    assert edit.status_code == 200
    assert "overwritten" in (elsewhere / ".claude/skills/target/SKILL.md").read_text(encoding="utf-8")
    assert client.delete("/api/skills/target", params={"workspace": str(elsewhere)}).status_code == 200
    assert not (elsewhere / ".claude/skills/target").exists()


def _symlink_or_skip(target, link) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")


def test_symlinked_skills_are_listed_but_never_written_or_deleted(
    client, skills_dir, tmp_path
) -> None:
    outside = tmp_path / "outside"
    write_skill(outside, "linked", skill_md("linked", "outside"))
    skills_dir.mkdir(parents=True, exist_ok=True)
    _symlink_or_skip(outside / "linked", skills_dir / "linked")
    listed = {s["name"]: s for s in client.get("/api/skills").json()["skills"]}["linked"]
    assert listed["symlinked"] is True and listed["editable"] is False
    put = client.put("/api/skills/linked", json={"content": skill_md("linked", "pwned")})
    assert put.status_code == 403
    assert put.json() == {"detail": "Skill 'linked' is read-only because it is symlinked."}
    delete = client.delete("/api/skills/linked")
    assert delete.status_code == 403
    assert (outside / "linked" / "SKILL.md").read_text(encoding="utf-8") == skill_md("linked", "outside")
    assert client.patch("/api/skills/linked", json={"enabled": False}).status_code == 200


def test_a_symlink_inside_an_editable_bundle_blocks_updates(client, skills_dir, tmp_path) -> None:
    directory = write_skill(skills_dir, "alpha")
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    try:
        os.symlink(secret, directory / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    files = client.get("/api/skills/alpha").json()["files"]
    assert files == []  # the link is neither listed nor counted
    response = client.put("/api/skills/alpha", json={"content": skill_md("alpha", "edit")})
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Symlinked files and directories are not allowed in editable skill bundles."
    }
    assert secret.read_text(encoding="utf-8") == "secret"


# ── Conductor-managed skills ────────────────────────────────────────────────


def test_a_conductor_managed_skill_is_read_only_but_can_be_switched(
    client, skills_dir, config_dir, state_dir
) -> None:
    write_skill(skills_dir, "governed")
    managed_state(state_dir, config_dir, skills=["governed"])
    skill = {s["name"]: s for s in client.get("/api/skills").json()["skills"]}["governed"]
    assert skill["editable"] is False
    assert skill["provider"]["project_name"] == "Acme"
    assert skill["provider"]["resource_id"] == "res-skill-0"
    message = "Skill 'governed' is managed by Conductor project 'Acme' and cannot be changed locally."
    put = client.put("/api/skills/governed", json={"content": skill_md("governed")})
    assert (put.status_code, put.json()) == (403, {"detail": message})
    delete = client.delete("/api/skills/governed")
    assert (delete.status_code, delete.json()) == (403, {"detail": message})
    assert (skills_dir / "governed" / "SKILL.md").is_file()
    assert client.patch("/api/skills/governed", json={"enabled": False}).status_code == 200


def test_a_project_skill_with_a_managed_name_is_user_owned(
    client, workspace, config_dir, state_dir, skills_dir
) -> None:
    write_skill(skills_dir, "governed")
    write_skill(workspace / ".claude" / "skills", "governed", skill_md("governed", "shadowing"))
    managed_state(state_dir, config_dir, skills=["governed"])
    skill = {
        s["name"]: s
        for s in client.get("/api/skills", params={"workspace": str(workspace)}).json()["skills"]
    }["governed"]
    assert skill["provider"] is None and skill["editable"] is True
    assert SKILL_BODY
