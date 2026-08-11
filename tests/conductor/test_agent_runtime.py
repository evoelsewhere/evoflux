from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.config import AgentConfig
from app.conductor.agent_runtime import apply_managed_agent_runtime_model
from app.conductor.models import ManagedResourceProvider
from app.core.agent_settings import write_agent_runtime_settings
from app.core.config import settings


def test_managed_agent_runtime_layer_is_additive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    provider = ManagedResourceProvider(
        project_id="project-1",
        project_name="Platform Core",
        resource_id="agent-1",
        version_id="version-1",
        version="1.0.0",
        release_channel="published",
        observed_state="in_sync",
    )
    write_agent_runtime_settings(
        project_id=provider.project_id,
        resource_id=provider.resource_id,
        name="reviewer",
        model="anthropic:claude-sonnet-5",
        extra_tools=["web_search", "read"],
        extra_skills=["local-skill", "managed-skill"],
        extra_mcp=["local-browser", "managed-browser"],
    )
    managed = AgentConfig(
        name="reviewer",
        role="member",
        system_prompt="Review changes.",
        model="xiaomi:mimo-v2.5",
        tools=["read"],
        skills=["managed-skill"],
        mcp=["managed-browser"],
    )

    effective = apply_managed_agent_runtime_model(managed, provider=provider)

    assert effective.model == "anthropic:claude-sonnet-5"
    assert effective.tools == ["read", "web_search"]
    assert effective.skills == ["managed-skill", "local-skill"]
    assert effective.mcp == ["managed-browser", "local-browser"]
    assert managed.tools == ["read"]
    assert managed.skills == ["managed-skill"]
    assert managed.mcp == ["managed-browser"]
