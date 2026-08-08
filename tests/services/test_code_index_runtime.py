"""End-to-end coverage for the dependency-free ported indexing runtime."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.code_index.models import RepositoryScope
from app.services.code_index.project import RepositoryIndex
from app.services.code_index.paths import paths_for_repository
from app.services.code_index.service import query_code_context
from app.services.code_index.chunking import MIN_CHUNK_CHARS, split_source
from app.services.code_index.pipeline import SymbolRow


@pytest.fixture
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "cache"
    monkeypatch.setattr(settings, "EVOFLUX_CACHE_DIR", str(cache))
    return cache


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
