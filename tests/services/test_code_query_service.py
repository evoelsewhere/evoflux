"""Regression coverage for native, symbol-first graph navigation."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import select

import app.models.chat  # noqa: F401 -- register SQLModel tables
import app.models.code_graph  # noqa: F401 -- register SQLModel tables


async def _index(root: Path):  # noqa: ANN202
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace

    async with async_session_factory() as db:
        workspace = await upsert_coding_workspace(db, path=str(root))
        await db.commit()
        await reindex_workspace(db, workspace_id=workspace.id, root_path=str(root))
        await db.commit()
        return workspace.id


@pytest.mark.asyncio
async def test_definition_resolves_exact_symbol_and_complete_source(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    (tmp_path / "service.py").write_text(
        "def calculate_total(values):\n    total = sum(values)\n    return total\n",
        encoding="utf-8",
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        result = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="calculate_total",
            operation="definition",
        )

    assert result.strategy == "native-exact-symbol-graph"
    assert result.freshness == "fresh"
    assert len(result.matches) == 1
    assert result.matches[0].node.qualified_name == "calculate_total"
    assert "def calculate_total" in (result.matches[0].source or "")
    assert "return total" in (result.matches[0].source or "")
    assert result.relations == []


@pytest.mark.asyncio
async def test_native_qualified_separator_resolves_dotted_index_symbol(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    (tmp_path / "animal.rs").write_text(
        "struct Animal;\nimpl Animal { fn create() -> Self { Animal } }\n",
        encoding="utf-8",
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        result = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="Animal::create",
            operation="definition",
            freshness_policy="fast",
        )

    assert [item.node.qualified_name for item in result.matches] == ["Animal.create"]


@pytest.mark.asyncio
async def test_callers_returns_exact_callsite_instead_of_search_hits(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    (tmp_path / "service.py").write_text(
        "def helper():\n"
        "    return 1\n\n"
        "def first_caller():\n"
        "    return helper()\n\n"
        "def unrelated_helper_text():\n"
        "    return 'helper'\n",
        encoding="utf-8",
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        result = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="helper",
            operation="callers",
        )

    assert [relation.source.node.qualified_name for relation in result.relations] == [
        "first_caller"
    ]
    relation = result.relations[0]
    assert relation.kind == "calls"
    assert relation.callsite_file == "service.py"
    assert relation.callsite_line == 5
    assert "return helper()" in (relation.callsite_source or "")
    assert "unrelated_helper_text" not in {
        item.source.node.qualified_name for item in result.relations
    }


@pytest.mark.asyncio
async def test_callers_includes_callable_passed_to_dispatcher(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    (tmp_path / "worker.py").write_text(
        "import asyncio\n\n"
        "def blocking_job():\n"
        "    return 1\n\n"
        "async def run_job():\n"
        "    return await asyncio.to_thread(blocking_job)\n",
        encoding="utf-8",
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        result = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="blocking_job",
            operation="callers",
        )

    relation = next(item for item in result.relations if item.kind == "references")
    assert relation.source.node.qualified_name == "run_job"
    assert relation.callsite_line == 7


@pytest.mark.asyncio
async def test_callees_only_follows_outbound_call_edges(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    (tmp_path / "flow.py").write_text(
        "def load_data():\n    return []\n\n"
        "def save_data(value):\n    return value\n\n"
        "def orchestrate():\n"
        "    rows = load_data()\n"
        "    return save_data(rows)\n",
        encoding="utf-8",
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        result = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="orchestrate",
            operation="callees",
        )

    assert {relation.target.node.qualified_name for relation in result.relations} == {
        "load_data",
        "save_data",
    }
    assert {relation.callsite_line for relation in result.relations} == {8, 9}


@pytest.mark.asyncio
async def test_same_named_symbol_is_explicitly_ambiguous_and_path_disambiguates(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    (tmp_path / "alpha.py").write_text(
        "def handler():\n    return 'a'\n", encoding="utf-8"
    )
    (tmp_path / "beta.py").write_text(
        "def handler():\n    return 'b'\n", encoding="utf-8"
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        ambiguous = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="handler",
        )
        selected = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="handler",
            path="beta.py",
        )

    assert len(ambiguous.matches) == 2
    assert any("2 exact definitions" in item for item in ambiguous.limitations)
    assert [item.node.file_path for item in selected.matches] == ["beta.py"]
    assert "return 'b'" in (selected.matches[0].source or "")


@pytest.mark.asyncio
async def test_ambiguous_symbol_is_not_traversed_until_root_is_disambiguated(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    (tmp_path / "alpha.py").write_text(
        "def handler():\n    return 'a'\n\ndef alpha_caller():\n    return handler()\n",
        encoding="utf-8",
    )
    (tmp_path / "beta.py").write_text(
        "def handler():\n    return 'b'\n\ndef beta_caller():\n    return handler()\n",
        encoding="utf-8",
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        ambiguous = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="handler",
            operation="callers",
        )
        selected = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="handler",
            operation="callers",
            path="beta.py",
        )

    assert len(ambiguous.matches) == 2
    assert ambiguous.relations == []
    assert any("Traversal was not executed" in item for item in ambiguous.limitations)
    assert [item.source.node.qualified_name for item in selected.relations] == [
        "beta_caller"
    ]


@pytest.mark.asyncio
async def test_prefix_suggestions_are_never_used_as_graph_roots(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    (tmp_path / "service.py").write_text(
        "def calculate_total():\n    return 1\n", encoding="utf-8"
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        result = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="calculate",
            operation="callers",
        )

    assert result.matches == []
    assert result.relations == []
    assert [item.node.name for item in result.suggestions] == ["calculate_total"]
    assert any("not traversed" in item for item in result.limitations)


@pytest.mark.asyncio
async def test_natural_language_is_rejected_at_the_graph_boundary(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        with pytest.raises(ValueError, match="raw symbol identifier"):
            await navigate_code_graph(
                db,
                root_path=str(tmp_path),
                workspace_id=workspace_id,
                symbol="how does authentication work",
                operation="neighborhood",
            )


@pytest.mark.asyncio
async def test_strict_navigation_reindexes_dirty_source(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.services.code_graph_navigation_service import navigate_code_graph

    source = tmp_path / "service.py"
    source.write_text("def old_handler():\n    return 1\n", encoding="utf-8")
    workspace_id = await _index(tmp_path)
    source.write_text("def fresh_handler():\n    return 2\n", encoding="utf-8")
    async with async_session_factory() as db:
        fresh = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="fresh_handler",
            freshness_policy="strict",
        )
        old = await navigate_code_graph(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            symbol="old_handler",
            freshness_policy="strict",
        )

    assert fresh.freshness == "fresh"
    assert fresh.dirty_files == 0
    assert fresh.matches[0].node.name == "fresh_handler"
    assert "return 2" in (fresh.matches[0].source or "")
    assert old.matches == []


@pytest.mark.asyncio
async def test_cross_repo_call_is_traversed_in_same_directional_graph(
    setup_db, tmp_path: Path
) -> None:
    from app.core.db import async_session_factory
    from app.models.code_graph import CodeNode, CrossRepoEdge
    from app.services.code_graph_navigation_service import (
        navigate_code_graph_across_workspaces,
    )
    from app.services.coding_project_service import create_project

    frontend = tmp_path / "frontend"
    backend = tmp_path / "backend"
    frontend.mkdir()
    backend.mkdir()
    (frontend / "entry.py").write_text(
        "def frontend_entry():\n    return 'request'\n", encoding="utf-8"
    )
    (backend / "remote.py").write_text(
        "def backend_handler():\n    return 'response'\n", encoding="utf-8"
    )
    frontend_id = await _index(frontend)
    backend_id = await _index(backend)

    async with async_session_factory() as db:
        project = await create_project(
            db,
            name="Native cross repo",
            workspace_paths=[str(frontend), str(backend)],
        )
        source = (
            await db.exec(
                select(CodeNode).where(
                    CodeNode.workspace_id == frontend_id,
                    CodeNode.name == "frontend_entry",
                )
            )
        ).one()
        target = (
            await db.exec(
                select(CodeNode).where(
                    CodeNode.workspace_id == backend_id,
                    CodeNode.name == "backend_handler",
                )
            )
        ).one()
        db.add(
            CrossRepoEdge(
                project_id=project.id,
                src_workspace_id=frontend_id,
                src_node_id=source.id,
                src_file_path=source.file_path,
                src_line=source.line_start,
                raw_reference="backend.backend_handler",
                dst_name_hint="backend_handler",
                kind="calls",
                status="resolved",
                method="static_fqn",
                confidence=1.0,
                dst_workspace_id=backend_id,
                dst_node_id=target.id,
                dst_qualified_name=target.qualified_name,
            )
        )
        await db.commit()
        callees = await navigate_code_graph_across_workspaces(
            db,
            workspaces=[
                (str(frontend), frontend_id, "frontend"),
                (str(backend), backend_id, "backend"),
            ],
            symbol="frontend_entry",
            operation="callees",
        )
        callers = await navigate_code_graph_across_workspaces(
            db,
            workspaces=[
                (str(frontend), frontend_id, "frontend"),
                (str(backend), backend_id, "backend"),
            ],
            symbol="backend_handler",
            operation="callers",
        )

    assert callees.strategy == "native-cross-repo-exact-symbol-graph"
    assert callers.relations[0].source.scope.label == "frontend"
    assert callers.relations[0].target.scope.label == "backend"
    assert callers.relations[0].cross_repo is True


def test_code_graph_tool_is_symbol_first_and_always_visible() -> None:
    from app.agent.tools.builtin.code_graph import code_graph

    assert code_graph.deferred is False
    assert code_graph.read_only is True
    schema = code_graph.definition["function"]["parameters"]
    assert set(schema["properties"]) == {
        "symbol",
        "operation",
        "path",
        "repository",
        "freshness_policy",
        "depth",
        "limit",
    }
    assert schema["required"] == ["symbol"]
    assert schema["properties"]["symbol"]["pattern"] == r"^\S+$"
    symbol_description = schema["properties"]["symbol"]["description"]
    assert "identifier present in source" in symbol_description
    assert "Never pass, translate, or summarize" in symbol_description
    freshness_schema = schema["properties"]["freshness_policy"]
    assert freshness_schema["default"] == "fast"
    assert freshness_schema["enum"] == ["fast", "balanced", "strict"]
    assert "exact call-site lines" in code_graph.description
    assert code_graph.deduplicate_in_batch is True


def test_code_graph_tool_owns_navigation_contract() -> None:
    from app.agent.tools.builtin.code_graph import code_graph

    expected_operations = {
        "definition",
        "callers",
        "callees",
        "references",
        "impact",
        "neighborhood",
    }
    schema = code_graph.definition["function"]["parameters"]
    assert set(schema["properties"]["operation"]["enum"]) == expected_operations

    assert "known code symbol" in code_graph.description
    assert "request" in schema["properties"]["symbol"]["description"]


@pytest.mark.asyncio
async def test_code_graph_tool_defaults_to_fast_and_accepts_stricter_freshness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    import app.agent.tools.builtin.code_graph as tool_module

    @asynccontextmanager
    async def fake_session_factory():
        yield object()

    result = SimpleNamespace(
        symbol="target",
        operation="definition",
        strategy="native-exact-symbol-graph",
        freshness="fresh",
        matches=[],
        relations=[],
        dirty_files=0,
        pending_edges=0,
        suggestions=[],
        limitations=[],
        truncated=False,
    )
    navigate = AsyncMock(return_value=result)
    monkeypatch.setattr(
        tool_module,
        "get_sandbox",
        lambda: SimpleNamespace(workspace_root=tmp_path, extra_workspace_paths=[]),
    )
    monkeypatch.setattr(tool_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(
        tool_module.graph_service,
        "resolve_workspace_id",
        AsyncMock(return_value=uuid4()),
    )
    monkeypatch.setattr(
        "app.services.code_graph_navigation_service.navigate_code_graph_across_workspaces",
        navigate,
    )
    monkeypatch.setattr(
        tool_module, "publish_code_graph_observation", lambda _obs: None
    )

    await tool_module._code_graph(symbol="target")
    assert navigate.await_args.kwargs["freshness_policy"] == "fast"

    await tool_module._code_graph(symbol="target", freshness_policy="balanced")
    assert navigate.await_args.kwargs["freshness_policy"] == "balanced"


@pytest.mark.asyncio
async def test_code_graph_tool_schema_rejects_natural_language_before_execution() -> (
    None
):
    from app.agent.errors import ToolArgumentError
    from app.agent.tools.builtin.code_graph import code_graph

    with pytest.raises(ToolArgumentError, match="string_pattern_mismatch"):
        await code_graph.arun(
            symbol="where is calculate_total called",
            operation="callers",
        )
