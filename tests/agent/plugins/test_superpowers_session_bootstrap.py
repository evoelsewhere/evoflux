from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.plugins.hook_contract import HookEvent
from app.agent.plugins.hook_lifecycle import (
    build_agent_lifecycle_hook,
    clear_session_hook_context,
    dispatch_session_event,
)
from app.agent.plugins.hook_runner import STATIC_CONTEXT_PROFILE, hook_trust_profile
from app.agent.schemas.chat import HumanMessage
from app.agent.state import RunContext
from app.core.config import settings
from app.plugin_platform.hook_trust_store import HookTrustGrant, HookTrustStore
from app.plugin_platform.installer import link_plugin
from app.plugin_platform.marketplaces import normalize_claude_plugin_directory
from app.plugin_platform.validator import inspect_plugin


def _claude_superpowers(source: Path) -> Path:
    (source / ".claude-plugin").mkdir(parents=True)
    (source / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "superpowers", "version": "6.4.1"}),
        encoding="utf-8",
    )
    (source / "hooks").mkdir()
    (source / "hooks" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup|clear|compact",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": '"${CLAUDE_PLUGIN_ROOT}/hooks/run-hook.cmd" session-start',
                                    "shell": "bash",
                                    "async": False,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    (source / "hooks" / "run-hook.cmd").write_text(
        "raise RuntimeError('the upstream command must not be launched')",
        encoding="utf-8",
    )
    skill = source / "skills" / "using-superpowers" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: using-superpowers\ndescription: Apply the Superpowers workflow\n---\n\n"
        "Use the required workflow before acting.\n",
        encoding="utf-8",
    )
    return source


@pytest.mark.asyncio
async def test_installed_superpowers_bootstrap_runs_once_as_untrusted_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(data_root))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    source = _claude_superpowers(tmp_path / "source")
    normalized = normalize_claude_plugin_directory(
        source,
        tmp_path / "normalized",
        name="superpowers",
    )
    installation = link_plugin(normalized.root, enabled=True)
    inspection = inspect_plugin(normalized.root)
    hook = inspection.hooks[0]

    assert hook.definition.execution_kind == "static_context"
    assert hook_trust_profile(hook.definition) == STATIC_CONTEXT_PROFILE
    HookTrustStore().approve(
        HookTrustGrant(
            owner_type="plugin",
            owner_id=installation.id,
            hook_id=hook.definition.hook_id,
            digest=hook.digest,
            isolation_profile=STATIC_CONTEXT_PROFILE,
        )
    )

    session_id = "superpowers-session"
    try:
        allowed = await dispatch_session_event(
            HookEvent.SESSION_START, session_id, "create"
        )
        lifecycle = build_agent_lifecycle_hook()
        assert allowed is True
        assert lifecycle is not None

        messages = [HumanMessage(content="Do the requested work.")]
        context = RunContext(session_id, "run-1", "worker")
        await lifecycle.prompt_submit(context, messages, "agent.run")

        injected = messages[-1]
        assert isinstance(injected, HumanMessage)
        assert injected.extra == {"plugin_hook_context": True, "trusted": False}
        assert "You have superpowers." in injected.content
        assert "Use the required workflow before acting." in injected.content
        assert "untrusted data" in injected.content

        second_messages = [HumanMessage(content="A later turn.")]
        await lifecycle.prompt_submit(context, second_messages, "agent.run")
        assert len(second_messages) == 1
    finally:
        clear_session_hook_context(session_id)


@pytest.mark.asyncio
async def test_untrusted_superpowers_keeps_skill_available_without_bootstrap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EVOFLUX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(settings, "EVOFLUX_CONFIG_DIR", str(tmp_path / "config"))
    source = _claude_superpowers(tmp_path / "source")
    normalized = normalize_claude_plugin_directory(
        source,
        tmp_path / "normalized",
        name="superpowers",
    )
    link_plugin(normalized.root, enabled=True)
    inspection = inspect_plugin(normalized.root)
    assert [skill.name for skill in inspection.skills] == ["using-superpowers"]

    session_id = "untrusted-superpowers-session"
    try:
        assert await dispatch_session_event(
            HookEvent.SESSION_START, session_id, "create"
        )
        lifecycle = build_agent_lifecycle_hook()
        assert lifecycle is not None
        messages = [HumanMessage(content="Do the requested work.")]
        await lifecycle.prompt_submit(
            RunContext(session_id, "run-1", "worker"), messages, "agent.run"
        )
        assert len(messages) == 1
    finally:
        clear_session_hook_context(session_id)
