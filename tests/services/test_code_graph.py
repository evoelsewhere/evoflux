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

        neighbours = await code_neighbors(name="Service.run", direction="out")
        assert "helper" in neighbours
    finally:
        _sandbox_ctx.reset(token)


# ── Embedding text + RRF (P3, pure functions) ─────────────────────────────────


def test_node_embedding_text_composes_and_clamps_whitespace():
    from app.services.code_graph.embeddings import node_embedding_text

    text = node_embedding_text(
        kind="function",
        name="run",
        qualified_name="Service.run",
        signature="def run(self) -> None",
        docstring="Do  the   thing.\n\nMore.",
    )
    assert "function Service.run" in text
    assert "run" in text
    assert "def run(self) -> None" in text
    assert "Do the thing. More." in text  # whitespace collapsed


def test_node_embedding_text_omits_redundant_name():
    from app.services.code_graph.embeddings import node_embedding_text

    text = node_embedding_text(
        kind="module",
        name="m",
        qualified_name="m",
        signature=None,
        docstring=None,
    )
    assert text == "module m"


def test_reciprocal_rank_fusion_rewards_overlap():
    from uuid import uuid4

    from app.services.code_graph_service import _reciprocal_rank_fusion

    a, b, c = uuid4(), uuid4(), uuid4()
    fused = _reciprocal_rank_fusion([a, b], [c, a], 0.5)
    assert set(fused) == {a, b, c}
    assert fused[0] == a  # ranked by both lists → highest fused score


def test_reciprocal_rank_fusion_weight_extremes():
    from uuid import uuid4

    from app.services.code_graph_service import _reciprocal_rank_fusion

    a, b = uuid4(), uuid4()
    # weight 0 → semantic ignored, lexical wins.
    assert _reciprocal_rank_fusion([a], [b], 0.0)[0] == a
    # weight 1 → lexical ignored, semantic wins.
    assert _reciprocal_rank_fusion([a], [b], 1.0)[0] == b


# ── sqlite-vec vector store (P3) ──────────────────────────────────────────────


def test_vector_store_roundtrip_and_knn(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    from app.services.code_graph import vector_store as vec

    db = str(tmp_path / "v.sqlite")
    with vec.open_connection(db) as conn:
        written = vec.replace_workspace_vectors(
            conn,
            workspace_id="ws1",
            dim=3,
            rows=[
                ("a", [1.0, 0.0, 0.0]),
                ("b", [0.0, 1.0, 0.0]),
                ("c", [0.0, 0.0, 1.0]),
            ],
        )
        assert written == 3
        assert vec.count_workspace(conn, "ws1") == 3

        hits = vec.knn(conn, workspace_id="ws1", query_vector=[0.9, 0.1, 0.0], k=2)
        assert hits[0][0] == "a"
        assert len(hits) == 2


def test_vector_store_skips_dimension_mismatch(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    from app.services.code_graph import vector_store as vec

    db = str(tmp_path / "v.sqlite")
    with vec.open_connection(db) as conn:
        written = vec.replace_workspace_vectors(
            conn,
            workspace_id="ws1",
            dim=3,
            rows=[("a", [1.0, 0.0, 0.0]), ("bad", [1.0, 0.0])],
        )
    assert written == 1


def test_vector_store_partitions_and_deletes_by_workspace(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    from app.services.code_graph import vector_store as vec

    db = str(tmp_path / "v.sqlite")
    with vec.open_connection(db) as conn:
        vec.replace_workspace_vectors(
            conn, workspace_id="ws1", dim=3, rows=[("a", [1.0, 0.0, 0.0])]
        )
        vec.replace_workspace_vectors(
            conn, workspace_id="ws2", dim=3, rows=[("x", [0.0, 1.0, 0.0])]
        )
        assert vec.count_workspace(conn, "ws1") == 1
        assert vec.count_workspace(conn, "ws2") == 1

        # KNN stays scoped to its own partition.
        hits = vec.knn(conn, workspace_id="ws2", query_vector=[0.0, 1.0, 0.0], k=5)
        assert {nid for nid, _ in hits} == {"x"}

        vec.delete_workspace(conn, "ws1")
        conn.commit()
        assert vec.count_workspace(conn, "ws1") == 0
        assert vec.count_workspace(conn, "ws2") == 1


# ── Hybrid semantic search end-to-end (P3, fake embedder) ─────────────────────

# Deterministic stand-in for fastembed/onnxruntime (unavailable on some dev
# boxes): the vector is a bag-of-words count over a fixed 8-word vocabulary, so
# semantically related text lands near a matching query without any ML runtime.
_FAKE_VOCAB = ["alpha", "beta", "gamma", "delta", "widget", "func", "run", "misc"]


def _fake_vector(text: str) -> list[float]:
    low = text.lower()
    vector = [float(low.count(token)) for token in _FAKE_VOCAB]
    if not any(vector):
        vector[-1] = 1.0
    return vector


class _FakeEmbedder:
    def __init__(self, dim: int) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_fake_vector(t) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return _fake_vector(text)


def _semantic_settings(weight: float = 0.6):
    from app.core.runtime_settings import CodeGraphSettings, RuntimeSettings

    return RuntimeSettings(
        code_graph=CodeGraphSettings(
            semantic_enabled=True,
            embedding_model="fake-test",
            embedding_dim=len(_FAKE_VOCAB),
            semantic_weight=weight,
        )
    )


async def _setup_semantic_workspace(tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import reindex_workspace
    from app.services.coding_workspace_service import upsert_coding_workspace

    # "widget" mentions "alpha" only in its docstring → lexical name search for
    # "alpha" misses it, but the embedding (which includes the docstring) hits.
    (tmp_path / "w.py").write_text(
        'def widget():\n    """alpha alpha alpha"""\n    pass\n',
        encoding="utf-8",
    )
    (tmp_path / "other.py").write_text(
        "def helper():\n    return 1\n", encoding="utf-8"
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
    return workspace_id, stats


@pytest.mark.asyncio
async def test_hybrid_search_surfaces_semantic_only_match(
    setup_db, tmp_path: Path, monkeypatch
):
    pytest.importorskip("sqlite_vec")
    import app.services.code_graph.embeddings as emb
    import app.services.code_graph_service as cgs
    from app.core.db import async_session_factory

    monkeypatch.setattr(cgs, "load_runtime_settings", _semantic_settings)
    monkeypatch.setattr(emb, "get_embedder", lambda model, dim: _FakeEmbedder(dim))

    workspace_id, stats = await _setup_semantic_workspace(tmp_path)
    assert stats.embedded_count > 0

    async with async_session_factory() as db:
        # Lexical-only would miss "alpha" (it's only in the docstring), but the
        # semantic pass surfaces the "widget" symbol.
        hits = await cgs.search_nodes(db, workspace_id=workspace_id, query="alpha")
        assert any(n.name == "widget" for n in hits)

    # Semantic status reflects the stored vectors.
    status = await cgs.get_semantic_status(workspace_id=workspace_id)
    assert status.enabled is True
    assert status.vector_count == stats.embedded_count


@pytest.mark.asyncio
async def test_semantic_disabled_keeps_lexical_only(setup_db, tmp_path: Path):
    from app.core.db import async_session_factory
    from app.services.code_graph_service import search_nodes

    workspace_id, _ = await _setup_semantic_workspace(tmp_path)

    async with async_session_factory() as db:
        # Default settings → semantic off → docstring-only term finds nothing.
        hits = await search_nodes(db, workspace_id=workspace_id, query="alpha")
        assert hits == []


@pytest.mark.asyncio
async def test_reindex_degrades_when_embedder_unavailable(
    setup_db, tmp_path: Path, monkeypatch
):
    pytest.importorskip("sqlite_vec")
    import app.services.code_graph.embeddings as emb
    import app.services.code_graph_service as cgs
    from app.core.db import async_session_factory

    def _broken(model, dim):
        raise emb.EmbeddingUnavailable("onnxruntime DLL load failed")

    monkeypatch.setattr(cgs, "load_runtime_settings", _semantic_settings)
    monkeypatch.setattr(emb, "get_embedder", _broken)

    workspace_id, stats = await _setup_semantic_workspace(tmp_path)
    # Graph still built; embedding step degraded to zero vectors.
    assert stats.node_count > 0
    assert stats.embedded_count == 0

    async with async_session_factory() as db:
        # Semantic query fails over to lexical, which still works.
        hits = await cgs.search_nodes(db, workspace_id=workspace_id, query="widget")
        assert any(n.name == "widget" for n in hits)


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


@pytest.mark.asyncio
async def test_incremental_reindex_updates_and_prunes_vectors(
    setup_db, tmp_path: Path, monkeypatch
):
    pytest.importorskip("sqlite_vec")
    import os

    import app.services.code_graph.embeddings as emb
    import app.services.code_graph_service as cgs
    from app.core.db import async_session_factory

    monkeypatch.setattr(cgs, "load_runtime_settings", _semantic_settings)
    monkeypatch.setattr(emb, "get_embedder", lambda model, dim: _FakeEmbedder(dim))

    (tmp_path / "a.py").write_text("def alpha_fn():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def beta_fn():\n    pass\n", encoding="utf-8")
    workspace_id = await _register_and_full_index(tmp_path)

    async with async_session_factory() as db:
        first = await cgs.get_semantic_status(workspace_id=workspace_id)
    # alpha_fn + beta_fn → two embeddable function vectors.
    assert first.vector_count == 2

    # Delete b.py and add a symbol to a.py → beta_fn's vector must be pruned and
    # gamma_fn's added. alpha_fn keeps its node id (vector upserted in place).
    os.remove(tmp_path / "b.py")
    (tmp_path / "a.py").write_text(
        "def alpha_fn():\n    pass\n\n\ndef gamma_fn():\n    pass\n", encoding="utf-8"
    )

    async with async_session_factory() as db:
        stats = await cgs.reindex_workspace(
            db, workspace_id=workspace_id, root_path=str(tmp_path), incremental=True
        )
        await db.commit()
    assert stats.changed_files == 1
    assert stats.deleted_files == 1
    assert stats.embedded_count >= 1

    async with async_session_factory() as db:
        after = await cgs.get_semantic_status(workspace_id=workspace_id)
    # alpha_fn + gamma_fn remain; beta_fn pruned. A stale (un-pruned) beta_fn
    # vector would make this 3 instead of 2.
    assert after.vector_count == 2


# ── Vector store incremental helpers (P4) ─────────────────────────────────────


def test_vector_store_upsert_and_delete_nodes(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    from app.services.code_graph import vector_store as vec

    db = str(tmp_path / "v.sqlite")
    with vec.open_connection(db) as conn:
        vec.ensure_table(conn, 3)
        written = vec.upsert_rows(
            conn,
            workspace_id="ws1",
            dim=3,
            rows=[("a", [1.0, 0.0, 0.0]), ("b", [0.0, 1.0, 0.0])],
        )
        assert written == 2
        assert vec.count_workspace(conn, "ws1") == 2

        # Upsert is idempotent on node_id — replacing "a" keeps the count at 2.
        vec.upsert_rows(conn, workspace_id="ws1", dim=3, rows=[("a", [0.0, 0.0, 1.0])])
        assert vec.count_workspace(conn, "ws1") == 2
        hits = vec.knn(conn, workspace_id="ws1", query_vector=[0.0, 0.0, 1.0], k=1)
        assert hits[0][0] == "a"  # "a" now points at the z-axis

        vec.delete_nodes(conn, ["a"])
        conn.commit()
        assert vec.count_workspace(conn, "ws1") == 1
