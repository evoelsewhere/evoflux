"""Contract tests for the unified model-facing code-context tool."""

from pathlib import Path

import pytest

from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
from app.agent.tools.builtin.code_context import (
    _INLINE_CHAR_LIMIT,
    _render_code_context,
    code_context,
)
from app.core.config import settings
from app.services.code_index.models import CodeContextResult, SearchHit
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
    # Both halves of the scoping contract. Omitting the repository searches
    # every authorized index, and the index that does *not* contain the
    # symbol is the expensive one because it reads itself in full to say so:
    # measured, one identifier lookup spent 6.4s inside a 73k-chunk index
    # that had nothing to do with the question. So the description has to
    # ask for a scope when the question already carries one, while still
    # warning against guessing the primary when the owner is unknown.
    repository_description = parameters["properties"]["repository"]["description"]
    assert "Pass it whenever the question already" in repository_description
    assert "guessing the primary would hide it" in repository_description
    assert "guessed language" in parameters["properties"]["languages"]["description"]


def test_code_context_renderer_keeps_evidence_when_one_section_is_oversized() -> None:
    result = CodeContextResult(
        action="search",
        query="needle",
        strategy="code-index-test",
        index_version="abc123",
        repositories=("repo",),
        hits=[
            SearchHit(
                repository="repo",
                file_path="minified.js",
                language="javascript",
                line_start=1,
                line_end=1,
                content="needle " + ("payload" * 5_000),
                score=1.0,
            )
        ],
    )

    rendered = _render_code_context(result)

    assert "repo/minified.js:1-1" in rendered
    assert "needle payload" in rendered
    assert "[section truncated]" in rendered
    assert "Output truncated." in rendered
    assert len(rendered) <= _INLINE_CHAR_LIMIT


def test_code_context_renderer_bounds_oversized_repository_metadata() -> None:
    result = CodeContextResult(
        action="search",
        query="needle",
        strategy="code-index-test",
        index_version="abc123",
        repositories=tuple(f"repository-{ordinal:04d}" for ordinal in range(2_000)),
    )

    rendered = _render_code_context(result)

    assert "[metadata truncated]" in rendered
    assert "Output truncated." in rendered
    assert len(rendered) <= _INLINE_CHAR_LIMIT


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
async def test_code_context_unknown_root_searches_every_authorized_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "primary-rust"
    sibling = tmp_path / "sibling-python"
    primary.mkdir()
    sibling.mkdir()
    (primary / "lib.rs").write_text("fn unrelated_storage() {}\n", encoding="utf-8")
    (sibling / "pipeline.py").write_text(
        "class SummarizationHook:\n    prompt_finalization_stage = 65\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(tmp_path / "cache"))
    registry = RepositoryIndexRegistry()
    monkeypatch.setattr("app.services.code_index.service.repository_indexes", registry)
    token = set_sandbox(
        SandboxConfig(
            workspace=str(primary),
            extra_workspace_paths=[str(sibling)],
            session_id="code-index-multi-repo-test",
            denied_roots=[],
        )
    )
    try:
        output = await code_context.arun(
            action="search",
            query="SummarizationHook prompt finalization",
            refresh=True,
        )
    finally:
        _sandbox_ctx.reset(token)

    assert "repositories: primary-rust, sibling-python" in output
    assert "sibling-python/pipeline.py" in output


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
