"""Cross-repository retrieval and symbolic graph resolution."""

from __future__ import annotations

import asyncio
import concurrent.futures
import fnmatch
import hashlib
import heapq
import posixpath
import re
import sqlite3
import threading
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass, replace
from pathlib import Path

from app.services.code_index.parsers.registry import default_registry
from app.services.code_index.executor import run_index_work, submit_graph_build
from app.services.code_index.models import (
    CodeContextResult,
    CodeSymbol,
    GraphOperation,
    GraphRelation,
    GraphSnapshot,
    IndexStats,
    SearchHit,
)
from app.services.code_index.paths import RepositoryIndexPaths
from app.services.code_index.project import ManagedDatabase, RepositoryIndex
from app.services.code_index.semantic import embed_text, similarity
from app.services.code_index.structural import StructuralPattern

_REFERENCE_KINDS = frozenset(
    {
        "calls",
        "references",
        "imports",
        "inherits",
        "implements",
        "uses",
        "overrides",
        "reads",
        "writes",
        "decorated_by",
        "throws",
    }
)
_TYPE_KINDS = frozenset({"class", "interface", "struct", "enum"})
_CALLABLE_KINDS = frozenset({"function", "method", "class", "struct", "enum"})
_SUPER_MEMBER_LANGUAGES = frozenset(
    {"javascript", "java", "kotlin", "python", "scala", "swift", "tsx", "typescript"}
)
_COMMON_MEMBER_NAMES = frozenset(
    {
        "add",
        "append",
        "build",
        "close",
        "create",
        "delete",
        "find",
        "get",
        "handle",
        "init",
        "insert",
        "load",
        "open",
        "parse",
        "read",
        "remove",
        "run",
        "save",
        "select",
        "send",
        "set",
        "start",
        "stop",
        "update",
        "write",
    }
)
_QUERY_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[0-9]{2,}")
_SOURCE_EXTENSIONS: tuple[str, ...] = tuple(
    sorted(
        default_registry().supported_extensions(),
        key=lambda extension: len(extension),
        reverse=True,
    )
)


@dataclass(frozen=True, slots=True)
class _StoredSymbol:
    repository: str
    index: RepositoryIndex
    value: CodeSymbol


@dataclass(frozen=True, slots=True)
class _StoredRelation:
    repository: str
    index: RepositoryIndex
    id: str
    src_id: str
    kind: str
    dst_id: str | None
    dst_name: str | None
    module_path: str | None
    local_name: str | None
    file_path: str
    line: int | None


@dataclass(frozen=True, slots=True)
class _ResolvedRelation:
    source: _StoredSymbol
    target: _StoredSymbol
    relation: _StoredRelation


_SYMBOL_CACHE_LIMIT = 32
_SYMBOL_CACHE_LOCK = threading.RLock()
_SYMBOL_CACHE: OrderedDict[
    tuple[int, str], tuple[str | None, tuple[_StoredSymbol, ...]]
] = OrderedDict()
_GRAPH_SNAPSHOT_CACHE_LIMIT = 4
_GRAPH_SNAPSHOT_LOCK = threading.RLock()
_GRAPH_SNAPSHOT_CACHE: OrderedDict[tuple[object, ...], GraphSnapshot] = OrderedDict()
_GRAPH_SNAPSHOT_INFLIGHT: dict[
    tuple[object, ...], concurrent.futures.Future[GraphSnapshot]
] = {}


def _fts_query(query: str) -> str:
    tokens = list(dict.fromkeys(_QUERY_TOKEN.findall(query)))
    if not tokens:
        return '"' + query.replace('"', '""') + '"'
    return " OR ".join(
        f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens[:24]
    )


def _path_matches(file_path: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return True
    normalized = file_path.replace("\\", "/")
    return any(
        fnmatch.fnmatch(normalized, pattern)
        or pattern.casefold() in normalized.casefold()
        for pattern in patterns
    )


# One chunk as the scan reads it, before its content: rowid, file_path,
# language, line_start, line_end, symbol_name, embedding.
_ScannedChunk = tuple[int, str, str, int, int, str | None, bytes]


def _shortlist_chunks(
    rows: list[_ScannedChunk],
    *,
    query_embedding: bytes,
    query_folded: str,
    tokens: tuple[str, ...],
    paths: list[str] | None,
    keep: int,
) -> list[tuple[float, _ScannedChunk]]:
    """Rank scanned chunks on everything except their content.

    What the full ranking takes from content is bounded: token coverage adds
    at most 40 points and a whole-query substring 20, against a vector score
    scaled to 100 and an exact-symbol match worth 80. A chunk can therefore
    only be shortlisted wrongly if its content would have lifted it more
    than 60 points past the cut, and `keep` is the same candidate pool the
    lexical branch settles for.
    """
    scored: list[tuple[float, float, _ScannedChunk]] = []
    for row in rows:
        _rowid, file_path, _language, _start, _end, symbol_name, embedding = row
        if not _path_matches(str(file_path), paths):
            continue
        symbol = str(symbol_name) if symbol_name is not None else None
        haystack = f"{file_path} {symbol or ''}".casefold()
        coverage = sum(token in haystack for token in tokens) / max(1, len(tokens))
        vector_score = similarity(query_embedding, bytes(embedding))
        rank = max(0.0, vector_score) * 100.0 + coverage * 40.0
        if symbol and (
            symbol.casefold() == query_folded
            or symbol.casefold().endswith(f".{query_folded}")
        ):
            rank += 80.0
        scored.append((rank, vector_score, row))
    return [
        (vector_score, row)
        for _rank, vector_score, row in heapq.nlargest(
            keep, scored, key=lambda entry: entry[0]
        )
    ]


def _rows_with_content(
    conn: sqlite3.Connection, shortlist: list[tuple[float, _ScannedChunk]]
) -> list[tuple[object, ...]]:
    """Read content for the shortlist alone, in the ranking loop's row shape."""
    if not shortlist:
        return []
    placeholders = ", ".join("?" for _ in shortlist)
    contents = dict(
        conn.execute(
            f"SELECT rowid, content FROM source_chunks WHERE rowid IN ({placeholders})",
            tuple(row[0] for _score, row in shortlist),
        ).fetchall()
    )
    return [
        (
            file_path,
            language,
            start,
            end,
            contents[rowid],
            symbol_name,
            embedding,
            vector_score,
        )
        # A writer that dropped the chunk between the two reads leaves no
        # content to show, and an empty snippet is worse than one fewer hit.
        for vector_score, (
            rowid,
            file_path,
            language,
            start,
            end,
            symbol_name,
            embedding,
        ) in shortlist
        if rowid in contents
    ]


async def search_index(
    indexes: list[tuple[str, RepositoryIndex]],
    *,
    query: str,
    languages: list[str] | None,
    paths: list[str] | None,
    limit: int,
    stats: dict[str, IndexStats],
) -> CodeContextResult:
    """Merge repository-local FTS ranks into one bounded result set."""
    wanted_languages = {value.casefold() for value in languages or []}
    # The public limit is global. Keep each repository's candidate pool bounded
    # so a project with many repositories does not multiply the work by the
    # full global limit on every keypress.
    per_repository_candidates = min(
        500,
        max(
            80, ((max(1, limit) + max(1, len(indexes)) - 1) // max(1, len(indexes))) * 8
        ),
    )
    # Per query, not per repository: the shortlist needs both inside the
    # connection block, and neither varies by index.
    query_folded = query.casefold()
    tokens = tuple(token.casefold() for token in _QUERY_TOKEN.findall(query))

    def search_one(
        label: str, index: RepositoryIndex
    ) -> tuple[list[SearchHit], list[str]]:
        query_embedding = embed_text(query)
        limitations: list[str] = []
        try:
            with index.database.readonly() as conn:
                lexical_available = True
                try:
                    lexical_rows = conn.execute(
                        """
                        SELECT c.file_path, c.language, c.line_start, c.line_end,
                               c.content, c.symbol_name, c.embedding,
                               bm25(source_chunks_fts) AS rank
                        FROM source_chunks_fts
                        JOIN source_chunks AS c
                          ON c.rowid = source_chunks_fts.rowid
                        WHERE source_chunks_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                        """,
                        (_fts_query(query), per_repository_candidates),
                    ).fetchall()
                except Exception as exc:
                    lexical_available = False
                    lexical_rows = []
                    limitations.append(f"{label}: lexical index unavailable ({exc})")
                eligible_lexical_rows = [
                    row
                    for row in lexical_rows
                    if (
                        not wanted_languages
                        or str(row[1]).casefold() in wanted_languages
                    )
                    and _path_matches(str(row[0]), paths)
                ]
                if eligible_lexical_rows:
                    semantic_rows = [(*row[:7], None) for row in eligible_lexical_rows]
                else:
                    # No lexical candidate does not mean no answer: the
                    # words a reader uses ("authentication") need not appear
                    # in the code that implements it, and the trigram
                    # features tolerate a misspelled identifier. So the scan
                    # stays, in two phases, because content is what makes it
                    # hurt. Measured over a 20k-chunk, 246 MB stand-in for
                    # the largest index here (73k chunks, 698 MB), one full
                    # scan costs 848 ms: 82 ms to walk the rows, 126 ms more
                    # to read the embeddings, 344 ms to score them, and
                    # 296 ms to read and casefold content that all but a few
                    # hundred rows are never ranked on. So phase one reads
                    # every column but content and keeps the best
                    # candidates; phase two reads content for those alone.
                    # The language filter belongs in SQL for the same
                    # reason: filtering in Python still paid to read the
                    # rows it excluded.
                    conditions: list[str] = []
                    parameters: list[object] = []
                    if wanted_languages:
                        placeholders = ", ".join("?" for _ in wanted_languages)
                        conditions.append(f"lower(language) IN ({placeholders})")
                        parameters.extend(sorted(wanted_languages))
                    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
                    try:
                        scanned = conn.execute(
                            "SELECT rowid, file_path, language, line_start, "
                            "line_end, symbol_name, embedding FROM source_chunks"
                            + where,
                            tuple(parameters),
                        ).fetchall()
                        semantic_rows = _rows_with_content(
                            conn,
                            _shortlist_chunks(
                                scanned,
                                query_embedding=query_embedding,
                                query_folded=query_folded,
                                tokens=tokens,
                                paths=paths,
                                keep=per_repository_candidates,
                            ),
                        )
                    except Exception as exc:
                        return [], [f"{label}: source index unavailable ({exc})"]
        except Exception as exc:
            return [], [f"{label}: index unavailable ({exc})"]
        lexical_ranks = {
            (str(path), int(start), int(end)): float(rank or 0.0)
            for path, _language, start, end, _content, _symbol, _embedding, rank in lexical_rows
        }
        output: list[SearchHit] = []
        stale_lexical_target = False
        for (
            file_path,
            language,
            start,
            end,
            content,
            symbol_name,
            embedding,
            vector_score,
        ) in semantic_rows:
            if wanted_languages and str(language).casefold() not in wanted_languages:
                continue
            if not _path_matches(str(file_path), paths):
                continue
            text = str(content)
            symbol = str(symbol_name) if symbol_name is not None else None
            haystack = f"{file_path} {symbol or ''} {text}".casefold()
            coverage = sum(token in haystack for token in tokens) / max(1, len(tokens))
            # Shortlisted rows only, in the scan branch. A chunk that holds
            # the query's own identifier scores high on the vector too, so a
            # lexical index that has gone blind still surfaces here.
            if lexical_available and not lexical_rows and tokens:
                indexed_tokens = {
                    token.casefold() for token in _QUERY_TOKEN.findall(haystack)
                }
                stale_lexical_target = stale_lexical_target or any(
                    token in indexed_tokens for token in tokens
                )
            if vector_score is None:
                vector_score = similarity(query_embedding, bytes(embedding))
            rank = lexical_ranks.get((str(file_path), int(start), int(end)))
            score = max(0.0, vector_score) * 100.0 + coverage * 40.0
            if rank is not None:
                score += 15.0 + max(0.0, -rank)
            if query_folded in text.casefold():
                score += 20.0
            if symbol and (
                symbol.casefold() == query_folded
                or symbol.casefold().endswith(f".{query_folded}")
            ):
                score += 80.0
            if score <= 0:
                continue
            output.append(
                SearchHit(
                    repository=label,
                    file_path=str(file_path),
                    language=str(language),
                    line_start=int(start),
                    line_end=int(end),
                    content=text,
                    score=round(score, 6),
                    symbol=symbol,
                    repository_path=str(index.root),
                )
            )
        if stale_lexical_target:
            try:
                index.rebuild_lexical_index()
            except Exception as exc:
                limitations.append(f"{label}: lexical index repair failed ({exc})")
        return output, limitations

    groups = await asyncio.gather(
        *(run_index_work(search_one, label, index) for label, index in indexes)
    )
    hits = [hit for group, _ in groups for hit in group]
    limitations = list(
        dict.fromkeys(
            item for _, group_limitations in groups for item in group_limitations
        )
    )
    hits.sort(
        key=lambda hit: (
            -hit.score,
            hit.repository.casefold(),
            hit.file_path.casefold(),
            hit.line_start,
        )
    )
    capped = max(1, min(100, limit))
    return CodeContextResult(
        action="search",
        query=query,
        strategy="code-index-vector-fts5-cross-repo",
        index_version=_combined_version(stats),
        repositories=tuple(label for label, _ in indexes),
        hits=hits[:capped],
        stats=stats,
        limitations=limitations,
        truncated=len(hits) > capped,
    )


async def structural_grep(
    indexes: list[tuple[str, RepositoryIndex]],
    *,
    pattern: str,
    languages: list[str] | None,
    paths: list[str] | None,
    limit: int,
    stats: dict[str, IndexStats],
) -> CodeContextResult:
    """Run the ported structural pattern matcher over authorized source files."""
    wanted_languages = {item.casefold() for item in languages or []}

    def grep_one(
        label: str, index: RepositoryIndex
    ) -> tuple[list[SearchHit], list[str]]:
        hits: list[SearchHit] = []
        limitations: list[str] = []
        try:
            with index.database.readonly() as conn:
                rows = conn.execute(
                    "SELECT file_path, language, content FROM source_files "
                    "ORDER BY file_path"
                ).fetchall()
        except Exception as exc:
            return [], [f"{label}: index unavailable ({exc})"]
        patterns: dict[str, StructuralPattern | None] = {}
        registry = default_registry()
        for file_path, language, source in rows:
            language = str(language)
            if wanted_languages and language.casefold() not in wanted_languages:
                continue
            if not _path_matches(str(file_path), paths):
                continue
            if language not in patterns:
                try:
                    parser = registry.for_language(language) or registry.for_path(
                        str(file_path)
                    )
                    grammar = getattr(parser, "grammar", None)
                    if grammar is None:
                        raise ValueError("language has no tree-sitter grammar")
                    patterns[language] = StructuralPattern(pattern, grammar=grammar)
                except (LookupError, ValueError) as exc:
                    patterns[language] = None
                    limitations.append(f"{label}/{language}: {exc}")
            compiled = patterns[language]
            if compiled is None:
                continue
            for match in compiled.match(str(source), limit=max(1, limit - len(hits))):
                hits.append(
                    SearchHit(
                        repository=label,
                        file_path=str(file_path),
                        language=language,
                        line_start=match.line_start,
                        line_end=match.line_end,
                        content=match.text,
                        score=1.0,
                        symbol=match.kind,
                        repository_path=str(index.root),
                    )
                )
                if len(hits) >= limit:
                    return hits, limitations
        return hits, limitations

    groups = await asyncio.gather(
        *(run_index_work(grep_one, label, index) for label, index in indexes)
    )
    hits = [hit for group, _ in groups for hit in group]
    limitations = list(
        dict.fromkeys(
            item for _, group_limitations in groups for item in group_limitations
        )
    )
    capped = max(1, min(100, limit))
    return CodeContextResult(
        action="grep",
        query=pattern,
        strategy="code-index-structural-pattern-cross-repo",
        index_version=_combined_version(stats),
        repositories=tuple(label for label, _ in indexes),
        hits=hits[:capped],
        stats=stats,
        limitations=limitations,
        truncated=len(hits) > capped,
    )


def _load_symbols(
    indexes: list[tuple[str, RepositoryIndex]],
    stats: dict[str, IndexStats] | None = None,
) -> list[_StoredSymbol]:
    symbols: list[_StoredSymbol] = []
    for label, index in indexes:
        version = (
            stats[label].version
            if stats is not None and label in stats
            else index.stats().version
        )
        cache_key = (id(index), label)
        with _SYMBOL_CACHE_LOCK:
            cached = _SYMBOL_CACHE.get(cache_key)
            if cached is not None and cached[0] == version:
                _SYMBOL_CACHE.move_to_end(cache_key)
                symbols.extend(cached[1])
                continue
        with index.database.readonly() as conn:
            symbol_rows = conn.execute(
                """
                SELECT id, file_path, language, kind, name, qualified_name,
                       line_start, line_end, signature, docstring
                FROM code_symbols
                """
            ).fetchall()
        loaded = tuple(
            _StoredSymbol(
                repository=label,
                index=index,
                value=CodeSymbol(
                    id=str(row[0]),
                    repository=label,
                    file_path=str(row[1]),
                    language=str(row[2]),
                    kind=str(row[3]),
                    name=str(row[4]),
                    qualified_name=str(row[5]),
                    line_start=int(row[6]),
                    line_end=int(row[7]),
                    signature=str(row[8]) if row[8] is not None else None,
                    docstring=str(row[9]) if row[9] is not None else None,
                ),
            )
            for row in symbol_rows
        )
        with _SYMBOL_CACHE_LOCK:
            _SYMBOL_CACHE[cache_key] = (version, loaded)
            _SYMBOL_CACHE.move_to_end(cache_key)
            while len(_SYMBOL_CACHE) > _SYMBOL_CACHE_LIMIT:
                _SYMBOL_CACHE.popitem(last=False)
        symbols.extend(loaded)
    return symbols


def _relation(
    label: str, index: RepositoryIndex, row: tuple[object, ...]
) -> _StoredRelation:
    return _StoredRelation(
        repository=label,
        index=index,
        id=str(row[0]),
        src_id=str(row[1]),
        kind=str(row[2]),
        dst_id=str(row[3]) if row[3] is not None else None,
        dst_name=str(row[4]) if row[4] is not None else None,
        module_path=str(row[5]) if row[5] is not None else None,
        local_name=str(row[6]) if row[6] is not None else None,
        file_path=str(row[7]),
        line=int(str(row[8])) if row[8] is not None else None,
    )


_RELATION_COLUMNS = (
    "id, src_id, kind, dst_id, dst_name, module_path, local_name, file_path, line"
)


def _relations_for_node(
    indexes: list[tuple[str, RepositoryIndex]],
    node: _StoredSymbol,
    *,
    outbound: bool,
    inbound: bool,
    kinds: frozenset[str],
) -> list[_StoredRelation]:
    """Load only edges that can touch one BFS node plus their import bindings."""
    output: list[_StoredRelation] = []
    names = {
        node.value.name,
        node.value.qualified_name,
        *(f"{prefix}.{node.value.name}" for prefix in ("self", "this", "cls", "super")),
    }
    for label, index in indexes:
        clauses: list[str] = []
        params: list[object] = []
        kind_values = sorted(kinds)
        placeholders = ",".join("?" for _ in kind_values)
        if outbound and label == node.repository:
            clauses.append(f"(src_id = ? AND kind IN ({placeholders}))")
            params.extend((node.value.id, *kind_values))
        if inbound:
            name_placeholders = ",".join("?" for _ in names)
            clauses.append(
                f"((dst_id = ? OR dst_name IN ({name_placeholders}) "
                f"OR dst_name LIKE ?) "
                f"AND kind IN ({placeholders}))"
            )
            params.extend(
                (node.value.id, *sorted(names), f"%.{node.value.name}", *kind_values)
            )
        if not clauses:
            continue
        with index.database.readonly() as conn:
            rows = conn.execute(
                f"SELECT {_RELATION_COLUMNS} FROM code_relations WHERE "
                + " OR ".join(clauses),
                params,
            ).fetchall()
            file_paths = sorted({str(row[7]) for row in rows})
            import_rows: list[tuple[object, ...]] = []
            for offset in range(0, len(file_paths), 500):
                batch = file_paths[offset : offset + 500]
                marks = ",".join("?" for _ in batch)
                import_rows.extend(
                    conn.execute(
                        f"SELECT {_RELATION_COLUMNS} FROM code_relations "
                        f"WHERE kind = 'imports' AND file_path IN ({marks})",
                        batch,
                    ).fetchall()
                )
        output.extend(_relation(label, index, row) for row in [*rows, *import_rows])
    return list({(item.repository, item.id): item for item in output}.values())


def _relations_from_selected(
    selected: list[_StoredSymbol],
) -> tuple[list[_StoredRelation], int]:
    output: list[_StoredRelation] = []
    total = 0
    by_repository: dict[str, list[_StoredSymbol]] = defaultdict(list)
    for item in selected:
        by_repository[item.repository].append(item)
    for label, values in by_repository.items():
        index = values[0].index
        ids = [item.value.id for item in values]
        rows: list[tuple[object, ...]] = []
        with index.database.readonly() as conn:
            total = total + int(
                conn.execute("SELECT COUNT(*) FROM code_relations").fetchone()[0]
            )
            for offset in range(0, len(ids), 500):
                batch = ids[offset : offset + 500]
                marks = ",".join("?" for _ in batch)
                rows.extend(
                    conn.execute(
                        f"SELECT {_RELATION_COLUMNS} FROM code_relations "
                        f"WHERE src_id IN ({marks})",
                        batch,
                    ).fetchall()
                )
            files = sorted({str(row[7]) for row in rows})
            for offset in range(0, len(files), 500):
                batch = files[offset : offset + 500]
                marks = ",".join("?" for _ in batch)
                rows.extend(
                    conn.execute(
                        f"SELECT {_RELATION_COLUMNS} FROM code_relations "
                        f"WHERE kind = 'imports' AND file_path IN ({marks})",
                        batch,
                    ).fetchall()
                )
        output.extend(_relation(label, index, row) for row in rows)
    return list({(item.repository, item.id): item for item in output}.values()), total


async def snapshot_graph(
    indexes: list[tuple[str, RepositoryIndex]],
    *,
    node_limit_per_repository: int,
    relation_limit_per_repository: int,
    stats: dict[str, IndexStats] | None = None,
) -> GraphSnapshot:
    """Return a versioned, single-flight graph projection for the repo set."""

    resolved_stats = stats or await run_index_work(_index_stats, indexes)
    cache_key: tuple[object, ...] = (
        tuple(
            (id(index), label, resolved_stats[label].version)
            for label, index in indexes
        ),
        node_limit_per_repository,
        relation_limit_per_repository,
    )
    with _GRAPH_SNAPSHOT_LOCK:
        cached = _GRAPH_SNAPSHOT_CACHE.get(cache_key)
        if cached is not None:
            _GRAPH_SNAPSHOT_CACHE.move_to_end(cache_key)
            return cached
        pending = _GRAPH_SNAPSHOT_INFLIGHT.get(cache_key)
        if pending is None:
            pending = submit_graph_build(
                _build_graph_snapshot,
                (
                    indexes,
                    resolved_stats,
                    node_limit_per_repository,
                    relation_limit_per_repository,
                ),
                process_function=_build_graph_snapshot_process,
                process_args=(
                    tuple(
                        (label, str(index.root), str(index.database.path))
                        for label, index in indexes
                    ),
                    resolved_stats,
                    node_limit_per_repository,
                    relation_limit_per_repository,
                ),
            )
            _GRAPH_SNAPSHOT_INFLIGHT[cache_key] = pending

            def remember(
                completed: concurrent.futures.Future[GraphSnapshot],
            ) -> None:
                try:
                    snapshot = completed.result()
                except BaseException:
                    snapshot = None
                with _GRAPH_SNAPSHOT_LOCK:
                    if _GRAPH_SNAPSHOT_INFLIGHT.get(cache_key) is completed:
                        _GRAPH_SNAPSHOT_INFLIGHT.pop(cache_key, None)
                    if snapshot is not None:
                        _GRAPH_SNAPSHOT_CACHE[cache_key] = snapshot
                        _GRAPH_SNAPSHOT_CACHE.move_to_end(cache_key)
                        while len(_GRAPH_SNAPSHOT_CACHE) > _GRAPH_SNAPSHOT_CACHE_LIMIT:
                            _GRAPH_SNAPSHOT_CACHE.popitem(last=False)

            pending.add_done_callback(remember)

    return await asyncio.shield(asyncio.wrap_future(pending))


def _index_stats(
    indexes: list[tuple[str, RepositoryIndex]],
) -> dict[str, IndexStats]:
    return {label: index.stats() for label, index in indexes}


def _build_graph_snapshot(
    indexes: list[tuple[str, RepositoryIndex]],
    stats: dict[str, IndexStats],
    node_limit_per_repository: int,
    relation_limit_per_repository: int,
) -> GraphSnapshot:
    """Build the complete projection inside the bounded code-index thread."""

    stored_symbols = _load_symbols(indexes, stats)
    selected: list[_StoredSymbol] = []
    for label, _index in indexes:
        values = [item for item in stored_symbols if item.repository == label]
        values.sort(
            key=lambda item: (
                item.value.kind == "file",
                item.value.file_path,
                item.value.line_start,
                item.value.qualified_name,
            )
        )
        selected.extend(values[:node_limit_per_repository])
    selected_ids = {item.value.identity for item in selected}
    stored_relations, total_relations = _relations_from_selected(selected)
    resolver = _GraphResolver(stored_symbols, stored_relations)
    resolved = resolver.resolve_all()
    relation_counts: dict[str, int] = defaultdict(int)
    output_relations: list[GraphRelation] = []
    for edge in resolved:
        if (
            edge.source.value.identity not in selected_ids
            or edge.target.value.identity not in selected_ids
            or relation_counts[edge.source.repository] >= relation_limit_per_repository
        ):
            continue
        relation_counts[edge.source.repository] += 1
        output_relations.append(
            GraphRelation(
                kind=edge.relation.kind,
                depth=1,
                cross_repo=edge.source.repository != edge.target.repository,
                source=edge.source.value,
                target=edge.target.value,
                callsite_file=edge.relation.file_path,
                callsite_line=edge.relation.line or edge.source.value.line_start,
            )
        )
    return GraphSnapshot(
        symbols=tuple(item.value for item in selected),
        relations=tuple(output_relations),
        total_symbols=len(stored_symbols),
        total_relations=total_relations,
    )


def _build_graph_snapshot_process(
    descriptors: tuple[tuple[str, str, str], ...],
    stats: dict[str, IndexStats],
    node_limit_per_repository: int,
    relation_limit_per_repository: int,
) -> GraphSnapshot:
    """Reconstruct repository handles and build a graph in an isolated process."""

    indexes: list[tuple[str, RepositoryIndex]] = []
    for label, root_value, database_value in descriptors:
        root = Path(root_value)
        database_path = Path(database_value)
        database = ManagedDatabase(database_path)
        indexes.append(
            (
                label,
                RepositoryIndex(
                    root=root,
                    paths=RepositoryIndexPaths(
                        root=root,
                        directory=database_path.parent,
                        target_db=database_path,
                    ),
                    database=database,
                ),
            )
        )
    return _build_graph_snapshot(
        indexes,
        stats,
        node_limit_per_repository,
        relation_limit_per_repository,
    )


class _GraphResolver:
    def __init__(
        self,
        symbols: list[_StoredSymbol],
        relations: list[_StoredRelation],
        *,
        catalog: _GraphResolver | None = None,
    ) -> None:
        self.symbols = catalog.symbols if catalog is not None else symbols
        self.relations = relations
        if catalog is not None:
            self.by_identity = catalog.by_identity
            self.by_repo_name = catalog.by_repo_name
            self.by_repo_qualified = catalog.by_repo_qualified
            self.by_name = catalog.by_name
            self.by_qualified = catalog.by_qualified
        else:
            self.by_identity = {
                (symbol.repository, symbol.value.id): symbol for symbol in symbols
            }
            self.by_repo_name: dict[tuple[str, str], list[_StoredSymbol]] = defaultdict(
                list
            )
            self.by_repo_qualified: dict[tuple[str, str], list[_StoredSymbol]] = (
                defaultdict(list)
            )
            self.by_name: dict[str, list[_StoredSymbol]] = defaultdict(list)
            self.by_qualified: dict[str, list[_StoredSymbol]] = defaultdict(list)
            for symbol in symbols:
                self.by_repo_name[
                    (symbol.repository, symbol.value.name.casefold())
                ].append(symbol)
                self.by_repo_qualified[
                    (symbol.repository, symbol.value.qualified_name.casefold())
                ].append(symbol)
                self.by_name[symbol.value.name.casefold()].append(symbol)
                self.by_qualified[symbol.value.qualified_name.casefold()].append(symbol)
        self.imports: dict[tuple[str, str, str], _StoredSymbol] = {}
        self.limitations: list[str] = []
        self.ambiguities: list[_StoredSymbol] = []

    def _record_ambiguity(
        self, relation: _StoredRelation, candidates: list[_StoredSymbol]
    ) -> None:
        self.limitations.append(
            f"{relation.repository}/{relation.file_path}:{relation.line or 1}: "
            f"'{relation.dst_name}' resolves to {len(candidates)} candidates."
        )
        known = {item.value.identity for item in self.ambiguities}
        self.ambiguities.extend(
            item for item in candidates if item.value.identity not in known
        )

    def resolve_all(self) -> list[_ResolvedRelation]:
        resolved: list[_ResolvedRelation] = []
        seen: set[tuple[tuple[str, str], tuple[str, str], str, int | None]] = set()
        import_relations = [item for item in self.relations if item.kind == "imports"]
        for relation in import_relations:
            edge = self._resolve(
                relation,
                allow_import_binding=False,
                report_ambiguity=False,
            )
            if edge is not None:
                binding = relation.local_name or relation.dst_name
                if binding:
                    self.imports[
                        (relation.repository, relation.file_path, binding.casefold())
                    ] = edge.target
                self._append_unique(resolved, seen, edge)
        for relation in self.relations:
            if relation.kind == "imports":
                continue
            edge = self._resolve(
                relation,
                allow_import_binding=True,
                report_ambiguity=True,
            )
            if edge is not None:
                self._append_unique(resolved, seen, edge)
        return resolved

    @staticmethod
    def _append_unique(
        output: list[_ResolvedRelation],
        seen: set[tuple[tuple[str, str], tuple[str, str], str, int | None]],
        edge: _ResolvedRelation,
    ) -> None:
        key = (
            edge.source.value.identity,
            edge.target.value.identity,
            edge.relation.kind,
            edge.relation.line,
        )
        if key not in seen:
            seen.add(key)
            output.append(edge)

    def _resolve(
        self,
        relation: _StoredRelation,
        *,
        allow_import_binding: bool,
        report_ambiguity: bool,
    ) -> _ResolvedRelation | None:
        source = self.by_identity.get((relation.repository, relation.src_id))
        if source is None:
            return None
        if relation.dst_id is not None:
            target = self.by_identity.get((relation.repository, relation.dst_id))
            return (
                _ResolvedRelation(source, target, relation)
                if target is not None
                else None
            )
        raw_name = (relation.dst_name or "").strip()
        if not raw_name:
            return None
        raw_normalized = raw_name.replace("::", ".").replace("->", ".").strip(".")
        if (
            source.value.language in _SUPER_MEMBER_LANGUAGES
            and raw_normalized.casefold().startswith("super.")
        ):
            member = raw_normalized.partition(".")[2]
            candidates = self._super_member_candidates(
                source,
                relation,
                member=member,
                allowed=_allowed_symbol_kinds(relation.kind),
            )
            if len(candidates) == 1:
                return _ResolvedRelation(source, candidates[0], relation)
            if len(candidates) > 1 and report_ambiguity:
                self._record_ambiguity(relation, candidates)
            # A statically spelled OOP `super` call must never fall back to
            # the current lexical member and become a false self-loop.
            return None
        normalized = _normalize_symbol(raw_name)
        explicit_receiver = "." in normalized
        short = normalized.rsplit(".", 1)[-1]
        allowed = _allowed_symbol_kinds(relation.kind)

        if relation.kind == "imports":
            candidates = self._module_candidates(relation, short, allowed)
            if len(candidates) == 1:
                return _ResolvedRelation(source, candidates[0], relation)
            if len(candidates) > 1:
                if report_ambiguity:
                    self._record_ambiguity(relation, candidates)
                return None

        if allow_import_binding:
            head, _, tail = normalized.partition(".")
            imported = self.imports.get(
                (relation.repository, relation.file_path, head.casefold())
            )
            if imported is not None:
                if not tail:
                    return _ResolvedRelation(source, imported, relation)
                candidates = [
                    item
                    for item in self.by_repo_name.get(
                        (
                            imported.repository,
                            tail.rsplit(".", 1)[-1].casefold(),
                        ),
                        [],
                    )
                    if item.repository == imported.repository
                    and item.value.kind in allowed
                    and _same_module(imported.value.file_path, item.value.file_path)
                ]
                if len(candidates) == 1:
                    return _ResolvedRelation(source, candidates[0], relation)
                if len(candidates) > 1 and report_ambiguity:
                    self._record_ambiguity(relation, candidates)
                    return None
            if tail:
                candidates = self._imported_receiver_candidates(
                    relation,
                    receiver=head,
                    short_name=short,
                    allowed=allowed,
                )
                if len(candidates) == 1:
                    return _ResolvedRelation(source, candidates[0], relation)
                if len(candidates) > 1 and report_ambiguity:
                    self._record_ambiguity(relation, candidates)
                    return None
                candidates = self._imported_namespace_candidates(
                    relation,
                    receiver=head,
                    short_name=short,
                    allowed=allowed,
                )
                if len(candidates) == 1:
                    return _ResolvedRelation(source, candidates[0], relation)
                if len(candidates) > 1 and report_ambiguity:
                    self._record_ambiguity(relation, candidates)
                    return None

        exact_local = [
            item
            for item in self.by_repo_qualified.get(
                (relation.repository, normalized.casefold()), []
            )
            if item.value.kind in allowed
        ]
        if len(exact_local) == 1:
            return _ResolvedRelation(source, exact_local[0], relation)
        if len(exact_local) > 1 and report_ambiguity:
            self._record_ambiguity(relation, exact_local)
            return None

        if not explicit_receiver:
            source_container = source.value.qualified_name.rsplit(".", 1)[0]
            lexical = self.by_repo_qualified.get(
                (relation.repository, f"{source_container}.{short}".casefold()), []
            )
            lexical = [item for item in lexical if item.value.kind in allowed]
            if len(lexical) == 1:
                return _ResolvedRelation(source, lexical[0], relation)

        same_file = [
            item
            for item in self.by_repo_name.get(
                (relation.repository, short.casefold()), []
            )
            if not explicit_receiver
            and item.value.file_path == relation.file_path
            and item.value.kind in allowed
        ]
        if len(same_file) == 1:
            return _ResolvedRelation(source, same_file[0], relation)

        local = (
            []
            if explicit_receiver
            else self.by_repo_name.get((relation.repository, short.casefold()), [])
        )
        local = [item for item in local if item.value.kind in allowed]
        if len(local) == 1:
            return _ResolvedRelation(source, local[0], relation)
        if len(local) > 1 and report_ambiguity:
            self._record_ambiguity(relation, local)
            return None

        module_candidates = self._module_candidates(relation, short, allowed)
        if len(module_candidates) == 1:
            return _ResolvedRelation(source, module_candidates[0], relation)
        if len(module_candidates) > 1 and report_ambiguity:
            self._record_ambiguity(relation, module_candidates)
            return None

        global_candidates = list(self.by_qualified.get(normalized.casefold(), []))
        if not explicit_receiver:
            global_candidates.extend(self.by_name.get(short.casefold(), []))
        global_candidates = list(dict.fromkeys(global_candidates))
        global_candidates = [
            item
            for item in global_candidates
            if item.value.kind in allowed and item.repository != relation.repository
        ]
        cross_repo_safe = relation.kind in {
            "imports",
            "inherits",
            "implements",
            "uses",
            "references",
        } or ("." in normalized and short.casefold() not in _COMMON_MEMBER_NAMES)
        if cross_repo_safe and len(global_candidates) == 1:
            return _ResolvedRelation(source, global_candidates[0], relation)
        if cross_repo_safe and len(global_candidates) > 1 and report_ambiguity:
            self._record_ambiguity(relation, global_candidates)
        return None

    def _super_member_candidates(
        self,
        source: _StoredSymbol,
        relation: _StoredRelation,
        *,
        member: str,
        allowed: frozenset[str],
    ) -> list[_StoredSymbol]:
        container_name, separator, _ = source.value.qualified_name.rpartition(".")
        if not separator or not member:
            return []
        containers = [
            item
            for item in self.by_repo_qualified.get(
                (source.repository, container_name.casefold()), []
            )
            if item.value.kind in _TYPE_KINDS
        ]
        output: list[_StoredSymbol] = []
        for container in containers:
            for heritage in self.relations:
                if (
                    heritage.repository != source.repository
                    or heritage.src_id != container.value.id
                    or heritage.kind != "inherits"
                ):
                    continue
                parent_edge = self._resolve(
                    heritage,
                    allow_import_binding=True,
                    report_ambiguity=False,
                )
                if parent_edge is None:
                    continue
                target_name = (
                    f"{parent_edge.target.value.qualified_name}.{member}".casefold()
                )
                output.extend(
                    item
                    for item in self.by_repo_qualified.get(
                        (parent_edge.target.repository, target_name), []
                    )
                    if item.value.kind in allowed
                    and item.value.identity != source.value.identity
                )
        return _prefer_same_repository(output, relation.repository)

    def _module_candidates(
        self,
        relation: _StoredRelation,
        short_name: str,
        allowed: frozenset[str],
    ) -> list[_StoredSymbol]:
        if not relation.module_path:
            return []
        named_symbols = self.by_name.get(short_name.casefold(), [])
        output = [
            item
            for item in named_symbols
            if item.value.kind in allowed
            and _file_matches_module(
                item.value.file_path,
                relation.module_path,
                source_file=relation.file_path,
            )
            and (
                item.repository == relation.repository
                or not _is_relative_module(relation.module_path)
            )
        ]
        if not output and not _is_relative_module(relation.module_path):
            output = [
                item
                for item in named_symbols
                if item.value.kind in allowed
                and _repository_matches_module(item, relation.module_path)
            ]
        return _prefer_same_repository(output, relation.repository)

    def _imported_receiver_candidates(
        self,
        relation: _StoredRelation,
        *,
        receiver: str,
        short_name: str,
        allowed: frozenset[str],
    ) -> list[_StoredSymbol]:
        """Resolve ``module.symbol`` only when the receiver is a real import."""
        module_paths = {
            item.module_path
            for item in self.relations
            if item.kind == "imports"
            and item.repository == relation.repository
            and item.file_path == relation.file_path
            and (item.local_name or item.dst_name or "").casefold()
            == receiver.casefold()
            and item.module_path
        }
        output: list[_StoredSymbol] = []
        named_symbols = self.by_name.get(short_name.casefold(), [])
        for module_path in module_paths:
            matched = [
                item
                for item in named_symbols
                if item.value.kind in allowed
                and _file_matches_module(
                    item.value.file_path,
                    module_path,
                    source_file=relation.file_path,
                )
                and (
                    item.repository == relation.repository
                    or not _is_relative_module(module_path)
                )
            ]
            if not matched and not _is_relative_module(module_path):
                matched = [
                    item
                    for item in named_symbols
                    if item.value.kind in allowed
                    and _repository_matches_module(item, module_path)
                ]
            output.extend(matched)
        return _prefer_same_repository(output, relation.repository)

    def _imported_namespace_candidates(
        self,
        relation: _StoredRelation,
        *,
        receiver: str,
        short_name: str,
        allowed: frozenset[str],
    ) -> list[_StoredSymbol]:
        """Resolve ``Type.member`` made visible by a namespace/package import."""
        module_paths = {
            item.module_path
            for item in self.relations
            if item.kind == "imports"
            and item.repository == relation.repository
            and item.file_path == relation.file_path
            and item.module_path
        }
        receivers: list[_StoredSymbol] = []
        named_receivers = self.by_name.get(receiver.casefold(), [])
        for module_path in module_paths:
            receivers.extend(
                item
                for item in named_receivers
                if item.value.kind in _TYPE_KINDS
                and (
                    _file_matches_module(
                        item.value.file_path,
                        module_path,
                        source_file=relation.file_path,
                    )
                    or _repository_matches_module(item, module_path)
                )
            )
        output = [
            item
            for receiver_symbol in dict.fromkeys(receivers)
            for item in self.by_repo_name.get(
                (receiver_symbol.repository, short_name.casefold()), []
            )
            if item.value.kind in allowed
            and item.value.qualified_name.casefold().startswith(
                f"{receiver_symbol.value.qualified_name}.".casefold()
            )
        ]
        return _prefer_same_repository(output, relation.repository)


def _prefer_same_repository(
    candidates: list[_StoredSymbol], repository: str
) -> list[_StoredSymbol]:
    unique = list(dict.fromkeys(candidates))
    local = [item for item in unique if item.repository == repository]
    return local or unique


def _repository_matches_module(symbol: _StoredSymbol, module_path: str) -> bool:
    value = module_path.strip().strip("'\"").replace("\\", "/")
    if value.startswith("package:"):
        value = value.removeprefix("package:")
    parts = {
        part.casefold()
        for part in value.replace("::", "/").replace(".", "/").split("/")
        if part and part != "@"
    }
    return (
        symbol.repository.casefold() in parts
        or symbol.index.root.name.casefold() in parts
    )


def _is_relative_module(module_path: str) -> bool:
    value = module_path.strip().strip("'\"").replace("\\", "/")
    return value.startswith(".")


def _without_source_suffix(path: str) -> str:
    folded = path.casefold()
    for extension in _SOURCE_EXTENSIONS:
        if folded.endswith(extension.casefold()):
            return path[: -len(extension)]
    return path


def _relative_module_path(module_path: str, source_file: str) -> str | None:
    value = module_path.strip().strip("'\"").replace("\\", "/")
    source_directory = posixpath.dirname(source_file.replace("\\", "/"))
    if value.startswith(("./", "../")):
        return posixpath.normpath(posixpath.join(source_directory, value))
    if not value.startswith("."):
        return None
    dots = len(value) - len(value.lstrip("."))
    remainder = value[dots:].replace(".", "/").strip("/")
    base = source_directory
    for _ in range(max(0, dots - 1)):
        base = posixpath.dirname(base)
    return posixpath.normpath(posixpath.join(base, remainder))


def _file_matches_module(file_path: str, module_path: str, *, source_file: str) -> bool:
    """Match import modules across Python, JS/TS and directory-based layouts."""
    candidate = posixpath.normpath(file_path.replace("\\", "/")).strip("./")
    candidate_base = _without_source_suffix(candidate)
    candidate_parent = posixpath.dirname(candidate)
    candidate_stem = posixpath.basename(candidate_base).casefold()

    relative = _relative_module_path(module_path, source_file)
    if relative is not None:
        target = _without_source_suffix(relative.strip("./"))
        return candidate_base.casefold() == target.casefold() or (
            candidate_parent.casefold() == target.casefold()
            and candidate_stem in {"index", "__init__", "mod"}
        )

    module = module_path.strip().strip("'\"").replace("\\", "/")
    if module.startswith("package:"):
        module = module.removeprefix("package:")
    module = _without_source_suffix(module).replace("::", "/")
    if "/" not in module:
        module = module.replace(".", "/")
    module = module.strip("/")
    module_base = posixpath.normpath(module)
    folded_module = module_base.casefold()
    folded_parent = candidate_parent.casefold()
    if not folded_module or folded_module == ".":
        return False
    return (
        candidate_base.casefold() == folded_module
        or candidate_base.casefold().endswith(f"/{folded_module}")
        or folded_parent == folded_module
        or folded_parent.endswith(f"/{folded_module}")
        or bool(folded_parent)
        and folded_module.endswith(f"/{folded_parent}")
    )


def _normalize_symbol(value: str) -> str:
    normalized = value.strip().replace("::", ".").replace("->", ".")
    for prefix in ("self.", "this.", "cls.", "super."):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized.strip(".")


def _allowed_symbol_kinds(kind: str) -> frozenset[str]:
    if kind in {"inherits", "implements", "uses"}:
        return _TYPE_KINDS
    if kind == "calls":
        return _CALLABLE_KINDS
    return frozenset(
        {
            "module",
            "namespace",
            "class",
            "interface",
            "struct",
            "enum",
            "function",
            "method",
            "variable",
            "field",
            "property",
        }
    )


def _same_module(left: str, right: str) -> bool:
    return left == right or Path(left).parent == Path(right).parent


async def navigate_graph(
    indexes: list[tuple[str, RepositoryIndex]],
    *,
    symbol: str,
    operation: GraphOperation,
    repository: str | None,
    paths: list[str] | None,
    depth: int,
    limit: int,
    stats: dict[str, IndexStats],
) -> CodeContextResult:
    folded = _normalize_symbol(symbol).casefold()
    matches, suggestions = await run_index_work(
        _find_symbols,
        indexes,
        folded,
        repository,
        paths,
    )
    matches.sort(
        key=lambda item: (
            0 if item.value.qualified_name.casefold() == folded else 1,
            item.repository.casefold(),
            item.value.file_path,
            item.value.line_start,
        )
    )
    limitations: list[str] = []
    if len(matches) > 1:
        limitations.append(
            "The symbol is ambiguous across the authorized repositories; add a "
            "repository, path, or qualified name before traversal."
        )
    root_values = [_attach_definition(item) for item in matches[:20]]
    if len(matches) != 1 or operation == "definition":
        return CodeContextResult(
            action=operation,
            query=symbol,
            strategy="code-index-symbolic-graph-cross-repo",
            index_version=_combined_version(stats),
            repositories=tuple(label for label, _ in indexes),
            matches=root_values,
            suggestions=[item.value for item in suggestions],
            stats=stats,
            limitations=limitations,
            truncated=len(matches) > 20,
        )

    stored_symbols = await run_index_work(_load_symbols, indexes, stats)
    root = matches[0]
    root = next(
        (item for item in stored_symbols if item.value.identity == root.value.identity),
        root,
    )
    capped_depth = max(1, min(3, depth))
    capped_limit = max(1, min(100, limit))
    (
        traversed,
        truncated,
        traversal_limitations,
        traversal_suggestions,
    ) = await run_index_work(
        _traverse_lazy,
        root,
        stored_symbols,
        indexes,
        operation=operation,
        depth=capped_depth,
        limit=capped_limit,
    )
    limitations.extend(traversal_limitations)
    rendered_relations = [
        GraphRelation(
            kind=edge.relation.kind,
            depth=edge_depth,
            cross_repo=edge.source.repository != edge.target.repository,
            source=edge.source.value,
            target=edge.target.value,
            callsite_file=edge.relation.file_path,
            callsite_line=edge.relation.line or edge.source.value.line_start,
            callsite_source=_source_window(
                edge.source,
                edge.relation.file_path,
                edge.relation.line or edge.source.value.line_start,
            ),
        )
        for edge, edge_depth in traversed
    ]
    return CodeContextResult(
        action=operation,
        query=symbol,
        strategy="code-index-symbolic-graph-cross-repo",
        index_version=_combined_version(stats),
        repositories=tuple(label for label, _ in indexes),
        matches=root_values,
        relations=rendered_relations,
        stats=stats,
        limitations=limitations,
        suggestions=[item.value for item in traversal_suggestions[:10]],
        truncated=truncated,
    )


def _find_symbols(
    indexes: list[tuple[str, RepositoryIndex]],
    folded: str,
    repository: str | None,
    paths: list[str] | None,
) -> tuple[list[_StoredSymbol], list[_StoredSymbol]]:
    matches: list[_StoredSymbol] = []
    suggestions: list[_StoredSymbol] = []
    for label, index in indexes:
        if repository is not None and label.casefold() != repository.casefold():
            continue
        with index.database.readonly() as conn:
            exact_rows = _fetch_path_filtered_rows(
                conn.execute(
                    """
                    SELECT id, file_path, language, kind, name, qualified_name,
                           line_start, line_end, signature, docstring
                    FROM code_symbols
                    WHERE name = ? COLLATE NOCASE OR qualified_name = ? COLLATE NOCASE
                    ORDER BY file_path, line_start
                    """,
                    (folded, folded),
                ),
                paths=paths,
                limit=101,
            )
            suggestion_rows = []
            if not exact_rows:
                suggestion_rows = _fetch_path_filtered_rows(
                    conn.execute(
                        """
                        SELECT id, file_path, language, kind, name, qualified_name,
                               line_start, line_end, signature, docstring
                        FROM code_symbols
                        WHERE kind != 'file' AND (
                          name LIKE ? OR qualified_name LIKE ?
                        )
                        ORDER BY name, qualified_name, file_path, line_start
                        """,
                        (f"{folded}%", f"%{folded}%"),
                    ),
                    paths=paths,
                    limit=20,
                )
        for target, rows in ((matches, exact_rows), (suggestions, suggestion_rows)):
            target.extend(_stored_symbol(label, index, row) for row in rows)
    return matches, suggestions[:10]


def _fetch_path_filtered_rows(
    cursor: sqlite3.Cursor,
    *,
    paths: list[str] | None,
    limit: int,
) -> list[tuple[object, ...]]:
    """Apply path filters before result caps so late files remain selectable."""
    output: list[tuple[object, ...]] = []
    while len(output) < limit:
        rows = cursor.fetchmany(256)
        if not rows:
            break
        output.extend(row for row in rows if _path_matches(str(row[1]), paths))
    return output[:limit]


def _stored_symbol(
    label: str, index: RepositoryIndex, row: tuple[object, ...]
) -> _StoredSymbol:
    return _StoredSymbol(
        repository=label,
        index=index,
        value=CodeSymbol(
            id=str(row[0]),
            repository=label,
            file_path=str(row[1]),
            language=str(row[2]),
            kind=str(row[3]),
            name=str(row[4]),
            qualified_name=str(row[5]),
            line_start=int(str(row[6])),
            line_end=int(str(row[7])),
            signature=str(row[8]) if row[8] is not None else None,
            docstring=str(row[9]) if row[9] is not None else None,
        ),
    )


def _traverse_lazy(
    root: _StoredSymbol,
    symbols: list[_StoredSymbol],
    indexes: list[tuple[str, RepositoryIndex]],
    *,
    operation: GraphOperation,
    depth: int,
    limit: int,
) -> tuple[list[tuple[_ResolvedRelation, int]], bool, list[str], list[_StoredSymbol]]:
    queue = deque([(root, 1)])
    visited = {root.value.identity}
    output: list[tuple[_ResolvedRelation, int]] = []
    seen_edges: set[tuple[str, str]] = set()
    limitations: list[str] = []
    suggestions: list[_StoredSymbol] = []
    catalog = _GraphResolver(symbols, [])
    while queue:
        node, current_depth = queue.popleft()
        if current_depth > depth:
            continue
        wants_outbound = operation in {"callees", "neighborhood"}
        wants_inbound = operation in {
            "callers",
            "references",
            "impact",
            "neighborhood",
        }
        kinds = (
            frozenset({"calls"})
            if operation == "callees"
            else frozenset({"calls", "references"})
            if operation == "callers"
            else _REFERENCE_KINDS
            if operation in {"references", "impact"}
            else _REFERENCE_KINDS | {"contains"}
        )
        relations = _relations_for_node(
            indexes,
            node,
            outbound=wants_outbound,
            inbound=wants_inbound,
            kinds=kinds,
        )
        heritage_owners: dict[tuple[str, str], _StoredSymbol] = {}
        for relation in relations:
            raw_target = (relation.dst_name or "").replace("::", ".").replace("->", ".")
            source = catalog.by_identity.get((relation.repository, relation.src_id))
            if (
                source is None
                or source.value.language not in _SUPER_MEMBER_LANGUAGES
                or not raw_target.casefold().startswith("super.")
            ):
                continue
            container_name, separator, _ = source.value.qualified_name.rpartition(".")
            if not separator:
                continue
            for owner in catalog.by_repo_qualified.get(
                (source.repository, container_name.casefold()), []
            ):
                if owner.value.kind in _TYPE_KINDS:
                    heritage_owners[owner.value.identity] = owner
        for owner in heritage_owners.values():
            relations.extend(
                _relations_for_node(
                    indexes,
                    owner,
                    outbound=True,
                    inbound=False,
                    kinds=frozenset({"inherits"}),
                )
            )
        relations = list(
            {(item.repository, item.id): item for item in relations}.values()
        )
        resolver = _GraphResolver(symbols, relations, catalog=catalog)
        edges = resolver.resolve_all()
        limitations.extend(resolver.limitations)
        suggestions.extend(resolver.ambiguities)
        candidates: list[tuple[_ResolvedRelation, _StoredSymbol]] = []
        if operation == "callees":
            candidates.extend(
                (edge, edge.target)
                for edge in edges
                if edge.source.value.identity == node.value.identity
                and edge.relation.kind == "calls"
            )
        elif operation == "callers":
            candidates.extend(
                (edge, edge.source)
                for edge in edges
                if edge.target.value.identity == node.value.identity
                and edge.relation.kind in {"calls", "references"}
            )
        elif operation in {"references", "impact"}:
            candidates.extend(
                (edge, edge.source)
                for edge in edges
                if edge.target.value.identity == node.value.identity
                and edge.relation.kind in _REFERENCE_KINDS
            )
        elif operation == "neighborhood":
            candidates.extend(
                (edge, edge.target)
                for edge in edges
                if edge.source.value.identity == node.value.identity
                and edge.relation.kind in _REFERENCE_KINDS | {"contains"}
            )
            candidates.extend(
                (edge, edge.source)
                for edge in edges
                if edge.target.value.identity == node.value.identity
                and edge.relation.kind in _REFERENCE_KINDS | {"contains"}
            )
        candidates.sort(
            key=lambda item: (
                item[0].relation.kind,
                item[0].source.repository,
                item[0].relation.file_path,
                item[0].relation.line or 0,
                item[0].target.value.qualified_name,
            )
        )
        for edge, neighbor in candidates:
            edge_identity = (edge.relation.repository, edge.relation.id)
            if edge_identity in seen_edges:
                continue
            seen_edges.add(edge_identity)
            if len(output) >= limit:
                return output, True, list(dict.fromkeys(limitations)), suggestions
            output.append((edge, current_depth))
            if neighbor.value.identity not in visited:
                visited.add(neighbor.value.identity)
                queue.append((neighbor, current_depth + 1))
    return output, False, list(dict.fromkeys(limitations)), suggestions


def _attach_definition(symbol: _StoredSymbol) -> CodeSymbol:
    return replace(
        symbol.value,
        source=_source_range(
            symbol,
            symbol.value.file_path,
            symbol.value.line_start,
            symbol.value.line_end,
            max_chars=20_000,
        ),
    )


def _source_range(
    symbol: _StoredSymbol,
    file_path: str,
    start: int,
    end: int,
    *,
    max_chars: int,
) -> str | None:
    try:
        with symbol.index.database.readonly() as connection:
            row = connection.execute(
                "SELECT content FROM source_files WHERE file_path = ?", (file_path,)
            ).fetchone()
        if row is None:
            return None
        lines = str(row[0]).splitlines()
    except Exception:
        return None
    first = max(1, start)
    last = min(len(lines), max(first, end))
    rendered = "\n".join(
        f"{number:>5} | {lines[number - 1]}" for number in range(first, last + 1)
    )
    return rendered if len(rendered) <= max_chars else None


def _source_window(symbol: _StoredSymbol, file_path: str, line: int) -> str | None:
    return _source_range(
        symbol,
        file_path,
        max(1, line - 1),
        line + 1,
        max_chars=2_000,
    )


def _combined_version(stats: dict[str, IndexStats]) -> str | None:
    versions = [
        (label, item.version) for label, item in sorted(stats.items()) if item.version
    ]
    if not versions:
        return None
    digest = hashlib.sha256()
    for label, version in versions:
        digest.update(label.encode("utf-8", "replace"))
        digest.update(str(version).encode("ascii", "replace"))
    return digest.hexdigest()[:12]


__all__ = ["navigate_graph", "search_index", "snapshot_graph", "structural_grep"]
