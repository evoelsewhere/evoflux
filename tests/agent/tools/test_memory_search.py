"""Tests for the memory_search built-in tool."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from app.agent.errors import ToolExecutionError
from app.agent.tools.builtin import memory_search as exported_memory_search
from app.agent.tools.builtin.memory_search import memory_search
from app.services.memory import seed_memory

memory_search_module = importlib.import_module("app.agent.tools.builtin.memory_search")


@pytest.fixture(autouse=True)
def _memory_dir(tmp_path: Path, monkeypatch):
    from app.core.config import settings

    target = tmp_path / "memory"
    monkeypatch.setattr(settings, "EVOFLUX_WIKI_DIR", str(target))
    seed_memory()
    yield target


@pytest.mark.asyncio
async def test_memory_search_tool_returns_cited_results(_memory_dir: Path):
    (_memory_dir / "wiki" / "user.md").write_text(
        "# User\n\nHoang prefers direct benchmarkable memory.", encoding="utf-8"
    )

    result = await memory_search.arun(query="Hoang benchmarkable", top_k=3)

    assert "Memory search results for" in result
    assert "source=wiki:user" in result
    assert "path=wiki/user.md" in result


@pytest.mark.asyncio
async def test_memory_search_tool_clamps_top_k(_memory_dir: Path):
    for i in range(25):
        (_memory_dir / "wiki" / f"page-{i}.md").write_text(
            f"# Page {i}\n\nsharedtoken memory page {i}", encoding="utf-8"
        )

    result = await memory_search.arun(query="sharedtoken memory", top_k=999)

    assert result.count("source=wiki:page-") <= 20


@pytest.mark.asyncio
async def test_memory_search_tool_surfaces_unexpected_errors(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(memory_search_module, "search_memory", _raise)

    with pytest.raises(ToolExecutionError):
        await memory_search.arun(query="anything")


def test_memory_search_is_exported_from_builtin_package():
    assert exported_memory_search is memory_search
