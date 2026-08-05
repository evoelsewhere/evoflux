"""Task-oriented code retrieval, fallback, and freshness regression tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import app.models.chat  # noqa: F401 -- register SQLModel tables for isolated run
import app.models.code_graph  # noqa: F401 -- register SQLModel tables for isolated run


def test_query_terms_preserve_symbol_and_path_structure_without_stopword_cases() -> None:
    from app.services.code_graph.query import query_terms

    terms = query_terms("explain CodeContextHook in app/agent/loader.py:640")

    assert "codecontexthook" in terms
    assert "context" in terms
    assert "app/agent/loader.py" in terms


def test_source_scan_respects_gitignored_vendor_tree(tmp_path: Path) -> None:
    from app.services.code_query_service import _iter_sourceish_files

    (tmp_path / ".gitignore").write_text("desktop/sidecar-bundle/\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text(
        "def reconnect_session():\n    return True\n", encoding="utf-8"
    )
    vendor = tmp_path / "desktop" / "sidecar-bundle" / "stdlib"
    vendor.mkdir(parents=True)
    (vendor / "inspect.py").write_text(
        "def reconnect_session():\n    return False\n", encoding="utf-8"
    )

    scanned = {
        path.relative_to(tmp_path).as_posix()
        for path in _iter_sourceish_files(tmp_path, ())
    }

    assert scanned == {"src/service.py"}


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


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _init_git(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")


@pytest.mark.asyncio
async def test_query_falls_back_for_unsupported_language(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code

    (tmp_path / "worker.ex").write_text(
        "defmodule Worker do\n  def reconnect_session(id), do: id\nend\n",
        encoding="utf-8",
    )
    async with async_session_factory() as db:
        result = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=None,
            query="reconnect_session",
            enable_lsp=False,
        )

    assert result.strategy == "lexical"
    assert result.freshness == "unavailable"
    assert result.results[0].file_path == "worker.ex"
    assert result.results[0].provenance == "lexical"
    assert any(not item.graph for item in result.capabilities)
    assert any("no graph parser" in item.lower() for item in result.limitations)


@pytest.mark.asyncio
async def test_dirty_file_overlay_shadows_stale_graph(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code

    source = tmp_path / "service.py"
    source.write_text("def old_handler():\n    return 1\n", encoding="utf-8")
    workspace_id = await _index(tmp_path)
    source.write_text("def fresh_handler():\n    return 2\n", encoding="utf-8")

    async with async_session_factory() as db:
        fresh = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="fresh_handler",
            intent="change",
            freshness_policy="strict",
            enable_lsp=False,
        )
        stale = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="old_handler",
            intent="change",
            freshness_policy="strict",
            enable_lsp=False,
        )

    assert fresh.freshness == "partial"
    assert fresh.dirty_files == 1
    assert fresh.results[0].provenance == "overlay"
    assert fresh.results[0].symbol == "fresh_handler"
    assert "return 2" in (fresh.results[0].snippet or "")
    assert not any(item.provenance == "graph" for item in stale.results)
    assert all("return 1" not in (item.snippet or "") for item in stale.results)


def test_git_rename_reports_destination_changed_and_source_deleted(tmp_path: Path):
    from app.services.code_query_service import _git_working_tree

    _init_git(tmp_path)
    (tmp_path / "old.py").write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "old.py")
    _git(tmp_path, "commit", "-m", "initial")
    _git(tmp_path, "mv", "old.py", "new.py")

    state = _git_working_tree(tmp_path)

    assert state.changed == frozenset({"new.py"})
    assert state.deleted == frozenset({"old.py"})


@pytest.mark.asyncio
async def test_cache_revision_changes_when_same_dirty_file_changes_again(
    setup_db, tmp_path: Path
):
    import app.services.code_query_service as query_service
    from app.core.db import async_session_factory

    _init_git(tmp_path)
    source = tmp_path / "service.py"
    source.write_text('def target():\n    return "indexed"\n', encoding="utf-8")
    _git(tmp_path, "add", "service.py")
    _git(tmp_path, "commit", "-m", "initial")
    workspace_id = await _index(tmp_path)
    query_service._query_cache.clear()

    source.write_text('def target():\n    return "first-dirty"\n', encoding="utf-8")
    async with async_session_factory() as db:
        first = await query_service.query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="target",
            freshness_policy="strict",
            enable_lsp=False,
        )
    source.write_text('def target():\n    return "second-dirty"\n', encoding="utf-8")
    async with async_session_factory() as db:
        second = await query_service.query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="target",
            freshness_policy="strict",
            enable_lsp=False,
        )

    assert "first-dirty" in (first.results[0].snippet or "")
    assert "second-dirty" in (second.results[0].snippet or "")
    assert first.working_tree_revision != second.working_tree_revision
    assert second.cache_hit is False


@pytest.mark.asyncio
async def test_clean_branch_switch_invalidates_cached_graph_result(
    setup_db, tmp_path: Path
):
    import app.services.code_query_service as query_service
    from app.core.db import async_session_factory

    _init_git(tmp_path)
    source = tmp_path / "service.py"
    source.write_text('def target():\n    return "main"\n', encoding="utf-8")
    _git(tmp_path, "add", "service.py")
    _git(tmp_path, "commit", "-m", "main")
    main_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    workspace_id = await _index(tmp_path)
    query_service._query_cache.clear()
    async with async_session_factory() as db:
        first = await query_service.query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="target",
            freshness_policy="strict",
            enable_lsp=False,
        )
    _git(tmp_path, "switch", "-c", "alternate")
    source.write_text('def target():\n    return "alternate"\n', encoding="utf-8")
    _git(tmp_path, "add", "service.py")
    _git(tmp_path, "commit", "-m", "alternate")
    async with async_session_factory() as db:
        switched = await query_service.query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="target",
            freshness_policy="strict",
            enable_lsp=False,
        )

    assert "main" in (first.results[0].snippet or "")
    assert "alternate" in (switched.results[0].snippet or "")
    assert switched.cache_hit is False
    _git(tmp_path, "switch", main_branch)


@pytest.mark.asyncio
async def test_query_returns_graph_handle_snippet_and_relationships(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code

    (tmp_path / "service.py").write_text(
        "def helper():\n    return 1\n\ndef caller():\n    return helper()\n",
        encoding="utf-8",
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        result = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="helper",
            intent="impact",
            enable_lsp=False,
        )

    candidate = next(item for item in result.results if item.symbol == "helper")
    assert candidate.handle.startswith(f"cg:{workspace_id}:")
    assert candidate.provenance == "graph"
    assert "def helper" in (candidate.snippet or "")
    assert any("caller" in relationship for relationship in candidate.callers)
    assert result.strategy.endswith("graph+lexical")


@pytest.mark.asyncio
async def test_locate_query_does_not_expand_relationship_lists(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code

    (tmp_path / "service.py").write_text(
        "def helper():\n    return 1\n\ndef caller():\n    return helper()\n",
        encoding="utf-8",
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        result = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="helper",
            intent="locate",
            enable_lsp=False,
        )

    candidate = next(item for item in result.results if item.symbol == "helper")
    assert candidate.callers == []
    assert candidate.callees == []
    assert candidate.tests == []


@pytest.mark.asyncio
async def test_natural_query_rejects_single_generic_token_match(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code

    (tmp_path / "card.py").write_text(
        "def summary_behavior():\n    return 'text'\n", encoding="utf-8"
    )
    workspace_id = await _index(tmp_path)
    query_parts = [
        "check " + "summary",
        "suggestion " + "rendering",
        "behavior",
    ]
    async with async_session_factory() as db:
        result = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query=" ".join(query_parts),
            enable_lsp=False,
        )

    assert result.results == []


@pytest.mark.asyncio
async def test_natural_query_matches_identifier_without_message_routing(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code

    (tmp_path / "session.py").write_text(
        "def reconnect_session():\n    return True\n", encoding="utf-8"
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        result = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="please explain how reconnect_session handles recovery",
            enable_lsp=False,
        )

    assert any(item.symbol == "reconnect_session" for item in result.results)


@pytest.mark.asyncio
async def test_coverage_uses_only_requested_path_scope(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text(
        "def scoped_target():\n    return True\n", encoding="utf-8"
    )
    (tmp_path / "elsewhere").mkdir()
    for index in range(4):
        (tmp_path / "elsewhere" / f"other_{index}.py").write_text(
            f"def other_{index}():\n    return {index}\n", encoding="utf-8"
        )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        result = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="scoped_target",
            paths=("src",),
            enable_lsp=False,
        )

    python = next(item for item in result.capabilities if item.language == "python")
    assert python.indexed_files == 1
    assert python.workspace_files == 1
    assert result.coverage == 1.0


@pytest.mark.asyncio
async def test_live_overlay_reports_new_caller_and_partial_relationships(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code

    (tmp_path / "service.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8"
    )
    workspace_id = await _index(tmp_path)
    (tmp_path / "caller.py").write_text(
        "from service import helper\n\ndef new_caller():\n    return helper()\n",
        encoding="utf-8",
    )

    async with async_session_factory() as db:
        result = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="helper",
            intent="impact",
            freshness_policy="strict",
            enable_lsp=False,
        )

    assert result.freshness == "partial"
    assert result.pending_edges >= 1
    assert any(item.symbol == "new_caller" for item in result.results)
    assert any(
        "helper" in relation for item in result.results for relation in item.callees
    )


@pytest.mark.asyncio
async def test_fallback_honors_language_and_kind_filters(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code

    (tmp_path / "worker.ex").write_text(
        "defmodule Worker do\n  def target(id), do: id\nend\n", encoding="utf-8"
    )
    async with async_session_factory() as db:
        included = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=None,
            query="target",
            languages=("unsupported:.ex",),
            enable_lsp=False,
        )
        excluded_language = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=None,
            query="target",
            languages=("python",),
            enable_lsp=False,
        )
        excluded_kind = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=None,
            query="target",
            kinds=("function",),
            enable_lsp=False,
        )

    assert included.results[0].language == "unsupported:.ex"
    assert excluded_language.results == []
    assert excluded_kind.results == []


@pytest.mark.asyncio
async def test_fast_policy_avoids_live_scan_but_balanced_verifies_dirty_source(
    setup_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import app.services.code_query_service as query_service
    from app.core.db import async_session_factory

    _init_git(tmp_path)
    (tmp_path / "target.py").write_text(
        "def exact_target():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "other.py").write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    workspace_id = await _index(tmp_path)
    (tmp_path / "other.py").write_text("value = 2\n", encoding="utf-8")
    calls = 0

    async def lexical(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal calls
        calls += 1
        return [], __import__("collections").Counter({".py": 2})

    monkeypatch.setattr(query_service, "_lexical_search", lexical)
    query_service._query_cache.clear()
    async with async_session_factory() as db:
        await query_service.query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="exact_target",
            freshness_policy="fast",
            enable_lsp=False,
        )
        await query_service.query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="exact_target",
            freshness_policy="balanced",
            enable_lsp=False,
        )

    assert calls == 1


@pytest.mark.asyncio
async def test_changed_graph_metadata_marks_relationships_partial(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code

    _init_git(tmp_path)
    (tmp_path / "service.py").write_text(
        "def target():\n    return 1\n", encoding="utf-8"
    )
    manifest = tmp_path / "pyproject.toml"
    manifest.write_text('[project]\nname = "before"\n', encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial")
    workspace_id = await _index(tmp_path)
    manifest.write_text('[project]\nname = "after"\n', encoding="utf-8")

    async with async_session_factory() as db:
        result = await query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="target",
            freshness_policy="fast",
            enable_lsp=False,
        )

    assert result.freshness == "partial"
    assert result.pending_edges >= 1
    assert any("graph metadata" in item for item in result.limitations)


@pytest.mark.asyncio
async def test_clean_exact_graph_hit_skips_full_source_scan(
    setup_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import app.services.code_query_service as query_service
    from app.core.db import async_session_factory

    (tmp_path / "service.py").write_text(
        "def exact_graph_symbol():\n    return 1\n", encoding="utf-8"
    )
    workspace_id = await _index(tmp_path)

    async def unexpected_scan(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("exact clean graph hit should not scan source contents")

    monkeypatch.setattr(query_service, "_lexical_search", unexpected_scan)
    async with async_session_factory() as db:
        result = await query_service.query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=workspace_id,
            query="exact_graph_symbol",
            enable_lsp=False,
        )

    assert result.strategy == "graph"
    assert result.results[0].symbol == "exact_graph_symbol"


@pytest.mark.asyncio
async def test_hybrid_search_filters_kind_before_limit(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services import code_graph_service as service

    classes = "\n".join(f"class Target{i}:\n    pass\n" for i in range(20))
    (tmp_path / "symbols.py").write_text(
        f"{classes}\ndef TargetFunction():\n    return 1\n", encoding="utf-8"
    )
    workspace_id = await _index(tmp_path)
    async with async_session_factory() as db:
        ranked = await service.search_nodes_ranked(
            db,
            workspace_id=workspace_id,
            query="Target",
            kind="function",
            limit=1,
        )

    assert len(ranked) == 1
    assert ranked[0].node.name == "TargetFunction"
    assert "requested kind" in ranked[0].match_reasons

    async with async_session_factory() as db:
        natural = await service.search_nodes_ranked(
            db,
            workspace_id=workspace_id,
            query="where does TargetFunction handle the request",
            limit=3,
        )
    assert any(item.node.name == "TargetFunction" for item in natural)


@pytest.mark.asyncio
async def test_graph_path_filter_does_not_match_sibling_prefix(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services import code_graph_service as service

    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "application").mkdir(parents=True)
    (tmp_path / "src" / "app" / "inside.py").write_text(
        "def shared_target():\n    return 'inside'\n", encoding="utf-8"
    )
    (tmp_path / "src" / "application" / "outside.py").write_text(
        "def shared_target():\n    return 'outside'\n", encoding="utf-8"
    )
    workspace_id = await _index(tmp_path)

    async with async_session_factory() as db:
        ranked = await service.search_nodes_ranked(
            db,
            workspace_id=workspace_id,
            query="shared_target",
            paths=("src/app",),
            limit=20,
        )

    assert ranked
    assert {item.node.file_path for item in ranked} == {"src/app/inside.py"}


@pytest.mark.asyncio
async def test_code_query_tool_is_always_visible():
    from app.agent.tools.builtin.code_graph import code_query

    assert code_query.deferred is False
    assert code_query.read_only is True
    assert code_query.definition["function"]["name"] == "code_query"
    schema = code_query.definition["function"]["parameters"]
    assert set(schema["properties"]) == {"query", "max_files"}
    assert schema["required"] == ["query"]


@pytest.mark.asyncio
async def test_large_change_parses_query_relevant_overlay_first(
    setup_db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import app.services.code_query_service as query_service
    from app.core.db import async_session_factory

    dirty = frozenset(f"src/file_{index}.py" for index in range(250))
    lexical_hit = query_service._LexicalHit(
        file_path="src/file_7.py",
        line=3,
        column=5,
        text="def reconnect_session():",
        score=100,
        reasons=("definition-like line",),
    )
    captured: list[str] = []

    async def working(_root):  # noqa: ANN001, ANN202
        return query_service._WorkingTreeState(
            revision="large",
            changed=dirty,
            deleted=frozenset(),
            source="watcher",
        )

    async def lexical(_root, _query, _paths, _limit):  # noqa: ANN001, ANN202
        return [lexical_hit], __import__("collections").Counter({".py": 250})

    async def overlay(_root, paths, _query, _registry, _limit, _languages, _kinds):  # noqa: ANN001, ANN202
        captured.extend(paths)
        return []

    monkeypatch.setattr(query_service, "_working_tree", working)
    monkeypatch.setattr(query_service, "_lexical_search", lexical)
    monkeypatch.setattr(query_service, "_overlay_candidates", overlay)
    async with async_session_factory() as db:
        result = await query_service.query_code(
            db,
            root_path=str(tmp_path),
            workspace_id=None,
            query="reconnect_session",
            enable_lsp=False,
        )

    assert captured == ["src/file_7.py"]
    assert result.pending_edges == 249
    assert any("Large working-tree change" in item for item in result.limitations)


@pytest.mark.asyncio
async def test_code_query_searches_authorized_sibling_repositories(
    setup_db, tmp_path: Path
):
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_query

    primary = tmp_path / "frontend"
    sibling = tmp_path / "backend"
    primary.mkdir()
    sibling.mkdir()
    (primary / "view.py").write_text("def render_view():\n    pass\n", encoding="utf-8")
    (sibling / "session.py").write_text(
        "def restore_remote_session():\n    return True\n", encoding="utf-8"
    )
    await _index(primary)
    await _index(sibling)

    token = set_sandbox(
        SandboxConfig(workspace=str(primary), extra_workspace_paths=[str(sibling)])
    )
    try:
        rendered = await code_query(query="restore_remote_session")
    finally:
        _sandbox_ctx.reset(token)

    assert "strategy: project:" in rendered
    assert "backend/session.py" in rendered
    assert "restore_remote_session" in rendered


@pytest.mark.asyncio
async def test_multi_workspace_query_applies_one_global_output_budget(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_query_service import query_code_across_workspaces

    roots = [tmp_path / "frontend", tmp_path / "backend"]
    for root in roots:
        root.mkdir()
        for index in range(4):
            (root / f"target_{index}.py").write_text(
                "def shared_target():\n"
                + "    payload = '"
                + ("x" * 900)
                + "'\n"
                + "    return payload\n",
                encoding="utf-8",
            )

    async with async_session_factory() as db:
        result = await query_code_across_workspaces(
            db,
            workspaces=[
                (str(roots[0]), None, "frontend"),
                (str(roots[1]), None, "backend"),
            ],
            query="shared_target",
            budget_tokens=500,
            limit=10,
            enable_lsp=False,
        )

    rendered_chars = sum(
        len(item.snippet or "")
        + len(item.file_path)
        + len(item.symbol or "")
        + sum(map(len, item.match_reasons + item.callers + item.callees + item.tests))
        + 120
        for item in result.results
    )
    assert rendered_chars <= 2_000
    assert result.truncated is True
