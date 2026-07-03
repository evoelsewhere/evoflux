"""Tests for the code knowledge graph (P1: parsers, indexer, service)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.code_graph.indexer import index_workspace
from app.services.code_graph.parsers.python import PythonParser
from app.services.code_graph.parsers.ecmascript import TypeScriptParser
from app.services.code_graph.parsers.registry import build_registry, default_registry
from app.services.code_graph.types import (
    EDGE_CALLS,
    EDGE_CONTAINS,
    EDGE_INHERITS,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_METHOD,
)


# ── Python parser ─────────────────────────────────────────────────────────────


def _by_kind(nodes, kind):
    return [n for n in nodes if n.kind == kind]


def test_python_parser_extracts_class_method_function():
    source = (
        b'"""Module doc."""\n\n'
        b"class Animal(Base):\n"
        b'    """An animal."""\n'
        b"    def speak(self):\n"
        b"        make_sound()\n\n"
        b"def top():\n"
        b"    Animal().speak()\n"
    )
    result = PythonParser().parse(file_path="a.py", source=source)

    classes = _by_kind(result.nodes, NODE_CLASS)
    methods = _by_kind(result.nodes, NODE_METHOD)
    functions = _by_kind(result.nodes, NODE_FUNCTION)

    assert [c.name for c in classes] == ["Animal"]
    assert classes[0].docstring == "An animal."
    assert [m.qualified_name for m in methods] == ["Animal.speak"]
    assert [f.name for f in functions] == ["top"]


def test_python_parser_emits_contains_inherits_calls():
    source = b"class Animal(Base):\n    def speak(self):\n        make_sound()\n"
    result = PythonParser().parse(file_path="a.py", source=source)
    edge_kinds = {e.kind for e in result.edges}
    assert EDGE_CONTAINS in edge_kinds
    assert EDGE_INHERITS in edge_kinds
    assert EDGE_CALLS in edge_kinds

    inherits = [e for e in result.edges if e.kind == EDGE_INHERITS]
    assert inherits[0].dst_name == "Base"

    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    assert calls[0].dst_name == "make_sound"


def test_python_method_call_resolves_attribute_name():
    source = b"def top():\n    obj.run()\n"
    result = PythonParser().parse(file_path="a.py", source=source)
    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    assert calls[0].dst_name == "run"


# ── TypeScript parser ─────────────────────────────────────────────────────────


def test_typescript_parser_extracts_symbols():
    source = (
        b"export class Animal extends Base implements I {\n"
        b"  speak(): void {\n"
        b"    makeSound();\n"
        b"  }\n"
        b"}\n\n"
        b"export function top(): void {\n"
        b"  new Animal().speak();\n"
        b"}\n\n"
        b"interface Shape {\n"
        b"  area(): number;\n"
        b"}\n"
    )
    result = TypeScriptParser().parse(file_path="a.ts", source=source)
    names = {n.name for n in result.nodes}
    assert {"Animal", "speak", "top", "Shape"} <= names

    inherits = [e for e in result.edges if e.kind == EDGE_INHERITS]
    assert any(e.dst_name == "Base" for e in inherits)
    calls = [e for e in result.edges if e.kind == EDGE_CALLS]
    assert any(e.dst_name == "makeSound" for e in calls)


def test_typescript_arrow_function_variable_is_function():
    source = b"const arrowFn = (a: number) => helper(a);\n"
    result = TypeScriptParser().parse(file_path="a.ts", source=source)
    functions = _by_kind(result.nodes, NODE_FUNCTION)
    assert [f.name for f in functions] == ["arrowFn"]


def test_javascript_object_literal_methods_are_methods():
    """Shorthand, function-valued, and arrow-valued object properties are all
    methods — only the shorthand form (`foo() {}`) produced a method_definition
    node; `bar: function() {}` and `baz: () => {}` used to be dropped entirely."""
    source = (
        b"const obj = {\n"
        b"  foo() { return 1; },\n"
        b"  bar: function() { return 2; },\n"
        b"  baz: () => { return 3; },\n"
        b"  'quoted-key': function() {},\n"
        b"};\n"
    )
    result = TypeScriptParser().parse(file_path="a.ts", source=source)
    methods = _by_kind(result.nodes, NODE_METHOD)
    assert {m.qualified_name for m in methods} == {
        "obj.foo",
        "obj.bar",
        "obj.baz",
        "obj.quoted-key",
    }


def test_javascript_object_literal_computed_key_is_skipped():
    """Computed keys have no static name and must not crash or emit a node."""
    source = b"const obj = {\n  [dynamicKey]: function() {},\n};\n"
    result = TypeScriptParser().parse(file_path="a.ts", source=source)
    methods = _by_kind(result.nodes, NODE_METHOD)
    assert methods == []


def test_javascript_prototype_and_this_assignment_are_methods():
    """Pre-ES6 method patterns (`Obj.prototype.foo = ...`, `this.foo = ...`)
    were previously invisible to the indexer — not counted as a function or
    a method at all."""
    source = (
        b"Obj.prototype.qux = function() { return 4; };\n"
        b"this.instanceMethod = function() {};\n"
        b"this.arrowMethod = () => {};\n"
    )
    result = TypeScriptParser().parse(file_path="a.ts", source=source)
    methods = _by_kind(result.nodes, NODE_METHOD)
    assert {m.name for m in methods} == {"qux", "instanceMethod", "arrowMethod"}


def test_typescript_type_literal_signatures_are_not_methods():
    """Type-level object shapes (`type`/`interface`) use property_signature /
    method_signature nodes, not `pair` — they must not be misclassified as
    real methods since they have no function body."""
    source = (
        b"type Foo = {\n"
        b"  bar: () => void;\n"
        b"};\n"
        b"interface Shape {\n"
        b"  area(): number;\n"
        b"}\n"
    )
    result = TypeScriptParser().parse(file_path="a.ts", source=source)
    names = {n.name for n in result.nodes}
    assert "bar" not in names
    assert "area" not in names


# ── Registry ──────────────────────────────────────────────────────────────────


def test_registry_resolves_by_extension():
    registry = default_registry()
    assert registry.for_path("x.py").name == "python"
    assert registry.for_path("x.ts").name == "typescript"
    assert registry.for_path("x.tsx").name == "tsx"
    assert registry.for_path("x.js").name == "javascript"
    assert registry.for_path("x.unknown") is None


def test_registry_can_restrict_languages():
    registry = build_registry(["python"])
    assert registry.for_path("x.py") is not None
    assert registry.for_path("x.ts") is None


# ── Workspace indexer (cross-file resolution) ─────────────────────────────────


def test_index_workspace_resolves_cross_file_calls(tmp_path: Path):
    (tmp_path / "helpers.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "main.py").write_text("def run():\n    helper()\n", encoding="utf-8")

    index = index_workspace(tmp_path)

    names = {n.name for n in index.nodes}
    assert {"helper", "run"} <= names
    assert not index.errors

    # A calls edge from run -> helper should be resolved across files.
    key_by_name = {n.name: n.key for n in index.nodes}
    resolved = [
        e
        for e in index.edges
        if e.kind == EDGE_CALLS
        and e.src_key == key_by_name["run"]
        and e.dst_key == key_by_name["helper"]
    ]
    assert len(resolved) == 1


def test_index_workspace_drops_ambiguous_names(tmp_path: Path):
    # Two definitions named "dup" → a call to "dup" is ambiguous and dropped.
    (tmp_path / "a.py").write_text("def dup():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def dup():\n    pass\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("def caller():\n    dup()\n", encoding="utf-8")

    index = index_workspace(tmp_path)
    calls = [e for e in index.edges if e.kind == EDGE_CALLS]
    assert calls == []


def test_index_workspace_respects_gitignore(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("def hidden():\n    pass\n", encoding="utf-8")
    (tmp_path / "kept.py").write_text("def shown():\n    pass\n", encoding="utf-8")

    index = index_workspace(tmp_path)
    names = {n.name for n in index.nodes}
    assert "shown" in names
    assert "hidden" not in names


# ── DB service ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reindex_workspace_and_queries(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import (
        get_index_status,
        get_neighbors,
        reindex_workspace,
        search_nodes,
    )
    from app.services.coding_workspace_service import upsert_coding_workspace

    (tmp_path / "helpers.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "main.py").write_text(
        "class Service:\n    def run(self):\n        helper()\n", encoding="utf-8"
    )

    async with async_session_factory() as db:
        ws = await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        workspace_id = ws.id

    async with async_session_factory() as db:
        stats = await reindex_workspace(
            db, workspace_id=workspace_id, root_path=str(tmp_path)
        )
        await db.commit()

    assert stats.file_count == 2
    assert stats.node_count >= 4  # 2 files + class + method + function
    assert stats.error_count == 0

    async with async_session_factory() as db:
        status = await get_index_status(db, workspace_id=workspace_id)
        assert status["files"] == 2
        assert status["nodes"] == stats.node_count

        hits = await search_nodes(db, workspace_id=workspace_id, query="helper")
        assert any(n.name == "helper" for n in hits)

        run_hits = await search_nodes(
            db, workspace_id=workspace_id, query="run", kind=NODE_METHOD
        )
        assert len(run_hits) == 1
        run_node = run_hits[0]

        neighbors = await get_neighbors(
            db,
            workspace_id=workspace_id,
            node_id=run_node.id,
            direction="out",
            edge_kind=EDGE_CALLS,
        )
        assert any(node.name == "helper" for _, node in neighbors)


@pytest.mark.asyncio
async def test_reindex_workspace_is_idempotent(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import get_index_status, reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace

    (tmp_path / "m.py").write_text("def f():\n    pass\n", encoding="utf-8")

    async with async_session_factory() as db:
        ws = await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        workspace_id = ws.id

    async def _reindex() -> int:
        async with async_session_factory() as db:
            stats = await reindex_workspace(
                db, workspace_id=workspace_id, root_path=str(tmp_path)
            )
            await db.commit()
            return stats.node_count

    first = await _reindex()
    second = await _reindex()
    assert first == second

    async with async_session_factory() as db:
        status = await get_index_status(db, workspace_id=workspace_id)
    assert status["nodes"] == second


# ── Agent tools (P2) ──────────────────────────────────────────────────────────


async def _index_sample_workspace(tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace

    (tmp_path / "helpers.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "main.py").write_text(
        "class Service:\n    def run(self):\n        helper()\n", encoding="utf-8"
    )
    async with async_session_factory() as db:
        ws = await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        await reindex_workspace(db, workspace_id=ws.id, root_path=str(tmp_path))
        await db.commit()


@pytest.mark.asyncio
async def test_code_tools_report_when_workspace_not_indexed(tmp_path):
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_search

    token = set_sandbox(SandboxConfig(workspace=str(tmp_path)))
    try:
        out = await code_search(query="anything")
    finally:
        _sandbox_ctx.reset(token)
    assert "no code index" in out.lower()


@pytest.mark.asyncio
async def test_code_tools_against_indexed_workspace(tmp_path):
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import (
        code_neighbors,
        code_overview,
        code_search,
        code_symbol,
    )

    await _index_sample_workspace(tmp_path)

    token = set_sandbox(SandboxConfig(workspace=str(tmp_path)))
    try:
        overview = await code_overview()
        assert "files" in overview
        assert "class=1" in overview

        found = await code_search(query="Service")
        assert "Service" in found
        assert "main.py" in found

        symbol = await code_symbol(name="Service.run")
        assert "Service.run" in symbol
        assert "helper" in symbol  # calls helper

        neighbours = await code_neighbors(name="Service.run")
        assert "helper" in neighbours
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_code_tools_scope_project_resolves_sibling_repo(tmp_path):
    """scope='project' must resolve a symbol that only exists in a sibling
    repo — the gap that motivated giving code_neighbors/code_references a
    scope param instead of adding separate cross-repo tools."""
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_project_service import create_project
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import (
        code_neighbors,
        code_references,
        code_search,
    )

    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "main.py").write_text("def caller():\n    pass\n", encoding="utf-8")
    (repo_b / "lib.py").write_text(
        "def shared_helper():\n    return support()\n\n"
        "def support():\n    return 1\n\n"
        "def other_caller():\n    shared_helper()\n",
        encoding="utf-8",
    )

    async with async_session_factory() as db:
        await create_project(
            db, name="Scope Test", workspace_paths=[str(repo_a), str(repo_b)]
        )
        await db.commit()

    async with async_session_factory() as db:
        from app.services.code_graph_service import resolve_workspace_id

        ws_a_id = await resolve_workspace_id(db, path=str(repo_a))
        ws_b_id = await resolve_workspace_id(db, path=str(repo_b))
        await reindex_workspace(db, workspace_id=ws_a_id, root_path=str(repo_a))
        await reindex_workspace(db, workspace_id=ws_b_id, root_path=str(repo_b))
        await db.commit()

    token = set_sandbox(SandboxConfig(workspace=str(repo_a)))
    try:
        # code_search: symbol only exists in the sibling repo.
        found = await code_search(query="shared_helper", scope="project")
        assert "shared_helper" in found
        assert "repo-b" in found

        # code_neighbors: outbound from a symbol resolved in the sibling repo.
        neighbours = await code_neighbors(name="shared_helper", scope="project")
        assert "support" in neighbours
        assert "repo-b" in neighbours

        # code_references: inbound to a symbol resolved in the sibling repo.
        refs = await code_references(name="shared_helper", scope="project")
        assert "other_caller" in refs
        assert "repo-b" in refs

        # Without scope='project', the symbol isn't visible from repo_a.
        local_only = await code_neighbors(name="shared_helper")
        assert "No symbol named" in local_only
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_code_path_resolves_pure_sibling_repo_path(tmp_path):
    """code_path must find a path between two symbols that BOTH live in a
    sibling repo, with neither in the active session's own workspace.

    Regression test: _code_path used to discard the workspace_id that
    _resolve_name_anywhere_in_project resolved each candidate to, and always
    seeded find_shortest_path's BFS with the ACTIVE session's workspace_id
    instead. When source and target both live in a sibling repo, that seed
    was wrong from the very first BFS iteration, so the intra-repo edge
    query looked in the wrong workspace and found nothing — even though a
    direct edge existed. Confirmed against real OpenMRS data before this fix
    (paths entirely within a non-active sibling repo always failed)."""
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_project_service import create_project
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_path

    active_repo = tmp_path / "active-repo"
    repo_a = tmp_path / "repo-a"
    active_repo.mkdir()
    repo_a.mkdir()
    (active_repo / "unrelated.py").write_text("def unrelated():\n    pass\n", encoding="utf-8")
    (repo_a / "main.py").write_text(
        "def foo():\n    return bar()\n\ndef bar():\n    return 1\n", encoding="utf-8"
    )

    async with async_session_factory() as db:
        await create_project(
            db, name="Path Scope Test", workspace_paths=[str(active_repo), str(repo_a)]
        )
        await db.commit()

    async with async_session_factory() as db:
        from app.services.code_graph_service import resolve_workspace_id

        active_id = await resolve_workspace_id(db, path=str(active_repo))
        repo_a_id = await resolve_workspace_id(db, path=str(repo_a))
        await reindex_workspace(db, workspace_id=active_id, root_path=str(active_repo))
        await reindex_workspace(db, workspace_id=repo_a_id, root_path=str(repo_a))
        await db.commit()

    # Active session is rooted at active_repo, which has neither foo nor bar.
    token = set_sandbox(SandboxConfig(workspace=str(active_repo)))
    try:
        result = await code_path(source="foo", target="bar", max_hops=6)
        assert "1 hops" in result, result
        assert "foo" in result and "bar" in result
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_code_path_tries_other_candidates_before_same_symbol(tmp_path):
    """A degenerate same-node match among multiple fuzzy candidates must not
    short-circuit a real path between two other, genuinely different
    candidates.

    Regression test: when source/target names are ambiguous enough that the
    sibling-repo fallback search returns multiple candidates for each side,
    _code_path used to try combinations in order and return immediately on
    the first one — including a combination that degenerately resolved both
    sides to the SAME node ("same symbol"), even when a different, correct
    combination existed with a real path between two distinct symbols.
    Confirmed against real OpenMRS data (RestHelperService -> "same symbol"
    instead of the real 1-hop `implements` edge to RestHelperServiceImpl)."""
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_project_service import create_project
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_path

    active_repo = tmp_path / "active-repo"
    repo_a = tmp_path / "repo-a"
    active_repo.mkdir()
    repo_a.mkdir()
    (active_repo / "unrelated.py").write_text("def unrelated():\n    pass\n", encoding="utf-8")
    # "Helper" is a substring of "HelperImpl" — the sibling fallback's
    # lexical search can match a query for one against both.
    (repo_a / "helper.py").write_text(
        "class Helper:\n    pass\n\n"
        "class HelperImpl(Helper):\n    pass\n",
        encoding="utf-8",
    )

    async with async_session_factory() as db:
        await create_project(
            db, name="Same Symbol Test", workspace_paths=[str(active_repo), str(repo_a)]
        )
        await db.commit()

    async with async_session_factory() as db:
        from app.services.code_graph_service import resolve_workspace_id

        active_id = await resolve_workspace_id(db, path=str(active_repo))
        repo_a_id = await resolve_workspace_id(db, path=str(repo_a))
        await reindex_workspace(db, workspace_id=active_id, root_path=str(active_repo))
        await reindex_workspace(db, workspace_id=repo_a_id, root_path=str(repo_a))
        await db.commit()

    token = set_sandbox(SandboxConfig(workspace=str(active_repo)))
    try:
        result = await code_path(source="Helper", target="HelperImpl", max_hops=6)
        assert "same symbol" not in result.lower(), result
        assert "inherits" in result, result
    finally:
        _sandbox_ctx.reset(token)


# ── Incremental indexing (P4) ─────────────────────────────────────────────────


async def _register_and_full_index(tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace

    async with async_session_factory() as db:
        ws = await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        workspace_id = ws.id
    async with async_session_factory() as db:
        await reindex_workspace(db, workspace_id=workspace_id, root_path=str(tmp_path))
        await db.commit()
    return workspace_id


@pytest.mark.asyncio
async def test_incremental_reindex_noop_when_unchanged(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import get_index_status, reindex_workspace

    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    workspace_id = await _register_and_full_index(tmp_path)

    async with async_session_factory() as db:
        before = await get_index_status(db, workspace_id=workspace_id)

    async with async_session_factory() as db:
        stats = await reindex_workspace(
            db, workspace_id=workspace_id, root_path=str(tmp_path), incremental=True
        )
        await db.commit()

    assert stats.changed_files == 0
    assert stats.deleted_files == 0
    assert stats.node_count == before["nodes"]
    assert stats.edge_count == before["edges"]


@pytest.mark.asyncio
async def test_incremental_reindex_adds_symbol_and_preserves_node_ids(
    setup_db, tmp_path: Path
):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import (
        find_nodes_by_name,
        get_neighbors,
        reindex_workspace,
        search_nodes,
    )

    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def caller():\n    foo()\n", encoding="utf-8")
    workspace_id = await _register_and_full_index(tmp_path)

    async with async_session_factory() as db:
        foo = (await find_nodes_by_name(db, workspace_id=workspace_id, name="foo"))[0]
        foo_id_before = foo.id
        # caller → foo edge exists (incoming on foo).
        incoming = await get_neighbors(
            db,
            workspace_id=workspace_id,
            node_id=foo.id,
            direction="in",
            edge_kind=EDGE_CALLS,
        )
        assert any(node.name == "caller" for _, node in incoming)

    # Edit a.py: change foo's body (still defined) and add a new function.
    (tmp_path / "a.py").write_text(
        "def foo():\n    return 2\n\n\ndef bar():\n    return 0\n", encoding="utf-8"
    )

    async with async_session_factory() as db:
        stats = await reindex_workspace(
            db, workspace_id=workspace_id, root_path=str(tmp_path), incremental=True
        )
        await db.commit()
    assert stats.changed_files == 1
    assert stats.deleted_files == 0

    async with async_session_factory() as db:
        # New symbol indexed.
        assert any(
            n.name == "bar"
            for n in await search_nodes(db, workspace_id=workspace_id, query="bar")
        )
        # foo kept its node id (stable symbol).
        foo_after = (
            await find_nodes_by_name(db, workspace_id=workspace_id, name="foo")
        )[0]
        assert foo_after.id == foo_id_before
        # Incoming cross-file edge from the UNCHANGED file survives.
        incoming = await get_neighbors(
            db,
            workspace_id=workspace_id,
            node_id=foo_after.id,
            direction="in",
            edge_kind=EDGE_CALLS,
        )
        assert any(node.name == "caller" for _, node in incoming)


@pytest.mark.asyncio
async def test_incremental_reindex_removes_deleted_file(setup_db, tmp_path: Path):
    import os

    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace, search_nodes

    (tmp_path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def caller():\n    foo()\n", encoding="utf-8")
    workspace_id = await _register_and_full_index(tmp_path)

    os.remove(tmp_path / "b.py")

    async with async_session_factory() as db:
        stats = await reindex_workspace(
            db, workspace_id=workspace_id, root_path=str(tmp_path), incremental=True
        )
        await db.commit()
    assert stats.deleted_files == 1
    assert stats.changed_files == 0

    async with async_session_factory() as db:
        assert await search_nodes(db, workspace_id=workspace_id, query="caller") == []
        assert any(
            n.name == "foo"
            for n in await search_nodes(db, workspace_id=workspace_id, query="foo")
        )


