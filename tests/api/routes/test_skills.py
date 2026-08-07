"""Tests for /api/skills HTTP routes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import skills as skills_routes
from app.api.routes.skills import router as skills_router
from app.services import agent_fs, team_manager


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def fs_dirs(tmp_path: Path, monkeypatch):
    """Redirect AGENTS_DIR and SKILLS_DIR to an isolated tmp tree."""
    from app.core.config import settings

    agents = tmp_path / "agents"
    skills = tmp_path / "skills"
    config = tmp_path / "config"
    agents.mkdir()
    skills.mkdir()
    config.mkdir()
    monkeypatch.setattr(settings, "AGENTS_DIR", str(agents))
    monkeypatch.setattr(settings, "SKILLS_DIR", str(skills))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(config))
    from app.agent.tools.builtin import skill as skill_module

    monkeypatch.setattr(skill_module, "_iter_skill_roots", lambda: [skills])
    skill_module._discover_skills_cached.cache_clear()
    return agents, skills


@pytest.fixture
async def client(fs_dirs):
    app = FastAPI()
    app.include_router(skills_router, prefix="/api/skills")
    # Clear any team state that may linger from parallel tests
    await team_manager.stop()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await team_manager.stop()


# ── Sample skill content ───────────────────────────────────────────────────────

VALID_SKILL = """\
---
name: research
description: A research skill.
---
Do research.
"""

MISMATCHED_NAME_SKILL = """\
---
name: other
description: Mismatch.
---
Body.
"""

NON_DICT_FRONTMATTER_SKILL = """\
---
- item1
- item2
---
Body.
"""

NON_STRING_DESC_SKILL = """\
---
name: research
description: 42
---
Body.
"""

INVALID_YAML_SKILL = """\
---
name: research
description: [unclosed
---
Body.
"""

MISSING_NAME_SKILL = """\
---
description: Missing name.
---
Body.
"""

EMPTY_DESCRIPTION_SKILL = """\
---
name: research
description: ""
---
Body.
"""


# ── _parse_skill unit tests (via POST /api/skills validation) ─────────────────


@pytest.mark.asyncio
async def test_create_invalid_yaml_returns_422(client):
    resp = await client.post(
        "/api/skills",
        json={"name": "research", "content": INVALID_YAML_SKILL},
    )
    assert resp.status_code == 422
    assert "frontmatter" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_non_dict_frontmatter_returns_422(client):
    resp = await client.post(
        "/api/skills",
        json={"name": "research", "content": NON_DICT_FRONTMATTER_SKILL},
    )
    assert resp.status_code == 422
    assert "mapping" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_non_string_description_returns_422(client):
    resp = await client.post(
        "/api/skills",
        json={"name": "research", "content": NON_STRING_DESC_SKILL},
    )
    assert resp.status_code == 422
    assert "description" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_name_mismatch_returns_422(client):
    resp = await client.post(
        "/api/skills",
        json={"name": "research", "content": MISMATCHED_NAME_SKILL},
    )
    assert resp.status_code == 422
    assert "other" in resp.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content, expected",
    [
        ("Instructions without frontmatter.", "name"),
        (MISSING_NAME_SKILL, "name"),
        (EMPTY_DESCRIPTION_SKILL, "description"),
    ],
)
async def test_create_rejects_runtime_invalid_required_metadata(
    client, content, expected
):
    response = await client.post(
        "/api/skills",
        json={"name": "research", "content": content},
    )

    assert response.status_code == 422
    assert expected in response.json()["detail"].lower()


# ── GET /api/skills ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_skills_empty(client):
    resp = await client.get("/api/skills")
    assert resp.status_code == 200
    assert resp.json() == {"skills": []}


@pytest.mark.asyncio
async def test_list_skills_returns_created_skill(client):
    await client.post("/api/skills", json={"name": "research", "content": VALID_SKILL})
    resp = await client.get("/api/skills")
    assert resp.status_code == 200
    skills = resp.json()["skills"]
    assert len(skills) == 1
    assert skills[0]["name"] == "research"
    assert skills[0]["valid"] is True
    assert skills[0]["built_in"] is False
    assert skills[0]["editable"] is True
    assert skills[0]["source"] == "global-EvoFlux"


@pytest.mark.asyncio
async def test_create_and_update_skill_mode_scope(client, fs_dirs):
    _, skills_dir = fs_dirs
    created = await client.post(
        "/api/skills",
        json={
            "name": "research",
            "content": VALID_SKILL,
            "modes": ["coding"],
        },
    )

    assert created.status_code == 201
    assert created.json()["modes"] == ["coding"]
    sidecar = skills_dir / "research" / ".evoflux.json"
    assert sidecar.read_text() == '{\n  "modes": [\n    "coding"\n  ]\n}\n'
    assert all(file["path"] != ".evoflux.json" for file in created.json()["files"])

    listed = await client.get("/api/skills")
    assert listed.json()["skills"][0]["modes"] == ["coding"]

    updated = await client.put(
        "/api/skills/research",
        json={
            "name": "research",
            "content": VALID_SKILL,
            "modes": ["coding", "work"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["modes"] == ["work", "coding"]
    assert not sidecar.exists()


@pytest.mark.asyncio
async def test_builtin_runtime_settings_override_and_reset_without_bundle_write(
    client, fs_dirs, monkeypatch
):
    from app.agent.tools.builtin import skill as skill_module
    from app.core.config import settings

    builtin_root = skills_routes._builtin_skills_root()
    skill_dir = builtin_root / "self-healing"
    skill_bytes = (skill_dir / "SKILL.md").read_bytes()
    metadata_bytes = (skill_dir / "agents" / "openai.yaml").read_bytes()
    monkeypatch.setattr(skill_module, "_iter_skill_roots", lambda: [builtin_root])
    skill_module._discover_skills_cached.cache_clear()

    before = await client.get("/api/skills/self-healing", params={"mode": "work"})
    assert before.status_code == 200
    detail = before.json()
    assert detail["editable"] is False
    assert detail["settings_editable"] is True
    assert detail["settings_overridden"] is False

    updated = await client.patch(
        "/api/skills/self-healing",
        params={"mode": "work"},
        json={
            "settings_id": detail["settings_id"],
            "modes": ["coding"],
            "allow_implicit_invocation": True,
            "user_invocable": False,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["modes"] == ["coding"]
    assert updated.json()["allow_implicit_invocation"] is True
    assert updated.json()["user_invocable"] is False
    assert updated.json()["settings_overridden"] is True
    assert (skill_dir / "SKILL.md").read_bytes() == skill_bytes
    assert (skill_dir / "agents" / "openai.yaml").read_bytes() == metadata_bytes
    assert (Path(settings.EVOFLUX_CONFIG_DIR) / "skill-settings.json").is_file()

    hidden_from_work = await client.get(
        "/api/skills/self-healing", params={"mode": "work"}
    )
    visible_in_coding = await client.get(
        "/api/skills/self-healing", params={"mode": "coding"}
    )
    assert hidden_from_work.status_code == 404
    assert visible_in_coding.status_code == 200

    # Reset remains target-specific even though the override removed this
    # skill from the request's Work projection.
    reset = await client.delete(
        "/api/skills/self-healing",
        params={"mode": "work", "settings_id": detail["settings_id"]},
    )
    assert reset.status_code == 200
    assert reset.json()["modes"] == ["work", "coding"]
    assert reset.json()["allow_implicit_invocation"] is False
    assert reset.json()["user_invocable"] is True
    assert reset.json()["settings_overridden"] is False
    assert not (Path(settings.EVOFLUX_CONFIG_DIR) / "skill-settings.json").exists()


@pytest.mark.asyncio
async def test_runtime_settings_reject_stale_variant_id(client):
    created = await client.post(
        "/api/skills", json={"name": "research", "content": VALID_SKILL}
    )
    settings_id = created.json()["settings_id"]
    replacement = "0" if settings_id[-1] != "0" else "1"

    response = await client.patch(
        "/api/skills/research",
        json={
            "settings_id": f"{settings_id[:-1]}{replacement}",
            "modes": ["work"],
            "allow_implicit_invocation": False,
            "user_invocable": False,
        },
    )

    assert response.status_code == 409
    assert "changed source or precedence" in response.json()["detail"]


@pytest.mark.asyncio
async def test_body_only_update_preserves_source_modes_under_runtime_override(
    client, fs_dirs
):
    _, skills_dir = fs_dirs
    created = await client.post(
        "/api/skills",
        json={"name": "research", "content": VALID_SKILL, "modes": ["work"]},
    )
    assert created.status_code == 201
    settings_id = created.json()["settings_id"]
    sidecar = skills_dir / "research" / ".evoflux.json"
    source_modes = sidecar.read_bytes()

    overridden = await client.patch(
        "/api/skills/research",
        params={"mode": "work"},
        json={
            "settings_id": settings_id,
            "modes": ["coding"],
            "allow_implicit_invocation": False,
            "user_invocable": True,
        },
    )
    assert overridden.status_code == 200

    updated = await client.put(
        "/api/skills/research",
        params={"mode": "coding"},
        json={
            "name": "research",
            "content": VALID_SKILL.replace("Do research.", "Updated body."),
        },
    )

    assert updated.status_code == 200
    assert updated.json()["modes"] == ["coding"]
    assert updated.json()["settings_overridden"] is True
    assert sidecar.read_bytes() == source_modes


@pytest.mark.asyncio
@pytest.mark.parametrize("modes", [[], ["work", "work"], ["unsupported"]])
async def test_create_rejects_invalid_mode_scope(client, modes):
    response = await client.post(
        "/api/skills",
        json={"name": "research", "content": VALID_SKILL, "modes": modes},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_skills_includes_opencode_skill(
    client, fs_dirs, tmp_path, monkeypatch
):
    _, EVOFLUX_skills = fs_dirs
    opencode_skills = tmp_path / "home" / ".config" / "opencode" / "skills"
    skill_dir = opencode_skills / "research"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(VALID_SKILL)

    from app.agent.tools.builtin import skill as skill_module

    monkeypatch.setattr(
        skill_module, "_iter_skill_roots", lambda: [EVOFLUX_skills, opencode_skills]
    )
    monkeypatch.setattr(
        skills_routes.Path, "home", classmethod(lambda cls: tmp_path / "home")
    )
    skill_module._discover_skills_cached.cache_clear()

    resp = await client.get("/api/skills")

    assert resp.status_code == 200
    skills = resp.json()["skills"]
    assert len(skills) == 1
    assert skills[0]["name"] == "research"
    assert skills[0]["description"] == "A research skill."
    assert skills[0]["valid"] is True
    assert skills[0]["error"] is None
    assert skills[0]["built_in"] is False
    assert skills[0]["editable"] is True
    assert skills[0]["source"] == "global-opencode"
    assert skills[0]["modes"] == ["work", "coding"]


@pytest.mark.asyncio
async def test_list_skills_labels_project_EVOFLUX_source(
    client, fs_dirs, tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    project_skills = workspace / ".evoflux" / "skills"
    skill_file = project_skills / "oad" / "commit" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        "---\nname: oad/commit\ndescription: Commit workflow.\n---\nBody."
    )
    EVOFLUX_skills = fs_dirs[1]

    from app.agent.tools.builtin import skill as skill_module

    monkeypatch.setattr(
        skill_module, "_iter_skill_roots", lambda: [project_skills, EVOFLUX_skills]
    )
    monkeypatch.setattr(skill_module, "_project_root", lambda: workspace)
    skill_module._discover_skills_cached.cache_clear()

    resp = await client.get("/api/skills")

    assert resp.status_code == 200
    skills = resp.json()["skills"]
    assert len(skills) == 1
    assert skills[0]["name"] == "oad/commit"
    assert skills[0]["description"] == "Commit workflow."
    assert skills[0]["valid"] is True
    assert skills[0]["editable"] is True
    assert skills[0]["source"] == "project-EvoFlux"
    assert skills[0]["modes"] == ["work", "coding"]
    assert {item["code"] for item in skills[0]["diagnostics"]} >= {
        "legacy-name",
        "nested-legacy-skill",
    }


@pytest.mark.asyncio
async def test_list_skills_labels_project_opencode_source(
    client, fs_dirs, tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    project_skills = workspace / ".opencode" / "skills"
    skill_file = project_skills / "research" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(VALID_SKILL)
    EVOFLUX_skills = fs_dirs[1]

    from app.agent.tools.builtin import skill as skill_module

    monkeypatch.setattr(
        skill_module, "_iter_skill_roots", lambda: [project_skills, EVOFLUX_skills]
    )
    monkeypatch.setattr(skill_module, "_project_root", lambda: workspace)
    skill_module._discover_skills_cached.cache_clear()

    resp = await client.get("/api/skills")

    assert resp.status_code == 200
    assert resp.json()["skills"][0]["source"] == "project-opencode"


@pytest.mark.asyncio
async def test_workspace_catalog_matches_mode_aware_runtime_collision(
    client, fs_dirs, tmp_path
):
    _, global_skills = fs_dirs
    workspace = tmp_path / "repo"
    (workspace / ".git").mkdir(parents=True)
    project_skill = workspace / ".evoflux" / "skills" / "shared"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Coding variant.\n---\nProject coding body.\n"
    )
    (project_skill / ".evoflux.json").write_text('{"modes":["coding"]}\n')
    global_skill = global_skills / "shared"
    global_skill.mkdir()
    (global_skill / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Work variant.\n---\nGlobal work body.\n"
    )
    (global_skill / ".evoflux.json").write_text('{"modes":["work"]}\n')

    params = [("workspace", str(workspace))]
    listed = await client.get("/api/skills", params=params)
    row = next(item for item in listed.json()["skills"] if item["name"] == "shared")
    assert row["description"] == "Coding variant."
    assert row["modes"] == ["work", "coding"]
    assert {item["code"] for item in row["diagnostics"]} >= {"mode-specific-collision"}

    synthetic_update = await client.patch(
        "/api/skills/shared",
        params=params,
        json={
            "settings_id": row["settings_id"],
            "modes": ["work"],
            "allow_implicit_invocation": False,
            "user_invocable": True,
        },
    )
    assert synthetic_update.status_code == 409
    assert "Choose an explicit mode" in synthetic_update.json()["detail"]

    work = await client.get("/api/skills/shared", params=[*params, ("mode", "work")])
    coding = await client.get(
        "/api/skills/shared", params=[*params, ("mode", "coding")]
    )
    assert "Global work body" in work.json()["content"]
    assert "Project coding body" in coding.json()["content"]
    assert work.json()["settings_id"] != coding.json()["settings_id"]

    coding_update = await client.patch(
        "/api/skills/shared",
        params=[*params, ("mode", "coding")],
        json={
            "settings_id": coding.json()["settings_id"],
            "modes": ["coding"],
            "allow_implicit_invocation": False,
            "user_invocable": False,
        },
    )
    assert coding_update.status_code == 200
    assert coding_update.json()["settings_overridden"] is True

    work_after = await client.get(
        "/api/skills/shared", params=[*params, ("mode", "work")]
    )
    coding_after = await client.get(
        "/api/skills/shared", params=[*params, ("mode", "coding")]
    )
    assert work_after.json()["modes"] == ["work"]
    assert work_after.json()["allow_implicit_invocation"] is True
    assert work_after.json()["user_invocable"] is True
    assert work_after.json()["settings_overridden"] is False
    assert coding_after.json()["modes"] == ["coding"]
    assert coding_after.json()["allow_implicit_invocation"] is False
    assert coding_after.json()["user_invocable"] is False
    assert coding_after.json()["settings_overridden"] is True


@pytest.mark.asyncio
async def test_reset_targets_overridden_variant_after_lower_collision_is_revealed(
    client, fs_dirs, tmp_path
):
    _, global_skills = fs_dirs
    workspace = tmp_path / "repo"
    (workspace / ".git").mkdir(parents=True)
    project_skill = workspace / ".evoflux" / "skills" / "shared"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Project variant.\n---\nProject body.\n"
    )
    global_skill = global_skills / "shared"
    global_skill.mkdir()
    (global_skill / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Global variant.\n---\nGlobal body.\n"
    )
    (global_skill / ".evoflux.json").write_text('{"modes":["coding"]}\n')
    params = [("workspace", str(workspace)), ("mode", "coding")]

    project = await client.get("/api/skills/shared", params=params)
    assert "Project body" in project.json()["content"]
    project_settings_id = project.json()["settings_id"]
    hidden = await client.patch(
        "/api/skills/shared",
        params=params,
        json={
            "settings_id": project_settings_id,
            "modes": ["work"],
            "allow_implicit_invocation": True,
            "user_invocable": True,
        },
    )
    assert hidden.status_code == 200

    revealed = await client.get("/api/skills/shared", params=params)
    assert "Global body" in revealed.json()["content"]
    assert revealed.json()["settings_id"] != project_settings_id

    reset = await client.delete(
        "/api/skills/shared",
        params=[*params, ("settings_id", project_settings_id)],
    )
    assert reset.status_code == 200
    assert "Project body" in reset.json()["content"]
    assert reset.json()["settings_overridden"] is False

    restored = await client.get("/api/skills/shared", params=params)
    assert "Project body" in restored.json()["content"]
    assert restored.json()["settings_id"] == project_settings_id


@pytest.mark.asyncio
async def test_workspace_symlinked_skill_root_is_read_only(client, tmp_path):
    workspace = tmp_path / "repo"
    (workspace / ".agents").mkdir(parents=True)
    outside = tmp_path / "outside-skills"
    skill_dir = outside / "linked"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: linked\ndescription: Linked skill.\n---\nOriginal.\n"
    )
    (workspace / ".agents" / "skills").symlink_to(outside, target_is_directory=True)

    params = [("workspace", str(workspace)), ("mode", "coding")]
    listed = await client.get("/api/skills", params=params)
    linked = next(item for item in listed.json()["skills"] if item["name"] == "linked")
    assert linked["symlinked"] is True
    assert linked["editable"] is False

    response = await client.put(
        "/api/skills/linked",
        params=params,
        json={
            "name": "linked",
            "content": "---\nname: linked\ndescription: Changed.\n---\nChanged.\n",
        },
    )
    assert response.status_code == 403
    assert "Original" in skill_file.read_text()


@pytest.mark.asyncio
async def test_delete_opencode_skill_removes_source_file(
    client, fs_dirs, tmp_path, monkeypatch
):
    EVOFLUX_skills = fs_dirs[1]
    opencode_skills = tmp_path / "home" / ".config" / "opencode" / "skills"
    skill_file = opencode_skills / "research" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(VALID_SKILL)

    from app.agent.tools.builtin import skill as skill_module

    monkeypatch.setattr(
        skill_module, "_iter_skill_roots", lambda: [EVOFLUX_skills, opencode_skills]
    )
    monkeypatch.setattr(
        skills_routes.Path, "home", classmethod(lambda cls: tmp_path / "home")
    )
    skill_module._discover_skills_cached.cache_clear()

    resp = await client.delete("/api/skills/research")

    assert resp.status_code == 200
    assert not skill_file.exists()


@pytest.mark.asyncio
async def test_list_skills_includes_read_error(client, fs_dirs, monkeypatch):
    """A skill whose file is unreadable shows up as invalid instead of crashing."""
    _, skills_dir = fs_dirs
    # Manually create a skill directory but make read_skill raise
    (skills_dir / "broken").mkdir()
    (skills_dir / "broken" / "SKILL.md").write_text("content")

    original_open = Path.open

    def bad_open(path, *args, **kwargs):
        if path.name == "SKILL.md" and path.parent.name == "broken":
            raise OSError("permission denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", bad_open)

    resp = await client.get("/api/skills")
    assert resp.status_code == 200
    skills = resp.json()["skills"]
    broken = next(s for s in skills if s["name"] == "broken")
    assert broken["valid"] is False
    assert "permission denied" in broken["error"]


# ── GET /api/skills/{name} ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_skill_not_found_returns_404(client):
    resp = await client.get("/api/skills/missing")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_skill_bad_name_returns_400(client):
    # Names with spaces/special chars fail _validate_name → AgentFsPathError → 400
    resp = await client.get("/api/skills/bad%20name")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_skill_returns_detail(client):
    await client.post("/api/skills", json={"name": "research", "content": VALID_SKILL})
    resp = await client.get("/api/skills/research")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "research"
    assert data["description"] == "A research skill."
    assert "Do research" in data["content"]
    assert data["files"] == []


@pytest.mark.asyncio
async def test_detail_rejects_oversized_skill_without_unbounded_read(client, fs_dirs):
    _, skills_dir = fs_dirs
    skill_dir = skills_dir / "huge"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: huge\ndescription: Huge.\n---\n" + ("x" * (512 * 1024))
    )

    listed = await client.get("/api/skills")
    row = next(item for item in listed.json()["skills"] if item["name"] == "huge")
    assert row["valid"] is False
    assert row["settings_editable"] is False

    detail = await client.get("/api/skills/huge")
    assert detail.status_code == 413


@pytest.mark.asyncio
async def test_invalid_skill_rejects_runtime_settings_without_persisting(
    client, fs_dirs
):
    from app.core.config import settings

    skill_dir = fs_dirs[1] / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: broken\ndescription: [invalid\n---\nBody.\n"
    )
    listed = await client.get("/api/skills")
    row = next(item for item in listed.json()["skills"] if item["name"] == "broken")
    assert row["valid"] is False
    assert row["settings_editable"] is False

    response = await client.patch(
        "/api/skills/broken",
        json={
            "settings_id": row["settings_id"],
            "modes": ["coding"],
            "allow_implicit_invocation": False,
            "user_invocable": False,
        },
    )

    assert response.status_code == 422
    assert "Fix its bundle diagnostics" in response.json()["detail"]
    assert not (Path(settings.EVOFLUX_CONFIG_DIR) / "skill-settings.json").exists()

    scoped_detail = await client.get("/api/skills/broken", params={"mode": "coding"})
    assert scoped_detail.status_code == 200
    assert scoped_detail.json()["settings_editable"] is False
    assert scoped_detail.json()["error"] is not None

    repaired_content = (
        "---\nname: broken\ndescription: Repaired skill.\n---\nFixed body.\n"
    )
    repaired = await client.put(
        "/api/skills/broken",
        params={"mode": "coding"},
        json={"name": "broken", "content": repaired_content},
    )
    assert repaired.status_code == 200
    assert repaired.json()["error"] is None
    assert repaired.json()["settings_editable"] is True


@pytest.mark.asyncio
async def test_management_detail_prefers_invalid_winner_over_runtime_fallback(
    client, fs_dirs, tmp_path
):
    workspace = tmp_path / "repo"
    (workspace / ".git").mkdir(parents=True)
    project_skill = workspace / ".evoflux" / "skills" / "shared"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text(
        "---\nname: shared\ndescription: [invalid\n---\nBroken project body.\n"
    )
    global_skill = fs_dirs[1] / "shared"
    global_skill.mkdir()
    (global_skill / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Global fallback.\n---\nGlobal body.\n"
    )
    management_params = [("workspace", str(workspace))]
    runtime_params = [*management_params, ("mode", "coding")]

    management_list = await client.get("/api/skills", params=management_params)
    managed = next(
        item for item in management_list.json()["skills"] if item["name"] == "shared"
    )
    assert managed["valid"] is False
    assert managed["settings_editable"] is False

    management_detail = await client.get("/api/skills/shared", params=management_params)
    assert management_detail.status_code == 200
    assert "Broken project body" in management_detail.json()["content"]
    assert management_detail.json()["settings_editable"] is False
    assert management_detail.json()["error"] is not None

    runtime_list = await client.get("/api/skills", params=runtime_params)
    listed = next(
        item for item in runtime_list.json()["skills"] if item["name"] == "shared"
    )
    assert listed["description"] == "Global fallback."
    assert listed["valid"] is True

    runtime_detail = await client.get("/api/skills/shared", params=runtime_params)
    assert runtime_detail.status_code == 200
    assert "Global body" in runtime_detail.json()["content"]
    assert runtime_detail.json()["error"] is None
    assert runtime_detail.json()["settings_editable"] is True


@pytest.mark.asyncio
async def test_create_and_update_skill_bundle(client, fs_dirs):
    create = await client.post(
        "/api/skills",
        json={
            "name": "research",
            "content": VALID_SKILL,
            "files": [
                {
                    "path": "references/method.md",
                    "content": "# Method\n",
                    "encoding": "utf-8",
                },
                {
                    "path": "scripts/run.py",
                    "content": "cHJpbnQoJ29rJykK",
                    "encoding": "base64",
                },
            ],
        },
    )
    assert create.status_code == 201
    files = {file["path"]: file for file in create.json()["files"]}
    assert files["references/method.md"]["content"] == "# Method\n"
    assert files["scripts/run.py"]["content"] == "print('ok')\n"

    update = await client.put(
        "/api/skills/research",
        json={
            "name": "research",
            "content": VALID_SKILL,
            "files": [
                {
                    "path": "references/guide.md",
                    "content": "# Guide\n",
                    "encoding": "utf-8",
                }
            ],
            "deleted_files": ["references/method.md"],
        },
    )
    assert update.status_code == 200
    paths = {file["path"] for file in update.json()["files"]}
    assert paths == {"references/guide.md", "scripts/run.py"}
    skills_dir = fs_dirs[1]
    assert not (skills_dir / "research" / "references" / "method.md").exists()


@pytest.mark.asyncio
async def test_skill_bundle_rejects_traversal_and_reserved_skill_file(client):
    for path in ("../outside.md", "references\\outside.md", "nested/SKILL.md"):
        response = await client.post(
            "/api/skills",
            json={
                "name": "research",
                "content": VALID_SKILL,
                "files": [{"path": path, "content": "bad"}],
            },
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_imported_legacy_sub_skill_crud_routes_accept_slash_name(client, fs_dirs):
    content = "---\nname: git/commit\ndescription: Commit helper.\n---\nCommit body.\n"
    skill_file = fs_dirs[1] / "git" / "commit" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(content)

    detail = await client.get("/api/skills/git/commit")
    assert detail.status_code == 200
    assert detail.json()["name"] == "git/commit"

    updated = content.replace("Commit helper.", "Updated helper.")
    update = await client.put(
        "/api/skills/git/commit",
        json={"name": "git/commit", "content": updated},
    )
    assert update.status_code == 200
    assert update.json()["description"] == "Updated helper."

    delete = await client.delete("/api/skills/git/commit")
    assert delete.status_code == 200
    assert delete.json() == {"name": "git/commit"}


@pytest.mark.asyncio
async def test_nested_settings_skill_can_reset_runtime_and_delete_bundle(
    client, fs_dirs
):
    content = (
        "---\nname: foo/settings\ndescription: Legacy settings helper.\n"
        "---\nNested body.\n"
    )
    skill_file = fs_dirs[1] / "foo" / "settings" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(content)

    detail = await client.get("/api/skills/foo/settings")
    assert detail.status_code == 200
    settings_id = detail.json()["settings_id"]
    overridden = await client.patch(
        "/api/skills/foo/settings",
        json={
            "settings_id": settings_id,
            "modes": ["coding"],
            "allow_implicit_invocation": False,
            "user_invocable": False,
        },
    )
    assert overridden.status_code == 200
    assert overridden.json()["settings_overridden"] is True

    reset = await client.delete(
        "/api/skills/foo/settings", params={"settings_id": settings_id}
    )
    assert reset.status_code == 200
    assert reset.json()["settings_overridden"] is False
    assert skill_file.is_file()

    deleted = await client.delete("/api/skills/foo/settings")
    assert deleted.status_code == 200
    assert deleted.json() == {"name": "foo/settings"}
    assert not skill_file.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["GitCommit", "git_commit", "git/commit"])
async def test_create_rejects_nonportable_skill_names(client, name):
    content = f"---\nname: {name}\ndescription: Legacy identity.\n---\nBody.\n"

    response = await client.post(
        "/api/skills",
        json={"name": name, "content": content},
    )

    assert response.status_code == 422
    assert "lowercase" in response.json()["detail"]


# ── POST /api/skills ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_skill_success(client):
    resp = await client.post(
        "/api/skills", json={"name": "research", "content": VALID_SKILL}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "research"
    assert data["description"] == "A research skill."


@pytest.mark.asyncio
async def test_create_skill_conflict_returns_409(client):
    await client.post("/api/skills", json={"name": "research", "content": VALID_SKILL})
    resp = await client.post(
        "/api/skills", json={"name": "research", "content": VALID_SKILL}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_skill_bad_path_returns_400(client, monkeypatch):
    from app.services.agent_fs import AgentFsPathError

    monkeypatch.setattr(
        skills_routes,
        "_stage_skill_bundle",
        lambda *a, **kw: (_ for _ in ()).throw(AgentFsPathError("bad")),
    )
    resp = await client.post(
        "/api/skills",
        json={"name": "research", "content": VALID_SKILL},
    )
    assert resp.status_code == 400


# ── PUT /api/skills/{name} ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_skill_name_mismatch_returns_422(client):
    await client.post("/api/skills", json={"name": "research", "content": VALID_SKILL})
    resp = await client.put(
        "/api/skills/research",
        json={"name": "other", "content": VALID_SKILL},
    )
    assert resp.status_code == 422
    assert "research" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_skill_invalid_content_returns_422(client):
    await client.post("/api/skills", json={"name": "research", "content": VALID_SKILL})
    resp = await client.put(
        "/api/skills/research",
        json={"name": "research", "content": INVALID_YAML_SKILL},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_skill_rejects_empty_instruction_body(client):
    response = await client.post(
        "/api/skills",
        json={
            "name": "empty",
            "content": "---\nname: empty\ndescription: Empty workflow.\n---\n",
        },
    )

    assert response.status_code == 422
    assert "instructions must not be empty" in response.json()["detail"]


@pytest.mark.asyncio
async def test_update_skill_success(client):
    await client.post("/api/skills", json={"name": "research", "content": VALID_SKILL})
    updated = VALID_SKILL.replace("A research skill.", "Updated description.")
    resp = await client.put(
        "/api/skills/research",
        json={"name": "research", "content": updated},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Updated description."


@pytest.mark.asyncio
async def test_update_skill_bundle_is_transactional_on_invalid_resource(
    client, fs_dirs
):
    _, skills_dir = fs_dirs
    created = await client.post(
        "/api/skills",
        json={
            "name": "research",
            "content": VALID_SKILL,
            "modes": ["coding"],
            "files": [
                {
                    "path": "references/original.md",
                    "content": "original resource\n",
                }
            ],
        },
    )
    assert created.status_code == 201
    skill_dir = skills_dir / "research"
    before_skill = (skill_dir / "SKILL.md").read_bytes()
    before_resource = (skill_dir / "references" / "original.md").read_bytes()
    before_scope = (skill_dir / ".evoflux.json").read_bytes()

    response = await client.put(
        "/api/skills/research",
        json={
            "name": "research",
            "content": VALID_SKILL.replace("Do research.", "Changed body."),
            "modes": ["work"],
            "files": [
                {
                    "path": "scripts/bad.bin",
                    "content": "not valid base64!",
                    "encoding": "base64",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert (skill_dir / "SKILL.md").read_bytes() == before_skill
    assert (skill_dir / "references" / "original.md").read_bytes() == before_resource
    assert (skill_dir / ".evoflux.json").read_bytes() == before_scope
    assert not (skill_dir / "scripts" / "bad.bin").exists()


@pytest.mark.asyncio
async def test_update_enforces_limit_on_final_accumulated_bundle(
    client, fs_dirs, monkeypatch
):
    _, skills_dir = fs_dirs
    monkeypatch.setattr(agent_fs, "_MAX_SKILL_BUNDLE_BYTES", 12)
    created = await client.post(
        "/api/skills",
        json={
            "name": "research",
            "content": VALID_SKILL,
            "files": [{"path": "assets/first.txt", "content": "12345678"}],
        },
    )
    assert created.status_code == 201
    skill_dir = skills_dir / "research"
    before_skill = (skill_dir / "SKILL.md").read_bytes()

    response = await client.put(
        "/api/skills/research",
        json={
            "name": "research",
            "content": VALID_SKILL.replace("Do research.", "Changed body."),
            "files": [{"path": "assets/second.txt", "content": "abcdefgh"}],
        },
    )

    assert response.status_code == 400
    assert "Final skill bundle resources exceed" in response.json()["detail"]
    assert (skill_dir / "SKILL.md").read_bytes() == before_skill
    assert (skill_dir / "assets" / "first.txt").read_text() == "12345678"
    assert not (skill_dir / "assets" / "second.txt").exists()


@pytest.mark.asyncio
async def test_update_skill_bad_path_returns_400(client, monkeypatch):
    await client.post("/api/skills", json={"name": "research", "content": VALID_SKILL})

    def bad_write(*_args, **_kwargs):
        raise OSError("bad")

    monkeypatch.setattr(skills_routes, "_atomic_write", bad_write)
    resp = await client.put(
        "/api/skills/research",
        json={"name": "research", "content": VALID_SKILL},
    )
    assert resp.status_code == 400


# ── DELETE /api/skills/{name} ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_skill_success(client, fs_dirs):
    await client.post(
        "/api/skills",
        json={
            "name": "research",
            "content": VALID_SKILL,
            "files": [
                {
                    "path": "references/guide.md",
                    "content": "# Guide\n",
                }
            ],
        },
    )
    resp = await client.delete("/api/skills/research")
    assert resp.status_code == 200
    assert resp.json() == {"name": "research"}
    assert not (fs_dirs[1] / "research").exists()


@pytest.mark.asyncio
async def test_delete_skill_removes_runtime_override_before_recreate(client, fs_dirs):
    created = await client.post(
        "/api/skills",
        json={"name": "research", "content": VALID_SKILL, "modes": ["coding"]},
    )
    assert created.status_code == 201
    settings_id = created.json()["settings_id"]

    updated = await client.patch(
        "/api/skills/research",
        json={
            "settings_id": settings_id,
            "modes": ["work"],
            "allow_implicit_invocation": False,
            "user_invocable": False,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["settings_overridden"] is True

    deleted = await client.delete("/api/skills/research")
    assert deleted.status_code == 200
    settings_path = fs_dirs[1].parent / "config" / "skill-settings.json"
    assert not settings_path.exists() or settings_id not in settings_path.read_text()

    recreated = await client.post(
        "/api/skills",
        json={"name": "research", "content": VALID_SKILL, "modes": ["coding"]},
    )
    assert recreated.status_code == 201
    assert recreated.json()["modes"] == ["coding"]
    assert recreated.json()["allow_implicit_invocation"] is True
    assert recreated.json()["user_invocable"] is True
    assert recreated.json()["settings_overridden"] is False


@pytest.mark.asyncio
async def test_delete_builtin_skill_returns_403(client, monkeypatch):
    from app.agent.tools.builtin import skill as skill_module

    monkeypatch.setattr(
        skill_module,
        "_iter_skill_roots",
        lambda: [skills_routes._builtin_skills_root()],
    )
    skill_module._discover_skills_cached.cache_clear()

    resp = await client.delete("/api/skills/self-healing")
    assert resp.status_code == 403
    assert "read-only" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_skill_not_found_returns_404(client):
    resp = await client.delete("/api/skills/missing")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_skill_bad_path_returns_400(client, monkeypatch):
    await client.post("/api/skills", json={"name": "research", "content": VALID_SKILL})

    def bad_delete(*_args, **_kwargs):
        raise OSError("bad")

    monkeypatch.setattr(skills_routes, "_delete_skill_bundle", bad_delete)
    resp = await client.delete("/api/skills/research")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_symlinked_skill_is_read_only_and_cannot_escape_crud(
    client, fs_dirs, tmp_path
):
    skills_root = fs_dirs[1]
    outside = tmp_path / "outside-target"
    outside.mkdir()
    outside_skill = outside / "SKILL.md"
    outside_skill.write_text(
        "---\nname: linked\ndescription: Linked external skill.\n---\nOutside body."
    )
    (skills_root / "linked").symlink_to(outside, target_is_directory=True)
    from app.agent.tools.builtin import skill as skill_module

    skill_module._discover_skills_cached.cache_clear()

    listed = await client.get("/api/skills")
    row = next(item for item in listed.json()["skills"] if item["name"] == "linked")
    assert row["symlinked"] is True
    assert row["editable"] is False

    update = await client.put(
        "/api/skills/linked",
        json={
            "name": "linked",
            "content": "---\nname: linked\ndescription: Changed.\n---\nChanged.",
        },
    )
    delete = await client.delete("/api/skills/linked")

    assert update.status_code == 403
    assert delete.status_code == 403
    assert "Outside body." in outside_skill.read_text()


# ── Cache invalidation — no team reload, drift detection picks up changes ─────


@pytest.mark.asyncio
async def test_create_skill_invalidates_cache_without_reloading_team(
    client, monkeypatch, fs_dirs
):
    """Skill mutations must invalidate the discovery cache but never reload the team.

    Mid-turn team reloads tear down in-flight tool execution.  Agents
    instead pick up new/updated skills at the start of their next turn
    via the config-stamp drift check.
    """
    invalidated: list[bool] = []
    reload_called: list[bool] = []

    monkeypatch.setattr(
        team_manager,
        "invalidate_skill_cache",
        lambda: invalidated.append(True),
    )
    # Sentinel: if the route accidentally re-introduces a reload call,
    # this will record it.
    monkeypatch.setattr(
        team_manager,
        "reload",
        AsyncMock(side_effect=lambda: reload_called.append(True)),
    )

    resp = await client.post(
        "/api/skills", json={"name": "research", "content": VALID_SKILL}
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "research"
    assert invalidated == [True], "skill cache must be invalidated"
    assert reload_called == [], "team must NOT be reloaded mid-turn"
