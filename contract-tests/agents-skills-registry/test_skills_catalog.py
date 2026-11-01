"""``GET /api/skills`` and ``GET /api/skills/{name}``: discovery, precedence, detail."""

from __future__ import annotations

import json

import pytest

from registry_helpers import skill_md, write_skill

SUMMARY_KEYS = {
    "name", "description", "location", "source", "plugin_id", "enabled",
    "model_invocable", "user_invocable", "license", "compatibility",
    "allowed_tools", "metadata", "valid", "diagnostics", "shadowed_paths",
    "editable", "symlinked", "resource_count", "provider",
}  # fmt: skip
DETAIL_KEYS = SUMMARY_KEYS | {"content", "files", "bundle_truncated"}


def listing(client, **params):
    response = client.get("/api/skills", params=params)
    assert response.status_code == 200
    return {item["name"]: item for item in response.json()["skills"]}


def test_builtin_skills_are_listed_sorted_and_read_only(client, snapshot) -> None:
    response = client.get("/api/skills")
    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["skills"]
    names = [item["name"] for item in body["skills"]]
    assert names == sorted(names)
    for item in body["skills"]:
        assert set(item) == SUMMARY_KEYS
        assert item["source"] == "builtin"
        assert item["editable"] is False
        assert item["symlinked"] is False
        assert item["valid"] is True
        assert item["enabled"] is True
        assert item["provider"] is None
        assert item["plugin_id"] is None
        assert item["location"].endswith("SKILL.md")
    snapshot.check("builtin_skill_names.json", names)


def test_user_skill_summary_shape_is_exact(client, skills_dir, scrub) -> None:
    write_skill(
        skills_dir,
        "alpha",
        skill_md(
            "alpha",
            "First skill.",
            extra=(
                "license: MIT\ncompatibility: Needs nothing.\n"
                "allowed-tools: read grep\nmetadata:\n  team: core\n"
                "disable-model-invocation: true\nuser-invocable: false\n"
            ),
        ),
        **{"scripts/run.py": "print(1)\n", "notes.txt": "n\n"},
    )
    skill = listing(client)["alpha"]
    assert scrub(skill) == {
        "name": "alpha",
        "description": "First skill.",
        "location": "<tmp>/config/skills/alpha/SKILL.md",
        "source": "user",
        "plugin_id": None,
        "enabled": True,
        "model_invocable": False,
        "user_invocable": False,
        "license": "MIT",
        "compatibility": "Needs nothing.",
        "allowed_tools": "read grep",
        "metadata": {"team": "core"},
        "valid": True,
        "diagnostics": [],
        "shadowed_paths": [],
        "editable": True,
        "symlinked": False,
        "resource_count": 2,
        "provider": None,
    }


def test_detail_has_content_and_sorted_bundle_files(client, skills_dir) -> None:
    write_skill(skills_dir, "alpha", **{"z.md": "z\n", "a/b.txt": "b\n", "a.json": "{}"})
    (skills_dir / "alpha" / "blob.bin").write_bytes(b"\x00\x01\x02")
    response = client.get("/api/skills/alpha")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == DETAIL_KEYS
    assert body["content"] == skill_md("alpha")
    assert body["bundle_truncated"] is False
    assert body["resource_count"] == 4
    assert body["files"] == [
        {"path": "a.json", "size": 2, "media_type": "application/json",
         "content": "{}", "encoding": "utf-8", "editable": True},
        {"path": "blob.bin", "size": 3, "media_type": "application/octet-stream",
         "content": None, "encoding": None, "editable": False},
        {"path": "z.md", "size": 2, "media_type": "text/markdown",
         "content": "z\n", "encoding": "utf-8", "editable": True},
        {"path": "a/b.txt", "size": 2, "media_type": "text/plain",
         "content": "b\n", "encoding": "utf-8", "editable": True},
    ]  # fmt: skip


def test_detail_listing_is_capped_at_200_files(client, skills_dir) -> None:
    directory = write_skill(skills_dir, "many")
    for index in range(201):
        (directory / f"f{index:03}.txt").write_text("x", encoding="utf-8")
    skill = listing(client)["many"]
    assert skill["resource_count"] == 201
    body = client.get("/api/skills/many").json()
    assert len(body["files"]) == 200
    assert body["bundle_truncated"] is True
    assert [f["path"] for f in body["files"]] == sorted(f["path"] for f in body["files"])


def test_detail_inlines_only_small_utf8_text_files(client, skills_dir) -> None:
    directory = write_skill(skills_dir, "budget")
    (directory / "big.txt").write_text("x" * (512 * 1024 + 1), encoding="utf-8")
    (directory / "nul.txt").write_bytes(b"a\x00b")
    (directory / "latin.txt").write_bytes(b"caf\xe9")
    (directory / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    files = {f["path"]: f for f in client.get("/api/skills/budget").json()["files"]}
    assert files["big.txt"]["content"] is None and files["big.txt"]["editable"] is False
    assert files["big.txt"]["size"] == 512 * 1024 + 1
    assert files["nul.txt"]["content"] is None and files["nul.txt"]["editable"] is False
    assert files["latin.txt"]["content"] is None and files["latin.txt"]["encoding"] is None
    assert files["img.png"]["media_type"] == "image/png"
    assert files["img.png"]["editable"] is False


def test_nested_skill_md_is_an_ordinary_read_only_bundle_file(client, skills_dir) -> None:
    write_skill(skills_dir, "outer", **{"inner/SKILL.md": skill_md("inner")})
    assert "inner" not in listing(client)
    files = client.get("/api/skills/outer").json()["files"]
    assert [(f["path"], f["editable"]) for f in files] == [("inner/SKILL.md", False)]


def test_hidden_directories_and_folders_without_skill_md_are_skipped(
    client, skills_dir
) -> None:
    write_skill(skills_dir, ".hidden")
    (skills_dir / "empty").mkdir(parents=True)
    (skills_dir / "stray.md").write_text("x", encoding="utf-8")
    write_skill(skills_dir, "kept")
    names = set(listing(client))
    assert "kept" in names
    assert not names & {".hidden", "empty", "stray.md"}


def test_invalid_skills_are_listed_with_diagnostics(client, skills_dir, scrub) -> None:
    write_skill(skills_dir, "no-frontmatter", "just text")
    write_skill(skills_dir, "no-desc", "---\nname: no-desc\n---\n\nBody\n")
    write_skill(skills_dir, "bad-dir", skill_md("other-name"))
    write_skill(skills_dir, "warns", skill_md("warns", extra="foo: 1\n"))
    skills = listing(client)
    broken = skills["no-frontmatter"]
    assert broken["valid"] is False and broken["description"] == ""
    assert broken["diagnostics"] == [
        {"code": "unreadable-skill", "severity": "error",
         "message": "SKILL.md must start with YAML frontmatter between '---' lines."}
    ]  # fmt: skip
    assert [d["code"] for d in skills["no-desc"]["diagnostics"]] == ["missing-description"]
    # The frontmatter name wins over the directory name, with a warning.
    renamed = skills["other-name"]
    assert renamed["valid"] is True
    assert scrub(renamed["location"]) == "<tmp>/config/skills/bad-dir/SKILL.md"
    assert renamed["diagnostics"] == [
        {"code": "name-directory-mismatch", "severity": "warning",
         "message": "name 'other-name' does not match its directory 'bad-dir'."}
    ]  # fmt: skip
    assert skills["warns"]["valid"] is True
    assert [d["code"] for d in skills["warns"]["diagnostics"]] == ["unknown-field"]


def test_detail_of_an_invalid_skill_shows_the_text_so_it_can_be_repaired(
    client, skills_dir
) -> None:
    write_skill(skills_dir, "broken", "no frontmatter\r\nsecond\r\n")
    body = client.get("/api/skills/broken").json()
    assert body["valid"] is False
    assert body["content"] == "no frontmatter\nsecond\n"  # newlines normalized


def test_detail_replaces_undecodable_bytes(client, skills_dir) -> None:
    directory = write_skill(skills_dir, "latin1")
    (directory / "SKILL.md").write_bytes(b"---\nname: latin1\n---\ncaf\xe9\n")
    body = client.get("/api/skills/latin1").json()
    assert body["valid"] is False
    assert "caf�" in body["content"]


def test_skill_md_over_the_size_limit_is_413_in_detail_and_invalid_in_the_list(
    client, skills_dir
) -> None:
    write_skill(skills_dir, "huge", skill_md("huge", body="x" * (512 * 1024)))
    assert listing(client)["huge"]["valid"] is False
    response = client.get("/api/skills/huge")
    assert response.status_code == 413
    assert response.json() == {"detail": "SKILL.md exceeds the 524288-byte limit."}


def test_unknown_name_is_404_and_names_with_slashes_do_not_route(client) -> None:
    missing = client.get("/api/skills/nope")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Skill 'nope' not found."}
    for path in ("/api/skills/a/b", "/api/skills/..%2F..%2Fx", "/api/skills/a%2Fb"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == {"detail": "Not Found"}


def test_precedence_project_then_user_then_home_then_builtin(
    client, skills_dir, home, workspace, scrub
) -> None:
    write_skill(workspace / ".claude" / "skills", "dup", skill_md("dup", "project"))
    write_skill(skills_dir, "dup", skill_md("dup", "user"))
    write_skill(home / ".claude" / "skills", "dup", skill_md("dup", "home"))
    write_skill(home / ".agents" / "skills", "dup", skill_md("dup", "home-agents"))
    write_skill(home / ".claude" / "skills", "homey", skill_md("homey"))
    plain = listing(client)
    assert plain["dup"]["description"] == "user"
    assert [scrub(p) for p in plain["dup"]["shadowed_paths"]] == [
        "<tmp>/home/.agents/skills/dup/SKILL.md",
        "<tmp>/home/.claude/skills/dup/SKILL.md",
    ]
    assert plain["homey"]["source"] == "user"
    with_ws = listing(client, workspace=str(workspace))
    assert with_ws["dup"]["description"] == "project"
    assert with_ws["dup"]["source"] == "project"
    assert len(with_ws["dup"]["shadowed_paths"]) == 3


def test_an_invalid_higher_root_skill_loses_to_a_valid_lower_one(
    client, skills_dir, workspace
) -> None:
    write_skill(workspace / ".evoflux" / "skills", "dup", "broken")
    write_skill(skills_dir, "dup", skill_md("dup", "valid user copy"))
    chosen = listing(client, workspace=str(workspace))["dup"]
    assert chosen["valid"] is True and chosen["source"] == "user"
    assert len(chosen["shadowed_paths"]) == 1


def test_project_roots_are_scanned_up_to_the_git_root(
    client, workspace, tmp_path
) -> None:
    nested = workspace / "pkg" / "inner"
    nested.mkdir(parents=True)
    write_skill(workspace / ".agents" / "skills", "from-root")
    write_skill(nested / ".claude" / "skills", "from-inner")
    # The walk stops at the Git root: its parent is never scanned.
    write_skill(tmp_path / ".claude" / "skills", "above-the-git-root")
    names = set(listing(client, workspace=str(nested)))
    assert {"from-root", "from-inner"} <= names
    assert "above-the-git-root" not in names


def test_workspace_must_be_an_existing_directory(client, tmp_path, scrub) -> None:
    missing = tmp_path / "does-not-exist"
    response = client.get("/api/skills", params={"workspace": str(missing)})
    assert response.status_code == 422
    assert scrub(response.json()) == {
        "detail": "Workspace does not exist or is not a directory: <tmp>/does-not-exist"
    }
    file = tmp_path / "file.txt"
    file.write_text("x", encoding="utf-8")
    assert client.get("/api/skills", params={"workspace": str(file)}).status_code == 422
    relative = client.get("/api/skills", params={"workspace": "relative"})
    assert relative.status_code == 422
    assert "cwd" in relative.json()["detail"]  # resolved against the process cwd
    both = client.get(
        "/api/skills",
        params=[("workspace", str(tmp_path)), ("workspace", str(missing))],
    )
    assert both.status_code == 422


def test_repeated_and_duplicate_workspaces_are_merged(client, workspace) -> None:
    write_skill(workspace / ".claude" / "skills", "once")
    response = client.get(
        "/api/skills",
        params=[("workspace", str(workspace)), ("workspace", str(workspace))],
    )
    assert response.status_code == 200
    names = [s["name"] for s in response.json()["skills"]]
    assert names.count("once") == 1


def test_any_existing_directory_is_accepted_as_a_workspace(client, tmp_path) -> None:
    """The route never checks the directory against an authorized workspace
    (NOTES finding S1): a skill below any directory the caller names is read."""
    elsewhere = tmp_path / "elsewhere"
    write_skill(
        elsewhere / ".claude" / "skills", "leak", skill_md("leak"), **{"secret.txt": "s3\n"}
    )
    body = client.get("/api/skills/leak", params={"workspace": str(elsewhere)}).json()
    assert body["source"] == "project"
    assert body["files"][0]["content"] == "s3\n"


def test_disabled_skills_are_flagged_everywhere(client, skills_dir, config_dir) -> None:
    write_skill(skills_dir, "dim")
    (config_dir / "skill-settings.json").write_text(
        json.dumps({"version": 2, "disabled": ["dim", "browser-use"]}), encoding="utf-8"
    )
    skills = listing(client)
    assert skills["dim"]["enabled"] is False
    assert skills["browser-use"]["enabled"] is False
    registry = client.get("/api/agents/registry").json()["skills"]
    assert {s["name"]: s["enabled"] for s in registry}["dim"] is False


@pytest.mark.parametrize(
    "document",
    [
        b"not json",
        b'{"version": 2, "disabled": "x"}',
        b'{"version": 2, "disabled": [1]}',
        b'{"version": 1, "disabled": ["dim"]}',
        b"[]",
    ],
    ids=["garbage", "wrong-type", "non-string", "old-version", "not-an-object"],
)
def test_a_malformed_settings_file_fails_open_on_reads(
    client, skills_dir, config_dir, document
) -> None:
    write_skill(skills_dir, "dim")
    (config_dir / "skill-settings.json").write_bytes(document)
    assert listing(client)["dim"]["enabled"] is True


@pytest.mark.parametrize("name", ["on", "off", "yes", "no", "true", "null"])
def test_a_yaml_1_1_scalar_name_is_not_a_name(client, skills_dir, name) -> None:
    """PyYAML reads an unquoted ``name: off`` as ``False``, so the Skill has no name."""
    write_skill(skills_dir, "scalar", skill_md(name))
    skill = listing(client)["scalar"]
    assert skill["valid"] is False
    assert [d["code"] for d in skill["diagnostics"]] == ["missing-name"]


def test_external_edits_are_visible_without_any_invalidation(client, skills_dir) -> None:
    write_skill(skills_dir, "live", skill_md("live", "one"))
    assert listing(client)["live"]["description"] == "one"
    write_skill(skills_dir, "live", skill_md("live", "two two"))
    assert listing(client)["live"]["description"] == "two two"
    (skills_dir / "live" / "SKILL.md").unlink()
    assert "live" not in listing(client)
