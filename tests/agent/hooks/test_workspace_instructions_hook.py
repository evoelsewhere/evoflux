from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.hooks.workspace_instructions import (
    MAX_AGENTS_MD_BYTES,
    WorkspaceInstructionsHook,
)


@pytest.mark.asyncio
async def test_workspace_instructions_hook_injects_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Follow project rules.", encoding="utf-8")
    hook = WorkspaceInstructionsHook(str(tmp_path))
    seen: dict[str, str] = {}

    class Request:
        system_prompt = "Base prompt"

        def override(self, **kwargs):
            return SimpleNamespace(**kwargs)

    async def handler(request):
        seen["prompt"] = request.system_prompt
        return SimpleNamespace(content="ok")

    await hook.wrap_model_call(None, None, Request(), handler)  # type: ignore[arg-type]

    assert "Base prompt" in seen["prompt"]
    assert "Follow project rules." in seen["prompt"]


@pytest.mark.asyncio
async def test_workspace_instructions_hook_skips_missing_agents_md(tmp_path):
    hook = WorkspaceInstructionsHook(str(tmp_path))
    seen: dict[str, str] = {}

    class Request:
        system_prompt = "Base prompt"

        def override(self, **kwargs):
            return SimpleNamespace(**kwargs)

    async def handler(request):
        seen["prompt"] = request.system_prompt
        return SimpleNamespace(content="ok")

    await hook.wrap_model_call(None, None, Request(), handler)  # type: ignore[arg-type]

    assert seen["prompt"] == "Base prompt"


@pytest.mark.asyncio
async def test_workspace_instructions_hook_skips_blank_agents_md(tmp_path):
    (tmp_path / "AGENTS.md").write_text("\n  \t\n", encoding="utf-8")
    hook = WorkspaceInstructionsHook(str(tmp_path))
    seen: dict[str, str] = {}

    class Request:
        system_prompt = "Base prompt"

        def override(self, **kwargs):
            raise AssertionError("blank AGENTS.md should not override the request")

    async def handler(request):
        seen["prompt"] = request.system_prompt
        return SimpleNamespace(content="ok")

    await hook.wrap_model_call(None, None, Request(), handler)  # type: ignore[arg-type]

    assert seen["prompt"] == "Base prompt"


@pytest.mark.asyncio
async def test_workspace_instructions_hook_truncates_oversized_agents_md(tmp_path):
    """Oversized AGENTS.md is truncated to the cap, not silently dropped."""
    (tmp_path / "AGENTS.md").write_text(
        "x" * (MAX_AGENTS_MD_BYTES + 100), encoding="utf-8"
    )
    hook = WorkspaceInstructionsHook(str(tmp_path))
    seen: dict[str, str] = {}

    class Request:
        system_prompt = "Base prompt"

        def override(self, **kwargs):
            return SimpleNamespace(**kwargs)

    async def handler(request):
        seen["prompt"] = request.system_prompt
        return SimpleNamespace(content="ok")

    await hook.wrap_model_call(None, None, Request(), handler)  # type: ignore[arg-type]

    assert "Base prompt" in seen["prompt"]
    assert "x" * 100 in seen["prompt"]
    assert "[AGENTS.md truncated" in seen["prompt"]
    # The injected block stays bounded near the cap (content + short notice).
    assert len(seen["prompt"]) < MAX_AGENTS_MD_BYTES + 500


@pytest.mark.asyncio
async def test_multi_repo_hook_truncates_oversized_agents_md(tmp_path):
    """Multi-repo AGENTS.md over its cap is truncated, not dropped."""
    from app.agent.hooks.multi_repo_context import (
        MAX_AGENTS_MD_BYTES as MULTI_CAP,
        _read_agents_md,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("y" * (MULTI_CAP + 100), encoding="utf-8")

    content = _read_agents_md(repo)

    assert content.startswith("y" * 100)
    assert "[AGENTS.md truncated" in content
    assert len(content) <= MULTI_CAP + 200
