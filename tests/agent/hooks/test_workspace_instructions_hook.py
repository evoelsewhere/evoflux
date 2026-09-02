from __future__ import annotations

from types import SimpleNamespace
import json

import pytest

from app.agent.hooks.workspace_instructions import (
    MAX_AGENTS_MD_BYTES,
    MAX_TOTAL_NESTED_INSTRUCTION_BYTES,
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
async def test_nested_override_preflights_mutation_once(tmp_path):
    (tmp_path / "AGENTS.md").write_text("root rule", encoding="utf-8")
    nested = tmp_path / "app" / "feature"
    nested.mkdir(parents=True)
    (tmp_path / "app" / "AGENTS.md").write_text("app rule", encoding="utf-8")
    (nested / "AGENTS.md").write_text("stale standard rule", encoding="utf-8")
    (nested / "AGENTS.override.md").write_text(
        "feature override rule", encoding="utf-8"
    )
    hook = WorkspaceInstructionsHook(str(tmp_path))
    state = SimpleNamespace(metadata={})
    tool_call = SimpleNamespace(
        function=SimpleNamespace(
            name="edit",
            arguments=json.dumps({"path": "app/feature/module.py"}),
        )
    )
    calls = 0

    async def handler(_ctx, _state, _tool_call):
        nonlocal calls
        calls += 1
        return "edited"

    first = await hook.wrap_tool_call(None, state, tool_call, handler)
    assert first.startswith("[Instruction preflight")
    assert "app rule" in first
    assert "feature override rule" in first
    assert "stale standard rule" not in first
    assert calls == 0

    second = await hook.wrap_tool_call(None, state, tool_call, handler)
    assert second == "edited"
    assert calls == 1


@pytest.mark.asyncio
async def test_nested_instructions_evict_oldest_beyond_aggregate_budget(tmp_path):
    """Accumulated nested AGENTS.md content must not grow without bound."""
    (tmp_path / "AGENTS.md").write_text("root rule", encoding="utf-8")
    per_file = MAX_TOTAL_NESTED_INSTRUCTION_BYTES // 2 + 100  # >half the budget each
    dirs = []
    for name in ("first", "second", "third"):
        nested = tmp_path / name
        nested.mkdir()
        (nested / "AGENTS.md").write_text("x" * per_file, encoding="utf-8")
        dirs.append(nested)

    hook = WorkspaceInstructionsHook(str(tmp_path))
    state = SimpleNamespace(metadata={})

    async def handler(_ctx, _state, _tool_call):
        return "done"

    for nested in dirs:
        tool_call = SimpleNamespace(
            function=SimpleNamespace(
                name="read",
                arguments=json.dumps({"path": str(nested / "module.py")}),
            )
        )
        result = await hook.wrap_tool_call(None, state, tool_call, handler)
        # Every newly-applicable rule is still surfaced once, regardless of budget.
        assert "New nested workspace instructions" in result

        loaded = state.metadata["_loaded_workspace_instruction_files"]
        # Each file alone is over half the budget, so at most one fits at a time.
        assert len(loaded) <= 1

    # The oldest ("first") must have been evicted once the budget was exceeded.
    final_loaded = state.metadata["_loaded_workspace_instruction_files"]
    assert str(dirs[0] / "AGENTS.md") not in final_loaded
    assert str(dirs[-1] / "AGENTS.md") in final_loaded


@pytest.mark.asyncio
async def test_multi_repo_context_lists_roots_and_injects_each_instruction_once(
    tmp_path,
):
    primary = tmp_path / "primary"
    sibling = tmp_path / "sibling"
    primary.mkdir()
    sibling.mkdir()
    (primary / "Cargo.toml").write_text("[package]\nname='primary'\n")
    (sibling / "pyproject.toml").write_text("[project]\nname='sibling'\n")
    (sibling / "package.json").write_text('{"name":"sibling"}\n')
    (primary / "AGENTS.md").write_text("primary unique rule", encoding="utf-8")
    (sibling / "AGENTS.md").write_text("sibling unique rule", encoding="utf-8")
    hook = WorkspaceInstructionsHook(str(primary), [str(sibling)])
    seen: dict[str, str] = {}

    class Request:
        system_prompt = "Base prompt"

        def override(self, **kwargs):
            return SimpleNamespace(**kwargs)

    async def handler(request):
        seen["prompt"] = request.system_prompt
        return SimpleNamespace(content="ok")

    await hook.wrap_model_call(None, None, Request(), handler)  # type: ignore[arg-type]

    assert "## Available Repositories" in seen["prompt"]
    assert "start discovery across every listed repository" in seen["prompt"]
    assert "Relative paths passed to ordinary filesystem tools" in seen["prompt"]
    assert "use its displayed absolute path" in seen["prompt"]
    assert "signals: Rust" in seen["prompt"]
    assert "signals: Python, JavaScript/TypeScript" in seen["prompt"]
    assert seen["prompt"].count("primary unique rule") == 1
    assert seen["prompt"].count("sibling unique rule") == 1
