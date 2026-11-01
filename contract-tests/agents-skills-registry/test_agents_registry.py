"""``GET /api/agents/registry``: the tool, skill, provider and model catalog."""

from __future__ import annotations

import pytest

from mock_provider.server import MockProvider
from provider_setup import configure_backend_provider
from registry_helpers import skill_md, write_skill

MODEL_KEYS = {
    "id", "provider", "model", "vision", "input_audio", "input_video",
    "output_image", "output_video", "summary_trigger_tokens", "context_length",
    "thinking_levels", "thinking_control", "thinking_default_level",
    "thinking_default_enabled", "thinking_source", "interfaces", "display_name",
    "description", "family", "status", "release_date", "last_updated",
    "knowledge", "max_output_tokens", "tool_call", "attachment", "temperature",
    "structured_output", "open_weights", "cost", "free", "thinking_budget",
    "modes", "mode_cost_multiplier",
}  # fmt: skip


@pytest.fixture
def provider():
    mock = MockProvider(model_ids=("mock-model", "other-model"))
    try:
        yield mock
    finally:
        mock.close()


def registry(client, **params):
    response = client.get("/api/agents/registry", params=params)
    assert response.status_code == 200
    return response.json()


def test_registry_shape_ordering_and_the_tool_catalog(client, snapshot) -> None:
    body = registry(client)
    assert list(body) == ["tools", "skills", "providers", "models"]
    tools = body["tools"]
    assert [t["name"] for t in tools] == sorted(t["name"] for t in tools)
    for tool in tools:
        assert set(tool) == {"name", "description", "tiers", "lead_only"}
        assert isinstance(tool["description"], str)
        assert tool["tiers"] is None or tool["tiers"] == sorted(tool["tiers"])
    snapshot.check(
        "registry_tools.json",
        [{k: t[k] for k in ("name", "tiers", "lead_only")} for t in tools],
    )
    assert body["providers"] == sorted(body["providers"])
    snapshot.check("registry_provider_ids.json", body["providers"])
    assert body["models"] == []  # nothing configured, nothing discovered


def test_registry_lists_valid_skills_only_with_their_flags(client, skills_dir, config_dir) -> None:
    write_skill(skills_dir, "ok-skill", skill_md("ok-skill", extra="disable-model-invocation: true\nuser-invocable: false\n"))
    write_skill(skills_dir, "broken", "no frontmatter")
    (config_dir / "skill-settings.json").write_text(
        '{"version": 2, "disabled": ["ok-skill"]}', encoding="utf-8"
    )
    skills = {s["name"]: s for s in registry(client)["skills"]}
    assert "broken" not in skills
    assert skills["ok-skill"] == {
        "name": "ok-skill", "description": "Does a thing.", "enabled": False,
        "model_invocable": False, "user_invocable": False,
    }  # fmt: skip
    names = [s["name"] for s in registry(client)["skills"]]
    assert names == sorted(names)


def test_registry_skills_follow_the_workspace_parameter(client, workspace, tmp_path) -> None:
    write_skill(workspace / ".claude" / "skills", "proj-only")
    assert "proj-only" not in {s["name"] for s in registry(client)["skills"]}
    assert "proj-only" in {s["name"] for s in registry(client, workspace=str(workspace))["skills"]}
    missing = client.get("/api/agents/registry", params={"workspace": str(tmp_path / "nope")})
    assert missing.status_code == 422
    assert missing.json()["detail"].startswith("Workspace does not exist or is not a directory:")


def test_registry_models_come_from_configured_providers_sorted(client, provider, snapshot) -> None:
    configure_backend_provider(client, provider)
    body = registry(client)
    assert [m["id"] for m in body["models"]] == ["router9:mock-model", "router9:other-model"]
    first = body["models"][0]
    assert set(first) == MODEL_KEYS
    assert (first["provider"], first["model"]) == ("router9", "mock-model")
    snapshot.check("registry_model_entry.json", first)
    assert "router9" in body["providers"]


def test_registry_models_respect_the_visible_models_setting(client, provider) -> None:
    configure_backend_provider(client, provider)
    saved = client.put("/api/settings/providers/router9/visible-models", json={"models": ["other-model"]})
    assert saved.status_code == 200
    assert [m["id"] for m in registry(client)["models"]] == ["router9:other-model"]


def test_registry_model_discovery_is_cached_in_memory_for_a_minute(client, provider) -> None:
    """``_registry_model_cache`` keeps the first successful list per provider."""
    configure_backend_provider(client, provider)
    assert [m["model"] for m in registry(client)["models"]] == ["mock-model", "other-model"]
    provider._model_ids = ("mock-model", "other-model", "third-model")
    assert [m["model"] for m in registry(client)["models"]] == ["mock-model", "other-model"]
    provider.close()
    assert [m["model"] for m in registry(client)["models"]] == ["mock-model", "other-model"]


def test_registry_is_not_shadowed_by_an_agent_named_registry(client, agents_dir) -> None:
    (agents_dir / "registry.md").write_text("---\nname: registry\nrole: member\n---\nx", encoding="utf-8")
    assert "tools" in client.get("/api/agents/registry").json()
    # ``/registry`` is also what GET resolves first; the agent file is reachable through its list row only.
    assert any(a["name"] == "registry" for a in client.get("/api/agents").json()["agents"])
