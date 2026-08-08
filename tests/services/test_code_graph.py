"""Tests for the code knowledge graph (P1: parsers, indexer, service)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.code_graph.indexer import index_workspace
from app.services.code_graph.parsers.python import PythonParser
from app.services.code_graph.parsers.ecmascript import TsxParser, TypeScriptParser
from app.services.code_graph.parsers.registry import build_registry, default_registry
from app.services.code_graph.types import (
    EDGE_CALLS,
    EDGE_CONTAINS,
    EDGE_INHERITS,
    EDGE_REFERENCES,
    NODE_CLASS,
    NODE_FUNCTION,
    NODE_METHOD,
)


def test_content_hash_changes_when_index_format_changes(monkeypatch):
    from app.services.code_graph import indexer

    current = indexer.content_hash(b"unchanged source")
    monkeypatch.setattr(indexer, "INDEX_FORMAT_VERSION", "next")

    assert indexer.content_hash(b"unchanged source") != current


def test_content_hash_embeds_the_current_index_format_tag():
    from app.services.code_graph import indexer

    digest = indexer.content_hash(b"source")

    assert len(digest) == 64
    assert digest.startswith(indexer.index_format_tag())


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


def test_shared_identifier_indexing_retains_multilanguage_reference_callsites(
    tmp_path: Path,
):
    """Direct symbol reads use one shared extraction contract across grammars."""
    (tmp_path / "settings.py").write_text(
        'PY_TAG = "python"\n\n'
        "def use_python(value):\n"
        "    if value == PY_TAG:\n"
        "        return PY_TAG\n",
        encoding="utf-8",
    )
    (tmp_path / "settings.ts").write_text(
        'export const TS_TAG = "typescript";\n'
        "export function useTs(value: string) {\n"
        "  return value === TS_TAG ? TS_TAG : value;\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "settings.go").write_text(
        'package settings\n\nconst GoTag = "go"\n\n'
        "func useGo(value string) string {\n"
        "    if value == GoTag { return GoTag }\n"
        "    return value\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "settings.rs").write_text(
        'const RUST_TAG: &str = "rust";\n\n'
        "fn use_rust(value: &str) -> &str {\n"
        "    if value == RUST_TAG { RUST_TAG } else { value }\n"
        "}\n",
        encoding="utf-8",
    )

    index = index_workspace(tmp_path)
    nodes = {node.name: node.key for node in index.nodes}
    references = [edge for edge in index.edges if edge.kind == EDGE_REFERENCES]

    for name in ("PY_TAG", "TS_TAG", "GoTag", "RUST_TAG"):
        assert any(edge.dst_key == nodes[name] for edge in references), name
    python_lines = {edge.line for edge in references if edge.dst_key == nodes["PY_TAG"]}
    assert python_lines == {4, 5}


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


def test_typescript_higher_order_callback_variable_is_function():
    source = b"const handleSubmit = useCallback(async () => { sendMessage() }, [])\n"

    result = TypeScriptParser().parse(file_path="view.ts", source=source)

    functions = _by_kind(result.nodes, NODE_FUNCTION)
    assert [function.name for function in functions] == ["handleSubmit"]
    assert any(
        edge.kind == "calls"
        and edge.src_local_id.startswith("handleSubmit#")
        and edge.dst_name == "sendMessage"
        for edge in result.edges
    )


def test_typescript_selector_result_is_not_misclassified_as_function():
    source = b"const sendMessage = useStore((state) => state.sendMessage)\n"

    result = TypeScriptParser().parse(file_path="view.ts", source=source)

    send_message = next(node for node in result.nodes if node.name == "sendMessage")
    assert send_message.kind != NODE_FUNCTION


def test_typescript_parser_extracts_framework_agnostic_callback_references():
    source = b"""
function onMessage() {}
function register(source: EventSource) {
  source.addEventListener('message', onMessage)
  return <InputBar onSubmit={onMessage} />
}
"""
    result = TsxParser().parse(file_path="stream.tsx", source=source)

    callback_edges = [
        edge
        for edge in result.edges
        if edge.kind == "references" and edge.dst_name == "onMessage"
    ]
    assert len(callback_edges) == 2
    assert all(edge.src_local_id.startswith("register#") for edge in callback_edges)
    assert any(
        edge.kind == "references"
        and edge.dst_name == "InputBar"
        and edge.src_local_id.startswith("register#")
        for edge in result.edges
    )


def test_callback_reference_resolves_to_function_valued_symbol(tmp_path: Path):
    (tmp_path / "view.tsx").write_text(
        "export const InputBar = () => null\n"
        "export function View() { return <InputBar /> }\n",
        encoding="utf-8",
    )

    index = index_workspace(tmp_path)

    nodes = {node.qualified_name: node.key for node in index.nodes}
    assert any(
        edge.kind == "references"
        and edge.src_key == nodes["View"]
        and edge.dst_key == nodes["InputBar"]
        for edge in index.edges
    )


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


def test_index_workspace_prefers_same_file_call_when_name_exists_elsewhere(
    tmp_path: Path,
):
    (tmp_path / "a.py").write_text(
        "def helper():\n    pass\n\ndef caller():\n    return helper()\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "def helper():\n    pass\n",
        encoding="utf-8",
    )

    index = index_workspace(tmp_path)
    caller = next(node for node in index.nodes if node.name == "caller")
    local_helper = next(
        node
        for node in index.nodes
        if node.name == "helper" and node.file_path == "a.py"
    )

    assert any(
        edge.kind == EDGE_CALLS
        and edge.src_key == caller.key
        and edge.dst_key == local_helper.key
        for edge in index.edges
    )


def test_index_workspace_respects_gitignore(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("def hidden():\n    pass\n", encoding="utf-8")
    (tmp_path / "kept.py").write_text("def shown():\n    pass\n", encoding="utf-8")

    index = index_workspace(tmp_path)
    names = {n.name for n in index.nodes}
    assert "shown" in names
    assert "hidden" not in names


def test_incremental_index_respects_gitignored_directory(tmp_path: Path):
    from app.services.code_graph.indexer import index_files

    (tmp_path / ".gitignore").write_text("vendor/\n", encoding="utf-8")
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "stdlib.py").write_text(
        "def hidden_vendor_symbol():\n    pass\n", encoding="utf-8"
    )

    result = index_files(tmp_path, ["vendor/stdlib.py"])

    assert result.files == []
    assert result.nodes == []


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
    from app.services.code_graph_service import (
        find_nodes_by_name,
        get_index_status,
        reindex_workspace,
    )
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
    async with async_session_factory() as db:
        node_id = (
            await find_nodes_by_name(db, workspace_id=workspace_id, name="f")
        )[0].id

    second = await _reindex()
    assert first == second

    async with async_session_factory() as db:
        status = await get_index_status(db, workspace_id=workspace_id)
        refreshed_id = (
            await find_nodes_by_name(db, workspace_id=workspace_id, name="f")
        )[0].id
    assert status["nodes"] == second
    assert refreshed_id == node_id


# ── Agent tools (P2) ──────────────────────────────────────────────────────────


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
async def test_incremental_reindex_recreates_ambiguous_edges(setup_db, tmp_path: Path):
    import json

    from sqlmodel import select

    from app.core.db import async_session_factory
    from app.models.code_graph import CodeAmbiguousEdge
    from app.services.code_graph_service import reindex_workspace

    (tmp_path / "a.py").write_text("def dup():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def dup():\n    pass\n", encoding="utf-8")
    caller_path = tmp_path / "caller.py"
    caller_path.write_text("def caller():\n    dup()\n", encoding="utf-8")
    workspace_id = await _register_and_full_index(tmp_path)

    async def _ambiguous_rows():
        async with async_session_factory() as db:
            return (
                await db.exec(
                    select(CodeAmbiguousEdge).where(
                        CodeAmbiguousEdge.workspace_id == workspace_id
                    )
                )
            ).all()

    before = await _ambiguous_rows()
    assert len(before) == 1
    assert len(json.loads(before[0].candidate_node_ids)) == 2

    caller_path.write_text(
        "def caller():\n    # shifted call site\n    dup()\n", encoding="utf-8"
    )
    async with async_session_factory() as db:
        await reindex_workspace(
            db, workspace_id=workspace_id, root_path=str(tmp_path), incremental=True
        )
        await db.commit()

    after = await _ambiguous_rows()
    assert len(after) == 1
    assert after[0].line == 3
    assert len(json.loads(after[0].candidate_node_ids)) == 2


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
