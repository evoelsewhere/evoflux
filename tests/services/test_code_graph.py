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
    assert calls[0].dst_name == "obj.run"


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


def test_typescript_namespace_qualifies_declarations():
    source = b"""namespace Validation {
    export interface Rule {}
    export class Validator { run() {} }
}
"""
    result = TypeScriptParser().parse(file_path="validation.ts", source=source)
    qualified = {node.name: node.qualified_name for node in result.nodes}

    assert qualified["Validation"] == "Validation"
    assert qualified["Rule"] == "Validation.Rule"
    assert qualified["Validator"] == "Validation.Validator"
    assert qualified["run"] == "Validation.Validator.run"


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
async def test_code_tool_workspace_resolution_flushes_index_first(
    monkeypatch, tmp_path
) -> None:
    from app.agent.tools.builtin import code_graph as tool_module
    from app.services.code_graph import watcher as watcher_module

    order: list[str] = []
    workspace_id = object()
    sibling = tmp_path / "sibling"

    class _Sandbox:
        workspace_root = tmp_path
        extra_workspace_paths = [str(sibling)]

    async def flush(workspace: str) -> None:
        order.append(f"flush:{workspace}")

    async def resolve(_db, *, path: str):
        order.append(f"resolve:{path}")
        return workspace_id

    monkeypatch.setattr(tool_module, "get_sandbox", lambda: _Sandbox())
    monkeypatch.setattr(watcher_module, "flush_code_graph_index", flush)
    monkeypatch.setattr(tool_module.svc, "resolve_workspace_id", resolve)

    resolved = await tool_module._resolve_workspace(object())

    workspace = str(tmp_path)
    assert resolved is workspace_id
    # Compatibility tools keep a strict active-repo barrier, but sibling
    # snapshots no longer serialize every query behind project-wide flushes.
    assert order == [f"flush:{workspace}", f"resolve:{workspace}"]


@pytest.mark.asyncio
async def test_code_tools_against_indexed_workspace(tmp_path):
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import (
        code_graph,
        code_overview,
        code_search,
    )

    await _index_sample_workspace(tmp_path)

    token = set_sandbox(SandboxConfig(workspace=str(tmp_path)))
    try:
        overview = await code_overview()
        assert "Files: 2" in overview
        assert "helper" in overview  # top-referenced symbol

        found = await code_search(query="Service")
        assert "Service" in found
        assert "main.py" in found

        graph = await code_graph(name="Service.run")
        assert "Service.run" in graph
        assert "helper" in graph  # calls helper
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_code_graph_surfaces_ambiguous_relationship_candidates(tmp_path):
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_graph
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace

    (tmp_path / "a.py").write_text("def dup():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def dup():\n    pass\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text("def caller():\n    dup()\n", encoding="utf-8")
    async with async_session_factory() as db:
        workspace = await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        await reindex_workspace(db, workspace_id=workspace.id, root_path=str(tmp_path))
        await db.commit()

    token = set_sandbox(SandboxConfig(workspace=str(tmp_path)))
    try:
        output = await code_graph(name="caller", direction="out")
    finally:
        _sandbox_ctx.reset(token)

    assert "ambiguous calls 'dup' (2 candidates)" in output
    assert "a.py:1-2" in output
    assert "b.py:1-2" in output


@pytest.mark.asyncio
async def test_code_graph_limit_param(tmp_path):
    """code_graph's `limit` must actually cap output for symbols with a
    large fan-out (e.g. an interface with 80+ methods) — regression test
    for the limit param being threaded through _code_graph and clamped,
    but never actually applied to any of _render_graph's output slices
    (calls/extends/called-by/imported-by/cross-repo were all hardcoded
    to fixed-size slices regardless of what the caller asked for)."""
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_graph

    (tmp_path / "main.py").write_text(
        "def a(): pass\ndef b(): pass\ndef c(): pass\n"
        "def caller():\n    a()\n    b()\n    c()\n",
        encoding="utf-8",
    )
    async with async_session_factory() as db:
        ws = await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        await reindex_workspace(db, workspace_id=ws.id, root_path=str(tmp_path))
        await db.commit()

    token = set_sandbox(SandboxConfig(workspace=str(tmp_path)))
    try:
        out = await code_graph(name="caller", direction="out", limit=2)
        assert "calls (3): a, b … and 1 more" in out
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_code_graph_imports_falls_back_to_file_node(tmp_path):
    """code_graph(name=<class>) must show the containing file's imports —
    regression test for import edges attaching to the file node rather
    than the class, which the 7-tool-to-4 consolidation dropped entirely
    (the old code_neighbors(edge_kind="imports") fallback wasn't ported,
    and the new tool didn't render outbound imports at all)."""
    from app.core.db import async_session_factory
    from app.models.code_graph import CodeEdge
    from app.services import code_graph_service as svc
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_graph

    (tmp_path / "main.py").write_text(
        "class Service:\n    def run(self):\n        pass\n", encoding="utf-8"
    )
    (tmp_path / "other.py").write_text("def target():\n    pass\n", encoding="utf-8")

    async with async_session_factory() as db:
        ws = await upsert_coding_workspace(db, path=str(tmp_path))
        await db.commit()
        await reindex_workspace(db, workspace_id=ws.id, root_path=str(tmp_path))
        await db.commit()

    async with async_session_factory() as db:
        file_node = await svc.find_file_node(
            db, workspace_id=ws.id, file_path="main.py"
        )
        assert file_node is not None
        target_node = (
            await svc.find_nodes_by_name(db, workspace_id=ws.id, name="target")
        )[0]
        db.add(
            CodeEdge(
                workspace_id=ws.id,
                src_id=file_node.id,
                dst_id=target_node.id,
                kind="imports",
                file_path="main.py",
                line=1,
            )
        )
        await db.commit()

    token = set_sandbox(SandboxConfig(workspace=str(tmp_path)))
    try:
        # Class-level lookup used to show nothing for imports at all —
        # they're attached to the containing file, not the class.
        out = await code_graph(name="Service")
        assert "target" in out
        assert "imports are file-level" in out
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_code_graph_cross_repo_limit_param(tmp_path):
    """code_graph must cap how many cross-repo refs it shows — regression
    test for unbounded cross-repo output (a heavily-referenced symbol could
    dump ~100 lines with no way to reduce it) — and, separately, that each
    cross-repo line is still prefixed with its source repo's name (that
    label resolution was dropped in the 7-to-4 tool consolidation)."""
    from app.core.db import async_session_factory
    from app.models.code_graph import CrossRepoEdge
    from app.services.code_graph_service import (
        find_nodes_by_name,
        reindex_workspace,
        resolve_workspace_id,
    )
    from app.services.coding_project_service import create_project
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_graph

    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "main.py").write_text(
        "def caller_one(): pass\ndef caller_two(): pass\ndef caller_three(): pass\n",
        encoding="utf-8",
    )
    (repo_b / "lib.py").write_text("def shared():\n    return 1\n", encoding="utf-8")

    async with async_session_factory() as db:
        project = await create_project(
            db, name="Cross Repo Limit Test", workspace_paths=[str(repo_a), str(repo_b)]
        )
        await db.commit()
        project_id = project.id

    async with async_session_factory() as db:
        repo_a_id = await resolve_workspace_id(db, path=str(repo_a))
        repo_b_id = await resolve_workspace_id(db, path=str(repo_b))
        await reindex_workspace(db, workspace_id=repo_a_id, root_path=str(repo_a))
        await reindex_workspace(db, workspace_id=repo_b_id, root_path=str(repo_b))
        await db.commit()

    async with async_session_factory() as db:
        shared_node = (
            await find_nodes_by_name(db, workspace_id=repo_b_id, name="shared")
        )[0]
        for caller_name in ("caller_one", "caller_two", "caller_three"):
            caller_node = (
                await find_nodes_by_name(db, workspace_id=repo_a_id, name=caller_name)
            )[0]
            db.add(
                CrossRepoEdge(
                    project_id=project_id,
                    src_workspace_id=repo_a_id,
                    src_node_id=caller_node.id,
                    src_file_path="main.py",
                    raw_reference="shared",
                    dst_name_hint="shared",
                    kind="calls",
                    status="resolved",
                    method="static_fqn",
                    confidence=1.0,
                    dst_workspace_id=repo_b_id,
                    dst_node_id=shared_node.id,
                    dst_qualified_name=shared_node.qualified_name,
                )
            )
        await db.commit()

    token = set_sandbox(SandboxConfig(workspace=str(repo_b)))
    try:
        out = await code_graph(name="shared", limit=1)
        assert "referenced by (3 cross-repo)" in out
        assert out.count(" ← repo-a/") == 1
        assert "and 2 more" in out

        outbound_only = await code_graph(name="shared", direction="out", limit=1)
        assert "referenced by" not in outbound_only
    finally:
        _sandbox_ctx.reset(token)


def test_code_graph_renders_all_indexed_relationship_kinds():
    """The agent tool must not discard relationship kinds stored by the indexer."""
    from uuid import uuid4

    from app.agent.tools.builtin.code_graph import _render_graph
    from app.models.code_graph import CodeNode

    workspace_id = uuid4()

    def node(name: str) -> CodeNode:
        return CodeNode(
            workspace_id=workspace_id,
            file_path="main.py",
            language="python",
            kind="class",
            name=name,
            qualified_name=name,
            line_start=1,
            line_end=1,
        )

    subject = node("Subject")
    output = _render_graph(
        subject,
        [
            ("implements", node("Protocol")),
            ("uses", node("Dependency")),
            ("references", node("Payload")),
            ("decorated_by", node("Decorator")),
            ("contains", node("member")),
        ],
        [
            ("uses", node("Consumer")),
            ("references", node("Api")),
            ("decorated_by", node("Route")),
            ("contains", node("module")),
        ],
    )

    assert "implements (1): Protocol" in output
    assert "uses (1): Dependency" in output
    assert "references (1): Payload" in output
    assert "decorated by (1): Decorator" in output
    assert "contains (1): member" in output
    assert "used by (1): Consumer" in output
    assert "referenced by (1): Api" in output
    assert "decorates (1): Route" in output
    assert "contained by (1): module" in output


@pytest.mark.asyncio
async def test_code_graph_limit_applies_independently_per_section(tmp_path):
    """code_graph shows local callers and cross-repo refs as separate
    sections, each capped by the same `limit` independently (not pooled
    into one combined budget the way the pre-consolidation code_references
    did) — this verifies neither section's limit starves or gets starved
    by the other when both are present at once."""
    from app.core.db import async_session_factory
    from app.models.code_graph import CrossRepoEdge
    from app.services.code_graph_service import (
        find_nodes_by_name,
        reindex_workspace,
        resolve_workspace_id,
    )
    from app.services.coding_project_service import create_project
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_graph

    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    (repo_a / "main.py").write_text(
        "def caller_one(): pass\ndef caller_two(): pass\ndef caller_three(): pass\n",
        encoding="utf-8",
    )
    (repo_b / "lib.py").write_text(
        "def shared():\n    return 1\n\ndef local_caller():\n    shared()\n",
        encoding="utf-8",
    )

    async with async_session_factory() as db:
        project = await create_project(
            db, name="Refs Limit Test", workspace_paths=[str(repo_a), str(repo_b)]
        )
        await db.commit()
        project_id = project.id

    async with async_session_factory() as db:
        repo_a_id = await resolve_workspace_id(db, path=str(repo_a))
        repo_b_id = await resolve_workspace_id(db, path=str(repo_b))
        await reindex_workspace(db, workspace_id=repo_a_id, root_path=str(repo_a))
        await reindex_workspace(db, workspace_id=repo_b_id, root_path=str(repo_b))
        await db.commit()

    async with async_session_factory() as db:
        shared_node = (
            await find_nodes_by_name(db, workspace_id=repo_b_id, name="shared")
        )[0]
        for caller_name in ("caller_one", "caller_two", "caller_three"):
            caller_node = (
                await find_nodes_by_name(db, workspace_id=repo_a_id, name=caller_name)
            )[0]
            db.add(
                CrossRepoEdge(
                    project_id=project_id,
                    src_workspace_id=repo_a_id,
                    src_node_id=caller_node.id,
                    src_file_path="main.py",
                    raw_reference="shared",
                    dst_name_hint="shared",
                    kind="calls",
                    status="resolved",
                    method="static_fqn",
                    confidence=1.0,
                    dst_workspace_id=repo_b_id,
                    dst_node_id=shared_node.id,
                    dst_qualified_name=shared_node.qualified_name,
                )
            )
        await db.commit()

    token = set_sandbox(SandboxConfig(workspace=str(repo_b)))
    try:
        out = await code_graph(name="shared", limit=2)
        assert "called by (1): local_caller" in out  # the 1 intra-repo ref, unaffected
        assert out.count(" ← repo-a/") == 2  # 2 of 3 cross-repo refs shown at limit=2
        assert "and 1 more" in out
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_code_tools_auto_detect_scope_resolves_sibling_repo(tmp_path):
    """code_search/code_graph must auto-resolve a symbol that only exists
    in a sibling repo of the same project — the new consolidated tools
    auto-detect project scope instead of requiring an explicit scope
    param (the gap that originally motivated giving code_neighbors/
    code_references a scope param at all)."""
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_project_service import create_project
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_graph, code_search

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
        found = await code_search(query="shared_helper")
        assert "shared_helper" in found
        assert "repo-b" in found

        # code_graph: both outbound and inbound resolved in the sibling repo,
        # in one call — direction="both" is the default.
        graph = await code_graph(name="shared_helper")
        assert "support" in graph
        assert "other_caller" in graph
        assert "repo-b" in graph
    finally:
        _sandbox_ctx.reset(token)


@pytest.mark.asyncio
async def test_code_graph_not_found_without_project_link(tmp_path):
    """A workspace with no CodingProject linking it to the repo that
    actually has the symbol must not see it — auto-scope depends on real
    project membership, not just being adjacent on disk."""
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace
    from app.agent.sandbox import SandboxConfig, _sandbox_ctx, set_sandbox
    from app.agent.tools.builtin.code_graph import code_graph

    lonely = tmp_path / "lonely-repo"
    other = tmp_path / "other-repo"
    lonely.mkdir()
    other.mkdir()
    (lonely / "main.py").write_text("def caller():\n    pass\n", encoding="utf-8")
    (other / "lib.py").write_text("def shared_helper():\n    pass\n", encoding="utf-8")

    async with async_session_factory() as db:
        ws_lonely = await upsert_coding_workspace(db, path=str(lonely))
        ws_other = await upsert_coding_workspace(db, path=str(other))
        await db.commit()
        await reindex_workspace(db, workspace_id=ws_lonely.id, root_path=str(lonely))
        await reindex_workspace(db, workspace_id=ws_other.id, root_path=str(other))
        await db.commit()

    token = set_sandbox(SandboxConfig(workspace=str(lonely)))
    try:
        out = await code_graph(name="shared_helper")
        assert "No symbol named" in out
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
    (active_repo / "unrelated.py").write_text(
        "def unrelated():\n    pass\n", encoding="utf-8"
    )
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
    (active_repo / "unrelated.py").write_text(
        "def unrelated():\n    pass\n", encoding="utf-8"
    )
    # "Helper" is a substring of "HelperImpl" — the sibling fallback's
    # lexical search can match a query for one against both.
    (repo_a / "helper.py").write_text(
        "class Helper:\n    pass\n\nclass HelperImpl(Helper):\n    pass\n",
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
