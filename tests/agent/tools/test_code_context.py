"""Contract tests for the unified model-facing code-context tool."""

from pathlib import Path

import pytest

from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.tools.builtin.code_context import code_context
from app.core.config import settings
from app.services.code_index.project import RepositoryIndexRegistry


def test_code_context_owns_discovery_and_graph_navigation() -> None:
    assert code_context.read_only is True
    assert code_context.deferred is False
    assert code_context.deduplicate_in_batch is True
    assert "code_context" in code_context.capabilities
    parameters = code_context.definition["function"]["parameters"]
    actions = parameters["properties"]["action"]["enum"]
    assert actions == [
        "search",
        "grep",
        "definition",
        "callers",
        "callees",
        "references",
        "impact",
        "neighborhood",
    ]
    assert parameters["properties"]["refresh"]["default"] is True


@pytest.mark.asyncio
async def test_code_context_dot_selects_active_sandbox_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def webbridge_enabled():\n    return True\n", encoding="utf-8"
    )
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    registry = RepositoryIndexRegistry()
    monkeypatch.setattr("app.services.code_index.service.repository_indexes", registry)
    token = set_sandbox(
        SandboxConfig(
            workspace=str(repository),
            session_id="code-index-test",
            denied_roots=[],
        )
    )
    try:
        output = await code_context.arun(
            action="search",
            query="webbridge_enabled",
            repository=".",
            refresh=True,
        )
    finally:
        _sandbox_ctx.reset(token)

    assert "strategy: code-index-vector-fts5-cross-repo" in output
    assert "repositories: repo" in output
    assert "service.py" in output


@pytest.mark.asyncio
async def test_code_context_recovers_string_encoded_list_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def selected_path():\n    return 'filter evidence'\n", encoding="utf-8"
    )
    (repository / "ignored.ts").write_text(
        "export const ignored = 'filter evidence'\n", encoding="utf-8"
    )
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    registry = RepositoryIndexRegistry()
    monkeypatch.setattr("app.services.code_index.service.repository_indexes", registry)
    token = set_sandbox(
        SandboxConfig(
            workspace=str(repository),
            session_id="code-index-string-list-test",
            denied_roots=[],
        )
    )
    try:
        output = await code_context.arun(
            action="search",
            query="filter evidence",
            repository=".",
            paths='["service.py"]',
            languages="python",
            refresh=True,
        )
    finally:
        _sandbox_ctx.reset(token)

    assert "service.py" in output
    assert "ignored.ts" not in output
