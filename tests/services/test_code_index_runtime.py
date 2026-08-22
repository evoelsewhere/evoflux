"""End-to-end coverage for the dependency-free ported indexing runtime."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.code_index.models import IndexStats, RepositoryScope
from app.services.code_index.project import (
    ProgressCallback,
    RepositoryIndex,
    RepositoryIndexRegistry,
)
from app.services.code_index.paths import paths_for_repository
from app.services.code_index.query import _fts_query, search_index
from app.services.code_index.service import query_code_context
from app.services.code_index.chunking import (
    MAX_CHUNK_CHARS,
    MIN_CHUNK_CHARS,
    split_source,
)
from app.services.code_index.pipeline import (
    SymbolRow,
    _processing_identity,
    processing_identity,
)


@pytest.fixture
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(cache))
    return cache


def test_ui_search_uses_fts_prefixes_for_partial_symbol_names() -> None:
    assert _fts_query("settle_pay") == '"settle_pay"*'
    assert _fts_query("payment service") == '"payment"* OR "service"*'


def test_processing_identity_tracks_shared_leaf_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _processing_identity.cache_clear()
    baseline = processing_identity("component.ts")
    original_read_bytes = Path.read_bytes

    def changed_dependency(path: Path) -> bytes:
        content = original_read_bytes(path)
        if path.name == "symbol_leaves.py":
            return content + b"\n# synthetic parser change\n"
        return content

    monkeypatch.setattr(Path, "read_bytes", changed_dependency)
    _processing_identity.cache_clear()
    changed = processing_identity("component.ts")
    _processing_identity.cache_clear()

    assert changed != baseline


@pytest.mark.asyncio
async def test_desired_state_add_update_delete_and_noop(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    source = repository / "service.py"
    source.write_text("def old_name():\n    return 1\n", encoding="utf-8")

    index = await RepositoryIndex.create(repository)
    initial = await index.update()
    assert initial.files == 1
    assert initial.symbols >= 2
    assert initial.chunks >= 1

    unchanged = await index.update()
    assert unchanged == initial

    source.write_text("def new_name():\n    return 2\n", encoding="utf-8")
    updated = await index.update()
    assert updated.version != initial.version
    with index.database.readonly() as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM code_symbols WHERE kind != 'file'"
            )
        }
    assert "new_name" in names
    assert "old_name" not in names

    source.unlink()
    deleted = await index.update()
    assert deleted.files == 0
    assert deleted.chunks == 0
    assert deleted.symbols == 0
    assert deleted.relations == 0


@pytest.mark.asyncio
async def test_noop_refresh_reuses_persisted_file_metadata(
    tmp_path: Path,
    isolated_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    source = repository / "service.py"
    source.write_text("def unchanged():\n    return 1\n", encoding="utf-8")
    index = await RepositoryIndex.create(repository)
    initial = await index.update()
    original_read_bytes = Path.read_bytes
    source_reads = 0

    def tracked_read_bytes(path: Path) -> bytes:
        nonlocal source_reads
        if path == source:
            source_reads += 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", tracked_read_bytes)

    unchanged = await index.update()

    assert unchanged == initial
    assert source_reads == 0


@pytest.mark.asyncio
async def test_concurrent_refreshes_share_one_committed_target(
    tmp_path: Path,
    isolated_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def stable_refresh():\n    return 1\n", encoding="utf-8"
    )
    index = await RepositoryIndex.create(repository)
    update_calls = 0
    original_update = index._update_sync

    def tracked_update(full: bool, progress: ProgressCallback | None) -> IndexStats:
        nonlocal update_calls
        update_calls += 1
        return original_update(full, progress)

    monkeypatch.setattr(index, "_update_sync", tracked_update)

    results = await asyncio.gather(*(index.update() for _ in range(8)))

    assert update_calls == 1
    assert len({item.version for item in results}) == 1
    assert all(item.files == 1 and not item.errors for item in results)


@pytest.mark.asyncio
async def test_registry_purge_evicts_and_deletes_repository_cache(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def disposable_index():\n    return 1\n", encoding="utf-8"
    )
    registry = RepositoryIndexRegistry()
    original = await registry.get(repository)
    await original.update()
    index_dir = paths_for_repository(repository).directory
    assert index_dir.is_dir()

    await registry.purge(repository)

    assert not index_dir.exists()
    recreated = await registry.get(repository)
    assert recreated is not original
    assert recreated.paths.target_db.is_file()


@pytest.mark.asyncio
async def test_index_work_does_not_use_asyncio_default_executor(
    tmp_path: Path,
    isolated_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def isolated_executor():\n    return 1\n", encoding="utf-8"
    )
    index = await RepositoryIndex.create(repository)

    async def reject_default_executor(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("code-index used asyncio's shared default executor")

    monkeypatch.setattr(asyncio, "to_thread", reject_default_executor)

    stats = await index.update()
    result = await search_index(
        [("repo", index)],
        query="isolated_executor",
        languages=None,
        paths=None,
        limit=10,
        stats={"repo": stats},
    )

    assert stats.files == 1
    assert result.hits and result.hits[0].file_path == "service.py"


def test_registry_and_refresh_are_safe_across_event_loops(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def cross_loop_refresh():\n    return 1\n", encoding="utf-8"
    )
    registry = RepositoryIndexRegistry()
    barrier = threading.Barrier(4)

    def get_index() -> RepositoryIndex:
        barrier.wait()
        return asyncio.run(registry.get(repository))

    with ThreadPoolExecutor(max_workers=4) as executor:
        indexes = list(executor.map(lambda _value: get_index(), range(4)))
    assert all(item is indexes[0] for item in indexes)

    barrier = threading.Barrier(4)

    def refresh() -> str | None:
        barrier.wait()
        return asyncio.run(indexes[0].update()).version

    with ThreadPoolExecutor(max_workers=4) as executor:
        versions = list(executor.map(lambda _value: refresh(), range(4)))
    assert len(set(versions)) == 1


@pytest.mark.asyncio
async def test_cross_repository_edges_are_resolved_at_query_time(
    tmp_path: Path, isolated_cache: Path
) -> None:
    caller_repo = tmp_path / "caller"
    target_repo = tmp_path / "target"
    caller_repo.mkdir()
    target_repo.mkdir()
    (caller_repo / "entry.py").write_text(
        "from shared import target\n"
        "import shared\n\n"
        "def caller():\n    return target()\n\n"
        "def module_caller():\n    return shared.target()\n",
        encoding="utf-8",
    )
    (target_repo / "shared.py").write_text(
        "def target():\n    return 42\n",
        encoding="utf-8",
    )
    scopes = (
        RepositoryScope(caller_repo, "caller"),
        RepositoryScope(target_repo, "target"),
    )

    result = await query_code_context(
        scopes=scopes,
        action="callers",
        query="target",
        refresh=True,
        limit=20,
    )

    assert len(result.matches) == 1
    assert result.matches[0].repository == "target"
    assert any(
        relation.source.name == "caller"
        and relation.target.name == "target"
        and relation.cross_repo
        for relation in result.relations
    )
    assert any(
        relation.source.name == "module_caller"
        and relation.target.name == "target"
        and relation.cross_repo
        for relation in result.relations
    )

    narrowed_root = await query_code_context(
        scopes=scopes,
        action="callers",
        query="target",
        repository="target",
        refresh=False,
        limit=20,
    )
    assert any(relation.cross_repo for relation in narrowed_root.relations)


@pytest.mark.asyncio
async def test_package_import_resolves_to_a_matching_repository_root(
    tmp_path: Path, isolated_cache: Path
) -> None:
    caller_repo = tmp_path / "app"
    target_repo = tmp_path / "shared"
    unrelated_repo = tmp_path / "unrelated"
    (caller_repo / "src").mkdir(parents=True)
    (target_repo / "src").mkdir(parents=True)
    (unrelated_repo / "src").mkdir(parents=True)
    (caller_repo / "src" / "entry.ts").write_text(
        'import { target } from "@acme/shared";\n'
        "export function caller() { return target(); }\n",
        encoding="utf-8",
    )
    (target_repo / "src" / "index.ts").write_text(
        "export function target() { return 42; }\n", encoding="utf-8"
    )
    (unrelated_repo / "src" / "index.ts").write_text(
        "export function target() { return 0; }\n", encoding="utf-8"
    )

    result = await query_code_context(
        scopes=(
            RepositoryScope(caller_repo, "app"),
            RepositoryScope(target_repo, "shared"),
            RepositoryScope(unrelated_repo, "unrelated"),
        ),
        action="callers",
        query="target",
        repository="shared",
        refresh=True,
        limit=20,
    )

    assert any(
        relation.source.name == "caller"
        and relation.target.name == "target"
        and relation.cross_repo
        for relation in result.relations
    )


@pytest.mark.asyncio
async def test_go_module_import_resolves_the_exact_package_directory(
    tmp_path: Path, isolated_cache: Path
) -> None:
    caller_repo = tmp_path / "app"
    target_repo = tmp_path / "shared"
    caller_repo.mkdir()
    (target_repo / "pkg" / "one").mkdir(parents=True)
    (target_repo / "pkg" / "two").mkdir(parents=True)
    (caller_repo / "main.go").write_text(
        'package main\nimport "example.com/shared/pkg/one"\n'
        "func Caller() { one.Target() }\n",
        encoding="utf-8",
    )
    (target_repo / "pkg" / "one" / "one.go").write_text(
        "package one\nfunc Target() {}\n", encoding="utf-8"
    )
    (target_repo / "pkg" / "two" / "two.go").write_text(
        "package two\nfunc Target() {}\n", encoding="utf-8"
    )

    result = await query_code_context(
        scopes=(
            RepositoryScope(caller_repo, "app"),
            RepositoryScope(target_repo, "shared"),
        ),
        action="callers",
        query="Target",
        repository="shared",
        paths=["pkg/one/one.go"],
        refresh=True,
        limit=20,
    )

    assert [relation.source.qualified_name for relation in result.relations] == [
        "main.Caller"
    ]


@pytest.mark.asyncio
async def test_callees_do_not_bind_unknown_object_methods_to_same_named_functions(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def discard():\n"
        "    return 'unrelated'\n\n"
        "class Worker:\n"
        "    def helper(self):\n"
        "        return 1\n\n"
        "    def run(self):\n"
        "        values = set()\n"
        "        values.discard('x')\n"
        "        return self.helper()\n",
        encoding="utf-8",
    )
    result = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="callees",
        query="Worker.run",
        refresh=True,
        limit=20,
    )

    targets = {relation.target.qualified_name for relation in result.relations}
    assert "Worker.helper" in targets
    assert "discard" not in targets


@pytest.mark.asyncio
async def test_callees_do_not_lexically_bind_an_explicit_unknown_receiver(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "class Worker:\n"
        "    def save(self):\n"
        "        return 1\n\n"
        "    def run(self, other):\n"
        "        return other.save()\n",
        encoding="utf-8",
    )

    result = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="callees",
        query="Worker.run",
        refresh=True,
        limit=20,
    )

    assert result.relations == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry_path", "target_path", "other_path", "entry_source", "target_source"),
    [
        (
            "pkg_a/entry.py",
            "pkg_a/shared.py",
            "pkg_b/shared.py",
            "from .shared import target\n\ndef caller():\n    return target()\n",
            "def target():\n    return 1\n",
        ),
        (
            "src/entry.ts",
            "src/shared.ts",
            "lib/shared.ts",
            'import { target } from "./shared";\n'
            "export function caller() { return target(); }\n",
            "export function target() { return 1; }\n",
        ),
    ],
)
async def test_relative_imports_resolve_to_the_callers_module(
    tmp_path: Path,
    isolated_cache: Path,
    entry_path: str,
    target_path: str,
    other_path: str,
    entry_source: str,
    target_source: str,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    for relative, source in (
        (entry_path, entry_source),
        (target_path, target_source),
        (other_path, target_source),
    ):
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    result = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="callers",
        query="target",
        paths=[target_path],
        refresh=True,
        limit=20,
    )

    assert [relation.source.name for relation in result.relations] == ["caller"]
    assert result.relations[0].target.file_path == target_path


@pytest.mark.asyncio
async def test_namespace_import_resolves_static_member_calls(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    (repository / "Shared").mkdir(parents=True)
    (repository / "Main.cs").write_text(
        "using Shared; class Main { void Caller(){ Util.Target(); } }",
        encoding="utf-8",
    )
    (repository / "Shared" / "Util.cs").write_text(
        "namespace Shared { public class Util { public static void Target() {} } }",
        encoding="utf-8",
    )

    result = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="callers",
        query="Target",
        refresh=True,
        limit=20,
    )

    assert [relation.source.qualified_name for relation in result.relations] == [
        "Main.Caller"
    ]


@pytest.mark.asyncio
async def test_declaration_and_import_identifiers_are_not_false_references(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    (repository / "src").mkdir(parents=True)
    (repository / "src" / "main.rs").write_text(
        "mod shared; use crate::shared::target; fn caller(){ target(); }",
        encoding="utf-8",
    )
    (repository / "src" / "shared.rs").write_text(
        "pub fn target() {}", encoding="utf-8"
    )

    result = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="callers",
        query="target",
        paths=["src/shared.rs"],
        refresh=True,
        limit=20,
    )

    assert [
        (relation.kind, relation.source.qualified_name) for relation in result.relations
    ] == [("calls", "caller")]


@pytest.mark.asyncio
async def test_search_and_structural_grep_share_the_committed_index(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "handler.py").write_text(
        "def handle_request(user_id: str):\n"
        "    message = 'payment accepted'\n"
        "    return message\n",
        encoding="utf-8",
    )
    scopes = (RepositoryScope(repository, "repo"),)

    search = await query_code_context(
        scopes=scopes,
        action="search",
        query="payment accepted",
        refresh=True,
    )
    grep = await query_code_context(
        scopes=scopes,
        action="grep",
        query=r"def \NAME(\(ARGS*\)):",
        refresh=False,
    )

    assert search.hits[0].file_path == "handler.py"
    assert grep.hits[0].symbol == "function_definition"
    assert "handle_request" in grep.hits[0].content
    assert search.index_version == grep.index_version


@pytest.mark.asyncio
async def test_search_degrades_to_semantic_results_when_fts_is_missing(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "handler.py").write_text(
        "def handle_request():\n    return 'durable payment evidence'\n",
        encoding="utf-8",
    )
    index = await RepositoryIndex.create(repository)
    await index.update()
    with index.database.transaction() as connection:
        connection.execute("DROP TABLE source_chunks_fts")

    result = await search_index(
        [("repo", index)],
        query="durable payment evidence",
        languages=None,
        paths=None,
        limit=10,
        stats={"repo": index.stats()},
    )

    assert result.hits and result.hits[0].file_path == "handler.py"
    assert any("lexical index unavailable" in item for item in result.limitations)


@pytest.mark.asyncio
async def test_search_scores_only_lexical_candidates_when_available(
    tmp_path: Path,
    isolated_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    for ordinal in range(40):
        (repository / f"module_{ordinal}.py").write_text(
            f"def unrelated_{ordinal}():\n    return 'ordinary content {ordinal}'\n",
            encoding="utf-8",
        )
    (repository / "target.py").write_text(
        "def needle_identifier():\n    return 'needle_identifier'\n",
        encoding="utf-8",
    )
    index = await RepositoryIndex.create(repository)
    stats = await index.update()
    similarity_calls = 0

    def tracked_similarity(_left: bytes, _right: bytes) -> float:
        nonlocal similarity_calls
        similarity_calls += 1
        return 0.5

    monkeypatch.setattr("app.services.code_index.query.similarity", tracked_similarity)

    result = await search_index(
        [("repo", index)],
        query="needle_identifier",
        languages=None,
        paths=None,
        limit=10,
        stats={"repo": stats},
    )

    assert result.hits and result.hits[0].file_path == "target.py"
    assert similarity_calls < stats.chunks


@pytest.mark.asyncio
async def test_search_keeps_semantic_fallback_without_lexical_candidates(
    tmp_path: Path,
    isolated_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "billing.py").write_text(
        "def settle_account():\n    return 'balance cleared'\n",
        encoding="utf-8",
    )
    index = await RepositoryIndex.create(repository)
    stats = await index.update()
    similarity_calls = 0

    def tracked_similarity(_left: bytes, _right: bytes) -> float:
        nonlocal similarity_calls
        similarity_calls += 1
        return 0.5

    monkeypatch.setattr("app.services.code_index.query.similarity", tracked_similarity)

    result = await search_index(
        [("repo", index)],
        query="abstractconcept",
        languages=None,
        paths=None,
        limit=10,
        stats={"repo": stats},
    )

    assert result.hits
    assert similarity_calls == stats.chunks


@pytest.mark.asyncio
async def test_search_repairs_an_inconsistent_fts_target(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "handler.py").write_text(
        "def handle_request():\n    return 'durable lexical evidence'\n",
        encoding="utf-8",
    )
    index = await RepositoryIndex.create(repository)
    stats = await index.update()
    with index.database.transaction() as connection:
        connection.execute(
            "INSERT INTO source_chunks_fts(source_chunks_fts) VALUES ('delete-all')"
        )

    reopened = await RepositoryIndex.create(repository)
    result = await search_index(
        [("repo", reopened)],
        query="durable lexical evidence",
        languages=None,
        paths=None,
        limit=10,
        stats={"repo": stats},
    )
    with reopened.database.readonly() as connection:
        repaired_rows = connection.execute(
            "SELECT COUNT(*) FROM source_chunks_fts WHERE source_chunks_fts MATCH ?",
            ('"durable"',),
        ).fetchone()

    assert result.hits and result.hits[0].file_path == "handler.py"
    assert not result.limitations
    assert repaired_rows is not None and int(repaired_rows[0]) > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("selector_kind", ["dot", "absolute", "label"])
async def test_search_accepts_primary_repository_selectors(
    tmp_path: Path, isolated_cache: Path, selector_kind: str
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def indexed_selector():\n    return 'selector evidence'\n", encoding="utf-8"
    )
    selector = {
        "dot": ".",
        "absolute": str(repository),
        "label": "repo",
    }[selector_kind]
    result = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="search",
        query="selector evidence",
        repository=selector,
        refresh=True,
    )
    assert result.repositories == ("repo",)
    assert result.hits and result.hits[0].file_path == "service.py"
    definition = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="definition",
        query="indexed_selector",
        repository=selector,
        refresh=False,
    )
    assert len(definition.matches) == 1
    assert definition.matches[0].repository == "repo"


@pytest.mark.asyncio
async def test_repository_label_wins_over_duplicate_root_names(
    tmp_path: Path, isolated_cache: Path
) -> None:
    first = tmp_path / "one" / "repo"
    second = tmp_path / "two" / "repo"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "first.py").write_text("first_only = 'selected'\n", encoding="utf-8")
    (second / "second.py").write_text("second_only = 'selected'\n", encoding="utf-8")

    result = await query_code_context(
        scopes=(RepositoryScope(first, "repo"), RepositoryScope(second, "repo-2")),
        action="search",
        query="selected",
        repository="repo",
        refresh=True,
        limit=20,
    )

    assert result.repositories == ("repo",)
    assert {hit.file_path for hit in result.hits} == {"first.py"}


@pytest.mark.asyncio
async def test_graph_path_filter_is_applied_before_the_ambiguity_cap(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    for ordinal in range(110):
        (repository / f"module_{ordinal:03d}.py").write_text(
            "def duplicate():\n    return 1\n", encoding="utf-8"
        )
    selected_path = "selected.py"
    (repository / selected_path).write_text(
        "def duplicate():\n    return 2\n", encoding="utf-8"
    )

    result = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="definition",
        query="duplicate",
        paths=[selected_path],
        refresh=True,
    )

    assert len(result.matches) == 1
    assert result.matches[0].file_path == selected_path
    assert not result.limitations


@pytest.mark.asyncio
async def test_queries_read_one_committed_snapshot(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    source = repository / "handler.py"
    source.write_text("def old_name():\n    return 'old value'\n", encoding="utf-8")
    scopes = (RepositoryScope(repository, "repo"),)
    indexed = await query_code_context(
        scopes=scopes, action="search", query="old value", refresh=True
    )

    source.write_text("def new_name():\n    return 'new value'\n", encoding="utf-8")
    grep = await query_code_context(
        scopes=scopes,
        action="grep",
        query=r"def \NAME(\(ARGS*\)):",
        refresh=False,
    )
    definition = await query_code_context(
        scopes=scopes,
        action="definition",
        query="old_name",
        refresh=False,
    )

    assert indexed.index_version == grep.index_version == definition.index_version
    assert "old_name" in grep.hits[0].content
    assert "old_name" in (definition.matches[0].source or "")
    assert "new_name" not in grep.hits[0].content


@pytest.mark.asyncio
async def test_parse_failure_preserves_last_good_component(
    tmp_path: Path,
    isolated_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    source = repository / "service.py"
    source.write_text("def stable():\n    return 1\n", encoding="utf-8")
    index = await RepositoryIndex.create(repository)
    initial = await index.update()

    source.write_text("def changed():\n    return 2\n", encoding="utf-8")

    def fail_parse(_record: object) -> object:
        raise ValueError("synthetic parser failure")

    monkeypatch.setattr(
        "app.services.code_index.project.build_file_state",
        fail_parse,
    )
    after_failure = await index.update()

    assert after_failure.version == initial.version
    with index.database.readonly() as connection:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM code_symbols WHERE kind != 'file'"
            )
        }
        error = connection.execute(
            "SELECT error FROM index_errors WHERE file_path = 'service.py'"
        ).fetchone()
    assert names == {"stable"}
    assert error == ("synthetic parser failure",)
    assert after_failure.errors == (("service.py", "synthetic parser failure"),)


@pytest.mark.asyncio
async def test_deleting_a_never_indexed_failed_file_clears_its_error(
    tmp_path: Path,
    isolated_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    source = repository / "broken.py"
    source.write_text("def broken():\n    return 1\n", encoding="utf-8")
    index = await RepositoryIndex.create(repository)

    def fail_parse(_record: object) -> object:
        raise ValueError("synthetic parser failure")

    monkeypatch.setattr("app.services.code_index.project.build_file_state", fail_parse)
    failed = await index.update()
    assert failed.errors == (("broken.py", "synthetic parser failure"),)

    source.unlink()
    recovered = await index.update()

    assert recovered.errors == ()


@pytest.mark.asyncio
async def test_project_settings_control_discovery_and_language_override(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    (repository / ".code-index").mkdir(parents=True)
    (repository / ".code-index" / "settings.yml").write_text(
        "include_patterns:\n  - 'src/**'\n"
        "language_overrides:\n  - ext: inc\n    lang: php\n",
        encoding="utf-8",
    )
    (repository / "src").mkdir()
    (repository / "other").mkdir()
    (repository / "src" / "service.inc").write_text(
        "<?php function selected() { return 1; }", encoding="utf-8"
    )
    (repository / "other" / "ignored.py").write_text(
        "def ignored(): pass\n", encoding="utf-8"
    )

    index = await RepositoryIndex.create(repository)
    stats = await index.update()

    assert stats.files == 1
    assert stats.languages == ("php",)
    assert stats.graph_languages == ("php",)
    with index.database.readonly() as connection:
        row = connection.execute(
            "SELECT processor, content FROM source_files WHERE file_path = ?",
            ("src/service.inc",),
        ).fetchone()
    assert row is not None and len(str(row[0])) > 64
    assert "selected" in str(row[1])

    grep = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="grep",
        query=r"function \NAME(\(ARGS*\)) { \BODY* }",
        languages=["php"],
        refresh=False,
    )
    assert grep.hits and grep.hits[0].file_path == "src/service.inc"
    assert not grep.limitations


def test_structural_pattern_rejects_code_shaped_strings() -> None:
    from app.services.code_index.structural import StructuralPattern

    matcher = StructuralPattern(r"def \NAME(\(ARGS*\)):", grammar="python")
    matches = matcher.match(
        "text = '''def fake():\n    pass'''\n\ndef real():\n    pass\n", limit=10
    )
    assert [item.captures["NAME"] for item in matches] == ["real"]


def test_chunker_packs_small_adjacent_definitions() -> None:
    text = "".join(
        f"def item_{index}():\n    return {index}\n\n" for index in range(20)
    )
    lines = text.splitlines()
    file_symbol = SymbolRow(
        "file",
        "file",
        "items.py",
        "python",
        "file",
        "items.py",
        "items.py",
        1,
        len(lines),
        None,
        None,
    )
    symbols = [file_symbol]
    for index in range(20):
        start = index * 3 + 1
        symbols.append(
            SymbolRow(
                str(index),
                str(index),
                "items.py",
                "python",
                "function",
                f"item_{index}",
                f"item_{index}",
                start,
                start + 1,
                None,
                None,
            )
        )
    chunks = split_source(file_path="items.py", text=text, symbols=symbols)
    assert len(chunks) < 10
    assert all(len(item.content) >= MIN_CHUNK_CHARS for item in chunks[:-1])


def test_chunker_bounds_minified_single_line_sources() -> None:
    text = "const payload = '" + ("indexed-long-line-" * 200) + "';"
    chunks = split_source(file_path="bundle.js", text=text, symbols=[])

    assert len(chunks) > 1
    assert all(0 < len(item.content) <= MAX_CHUNK_CHARS for item in chunks)
    assert all(item.line_start == item.line_end == 1 for item in chunks)
    assert any("indexed-long-line" in item.content for item in chunks)


def test_runtime_adds_no_external_path_matching_dependency() -> None:
    project = Path(__file__).parents[2]
    dependency_files = (project / "pyproject.toml", project / "uv.lock")
    for path in dependency_files:
        content = path.read_text(encoding="utf-8").casefold()
        assert "pathspec" not in content


@pytest.mark.asyncio
async def test_canonical_index_replaces_stale_schema_without_version_fallback(
    tmp_path: Path, isolated_cache: Path
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    paths = paths_for_repository(repository)
    assert paths.directory.parent.name == "code-index"
    paths.directory.mkdir(parents=True)
    connection = sqlite3.connect(paths.target_db)
    connection.execute(
        "CREATE TABLE source_files(file_path TEXT PRIMARY KEY, fingerprint TEXT)"
    )
    connection.execute(
        "INSERT INTO source_files(file_path, fingerprint) VALUES ('stale.py', 'old')"
    )
    connection.commit()
    connection.close()

    index = await RepositoryIndex.create(repository)

    with index.database.readonly() as current:
        columns = {
            str(row[1])
            for row in current.execute('PRAGMA table_info("source_files")').fetchall()
        }
        stale = current.execute(
            "SELECT 1 FROM source_files WHERE file_path = 'stale.py'"
        ).fetchone()
    assert {"content", "processor", "graph_enabled"}.issubset(columns)
    assert stale is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reopen", [False, True])
async def test_refresh_rebuilds_a_corrupt_regeneratable_cache(
    tmp_path: Path, isolated_cache: Path, reopen: bool
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def recovered_symbol():\n    return 'recovered evidence'\n",
        encoding="utf-8",
    )
    index = await RepositoryIndex.create(repository)
    await index.update()
    index.paths.target_db.write_bytes(b"not a sqlite database")
    if reopen:
        index = await RepositoryIndex.create(repository)

    recovered = await index.update()

    assert recovered.files == 1
    assert recovered.errors == ()
    assert index.paths.target_db.with_suffix(".sqlite3.corrupt").is_file()
    result = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="definition",
        query="recovered_symbol",
        refresh=False,
    )
    assert result.matches and result.matches[0].file_path == "service.py"


@pytest.mark.asyncio
async def test_refresh_disabled_reopens_committed_index_without_rescan(
    tmp_path: Path,
    isolated_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    source = repository / "service.py"
    source.write_text("def committed_symbol():\n    return 1\n", encoding="utf-8")

    initial_index = await RepositoryIndex.create(repository)
    committed = await initial_index.update()
    source.write_text("def changed_after_commit():\n    return 2\n", encoding="utf-8")
    reopened = await RepositoryIndex.create(repository)

    async def unexpected_update(**_kwargs) -> IndexStats:
        raise AssertionError("refresh=False must not scan a committed index")

    monkeypatch.setattr(reopened, "update", unexpected_update)
    reused = await reopened.ensure_ready(refresh=False)

    assert reused.version == committed.version
    assert reused.files == 1


@pytest.mark.asyncio
async def test_cached_graph_query_reports_corruption_when_refresh_is_disabled(
    tmp_path: Path,
    isolated_cache: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "service.py").write_text(
        "def indexed_symbol():\n    return 1\n", encoding="utf-8"
    )
    registry = RepositoryIndexRegistry()
    monkeypatch.setattr("app.services.code_index.service.repository_indexes", registry)
    index = await registry.get(repository)
    await index.update()
    index.paths.target_db.write_bytes(b"not a sqlite database")

    result = await query_code_context(
        scopes=(RepositoryScope(repository, "repo"),),
        action="definition",
        query="indexed_symbol",
        refresh=False,
    )

    assert result.matches == []
    assert result.strategy == "code-index-unavailable"
    assert any("refresh to repair" in item for item in result.limitations)
