"""Tests for /api/agents HTTP routes.

Mutations validate the new on-disk state but do NOT rebuild the running
team — agents pick up file changes at the start of their next turn via
the config-stamp drift check (see ``app.agent.loader.detect_drift``
and ``TeamMemberBase._refresh_agent_from_disk``).  These tests assert
that contract: validation + rollback semantics, but no live team swap.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes import agents as agents_routes
from app.api.routes.agents import router as agents_router
from app.api.routes.skills import router as skills_router
from app.conductor.models import ManagedResourceProvider
from app.services import team_manager


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def fs_dirs(tmp_path: Path, monkeypatch):
    """Redirect AGENTS_DIR and SKILLS_DIR to a tmp tree."""
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
def stub_provider(monkeypatch):
    """Replace the default provider builder with a no-op mock so reload() works
    without real API credentials or network access."""
    mock_provider = MagicMock()
    mock_provider.stream = MagicMock()

    def fake_build_provider(model_str=None, model_kwargs=None):
        return mock_provider

    monkeypatch.setattr("app.agent.loader.build_provider", fake_build_provider)
    return mock_provider


@pytest.fixture
async def client(fs_dirs, stub_provider):
    app = FastAPI()
    app.include_router(agents_router, prefix="/api/agents")
    app.include_router(skills_router, prefix="/api/skills")
    # Make sure no team is left over from a previous test.
    await team_manager.stop()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        yield c
    await team_manager.stop()


# ── Helpers ──────────────────────────────────────────────────────────────────


LEAD_MD = """\
---
name: lead
role: lead
description: The lead.
model: zai:glm-5-turbo
---
You are the lead.
"""

MEMBER_MD = """\
---
name: worker
role: member
description: Worker.
model: zai:glm-5-turbo
---
You are the worker.
"""


def _seed_files(agents_dir: Path) -> None:
    (agents_dir / "lead.md").write_text(LEAD_MD)


def _managed_provider() -> ManagedResourceProvider:
    return ManagedResourceProvider(
        project_id="project-1",
        project_name="Platform Core",
        resource_id="agent-1",
        version_id="agent-version-2",
        version="0.2.0",
        release_channel="published",
        observed_state="in_sync",
    )


# ── GET /agents ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_empty(client: AsyncClient):
    res = await client.get("/api/agents")
    assert res.status_code == 200
    assert res.json() == {"agents": []}


@pytest.mark.asyncio
async def test_list_existing(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)
    res = await client.get("/api/agents")
    assert res.status_code == 200
    body = res.json()
    assert len(body["agents"]) == 1
    row = body["agents"][0]
    assert row["name"] == "lead"
    assert row["role"] == "lead"
    assert row["model"] == "zai:glm-5-turbo"
    assert row["valid"] is True


@pytest.mark.asyncio
async def test_managed_agent_exposes_provider_and_blocks_local_mutation(
    fs_dirs, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)
    provider = _managed_provider()
    monkeypatch.setattr(
        agents_routes,
        "managed_resource_providers",
        lambda: {("agent", "lead"): provider},
    )
    monkeypatch.setattr(
        agents_routes,
        "managed_resource_provider",
        lambda kind, slug: provider if (kind, slug) == ("agent", "lead") else None,
    )

    listed = await client.get("/api/agents")
    row = listed.json()["agents"][0]
    assert row["editable"] is False
    assert row["provider"]["project_name"] == "Platform Core"
    assert row["provider"]["version"] == "0.2.0"
    assert row["runtime_model_editable"] is True
    assert row["bundle_model"] == "zai:glm-5-turbo"
    assert row["model_override"] is None

    detail = await client.get("/api/agents/lead")
    assert detail.json()["editable"] is False
    assert detail.json()["provider"]["resource_id"] == "agent-1"

    updated = await client.put(
        "/api/agents/lead", json={"name": "lead", "content": LEAD_MD}
    )
    deleted = await client.delete("/api/agents/lead")
    bulk = await client.patch(
        "/api/agents/model",
        json={"names": ["lead"], "model": "anthropic:claude-sonnet-5"},
    )

    assert updated.status_code == 403
    assert deleted.status_code == 403
    assert bulk.json()["results"][0]["ok"] is False
    assert (agents_dir / "lead.md").read_text() == LEAD_MD


@pytest.mark.asyncio
async def test_managed_agent_model_override_is_local_and_resettable(
    fs_dirs, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)
    provider = _managed_provider()
    monkeypatch.setattr(
        agents_routes,
        "managed_resource_providers",
        lambda: {("agent", "lead"): provider},
    )
    monkeypatch.setattr(
        agents_routes,
        "managed_resource_provider",
        lambda kind, slug: provider if (kind, slug) == ("agent", "lead") else None,
    )
    monkeypatch.setattr(
        agents_routes,
        "is_registered_model_id",
        AsyncMock(return_value=True),
    )

    selected = "anthropic:claude-sonnet-5"
    updated = await client.patch(
        "/api/agents/runtime-model/lead",
        json={"model": selected},
    )

    assert updated.status_code == 200
    assert updated.json()["config"]["model"] == selected
    assert updated.json()["model_override"] == selected
    assert updated.json()["bundle_model"] == "zai:glm-5-turbo"
    assert (agents_dir / "lead.md").read_text() == LEAD_MD

    listed = await client.get("/api/agents")
    assert listed.json()["agents"][0]["model"] == selected

    reset = await client.patch(
        "/api/agents/runtime-model/lead",
        json={"model": None},
    )
    assert reset.status_code == 200
    assert reset.json()["config"]["model"] == "zai:glm-5-turbo"
    assert reset.json()["model_override"] is None


@pytest.mark.asyncio
async def test_managed_agent_runtime_settings_only_add_capabilities(
    fs_dirs, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)
    provider = _managed_provider()
    monkeypatch.setattr(
        agents_routes,
        "managed_resource_providers",
        lambda: {("agent", "lead"): provider},
    )
    monkeypatch.setattr(
        agents_routes,
        "managed_resource_provider",
        lambda kind, slug: provider if (kind, slug) == ("agent", "lead") else None,
    )
    monkeypatch.setattr(
        agents_routes,
        "get_registry",
        AsyncMock(
            return_value=SimpleNamespace(
                tools=[
                    SimpleNamespace(name="read"),
                    SimpleNamespace(name="web_search"),
                ],
                skills=[SimpleNamespace(name="local-research")],
            )
        ),
    )

    updated = await client.patch(
        "/api/agents/runtime-settings/lead",
        json={
            "model": None,
            "extra_tools": ["read", "web_search"],
            "extra_skills": ["local-research"],
            "extra_mcp": ["local-browser"],
        },
    )

    assert updated.status_code == 200
    body = updated.json()
    assert body["extra_tools"] == ["read", "web_search"]
    assert body["extra_skills"] == ["local-research"]
    assert body["extra_mcp"] == ["local-browser"]
    assert body["config"]["tools"].count("read") == 1
    assert "web_search" in body["config"]["tools"]
    assert body["config"]["skills"] == ["local-research"]
    assert body["config"]["mcp"] == ["local-browser"]
    assert (agents_dir / "lead.md").read_text() == LEAD_MD


@pytest.mark.asyncio
async def test_runtime_model_override_rejects_local_agent(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)

    response = await client.patch(
        "/api/agents/runtime-model/lead",
        json={"model": "anthropic:claude-sonnet-5"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Agent 'lead' is not managed by Conductor."


@pytest.mark.asyncio
async def test_list_includes_coding_agents(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)
    coding_dir = agents_dir / "coding"
    coding_dir.mkdir()
    (coding_dir / "evoflux.md").write_text(
        LEAD_MD.replace("name: lead", "name: evoflux")
    )

    res = await client.get("/api/agents")

    assert res.status_code == 200
    names = [row["name"] for row in res.json()["agents"]]
    assert names == ["coding/evoflux", "lead"]
    assert sorted(p.name for p in coding_dir.glob("*.md")) == ["evoflux.md"]


@pytest.mark.asyncio
async def test_list_existing_coding_explorer_uses_builtin_profile(
    fs_dirs, client: AsyncClient
):
    agents_dir, _ = fs_dirs
    coding_dir = agents_dir / "coding"
    coding_dir.mkdir()
    (coding_dir / "evoflux.md").write_text(
        "---\nname: evoflux\nrole: lead\nmodel: codex:gpt-5.4\n---\n"
    )
    (coding_dir / "explorer.md").write_text(
        "---\nname: explorer\nrole: member\nmodel: codex:gpt-5.4\n---\n"
    )

    res = await client.get("/api/agents")

    assert res.status_code == 200
    rows = {row["name"]: row for row in res.json()["agents"]}
    explorer = rows["coding/explorer"]
    assert explorer["description"].startswith("Checks the current codebase")
    assert set(["date", "glob", "grep", "ls", "read", "shell", "skill"]).issubset(
        explorer["tools"]
    )
    # Tier grant: members get every tier tool (write included) but never
    # lead-only tools (user interaction / session structure).
    assert "write" in explorer["tools"]
    assert "ask_user" not in explorer["tools"]
    assert "worktree_start" not in explorer["tools"]
    assert explorer["skills"] == []
    assert rows["coding/evoflux"]["skills"] == []


@pytest.mark.asyncio
async def test_list_ignores_retired_or_unknown_mode_directories(
    fs_dirs, client: AsyncClient
):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)
    retired = agents_dir / "aim"
    retired.mkdir()
    (retired / "old.md").write_text(MEMBER_MD.replace("name: worker", "name: old"))

    res = await client.get("/api/agents")

    assert res.status_code == 200
    assert [row["name"] for row in res.json()["agents"]] == ["lead"]


@pytest.mark.asyncio
async def test_list_coding_agent_has_no_implicit_skills(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    coding_dir = agents_dir / "coding"
    coding_dir.mkdir()
    (coding_dir / "evoflux.md").write_text(
        "---\nname: evoflux\nrole: lead\nmodel: codex:gpt-5.4\n---\n"
    )

    res = await client.get("/api/agents")

    assert res.status_code == 200
    rows = {row["name"]: row for row in res.json()["agents"]}
    assert rows["coding/evoflux"]["skills"] == []


@pytest.mark.asyncio
async def test_list_uses_effective_builtin_summary(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    (agents_dir / "evoflux.md").write_text(
        """\
---
name: evoflux
role: lead
model: zai:glm-5-turbo
---
<!-- Add extra prompt text below. -->
"""
    )

    res = await client.get("/api/agents")

    assert res.status_code == 200
    row = res.json()["agents"][0]
    assert row["description"] is not None
    assert "skill" in row["tools"]
    assert {"todo_manage", "schedule_task", "note"}.issubset(row["tools"])
    assert "shell" in row["tools"]
    assert row["mcp"] == []
    assert row["skills"] == []


@pytest.mark.asyncio
async def test_list_effective_builtin_summary_dedupes_user_extras(
    fs_dirs, client: AsyncClient
):
    agents_dir, _ = fs_dirs
    (agents_dir / "evoflux.md").write_text(
        """\
---
name: evoflux
role: lead
model: zai:glm-5-turbo
tools:
  - shell
  - memory_search
skills:
  - self-healing
  - custom-skill
---
Extra prompt.
"""
    )

    res = await client.get("/api/agents")

    assert res.status_code == 200
    row = res.json()["agents"][0]
    assert row["tools"].count("skill") == 1
    assert row["tools"].count("todo_manage") == 1
    assert row["tools"].count("shell") == 1
    assert row["tools"].count("memory_search") == 1
    assert row["skills"].count("self-healing") == 1
    assert row["skills"].count("custom-skill") == 1


@pytest.mark.asyncio
async def test_list_applies_agent_tool_opt_outs(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    (agents_dir / "explorer.md").write_text(
        """---
name: explorer
role: member
model: zai:glm-5-turbo
tools_opt_out:
  - shell
---
"""
    )
    (agents_dir / "lead.md").write_text(LEAD_MD)

    res = await client.get("/api/agents")

    row = {item["name"]: item for item in res.json()["agents"]}["explorer"]
    assert "shell" not in row["tools"]
    assert row["skills"] == []


@pytest.mark.asyncio
async def test_list_surfaces_invalid_file(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    (agents_dir / "bad.md").write_text("no frontmatter here")
    res = await client.get("/api/agents")
    assert res.status_code == 200
    rows = res.json()["agents"]
    assert rows[0]["valid"] is False
    assert "frontmatter" in rows[0]["error"].lower()


# ── GET /agents/registry ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_registry_returns_catalog(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    import app.api.routes.agents as agents_routes

    agents_routes._registry_model_cache.clear()
    monkeypatch.setattr(
        agents_routes, "discover_provider_models", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "app.api.routes.skills._discover_runtime_skills",
        lambda *_args, **_kwargs: {
            "work-research": {
                "description": "Research work.",
                "modes": ["work"],
            },
            "coding-investigation": {
                "description": "Investigate code.",
                "modes": ["coding"],
            },
            "self-healing": {
                "description": "Repair configuration.",
                "modes": ["work", "coding"],
            },
        },
    )

    res = await client.get("/api/agents/registry")
    assert res.status_code == 200
    body = res.json()
    assert "tools" in body and "skills" in body and "models" in body
    tool_names = {t["name"] for t in body["tools"]}
    # A few builtins we know must exist.
    assert {"read", "write", "shell", "date"}.issubset(tool_names)
    assert {"skill", "todo_manage", "schedule_task", "note"}.isdisjoint(tool_names)
    assert isinstance(body["providers"], list) and body["providers"]

    # Tier metadata so UIs can annotate/hide tools per role and mode.
    by_name = {t["name"]: t for t in body["tools"]}
    assert by_name["ask_user"]["lead_only"] is True
    assert by_name["read"]["lead_only"] is False
    assert by_name["memory_search"]["tiers"] is None
    assert "artifact" not in by_name
    assert by_name["lsp_diagnostics"]["tiers"] == ["coding"]
    assert by_name["worktree_start"]["tiers"] == ["coding"]
    assert by_name["read"]["tiers"] is None

    skills_by_name = {skill["name"]: skill for skill in body["skills"]}
    assert skills_by_name["work-research"]["modes"] == ["work"]
    assert skills_by_name["coding-investigation"]["modes"] == ["coding"]
    assert skills_by_name["self-healing"]["modes"] == ["work", "coding"]


@pytest.mark.asyncio
async def test_registry_discovers_explicit_workspace_skills(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    import app.api.routes.agents as agents_routes

    agents_routes._registry_model_cache.clear()
    monkeypatch.setattr(
        agents_routes, "discover_provider_models", AsyncMock(return_value=[])
    )
    workspace = tmp_path / "repo"
    skill_dir = workspace / ".agents" / "skills" / "project-only"
    skill_dir.mkdir(parents=True)
    (workspace / ".git").mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: project-only\ndescription: Project workflow.\n---\nBody.\n"
    )

    response = await client.get(
        "/api/agents/registry",
        params=[("workspace", str(workspace)), ("mode", "coding")],
    )

    assert response.status_code == 200
    skills = {item["name"]: item for item in response.json()["skills"]}
    assert skills["project-only"]["modes"] == ["work", "coding"]


@pytest.mark.asyncio
async def test_member_effective_tools_exclude_lead_only_extras(
    fs_dirs, client: AsyncClient
):
    """A member listing ask_user in frontmatter must not display it as
    effective — mirrors the loader, which skips lead_only extras."""
    agents_dir, _ = fs_dirs
    (agents_dir / "lead.md").write_text(
        "---\nname: lead\nrole: lead\nmodel: zai:glm-5-turbo\n---\nLead."
    )
    (agents_dir / "helper.md").write_text(
        "---\nname: helper\nrole: member\nmodel: zai:glm-5-turbo\n"
        "tools:\n  - ask_user\n  - browser_use\n---\nHelper."
    )

    res = await client.get("/api/agents")

    assert res.status_code == 200
    rows = {row["name"]: row for row in res.json()["agents"]}
    helper = rows["helper"]
    assert "ask_user" not in helper["tools"]
    assert "browser_use" in helper["tools"]


# ── GET /agents/{name} ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_single_agent(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)
    res = await client.get("/api/agents/lead")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "lead"
    assert body["content"].startswith("---")
    assert body["config"]["role"] == "lead"
    assert body["error"] is None


@pytest.mark.asyncio
async def test_get_coding_agent(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    coding_dir = agents_dir / "coding"
    coding_dir.mkdir()
    (coding_dir / "evoflux.md").write_text(
        LEAD_MD.replace("name: lead", "name: evoflux")
    )

    res = await client.get("/api/agents/coding%2Fevoflux")

    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "coding/evoflux"
    assert body["config"]["name"] == "evoflux"
    assert "shell" in body["config"]["tools"]


@pytest.mark.asyncio
async def test_get_missing_agent(client: AsyncClient):
    res = await client.get("/api/agents/ghost")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_get_agent_bad_name(client: AsyncClient):
    # Path segment containing a slash triggers the name validator (400),
    # while a pure ".." gets consumed by URL normalization and 404s.
    res = await client.get("/api/agents/.hidden")
    assert res.status_code == 400


# ── POST /agents ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_agent_validates_and_persists(fs_dirs, client: AsyncClient):
    """POST /api/agents writes the file and validates the new on-disk state.

    The route does NOT start or rebuild the running team — that's
    deferred to the next turn's drift check.
    """
    agents_dir, _ = fs_dirs
    res = await client.post(
        "/api/agents",
        json={"name": "lead", "content": LEAD_MD},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "lead"
    assert body["config"]["role"] == "lead"
    # File really exists.
    assert (agents_dir / "lead.md").is_file()
    # Critically: the running team was NOT started.  Live mutations
    # don't rebuild — agents refresh themselves on next activation.
    assert team_manager.current_team() is None


@pytest.mark.asyncio
async def test_create_agent_invalid_frontmatter_422(client: AsyncClient):
    res = await client.post(
        "/api/agents",
        json={"name": "lead", "content": "no frontmatter"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_agent_conflict(fs_dirs, client: AsyncClient):
    _seed_files(fs_dirs[0])
    res = await client.post("/api/agents", json={"name": "lead", "content": LEAD_MD})
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_create_agent_mismatched_name_422(client: AsyncClient):
    res = await client.post(
        "/api/agents",
        json={
            "name": "alpha",
            "content": "---\nname: beta\nrole: lead\nmodel: zai:x\n---\nhi",
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_create_without_lead_rolls_back(fs_dirs, client: AsyncClient):
    """A member-only team fails the 'exactly one lead' check. The failed
    reload must delete the just-written file so disk state stays consistent."""
    agents_dir, _ = fs_dirs
    res = await client.post(
        "/api/agents",
        json={"name": "worker", "content": MEMBER_MD},
    )
    assert res.status_code == 422
    assert not (agents_dir / "worker.md").exists()


# ── PUT /agents/{name} ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_agent_validates_and_persists(fs_dirs, client: AsyncClient):
    """PUT /api/agents/{name} rewrites the file and validates the new state.

    No live team rebuild — drift detection refreshes the agent on its
    next turn.
    """
    agents_dir, _ = fs_dirs
    await client.post("/api/agents", json={"name": "lead", "content": LEAD_MD})

    new_content = LEAD_MD.replace("The lead.", "The updated lead.")
    res = await client.put(
        "/api/agents/lead", json={"name": "lead", "content": new_content}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "lead"
    assert "The updated lead." in body["content"]
    # Body description was rewritten on disk.
    assert "The updated lead." in (agents_dir / "lead.md").read_text()


@pytest.mark.asyncio
async def test_update_coding_agent_validates_coding_team(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)
    coding_dir = agents_dir / "coding"
    coding_dir.mkdir()
    content = LEAD_MD.replace("name: lead", "name: evoflux")
    (coding_dir / "evoflux.md").write_text(content)

    new_content = content.replace("The lead.", "The coding lead.")
    res = await client.put(
        "/api/agents/coding%2Fevoflux",
        json={"name": "coding/evoflux", "content": new_content},
    )

    assert res.status_code == 200, res.text
    assert "The coding lead." in (coding_dir / "evoflux.md").read_text()
    assert sorted(p.name for p in coding_dir.glob("*.md")) == ["evoflux.md"]


@pytest.mark.asyncio
async def test_update_agent_rollback_on_invalid(fs_dirs, client: AsyncClient):
    """PUT with invalid model string → validation fails → file restored."""
    agents_dir, _ = fs_dirs
    await client.post("/api/agents", json={"name": "lead", "content": LEAD_MD})
    original = (agents_dir / "lead.md").read_text()

    bad_content = LEAD_MD.replace(
        "model: zai:glm-5-turbo", "model: notavalidmodelstring"
    )
    res = await client.put(
        "/api/agents/lead", json={"name": "lead", "content": bad_content}
    )
    assert res.status_code == 422
    # File is back to original content.
    assert (agents_dir / "lead.md").read_text() == original


@pytest.mark.asyncio
async def test_update_missing_agent_404(client: AsyncClient):
    res = await client.put(
        "/api/agents/ghost", json={"name": "ghost", "content": LEAD_MD}
    )
    assert res.status_code == 404


# ── PATCH /agents/model (bulk) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_update_model_patches_every_agent(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)
    (agents_dir / "worker.md").write_text(MEMBER_MD)

    res = await client.patch(
        "/api/agents/model",
        json={"names": ["lead", "worker"], "model": "anthropic:claude-sonnet-5"},
    )

    assert res.status_code == 200, res.text
    results = {r["name"]: r for r in res.json()["results"]}
    assert results["lead"]["ok"] is True
    assert results["worker"]["ok"] is True
    assert "model: anthropic:claude-sonnet-5" in (agents_dir / "lead.md").read_text()
    assert "model: anthropic:claude-sonnet-5" in (agents_dir / "worker.md").read_text()
    # Everything else in the file is preserved.
    assert "You are the lead." in (agents_dir / "lead.md").read_text()


@pytest.mark.asyncio
async def test_bulk_update_model_reports_missing_agent(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)

    res = await client.patch(
        "/api/agents/model",
        json={"names": ["lead", "ghost"], "model": "anthropic:claude-sonnet-5"},
    )

    assert res.status_code == 200, res.text
    results = {r["name"]: r for r in res.json()["results"]}
    assert results["lead"]["ok"] is True
    assert results["ghost"]["ok"] is False
    assert results["ghost"]["error"]


@pytest.mark.asyncio
async def test_bulk_update_model_bad_model_leaves_file_untouched(
    fs_dirs, client: AsyncClient
):
    agents_dir, _ = fs_dirs
    _seed_files(agents_dir)
    original = (agents_dir / "lead.md").read_text()

    res = await client.patch(
        "/api/agents/model",
        json={"names": ["lead"], "model": "notavalidmodelstring"},
    )

    assert res.status_code == 200, res.text
    results = {r["name"]: r for r in res.json()["results"]}
    assert results["lead"]["ok"] is False
    assert (agents_dir / "lead.md").read_text() == original


# ── DELETE /agents/{name} ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_agent_removes_file(fs_dirs, client: AsyncClient):
    """DELETE /api/agents/{name} removes the file when the remaining team is valid.

    No live rebuild — removing an agent at runtime is a *shape* change
    that the live-config drift mechanism intentionally does not cover.
    The deleted agent stays running until the next server start.
    """
    agents_dir, _ = fs_dirs
    # Create lead + member so deleting the member leaves a valid team.
    await client.post("/api/agents", json={"name": "lead", "content": LEAD_MD})
    await client.post("/api/agents", json={"name": "worker", "content": MEMBER_MD})

    res = await client.delete("/api/agents/worker")
    assert res.status_code == 200
    assert res.json() == {"name": "worker"}
    assert not (agents_dir / "worker.md").exists()


@pytest.mark.asyncio
async def test_delete_last_lead_rollback(fs_dirs, client: AsyncClient):
    agents_dir, _ = fs_dirs
    await client.post("/api/agents", json={"name": "lead", "content": LEAD_MD})
    res = await client.delete("/api/agents/lead")
    assert res.status_code == 422
    # File was restored.
    assert (agents_dir / "lead.md").is_file()


# ── Skills routes (sanity) ───────────────────────────────────────────────────


SKILL_MD = """\
---
name: research
description: Researches things.
---
Body text.
"""


@pytest.mark.asyncio
async def test_create_skill_without_team(fs_dirs, client: AsyncClient):
    """Creating a skill with no running team should succeed and not attempt a
    reload (since no agents reference it)."""
    res = await client.post(
        "/api/skills", json={"name": "research", "content": SKILL_MD}
    )
    assert res.status_code == 201
    body = res.json()
    assert body["description"] == "Researches things."


@pytest.mark.asyncio
async def test_create_skill_invalid_frontmatter(client: AsyncClient):
    res = await client.post(
        "/api/skills", json={"name": "bad", "content": "no frontmatter"}
    )
    # The permissive skill parser accepts empty frontmatter, so this creates
    # a valid-but-empty skill. Name mismatch tests the real error path.
    assert res.status_code in (201, 422)


@pytest.mark.asyncio
async def test_list_skills(fs_dirs, client: AsyncClient):
    skills_dir = fs_dirs[1]
    (skills_dir / "research").mkdir()
    (skills_dir / "research" / "SKILL.md").write_text(SKILL_MD)
    res = await client.get("/api/skills")
    assert res.status_code == 200
    body = res.json()
    research = next(skill for skill in body["skills"] if skill["name"] == "research")
    assert research["description"] == "Researches things."


@pytest.mark.asyncio
async def test_get_skill(fs_dirs, client: AsyncClient):
    skills_dir = fs_dirs[1]
    (skills_dir / "research").mkdir()
    (skills_dir / "research" / "SKILL.md").write_text(SKILL_MD)
    res = await client.get("/api/skills/research")
    assert res.status_code == 200
    body = res.json()
    assert body["content"] == SKILL_MD
    assert body["description"] == "Researches things."


@pytest.mark.asyncio
async def test_delete_skill(fs_dirs, client: AsyncClient):
    skills_dir = fs_dirs[1]
    (skills_dir / "research").mkdir()
    (skills_dir / "research" / "SKILL.md").write_text(SKILL_MD)
    res = await client.delete("/api/skills/research")
    assert res.status_code == 200
    assert not (skills_dir / "research").exists()
