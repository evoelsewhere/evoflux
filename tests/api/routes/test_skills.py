"""Tests for the ``/api/skills`` routes (Agent Skills management)."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.agent.skills import registry
from app.agent.skills.registry import SkillRoot, invalidate_skill_cache
from app.api.routes.skills import router as skills_router
from app.conductor.models import ManagedResourceProvider
from app.core.skill_settings import disabled_skill_names, skill_settings_path
from app.services import skills_service, team_manager


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def roots(tmp_path: Path, monkeypatch) -> dict[str, Path]:
    """Isolate every skills root: user, home, plugin and built-in."""
    from app.core.config import settings
    import app.plugin_platform.skills as plugin_skills

    user = tmp_path / "config" / "skills"
    home = tmp_path / "home"
    builtin = tmp_path / "builtin"
    plugin = tmp_path / "plugin" / "skills"
    for path in (user, home, builtin, plugin):
        path.mkdir(parents=True)
    monkeypatch.setattr(settings, "SKILLS_DIR", str(user))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(registry, "builtin_skills_dir", lambda: builtin)
    monkeypatch.setattr(
        plugin_skills,
        "plugin_skill_roots",
        lambda: [SkillRoot(plugin, "plugin", plugin_id="demo-plugin")],
    )
    monkeypatch.setattr(skills_service, "managed_resource_providers", lambda: {})
    invalidate_skill_cache()
    yield {"user": user, "home": home, "builtin": builtin, "plugin": plugin}
    invalidate_skill_cache()


@pytest.fixture
async def client(roots):
    app = FastAPI()
    app.include_router(skills_router, prefix="/api/skills")
    await team_manager.stop()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await team_manager.stop()


def skill_text(
    name: str, description: str = "Does research on a topic.", **extra
) -> str:
    lines = [f"name: {name}", f"description: {description}"]
    lines.extend(f"{key}: {value}" for key, value in extra.items())
    return "---\n" + "\n".join(lines) + "\n---\n\nFollow these steps.\n"


def write_skill(root: Path, name: str, content: str | None = None) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        content if content is not None else skill_text(name),
        encoding="utf-8",
        newline="",
    )
    return directory


def _provider() -> ManagedResourceProvider:
    return ManagedResourceProvider(
        project_id="project-1",
        project_name="Platform Core",
        resource_id="skill-1",
        version_id="skill-version-3",
        version="0.3.0",
        observed_state="applied",
    )


# ── List ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_every_source_sorted_with_metadata(client, roots):
    write_skill(roots["user"], "research")
    (roots["user"] / "research" / "notes.md").write_text("n", encoding="utf-8")
    write_skill(roots["builtin"], "pdf-tools")
    write_skill(roots["plugin"], "deploy")
    write_skill(roots["user"], "broken", "---\nname: broken\n---\n\nBody\n")

    response = await client.get("/api/skills")

    assert response.status_code == 200
    rows = response.json()["skills"]
    assert [row["name"] for row in rows] == [
        "broken",
        "deploy",
        "pdf-tools",
        "research",
    ]
    by_name = {row["name"]: row for row in rows}
    research = by_name["research"]
    assert research["source"] == "user"
    assert research["editable"] is True
    assert research["valid"] is True
    assert research["enabled"] is True
    assert research["resource_count"] == 1
    assert research["location"] == str(
        (roots["user"] / "research" / "SKILL.md").absolute()
    )
    assert by_name["deploy"]["source"] == "plugin"
    assert by_name["deploy"]["plugin_id"] == "demo-plugin"
    assert by_name["deploy"]["editable"] is False
    assert by_name["pdf-tools"]["source"] == "builtin"
    assert by_name["pdf-tools"]["editable"] is False
    broken = by_name["broken"]
    assert broken["valid"] is False
    assert any(item["code"] == "missing-description" for item in broken["diagnostics"])
    assert "mode" not in research and "modes" not in research


@pytest.mark.asyncio
async def test_list_reports_frontmatter_fields_and_shadowing(client, roots):
    write_skill(
        roots["user"],
        "research",
        skill_text(
            "research",
            license="MIT",
            compatibility="Needs git",
            **{"allowed-tools": "read shell", "disable-model-invocation": "true"},
        ),
    )
    write_skill(roots["builtin"], "research")

    rows = (await client.get("/api/skills")).json()["skills"]

    [row] = rows
    assert row["source"] == "user"
    assert row["license"] == "MIT"
    assert row["compatibility"] == "Needs git"
    assert row["allowed_tools"] == "read shell"
    assert row["model_invocable"] is False
    assert row["user_invocable"] is True
    assert row["shadowed_paths"] == [
        str((roots["builtin"] / "research" / "SKILL.md").absolute())
    ]


@pytest.mark.asyncio
async def test_list_includes_project_skills_for_workspace(client, roots, tmp_path):
    workspace = tmp_path / "repo"
    (workspace / ".git").mkdir(parents=True)
    write_skill(workspace / ".agents" / "skills", "project-flow")
    write_skill(roots["user"], "project-flow", skill_text("project-flow", "User copy."))

    without = (await client.get("/api/skills")).json()["skills"]
    with_workspace = (
        await client.get("/api/skills", params={"workspace": str(workspace)})
    ).json()["skills"]

    assert [row["source"] for row in without] == ["user"]
    [row] = with_workspace
    assert row["source"] == "project"
    assert row["editable"] is True
    assert row["description"] == "Does research on a topic."


@pytest.mark.asyncio
async def test_list_rejects_missing_workspace(client, tmp_path):
    response = await client.get(
        "/api/skills", params={"workspace": str(tmp_path / "missing")}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_skips_nested_skill_files(client, roots):
    directory = write_skill(roots["user"], "suite")
    write_skill(directory / "references", "inner")

    rows = (await client.get("/api/skills")).json()["skills"]

    assert [row["name"] for row in rows] == ["suite"]
    assert rows[0]["resource_count"] == 1


@pytest.mark.asyncio
async def test_list_marks_conductor_managed_skill_read_only(client, roots, monkeypatch):
    write_skill(roots["user"], "governed")
    monkeypatch.setattr(
        skills_service,
        "managed_resource_providers",
        lambda: {("skill", "governed"): _provider()},
    )

    [row] = (await client.get("/api/skills")).json()["skills"]

    assert row["editable"] is False
    assert row["provider"]["project_name"] == "Platform Core"


@pytest.mark.asyncio
async def test_managed_provenance_ignores_shadowing_project_skill(
    client, roots, monkeypatch, tmp_path
):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    write_skill(roots["user"], "governed")
    write_skill(workspace / ".evoflux" / "skills", "governed")
    monkeypatch.setattr(
        skills_service,
        "managed_resource_providers",
        lambda: {("skill", "governed"): _provider()},
    )

    [row] = (
        await client.get("/api/skills", params={"workspace": str(workspace)})
    ).json()["skills"]

    assert row["source"] == "project"
    assert row["provider"] is None
    assert row["editable"] is True


# ── Detail ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detail_returns_content_and_bundle_files(client, roots):
    directory = write_skill(roots["user"], "research")
    (directory / "references").mkdir()
    (directory / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (directory / "logo.bin").write_bytes(b"\x00\x01\x02")

    response = await client.get("/api/skills/research")

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == skill_text("research")
    files = {item["path"]: item for item in body["files"]}
    assert files["references/guide.md"]["content"] == "# Guide\n"
    assert files["references/guide.md"]["editable"] is True
    assert files["logo.bin"]["content"] is None
    assert files["logo.bin"]["editable"] is False
    assert body["bundle_truncated"] is False
    assert body["resource_count"] == 2


@pytest.mark.asyncio
async def test_detail_of_builtin_marks_files_read_only(client, roots):
    directory = write_skill(roots["builtin"], "pdf-tools")
    (directory / "forms.md").write_text("forms", encoding="utf-8")

    body = (await client.get("/api/skills/pdf-tools")).json()

    assert body["editable"] is False
    assert body["files"][0]["editable"] is False


@pytest.mark.asyncio
async def test_detail_unknown_skill_is_404(client):
    assert (await client.get("/api/skills/missing")).status_code == 404


@pytest.mark.asyncio
async def test_detail_oversized_skill_is_413(client, roots):
    directory = roots["user"] / "huge"
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        skill_text("huge") + "x" * (600 * 1024), encoding="utf-8"
    )

    assert (await client.get("/api/skills/huge")).status_code == 413


# ── Create ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_writes_bundle_in_user_root(client, roots, monkeypatch):
    calls: list[int] = []
    original = team_manager.invalidate_skill_cache
    monkeypatch.setattr(
        team_manager,
        "invalidate_skill_cache",
        lambda: (calls.append(1), original())[1],
    )
    payload = {
        "name": "research",
        "content": skill_text("research"),
        "files": [
            {"path": "references/guide.md", "content": "# Guide\n"},
            {
                "path": "assets/logo.bin",
                "content": base64.b64encode(b"\x00\x01").decode(),
                "encoding": "base64",
            },
        ],
    }

    response = await client.post("/api/skills", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "research"
    assert body["source"] == "user"
    assert body["editable"] is True
    assert sorted(item["path"] for item in body["files"]) == [
        "assets/logo.bin",
        "references/guide.md",
    ]
    directory = roots["user"] / "research"
    assert (directory / "SKILL.md").read_text(encoding="utf-8") == skill_text(
        "research"
    )
    assert (directory / "assets" / "logo.bin").read_bytes() == b"\x00\x01"
    assert not (directory / ".evoflux.json").exists()
    assert calls == [1]
    listed = (await client.get("/api/skills")).json()["skills"]
    assert [row["name"] for row in listed] == ["research"]


@pytest.mark.asyncio
async def test_create_existing_skill_is_409(client, roots):
    write_skill(roots["user"], "research")

    response = await client.post(
        "/api/skills", json={"name": "research", "content": skill_text("research")}
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_into_non_empty_directory_is_409(client, roots):
    (roots["user"] / "research").mkdir()
    (roots["user"] / "research" / "stray.txt").write_text("x", encoding="utf-8")

    response = await client.post(
        "/api/skills", json={"name": "research", "content": skill_text("research")}
    )

    assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    ["Research", "my_skill", "-lead", "a--b", "claude-helper", "x" * 65, "a/b", ".."],
)
async def test_create_rejects_non_spec_names(client, roots, name):
    response = await client.post(
        "/api/skills", json={"name": name, "content": skill_text(name)}
    )

    assert response.status_code == 422
    assert not any(roots["user"].iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "fragment"),
    [
        ("no frontmatter\n", "frontmatter"),
        ("---\n- a\n- b\n---\n\nBody\n", "mapping"),
        ("---\nname: research\ndescription: [unclosed\n---\n\nBody\n", "yaml"),
        ("---\ndescription: Missing name.\n---\n\nBody\n", "name"),
        ('---\nname: research\ndescription: ""\n---\n\nBody\n', "description"),
        ("---\nname: research\ndescription: Fine.\n---\n", "empty"),
        (skill_text("other"), "does not match"),
        (skill_text("research", "Uses <b>tags</b>."), "xml"),
        (skill_text("research", "d" * 1025), "exceeds"),
        (skill_text("research", modes="[work]"), "not supported"),
        (skill_text("research", metadata="{a: 1}"), "metadata"),
    ],
)
async def test_create_validates_strictly(client, roots, content, fragment):
    response = await client.post(
        "/api/skills", json={"name": "research", "content": content}
    )

    assert response.status_code == 422, response.text
    assert fragment in response.json()["detail"].lower()
    assert not (roots["user"] / "research").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["../escape.md", "/abs.md", "nested/SKILL.md", "SKILL.md", "a\\b.md", ""]
)
async def test_create_rejects_unsafe_bundle_paths(client, roots, path):
    response = await client.post(
        "/api/skills",
        json={
            "name": "research",
            "content": skill_text("research"),
            "files": [{"path": path, "content": "x"}],
        },
    )

    assert response.status_code == 400
    assert not (roots["user"] / "research").exists()
    assert not (roots["user"] / "escape.md").exists()


@pytest.mark.asyncio
async def test_create_rejects_invalid_base64_without_partial_bundle(client, roots):
    response = await client.post(
        "/api/skills",
        json={
            "name": "research",
            "content": skill_text("research"),
            "files": [{"path": "a.bin", "content": "***", "encoding": "base64"}],
        },
    )

    assert response.status_code == 400
    assert list(roots["user"].iterdir()) == []


# ── Update ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_replaces_content_and_applies_file_changes(client, roots):
    directory = write_skill(roots["user"], "research")
    (directory / "old.md").write_text("old", encoding="utf-8")
    (directory / "keep.md").write_text("keep", encoding="utf-8")
    new_content = skill_text("research", "Researches topics in depth.")

    response = await client.put(
        "/api/skills/research",
        json={
            "content": new_content,
            "files": [{"path": "references/new.md", "content": "new"}],
            "deleted_files": ["old.md"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["description"] == "Researches topics in depth."
    assert body["content"] == new_content
    assert sorted(item["path"] for item in body["files"]) == [
        "keep.md",
        "references/new.md",
    ]
    assert not (directory / "old.md").exists()
    assert (directory / "SKILL.md").read_text(encoding="utf-8") == new_content


@pytest.mark.asyncio
async def test_update_project_skill_in_place(client, tmp_path):
    workspace = tmp_path / "repo"
    directory = write_skill(workspace / ".claude" / "skills", "flow")
    new_content = skill_text("flow", "Runs the flow.")

    response = await client.put(
        "/api/skills/flow",
        params={"workspace": str(workspace)},
        json={"content": new_content},
    )

    assert response.status_code == 200, response.text
    assert response.json()["source"] == "project"
    assert (directory / "SKILL.md").read_text(encoding="utf-8") == new_content


@pytest.mark.asyncio
async def test_update_requires_matching_frontmatter_name(client, roots):
    write_skill(roots["user"], "research")

    response = await client.put(
        "/api/skills/research", json={"content": skill_text("other")}
    )

    assert response.status_code == 422
    assert (roots["user"] / "research" / "SKILL.md").read_text(
        encoding="utf-8"
    ) == skill_text("research")


@pytest.mark.asyncio
async def test_update_invalid_content_leaves_bundle_untouched(client, roots):
    directory = write_skill(roots["user"], "research")
    (directory / "keep.md").write_text("keep", encoding="utf-8")

    response = await client.put(
        "/api/skills/research",
        json={
            "content": "---\nname: research\n---\n\nBody\n",
            "deleted_files": ["keep.md"],
        },
    )

    assert response.status_code == 422
    assert (directory / "keep.md").exists()


@pytest.mark.asyncio
async def test_update_rejects_traversal_in_deleted_files(client, roots):
    write_skill(roots["user"], "research")
    victim = roots["user"] / "victim.md"
    victim.write_text("x", encoding="utf-8")

    response = await client.put(
        "/api/skills/research",
        json={"content": skill_text("research"), "deleted_files": ["../victim.md"]},
    )

    assert response.status_code == 400
    assert victim.exists()


@pytest.mark.asyncio
async def test_update_builtin_and_plugin_are_403(client, roots):
    write_skill(roots["builtin"], "pdf-tools")
    write_skill(roots["plugin"], "deploy")

    builtin = await client.put(
        "/api/skills/pdf-tools", json={"content": skill_text("pdf-tools")}
    )
    plugin = await client.put(
        "/api/skills/deploy", json={"content": skill_text("deploy")}
    )

    assert builtin.status_code == 403
    assert plugin.status_code == 403


@pytest.mark.asyncio
async def test_update_symlinked_skill_is_403(client, roots, tmp_path):
    target = write_skill(tmp_path / "elsewhere", "linked")
    try:
        (roots["user"] / "linked").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available")

    listed = (await client.get("/api/skills")).json()["skills"]
    response = await client.put(
        "/api/skills/linked", json={"content": skill_text("linked")}
    )

    assert listed[0]["symlinked"] is True
    assert listed[0]["editable"] is False
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_managed_skill_is_403(client, roots, monkeypatch):
    write_skill(roots["user"], "governed")
    monkeypatch.setattr(
        skills_service,
        "managed_resource_providers",
        lambda: {("skill", "governed"): _provider()},
    )

    response = await client.put(
        "/api/skills/governed", json={"content": skill_text("governed")}
    )

    assert response.status_code == 403
    assert "Platform Core" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_unknown_skill_is_404(client):
    response = await client.put(
        "/api/skills/missing", json={"content": skill_text("missing")}
    )
    assert response.status_code == 404


# ── Enable / disable ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disable_and_enable_user_skill(client, roots):
    write_skill(roots["user"], "research")

    disabled = await client.patch("/api/skills/research", json={"enabled": False})

    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled_skill_names() == frozenset({"research"})
    payload = json.loads(skill_settings_path().read_text(encoding="utf-8"))
    assert payload == {"version": 2, "disabled": ["research"]}
    listed = (await client.get("/api/skills")).json()["skills"]
    assert listed[0]["enabled"] is False

    enabled = await client.patch("/api/skills/research", json={"enabled": True})

    assert enabled.json()["enabled"] is True
    assert disabled_skill_names() == frozenset()


@pytest.mark.asyncio
async def test_read_only_skills_can_be_toggled(client, roots, monkeypatch):
    write_skill(roots["builtin"], "pdf-tools")
    write_skill(roots["plugin"], "deploy")
    write_skill(roots["user"], "governed")
    monkeypatch.setattr(
        skills_service,
        "managed_resource_providers",
        lambda: {("skill", "governed"): _provider()},
    )

    for name in ("pdf-tools", "deploy", "governed"):
        response = await client.patch(f"/api/skills/{name}", json={"enabled": False})
        assert response.status_code == 200, name
        assert response.json()["enabled"] is False
        assert response.json()["editable"] is False

    assert disabled_skill_names() == frozenset({"pdf-tools", "deploy", "governed"})


@pytest.mark.asyncio
async def test_toggle_invalid_skill_is_allowed(client, roots):
    write_skill(roots["user"], "broken", "---\nname: broken\n---\n\nBody\n")

    response = await client.patch("/api/skills/broken", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["valid"] is False


@pytest.mark.asyncio
async def test_toggle_unknown_skill_is_404(client):
    response = await client.patch("/api/skills/missing", json={"enabled": False})
    assert response.status_code == 404


# ── Delete ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_removes_bundle_and_disabled_entry(client, roots):
    directory = write_skill(roots["user"], "research")
    (directory / "references").mkdir()
    (directory / "references" / "guide.md").write_text("g", encoding="utf-8")
    await client.patch("/api/skills/research", json={"enabled": False})

    response = await client.delete("/api/skills/research")

    assert response.status_code == 200
    assert response.json() == {"name": "research"}
    assert not directory.exists()
    assert disabled_skill_names() == frozenset()
    assert (await client.get("/api/skills")).json()["skills"] == []


@pytest.mark.asyncio
async def test_delete_reveals_shadowed_skill(client, roots):
    write_skill(roots["user"], "research")
    write_skill(roots["builtin"], "research")

    await client.delete("/api/skills/research")

    [row] = (await client.get("/api/skills")).json()["skills"]
    assert row["source"] == "builtin"


@pytest.mark.asyncio
async def test_delete_read_only_skills_is_403(client, roots, monkeypatch):
    write_skill(roots["builtin"], "pdf-tools")
    write_skill(roots["plugin"], "deploy")
    managed = write_skill(roots["user"], "governed")
    monkeypatch.setattr(
        skills_service,
        "managed_resource_providers",
        lambda: {("skill", "governed"): _provider()},
    )

    for name in ("pdf-tools", "deploy", "governed"):
        assert (await client.delete(f"/api/skills/{name}")).status_code == 403

    assert (roots["builtin"] / "pdf-tools").exists()
    assert managed.exists()


@pytest.mark.asyncio
async def test_delete_unknown_skill_is_404(client):
    assert (await client.delete("/api/skills/missing")).status_code == 404


@pytest.mark.asyncio
async def test_mutations_invalidate_skill_cache(client, roots, monkeypatch):
    calls: list[str] = []
    original = team_manager.invalidate_skill_cache

    def spy() -> None:
        calls.append("invalidate")
        original()

    monkeypatch.setattr(team_manager, "invalidate_skill_cache", spy)
    await client.post(
        "/api/skills", json={"name": "research", "content": skill_text("research")}
    )
    await client.put(
        "/api/skills/research", json={"content": skill_text("research", "Updated.")}
    )
    await client.patch("/api/skills/research", json={"enabled": False})
    await client.delete("/api/skills/research")

    assert calls == ["invalidate"] * 4
